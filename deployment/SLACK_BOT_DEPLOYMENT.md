# OAR Slack Bot Deployment Guide

This guide explains how to deploy the OAR Slack Bot on your VM to enable OAR CLI execution via Slack.

## Architecture

```
┌─────────────────┐         Socket Mode          ┌─────────────────┐
│  Slack Workspace│◄────────────────────────────►│   VM Server     │
│  - Users        │   WebSocket (wss://)         │  - OAR CLI      │
│  - Channels     │                              │  - Credentials  │
│  - Bot App      │                              │  - Slack Bot    │
└─────────────────┘                              └─────────────────┘
```

The bot uses **Slack Socket Mode** which:
- Establishes WebSocket connection from VM to Slack (no inbound firewall rules needed)
- Receives events in real-time
- Posts command results back to Slack threads

## Prerequisites

On the VM, ensure you have:
- ✅ OAR installed and working (`oar --version`, `oarctl --help`)
- ✅ All credentials configured in `~/.bash_profile` or `~/.bashrc`
- ✅ Python 3.12 with pip
- ✅ Active Kerberos ticket (run `kinit` before starting bot)
- ✅ Slack App-Level Token (`SLACK_APP_TOKEN`)
- ✅ Slack Bot User OAuth Token (`SLACK_BOT_TOKEN`)

## Installation on VM

### 1. Install OAR CLI

```bash
cd ~/coderepo/release-tests

# Install OAR CLI (oar, oarctl)
pip3 install -e .

# Verify installation
oar --version
oarctl --help
```

### 2. Install Bot Dependencies

```bash
# Install Slack SDK and AI libraries
pip3 install slack-sdk langchain-community openai
```

### 3. Configure Environment Variables

Add to your `~/.bash_profile` or `~/.bashrc`:

```bash
# Slack Bot Tokens
export SLACK_APP_TOKEN="xapp-1-..." # App-level token (Socket Mode)
export SLACK_BOT_TOKEN="xoxb-..."   # Bot user OAuth token

# OAR Configuration (required for OAR CLI)
export OAR_JWK="your-jwk-key"       # From Bitwarden
export JIRA_TOKEN="your-jira-token"
export GCP_SA_FILE="/path/to/service-account.json"
export JENKINS_USER="your-username"
export JENKINS_TOKEN="your-token"
export GITLAB_TOKEN="your-gitlab-token"

# Optional: AI Model Integration (for intelligent responses)
export MODEL_API_BASE="https://your-model-api-url"
export MODEL_API_KEY="your-api-key"
export MODEL_API_NAME="model-name"
```

Apply the changes:
```bash
source ~/.bash_profile
```

### 4. Verify Bot Can Run

```bash
# Load environment
source ~/.bash_profile

# Verify tokens are set
echo $SLACK_APP_TOKEN  # Should print xapp-...
echo $SLACK_BOT_TOKEN  # Should print xoxb-...

# Test the bot manually (Ctrl+C to stop)
python3 ~/coderepo/release-tests/tools/slack_message_receiver.py
```

You should see:
```
INFO - Bot initialized with user_id: U12345...
INFO - Establishing a new connection to Slack...
INFO - Connected to Slack
```

## Set Up Systemd Service

### 1. Copy and Configure Service File

```bash
# Copy service file to systemd directory
sudo cp deployment/systemd/oar-bot.service /etc/systemd/system/

# Edit the service file to set your username and paths
sudo vi /etc/systemd/system/oar-bot.service
```

**Edit these fields in the service file:**
```ini
User=YOUR_USER → Replace with your actual VM username
Group=YOUR_GROUP → Replace with your group (usually same as username)
WorkingDirectory=/home/YOUR_USER → Adjust to your home directory
ExecStart=... /home/YOUR_USER/release-tests/... → Adjust path
```

Example after editing:
```ini
[Service]
Type=simple
WorkingDirectory=/home/johndoe
ExecStart=/usr/bin/bash -l -c 'python3 /home/johndoe/release-tests/tools/slack_message_receiver.py'
User=johndoe
Group=johndoe
```

### 2. Enable and Start Service

```bash
# Reload systemd to recognize new service
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable oar-bot

# Start the service
sudo systemctl start oar-bot

# Check status
sudo systemctl status oar-bot
```

Expected output:
```
● oar-bot.service - OAR Slack Bot service
   Loaded: loaded (/etc/systemd/system/oar-bot.service; enabled)
   Active: active (running) since ...
```

### 3. View Logs

```bash
# Follow logs in real-time
sudo journalctl -u oar-bot -f

# View recent logs
sudo journalctl -u oar-bot -n 50

# View logs since last boot
sudo journalctl -u oar-bot -b

# Search for errors
sudo journalctl -u oar-bot | grep -i error
```

## Kerberos Ticket Management

Since Kerberos tickets expire (typically after 24 hours), you need to renew them automatically for Errata Tool access.

### Setup Automatic Renewal with Keytab and Cron

**Step 1: Create/Obtain Keytab**
```bash
# Ask your admin for a keytab file, or create one:
ktutil
ktutil: addent -password -p YOUR_USERNAME@DOMAIN -k 1 -e aes256-cts
ktutil: wkt /home/YOUR_USER/.keytab
ktutil: quit

# Secure the keytab
chmod 600 /home/YOUR_USER/.keytab
```

**Step 2: Add Cron Job for Automatic Renewal**
```bash
crontab -e

# Add this line to renew every 8 hours
0 */8 * * * /usr/bin/kinit -k -t /home/YOUR_USER/.keytab YOUR_USERNAME@DOMAIN
```

**Step 3: Initial Kinit**
```bash
# Initialize Kerberos ticket before starting bot
kinit -k -t /home/YOUR_USER/.keytab YOUR_USERNAME@DOMAIN

# Verify ticket is valid
klist
```

**Step 4: Start/Restart Bot Service**
```bash
sudo systemctl restart oar-bot
```

The cron job will automatically renew the Kerberos ticket every 8 hours, ensuring the bot always has valid credentials.

## Using the Bot

### 1. Basic OAR Commands

In any Slack channel where the bot is invited:

```
oar -r 4.19.1 check-greenwave-cvp-tests
oar -r 4.19.1 update-bug-list
oarctl jira-notificator --dry-run
```

### 2. Mention Bot

You can also @mention the bot:
```
@ert-release-bot oar -r 4.19.1 create-test-report
```

### 3. Thread Responses

The bot automatically replies in threads to keep channels organized.

### 4. Greeting

Test bot is alive:
```
Hello
```
Bot responds: `I'm ERT release bot`

### 5. Command Format Examples

**Example commands:**
- `oar -r 4.19.1 update-bug-list`
- `oar -r 4.19.1 take-ownership -e user@redhat.com`

## Troubleshooting

### Service Won't Start

```bash
# Check detailed error logs
sudo journalctl -u oar-bot -xe

# Common issues:
# 1. Missing dependencies → pip3 install slack-sdk langchain-community openai
# 2. Wrong user/group in service file
# 3. Environment variables not loaded → check ~/.bash_profile
# 4. Missing tokens → echo $SLACK_APP_TOKEN
```

### Bot Not Responding in Slack

```bash
# 1. Check if service is running
sudo systemctl status oar-bot

# 2. Check recent logs for errors
sudo journalctl -u oar-bot -n 100

# 3. Verify bot is connected
sudo journalctl -u oar-bot | grep "Connected to Slack"

# 4. Check bot is in channel
# In Slack: /invite @qe-release-bot
```

### Invalid Token Errors

```bash
# Test tokens manually
python3 -c "
from slack_sdk import WebClient
import os
client = WebClient(token=os.environ['SLACK_BOT_TOKEN'])
print(client.auth_test())
"

# If fails, check your token values
```

### Kerberos Ticket Expired

```bash
# Check ticket status
klist

# If expired or missing, renew manually:
kinit -k -t /home/YOUR_USER/.keytab YOUR_USERNAME@DOMAIN

# Verify cron job is running
crontab -l | grep kinit

# Check cron logs
grep CRON /var/log/cron
```

### Environment Variables Not Loaded

```bash
# Test that bash login shell loads variables
/usr/bin/bash -l -c 'echo $SLACK_BOT_TOKEN'
# Should print xoxb-...

# If empty, check which file has the exports
grep SLACK_BOT_TOKEN ~/.bash_profile ~/.bashrc

# Make sure the file is sourced for login shells
```

### Bot Ignoring Commands

Check command format:
```bash
# View recent messages bot received
sudo journalctl -u oar-bot | grep "received cmd"

# Verify command validation
sudo journalctl -u oar-bot | grep "Invalid command"
```

## Service Management Commands

```bash
# Start service
sudo systemctl start oar-bot

# Stop service
sudo systemctl stop oar-bot

# Restart service (after config changes)
sudo systemctl restart oar-bot

# Check status
sudo systemctl status oar-bot

# Enable auto-start on boot
sudo systemctl enable oar-bot

# Disable auto-start
sudo systemctl disable oar-bot

# View logs
sudo journalctl -u oar-bot -f

# View logs with timestamps
sudo journalctl -u oar-bot --since "1 hour ago"
```

## Updating the Bot

When you update the bot code:

```bash
# Pull latest changes
cd ~/coderepo/release-tests
git pull

# Reinstall if dependencies changed
pip3 install -e .

# Restart service
sudo systemctl restart oar-bot

# Check logs for successful restart
sudo journalctl -u oar-bot -f
```

## Advanced Features

### Background Notifications

The bot supports background notifications when OAR commands post updates:

1. Commands set `OAR_SLACK_CHANNEL` and `OAR_SLACK_THREAD` env vars
2. OAR CLI can post progress updates to the same thread
3. Provides real-time feedback for long-running operations

### AI Model Integration (Optional)

If `MODEL_API_BASE`, `MODEL_API_KEY`, and `MODEL_API_NAME` are configured:
- Bot can use AI model for intelligent responses
- Currently supports OpenAI-compatible APIs
- Useful for natural language command interpretation
- Currently only support OpenAI compatible API

### Multi-Channel Support

The bot can work in multiple channels simultaneously:
```bash
# Invite to multiple channels
/invite @ert-release-bot  # in #team-releases
/invite @ert-release-bot  # in #team-qe
/invite @ert-release-bot  # in #alerts
```

Each channel gets its own threaded responses.

## Best Practices

1. **Use Threads**: Bot automatically replies in threads to keep channels clean
2. **Test in Private Channel**: Test new commands in a private channel first
3. **Monitor Logs**: Regularly check logs for errors or issues
4. **Update Dependencies**: Keep Python packages updated for security patches
5. **Backup Config**: Keep backup of environment variables in secure location
6. **Monitor Kerberos**: Check cron logs periodically to ensure ticket renewal is working

## Support

For issues or questions:
- **Check Logs**: `sudo journalctl -u oar-bot -n 100`
- **GitHub Issues**: https://github.com/openshift/release-tests/issues