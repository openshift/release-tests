from threading import Event
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient
from slack_sdk.socket_mode import SocketModeClient
from langchain_community.llms.vllm import VLLMOpenAI
import os
import logging
import re
import subprocess
import shlex

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("QEReleaseBot")


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
        message = event["text"]
        channel_id = event["channel"]
        thread_ts = event["ts"]
        username = get_username(event["user"])

        if username == "qe-release-bot":
            return

        if event_type in ["message", "app_mention"]:
            if "Hello" in message:
                client.web_client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text="I'm qe release bot",
                )

            # slack will transform the email address in message with mailto format e.g. <mailto:xx@foo.com|xx@foo.com>
            message = replace_mailto(message)
            if is_oar_related_message(message):
                logger.info(f"received cmd from user <{username}>: {message}")
                cmd = message[message.index("oar"):]
                result = subprocess.run(shlex.split(
                    cmd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                output = result.stdout
                # if the message size > 4000, we need to split the message due to api limit
                if len(output) > 4000:
                    chunks, chunk_size = len(output), 2500
                    for msg in [output[i:i+chunk_size] for i in range(0, chunks, chunk_size)]:
                        client.web_client.chat_postMessage(
                            channel=channel_id,
                            thread_ts=thread_ts,
                            text=f"```{msg}```")
                else:
                    client.web_client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=f"```{result.stdout}```")
            else:
                # forward message as prompt to LLM, this feature is optional
                # if required system environment variables are not defined
                # API call with AI model is disabled, none will be returned
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
