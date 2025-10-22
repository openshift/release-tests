import logging
import os
import re
import shlex
import subprocess
import oar.core.util as util
from threading import Event

from langchain_community.llms.vllm import VLLMOpenAI
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("ERTReleaseBot")


# Initialize SocketModeClient with an app-level token + WebClient
client = SocketModeClient(
    # This app-level token will be used only for establishing a connection
    app_token=os.environ.get("SLACK_APP_TOKEN"),  # xapp-A111-222-xyz
    # You will be using this WebClient for performing Web API calls in listeners
    web_client=WebClient(token=os.environ.get(
        "SLACK_BOT_TOKEN")),  # xoxb-111-222-xyz
    trace_enabled=True,
    logger=logger,
)

# Get bot's own user ID for mention detection
try:
    bot_auth_info = client.web_client.auth_test()
    BOT_USER_ID = bot_auth_info.get("user_id")
    logger.info(f"Bot initialized with user_id: {BOT_USER_ID}")
except Exception as e:
    logger.error(f"Failed to get bot user ID: {e}")
    BOT_USER_ID = None


def replace_mailto(message):
    pattern = r'<mailto:([^|]+)\|([^>]+)>'
    match = re.search(pattern, message)
    if match:
        email = match.group(2)
        return message.replace(match.group(0), email)
    else:
        return message


def get_username(user_id):
    resp = client.web_client.users_info(user=user_id)
    if resp['ok']:
        user_info = resp['user']
        username = user_info['name']
        return username
    else:
        return "unknown user"


def is_oar_related_message(message):
    return message.startswith("oar") or message.startswith("oarctl") or re.search("^<\@.*>\ oar\ ", message) or re.search("^<\@.*>\ oarctl\ ", message)


def validate_oar_command(message):
    """
    Validate and extract OAR command from Slack message.

    Returns:
        tuple: (is_valid, command_string, error_message)

    Security checks:
    - Command must start with 'oar' or 'oarctl'
    - No shell metacharacters that could chain commands
    - No command substitution attempts
    """
    # Shell metacharacters that could be used for command injection
    DANGEROUS_CHARS = [';', '&', '|', '`', '$', '(', ')', '<', '>', '\n', '\r']

    # Extract the command part (handle both direct commands and @mentions)
    if message.startswith("oar") or message.startswith("oarctl"):
        cmd = message
    else:
        # Extract from @mention format: <@U12345> oar -r 4.19.1 ...
        match = re.search(r'<@.*?>\s+(oar(?:ctl)?(?:\s|$).*)', message)
        if not match:
            return False, None, "Could not extract OAR command from message"
        cmd = match.group(1)

    # Check for dangerous shell metacharacters
    for char in DANGEROUS_CHARS:
        if char in cmd:
            return False, None, f"Invalid character '{char}' detected in command. Command injection attempt blocked."

    # Validate command starts with allowed commands
    try:
        cmd_parts = shlex.split(cmd)
    except ValueError as e:
        return False, None, f"Invalid command syntax: {e}"

    if not cmd_parts:
        return False, None, "Empty command"

    ALLOWED_COMMANDS = ['oar', 'oarctl']
    if cmd_parts[0] not in ALLOWED_COMMANDS:
        return False, None, f"Command must start with 'oar' or 'oarctl', got: {cmd_parts[0]}"

    return True, cmd, None


def send_prompt_to_ai_model(prompt):
    """
    Send prompt message to LLM model and return the answer
    We only support OpenAI-compatible API
    """
    model_api_base = os.environ.get("MODEL_API_BASE")
    model_api_key = os.environ.get("MODEL_API_KEY")
    model_api_name = os.environ.get("MODEL_API_NAME")

    if not model_api_base or not model_api_key or not model_api_name:
        logger.warning(
            "environment variables MODEL_API_BASE/MODEL_API_KEY/MODEL_API_NAME are not defined")
        return None

    if prompt:
        llm = VLLMOpenAI(
            openai_api_key=model_api_key,
            openai_api_base=f"{model_api_base}/v1",
            model_name=model_api_name,
            streaming=True,
            max_tokens=4096
        )
        return llm.invoke(prompt)

    return None


def process(client: SocketModeClient, req: SocketModeRequest):
    # Acknowledge the request anyway
    response = SocketModeResponse(envelope_id=req.envelope_id)
    client.send_socket_mode_response(response)

    if req.type == "events_api":
        event = req.payload["event"]
        event_type = event["type"]

        # CRITICAL: Ignore bot messages to prevent infinite loops
        # Bot messages have "bot_id" instead of "user"
        if "bot_id" in event:
            logger.debug(f"Ignoring bot message from bot_id: {event.get('bot_id')}")
            return

        # Check for bot_message subtype as additional safety
        if event.get("subtype") == "bot_message":
            logger.debug("Ignoring message with subtype: bot_message")
            return

        # Now safe to access user field
        if "user" not in event:
            logger.debug(f"Skipping event without user field: {event_type}")
            return

        message = event["text"]
        channel_id = event["channel"]
        thread_ts = event["ts"]
        username = get_username(event["user"])

        # Backup check: ignore known bot usernames
        if username == "qe-release-bot":
            logger.debug(f"Ignoring message from bot username: {username}")
            return

        if event_type in ["message", "app_mention"]:
            if "Hello" in message:
                client.web_client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text="I'm ERT release bot",
                )

            # slack will transform the email address in message with mailto format e.g. <mailto:xx@foo.com|xx@foo.com>
            message = replace_mailto(message)
            if is_oar_related_message(message):
                logger.info(f"received cmd from user <{username}>: {message}")

                # Validate command for security
                is_valid, cmd, error_msg = validate_oar_command(message)
                if not is_valid:
                    logger.warning(f"Invalid command from user <{username}>: {error_msg}")
                    client.web_client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=f"❌ Invalid command: {error_msg}"
                    )
                    return

                # Set environment variables for Slack context to enable background notifications
                env = os.environ.copy()
                env['OAR_SLACK_CHANNEL'] = channel_id
                env['OAR_SLACK_THREAD'] = thread_ts

                try:
                    result = subprocess.run(
                        shlex.split(cmd),
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        env=env,
                        timeout=600  # 10 minute timeout
                    )
                    output = result.stdout or "Command completed with no output"

                    if result.returncode != 0:
                        output = f"⚠️ Command failed with exit code {result.returncode}\n\n{output}"
                        logger.warning(f"Command failed with exit code {result.returncode}: {cmd}")

                except subprocess.TimeoutExpired:
                    output = "❌ Command timed out after 10 minutes"
                    logger.error(f"Command timeout for user <{username}>: {cmd}")
                except Exception as e:
                    output = f"❌ Command execution failed: {str(e)}"
                    logger.error(f"Command execution error for user <{username}>: {e}", exc_info=True)

                # Use utility function to split large messages
                message_chunks = util.split_large_message(output)
                for chunk in message_chunks:
                    client.web_client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=f"```{chunk}```")
            else:
                # Check if this is a direct bot mention without a valid OAR command
                # Don't forward these to LLM to avoid generating garbage responses
                if BOT_USER_ID and message.strip().startswith(f"<@{BOT_USER_ID}>"):
                    # Extract the part after the mention
                    mention_prefix = f"<@{BOT_USER_ID}>"
                    remaining_text = message[len(mention_prefix):].strip()

                    # If it's a dash command (like -help, -version) or very short, provide help instead of forwarding to LLM
                    if not remaining_text or remaining_text.startswith("-") or len(remaining_text.split()) <= 2:
                        logger.info(f"Bot mentioned with short/dash command from user <{username}>: {remaining_text}")
                        client.web_client.chat_postMessage(
                            channel=channel_id,
                            thread_ts=thread_ts,
                            text="I'm ERT Release Bot. What can I do for you?"
                        )
                        return

                # forward message as prompt to LLM, this feature is optional
                # if required system environment variables are not defined
                # API call with AI model is disabled, none will be returned
                logger.debug(f"Forwarding message to LLM from user <{username}>: {message[:100]}")
                answer = send_prompt_to_ai_model(message)
                if answer:
                    client.web_client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=answer)


# Add a new listener to receive messages from Slack
# You can add more listeners like this
# client.socket_mode_request_listeners.append(process)
client.socket_mode_request_listeners.append(process)
# Establish a WebSocket connection to the Socket Mode servers
client.connect()
# Just not to stop this process

Event().wait()
