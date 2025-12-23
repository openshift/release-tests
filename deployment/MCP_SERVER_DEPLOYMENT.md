# Release Tests MCP Server Deployment Guide

This guide explains how to deploy the Release Tests MCP server on your VM for remote access.

## Architecture

```
┌─────────────────┐           HTTP            ┌─────────────────┐
│  Your Laptop    │◄─────────────────────────►│   VM Server     │
│  - Claude Code  │   http://vm-hostname:8000  │  - OAR CLI      │
│  - Other AI     │                            │  - Credentials  │
│    tools        │                            │  - MCP Server   │
└─────────────────┘                            └─────────────────┘
```

## Prerequisites

On the VM, ensure you have:
- ✅ OAR installed and working (`oar --version`, `oarctl --help`)
- ✅ Prow job tools installed (`job --help`, `jobctl --help`)
- ✅ All credentials configured in `~/.bash_profile` or `~/.bashrc`
- ✅ Python 3.12 with pip
- ✅ Active Kerberos ticket (run `kinit` before starting server)

## Installation

### 1. Install Required CLI Tools

The MCP server requires all CLI tools to be installed:

```bash
# On the VM
cd ~/coderepo/release-tests

# Install OAR CLI (oar, oarctl)
pip3 install -e .

# Install Prow job tools (job, jobctl)
cd prow
pip3 install -e .
cd ..

# Verify installations
oar --version
oarctl --help
job --help
jobctl --help
```

### 2. Install FastMCP Dependency

```bash
pip3 install fastmcp
```

### 3. Verify MCP Server

Test that the server can run:

```bash
# Load your environment
source ~/.bash_profile

# Check credentials are loaded
echo $OAR_JWK  # Should print your JWK key

# Test the server (Ctrl+C to stop)
python3 -m mcp.server
```

You should see:
```
INFO - Starting Release Tests MCP Server
INFO - Transport: streamable-http
INFO - Running on http://127.0.0.1:8000
```

### 4. Configure for Remote Access

Edit `mcp_server/server.py` and change the last line:

```python
# Change from:
mcp.run(transport="streamable-http")

# To (listen on all interfaces):
mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)
```

### 5. Configure Firewall (If Needed)

```bash
# Check if firewalld is running
sudo systemctl status firewalld

# If running, open the MCP server port
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --reload

# Verify
sudo firewall-cmd --list-ports
```

### 6. Set Up Systemd Service

#### Copy and Configure Service File

```bash
# Copy service file to systemd directory
sudo cp deployment/systemd/release-tests-mcp.service /etc/systemd/system/

# Edit the service file to set your username and paths
sudo vi /etc/systemd/system/release-tests-mcp.service
```

**Edit these fields:**
- `User=your-username` → Replace with your actual VM username
- `WorkingDirectory=/home/your-username/coderepo/release-tests` → Adjust path

#### Enable and Start Service

```bash
# Reload systemd to recognize new service
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable release-tests-mcp

# Start the service
sudo systemctl start release-tests-mcp

# Check status
sudo systemctl status release-tests-mcp
```

Expected output:
```
● release-tests-mcp.service - Release Tests MCP Server
   Loaded: loaded (/etc/systemd/system/release-tests-mcp.service; enabled)
   Active: active (running) since ...
```

#### View Logs

```bash
# Follow logs in real-time
sudo journalctl -u release-tests-mcp -f

# View recent logs
sudo journalctl -u release-tests-mcp -n 50

# View logs since last boot
sudo journalctl -u release-tests-mcp -b
```

### 7. Kerberos Ticket Management

Since Kerberos tickets expire, you need to renew them periodically:

**Option A: Manual Renewal** (before starting service)
```bash
kinit your-username@DOMAIN
sudo systemctl restart release-tests-mcp
```

**Option B: Keytab for Auto-Renewal** (recommended for production)

```bash
# Create keytab (ask your admin if you don't have one)
# ktutil, addent, wkt /home/your-username/.keytab

# Add to systemd service:
ExecStartPre=/usr/bin/kinit -k -t /home/your-username/.keytab your-username@DOMAIN

# Add cron job for periodic renewal
crontab -e
# Add: 0 */6 * * * /usr/bin/kinit -k -t /home/your-username/.keytab your-username@DOMAIN
```

## Client Configuration

### For Claude Code (on your laptop)

Add to your Claude Code MCP settings:

**File:** `~/.config/claude-code/mcp_settings.json` (macOS/Linux)
**File:** `%APPDATA%\claude-code\mcp_settings.json` (Windows)

```json
{
  "mcpServers": {
    "release-tests": {
      "type": "http",
      "url": "http://your-vm-hostname.redhat.com:8080/mcp"
    }
  }
}
```

**Important:** Replace `your-vm-hostname.redhat.com` with your actual VM hostname or IP.

### For Other MCP Clients

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async with streamable_http_client(
    url="http://your-vm-hostname.redhat.com:8080/mcp"
) as (read, write, _):
    async with ClientSession(read, write) as session:
        # List available tools
        tools = await session.list_tools()
        print(f"Available tools: {[t.name for t in tools]}")

        # Call a tool
        result = await session.call_tool(
            "oar_check_greenwave_cvp_tests",
            arguments={"release": "4.19.1"}
        )
        print(result)
```

## Testing the Setup

### 1. Test from VM (Local)

```bash
# On the VM
curl http://localhost:8080/mcp
```

Should return MCP connection info or server metadata.

### 2. Test from Your Laptop (Remote)

```bash
# On your laptop
curl http://your-vm-hostname.redhat.com:8080/mcp
```

Should also connect successfully.

### 3. Test with Claude Code

1. Restart Claude Code after adding MCP settings
2. In a conversation, ask: "What MCP tools are available?"
3. Claude should list the release-tests tools
4. Try: "Check greenwave CVP tests for release 4.19.1"

## Troubleshooting

### Service Won't Start

```bash
# Check detailed error logs
sudo journalctl -u release-tests-mcp -xe

# Common issues:
# 1. Missing dependencies → pip3 install fastmcp
# 2. Wrong user in service file
# 3. Environment variables not loaded → check bash_profile
```

### Can't Connect from Laptop

```bash
# On VM, check if service is listening
sudo netstat -tlnp | grep 8080
# Should show: tcp 0.0.0.0:8080 ... LISTEN

# Check firewall
sudo firewall-cmd --list-ports

# Test connectivity from laptop
telnet your-vm-hostname.redhat.com 8080
```

### Kerberos Ticket Expired

```bash
# On VM
klist  # Check ticket status

# If expired:
kinit your-username@DOMAIN
sudo systemctl restart release-tests-mcp
```

### Environment Variables Not Loaded

```bash
# Test that bash login shell loads variables
/bin/bash -l -c 'echo $OAR_JWK'
# Should print your key

# If empty, check ~/.bash_profile or ~/.bashrc
grep OAR_JWK ~/.bash_profile ~/.bashrc
```

## Security Considerations

Since this is running on internal network:

✅ **Network Security:** VM accessible only from corporate network/VPN
✅ **Credential Security:** Environment variables not exposed in systemd file
✅ **Access Control:** Limited to users who can reach VM network

**Note:** If you need to expose outside internal network, add authentication layer.

## Service Management Commands

```bash
# Start service
sudo systemctl start release-tests-mcp

# Stop service
sudo systemctl stop release-tests-mcp

# Restart service
sudo systemctl restart release-tests-mcp

# Check status
sudo systemctl status release-tests-mcp

# Enable auto-start on boot
sudo systemctl enable release-tests-mcp

# Disable auto-start
sudo systemctl disable release-tests-mcp

# View logs
sudo journalctl -u release-tests-mcp -f
```

## Available MCP Tools

Once configured, these tools are available to AI agents:

### Read-Only Tools (Safe)
- `oar_check_greenwave_cvp_tests` - Check CVP test status
- `oar_check_cve_tracker_bug` - Check CVE coverage
- `oar_image_signed_check` - Verify image signatures

### Query Tools
- `oar_image_consistency_check` - Check/start image consistency tests
- `oar_stage_testing` - Check/start stage testing

### Write Operations (Use Carefully)
- `oar_create_test_report` - Create new test report
- `oar_take_ownership` - Assign release owner
- `oar_update_bug_list` - Sync bugs from advisory
- `oar_push_to_cdn_staging` - Push to CDN staging
- `oar_drop_bugs` - Remove unverified bugs
- `oar_change_advisory_status` - Change advisory status
- `oar_add_qe_approval` - Add QE approval

### Controller Tools
- `oarctl_start_release_detector` - Start release detector agent
- `oarctl_jira_notificator` - Run Jira notificator

### Job Tools
- `job_run` - Run Prow job
- `jobctl_start_controller` - Start job controller for monitoring builds
- `jobctl_trigger_jobs_for_build` - Trigger Prow jobs for specific build
- `jobctl_start_aggregator` - Start test result aggregator
- `jobctl_promote_test_results` - Promote test results for a build
- `jobctl_update_retried_job_run` - Update retried job run information

### Configuration Tools
- `oar_get_release_metadata` - Get release metadata (advisories, jira ticket, builds, etc.)
  - **Note:** Does NOT expose sensitive data (Slack contacts, credentials)
  - Safe to use without authentication

## Next Steps

1. ✅ Deploy server on VM
2. ✅ Configure Claude Code on laptop
3. ✅ Test basic commands
4. Consider: Add more OAR commands as MCP tools
5. Consider: Add custom resources for config/state access

## Support

For issues or questions:
- Check logs: `sudo journalctl -u release-tests-mcp -n 100`
- GitHub Issues: https://github.com/openshift/release-tests/issues
