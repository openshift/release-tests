from threading import Event
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
import os
import logging
from slack_sdk.web import WebClient
from slack_sdk.socket_mode import SocketModeClient
import subprocess

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("TestSocketMode")


# Initialize SocketModeClient with an app-level token + WebClient
client = SocketModeClient(
    # This app-level token will be used only for establishing a connection
    app_token=os.environ.get("SLACK_APP_TOKEN"),  # xapp-A111-222-xyz
    # You will be using this WebClient for performing Web API calls in listeners
    web_client=WebClient(token=os.environ.get("SLACK_BOT_TOKEN")),  # xoxb-111-222-xyz
    trace_enabled=True,
    logger=logger,
)


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

        if event_type in ["message", "app_mention"]:
            if "Hello" in message:
                client.web_client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text="I'm qe release bot",
                )

            if message.startswith("oar") or message.startswith("<@U0546N1SBB2> oar"):
                cmd = message[message.index("oar") :]
                result = subprocess.run(cmd.split(" "), capture_output=True, text=True)
                client.web_client.chat_postMessage(
                    channel=channel_id,
                    text=f"```{result.stdout} {result.stderr}```",
                )


# Add a new listener to receive messages from Slack
# You can add more listeners like this
# client.socket_mode_request_listeners.append(process)
client.socket_mode_request_listeners.append(process)
# Establish a WebSocket connection to the Socket Mode servers
client.connect()
# Just not to stop this process

Event().wait()
