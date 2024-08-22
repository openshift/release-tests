from threading import Event
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient
from slack_sdk.socket_mode import SocketModeClient
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


def process(client: SocketModeClient, req: SocketModeRequest):
    # Acknowledge the request anyway
    response = SocketModeResponse(envelope_id=req.envelope_id)
    client.send_socket_mode_response(response)

    if req.type == "events_api":
        # Add a reaction to the message if it's a new message
        event = req.payload["event"]
        event_type = event["type"]
        event_subtype = event.get("subtype")
        message = event["text"]
        channel_id = event["channel"]
        thread_ts = event["ts"]
        username = get_username(event["user"])

        if event_type in ["message", "app_mention"]:
            if "Hello" in message:
                client.web_client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text="I'm qe release bot",
                )

            # slack will transform the email address in message with mailto format e.g. <mailto:xx@foo.com|xx@foo.com>
            message = replace_mailto(message)
            if message.startswith("oar") or re.search("^<\@.*>\ oar\ ", message):
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


# Add a new listener to receive messages from Slack
# You can add more listeners like this
# client.socket_mode_request_listeners.append(process)
client.socket_mode_request_listeners.append(process)
# Establish a WebSocket connection to the Socket Mode servers
client.connect()
# Just not to stop this process

Event().wait()
