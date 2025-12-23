# Release Progress Dashboard Deployment Guide

This guide covers deploying the Release Progress Dashboard as a systemd service on a VM.

## Prerequisites

1. **VM Requirements**:
   - Linux system with systemd
   - Python 3.12+
   - Network access to MCP server (default: localhost:8000)

2. **Environment Variables** (in `~/.bash_profile` or `~/.bashrc`):
   ```bash
   # Optional: MCP server URL (defaults to localhost:8000)
   export MCP_SERVER_URL="http://localhost:8000/mcp"  # Or remote MCP server URL
   ```

3. **Dependencies**:
   ```bash
   # Install dashboard dependencies
   cd ~/release-tests
   pip3 install -r tools/release_progress_dashboard/requirements.txt
   ```

4. **MCP Server**:
   - The dashboard requires the MCP server to be running
   - See `MCP_SERVER_DEPLOYMENT.md` for MCP server deployment
   - Default MCP server URL: `http://localhost:8000/mcp`

## Installation Steps

### 1. Clone Repository

```bash
cd ~
git clone https://github.com/openshift/release-tests.git
cd release-tests
```

### 2. Configure Systemd Service

```bash
# Copy the service file
sudo cp deployment/systemd/release-progress-dashboard.service /etc/systemd/system/

# Edit the service file to customize
sudo vi /etc/systemd/system/release-progress-dashboard.service
```

**Required Customizations**:
```ini
# Replace 'your-username' with your actual username (2 occurrences)
User=your-username
WorkingDirectory=/home/your-username/release-tests
ExecStart=/bin/bash -l -c 'cd /home/your-username/release-tests && ...'

# Optional: Customize MCP server URL if using remote server
Environment="MCP_SERVER_URL=http://your-mcp-server:8000/mcp"

# Optional: Change dashboard port (default: 8501)
Environment="STREAMLIT_SERVER_PORT=8501"
```

### 3. Enable and Start Service

```bash
# Reload systemd to recognize new service
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable release-progress-dashboard.service

# Start the service
sudo systemctl start release-progress-dashboard.service

# Check status
sudo systemctl status release-progress-dashboard.service
```

### 4. Verify Deployment

```bash
# Check if service is running
sudo systemctl status release-progress-dashboard.service

# View logs
sudo journalctl -u release-progress-dashboard.service -f

# Test dashboard access
curl http://localhost:8501
```

## Access the Dashboard

### Local Access (on VM)
```
http://localhost:8501
```

### Remote Access
1. **Option 1: SSH Port Forwarding** (Recommended for security)
   ```bash
   # From your local machine
   ssh -L 8501:localhost:8501 your-username@vm-hostname

   # Then access dashboard at:
   http://localhost:8501
   ```

2. **Option 2: Direct Access** (if firewall allows)
   ```
   http://vm-hostname:8501
   ```

   Note: Requires opening port 8501 in firewall:
   ```bash
   sudo firewall-cmd --permanent --add-port=8501/tcp
   sudo firewall-cmd --reload
   ```

## Service Management

### Start/Stop/Restart
```bash
# Start service
sudo systemctl start release-progress-dashboard.service

# Stop service
sudo systemctl stop release-progress-dashboard.service

# Restart service
sudo systemctl restart release-progress-dashboard.service

# Check status
sudo systemctl status release-progress-dashboard.service
```

### View Logs
```bash
# Follow logs in real-time
sudo journalctl -u release-progress-dashboard.service -f

# View last 100 lines
sudo journalctl -u release-progress-dashboard.service -n 100

# View logs since boot
sudo journalctl -u release-progress-dashboard.service -b
```

### Disable Service
```bash
# Stop and disable service
sudo systemctl stop release-progress-dashboard.service
sudo systemctl disable release-progress-dashboard.service
```

## Configuration

### Environment Variables

The service can optionally use environment variables from the user's `.bash_profile`:

```bash
# ~/.bash_profile or ~/.bashrc

# MCP server URL (optional, defaults to localhost:8000)
export MCP_SERVER_URL="http://localhost:8000/mcp"
```

After modifying environment variables, restart the service:
```bash
sudo systemctl restart release-progress-dashboard.service
```

### Streamlit Configuration

Dashboard configuration is set via environment variables in the service file:

```ini
Environment="STREAMLIT_SERVER_PORT=8501"           # Dashboard port
Environment="STREAMLIT_SERVER_ADDRESS=0.0.0.0"     # Listen on all interfaces
Environment="STREAMLIT_SERVER_HEADLESS=true"       # Headless mode (no browser)
```

To customize:
1. Edit `/etc/systemd/system/release-progress-dashboard.service`
2. Modify environment variables
3. Reload and restart:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart release-progress-dashboard.service
   ```

## Troubleshooting

### Service Won't Start

**Check logs**:
```bash
sudo journalctl -u release-progress-dashboard.service -n 50
```

**Common issues**:
1. **Missing dependencies**: Install dashboard requirements
   ```bash
   pip3 install -r tools/release_progress_dashboard/requirements.txt
   ```

2. **Wrong working directory**: Verify paths in service file match your setup

3. **MCP server not running**: Start MCP server first
   ```bash
   sudo systemctl start release-tests-mcp.service
   ```

4. **Environment variables not set**: Check `.bash_profile`
   ```bash
   # Verify MCP server URL (optional)
   bash -l -c 'echo $MCP_SERVER_URL'
   ```

### Dashboard Shows "Failed to load data"

**Verify MCP server connection**:
```bash
# Check MCP server is running
sudo systemctl status release-tests-mcp.service

# Test MCP server endpoint
curl http://localhost:8000/mcp
```

**Check network connectivity**:
```bash
# If using remote MCP server
curl http://your-mcp-server:8000/mcp
```

**Review dashboard logs**:
```bash
sudo journalctl -u release-progress-dashboard.service -f
```

### Port Already in Use

If port 8501 is already in use:

1. **Find what's using the port**:
   ```bash
   sudo lsof -i :8501
   ```

2. **Change dashboard port**:
   Edit `/etc/systemd/system/release-progress-dashboard.service`:
   ```ini
   Environment="STREAMLIT_SERVER_PORT=8502"
   ```

3. **Reload and restart**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart release-progress-dashboard.service
   ```

### Permission Issues

If service fails due to permissions:

1. **Check file ownership**:
   ```bash
   ls -la ~/release-tests/tools/release_progress_dashboard/
   ```

2. **Ensure user matches service file**:
   ```bash
   # Service file should have:
   User=your-actual-username
   ```

3. **Verify working directory exists**:
   ```bash
   ls -la /home/your-username/release-tests
   ```

## Architecture

### Service Dependencies
```
release-progress-dashboard.service
    ↓ requires
release-tests-mcp.service (MCP server)
    ↓ requires
network.target
```

### Component Flow
```
Browser → Dashboard (port 8501)
             ↓
MCP Server (port 8000)
             ↓
OAR Core Modules
             ↓
External Services (Google Sheets, Jira, etc.)
```

### Ports Used
- **8501**: Dashboard web interface (Streamlit)
- **8000**: MCP server (default)

## Updating the Dashboard

### Update Code
```bash
cd ~/release-tests
git pull origin master

# If dependencies changed
pip3 install -r tools/release_progress_dashboard/requirements.txt

# Restart service
sudo systemctl restart release-progress-dashboard.service
```

### Update Service Configuration
```bash
# Edit service file
sudo vi /etc/systemd/system/release-progress-dashboard.service

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart release-progress-dashboard.service
```

## Security Considerations

1. **Firewall**: Restrict port 8501 access to trusted networks
2. **SSH Tunneling**: Prefer SSH port forwarding over direct access
3. **Environment Variables**: Keep tokens secure in `.bash_profile` with proper permissions
4. **User Permissions**: Run service as non-root user
5. **MCP Server**: Ensure MCP server is properly secured (see MCP_SERVER_DEPLOYMENT.md)

## Monitoring

### Health Check
```bash
# Check service status
sudo systemctl is-active release-progress-dashboard.service

# Check if dashboard is responding
curl -I http://localhost:8501

# Monitor resource usage
top -p $(pgrep -f release_progress_dashboard)
```

### Log Rotation
Systemd journal handles log rotation automatically. To configure retention:

```bash
# Edit journald config
sudo vi /etc/systemd/journald.conf

# Set retention (example: 1 month)
SystemMaxUse=1G
MaxRetentionSec=2592000
```

## Related Documentation

- **Dashboard Usage**: `docs/RELEASE_PROGRESS_DASHBOARD.md`
- **MCP Server Deployment**: `deployment/MCP_SERVER_DEPLOYMENT.md`
- **Slack Bot Deployment**: `deployment/SLACK_BOT_DEPLOYMENT.md`
