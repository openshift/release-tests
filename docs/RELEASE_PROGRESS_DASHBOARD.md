# Release Progress Dashboard

A Streamlit-based dashboard for tracking OpenShift z-stream release progress in real-time.

## Overview

This dashboard provides QE managers and release leads with comprehensive visibility into:
- **Task Status Tracking** - Monitor all 9 tasks in the release workflow
- **Multi-Release Comparison** - Compare progress across multiple releases
- **Release Metadata** - View advisories, builds, and target dates
- **Shipment Status** - Track release shipment state and flow type
- **Visual Analytics** - Interactive charts and heatmaps

## Features

### 🎯 Key Capabilities

1. **Real-Time Status Monitoring**
   - Overall status (Green/Red) for each release
   - Individual task progress (Pass/Fail/In Progress/Not Started)
   - Manual refresh with dual-cache clearing

2. **Multi-Release Dashboard**
   - Track multiple releases simultaneously
   - Task-by-task progress heatmap
   - Custom release version input
   - Add/remove releases dynamically

3. **Interactive Visualizations**
   - Progress heatmap with color coding
   - Symbol-based status indicators (✓/▶/✗/○)
   - Hover tooltips for detailed task information

4. **Release Information Tabs**
   - **Advisories** - Clickable links to Errata Tool with status
   - **Candidate Builds** - Build versions by architecture
   - **Jira Ticket** - Clickable link to issue tracker
   - **Shipment** - MR URL and status
   - **Release Info** - Target release date and version

## Installation

### Prerequisites

1. **MCP Server**

   The dashboard requires the release-tests MCP server to be running:
   ```bash
   # Start the MCP server
   cd mcp_server
   python3 server.py
   ```

   The MCP server should be running at `http://localhost:8000` (default).

   To use a different MCP server URL, set the environment variable:
   ```bash
   export MCP_SERVER_URL="http://your-server:8000"
   ```

2. **Environment Setup**

   Make sure you have the OAR CLI environment configured:
   ```bash
   export OAR_JWK="..."
   export JIRA_TOKEN="..."
   export GCP_SA_FILE="..."
   # ... other OAR environment variables
   ```

3. **Install Dependencies**

   ```bash
   # From the release-tests root directory
   pip install -r tools/release_progress_dashboard/requirements.txt
   ```

   Or install individually:
   ```bash
   pip install streamlit pandas plotly requests PyGithub
   ```

## Usage

### Starting the Dashboard

1. **Start the MCP Server** (in one terminal):
   ```bash
   cd mcp_server
   python3 server.py
   ```

2. **Start the Dashboard** (in another terminal):
   ```bash
   # From the release-tests root directory
   streamlit run tools/release_progress_dashboard/release_progress_dashboard.py
   ```

The dashboard will open in your browser at `http://localhost:8501`

### Dashboard Controls

#### Sidebar - Release Management

1. **Add Release**
   - Text input field for release version (e.g., "4.19.1")
   - "➕ Add Release" button
   - Input field clears automatically after adding

2. **Tracked Releases List**
   - Shows all currently tracked releases
   - "❌" button next to each release to remove it
   - Removal clears both data and cache

3. **Refresh Controls**
   - "🔄 Refresh Data" - Clears both Streamlit cache and session state cache
   - "🗑️ Clear All Releases" - Removes all tracked releases
   - Data cached for 5 minutes (300 seconds)

#### Main Dashboard Views

**Release Progress Overview**
- Heatmap showing task-by-task status across all releases
- Color-coded: Green=Pass, Yellow=In Progress, Red=Fail, Gray=Not Started
- Status symbols: ✓=Pass, ▶=In Progress, ✗=Fail, ○=Not Started
- Hover over cells for task details
- Releases sorted in reverse order (newest first)

**Release Details Section**
- Dropdown to select a release to view
- Overall status badge (Green/Red)
- Tabbed interface with 5 tabs:
  - **Advisories** - Advisory IDs with clickable links and status
  - **Candidate Builds** - Build versions by architecture
  - **Jira Ticket** - Clickable link to Jira issue
  - **Shipment** - MR URL, merge status
  - **Release Info** - Version and target release date

## Data Sources

The dashboard fetches data from the **release-tests MCP Server** using three main tools:

1. `oar_get_release_status` - Task execution status
2. `oar_get_release_metadata` - Advisory, build, and date information
3. `oar_is_release_shipped` - Shipment verification

Data is collected via the `mcp_data_collector.py` module.

## Architecture

```
tools/
├── release_progress_dashboard/     # Dashboard application directory
│   ├── release_progress_dashboard.py  # Main Streamlit app
│   └── requirements.txt               # Dashboard dependencies
├── mcp_data_collector.py            # Shared MCP server data interface (reusable)
└── ...                              # Other tools

docs/
└── RELEASE_PROGRESS_DASHBOARD.md   # This documentation
```

### Component Flow

```
Streamlit UI
    ↓
MCPDataCollector (dual-tier caching: @st.cache_data + session_state)
    ↓
MCP Server (SSE transport with 10min timeout)
    ↓
OAR Core Modules (ConfigStore, WorksheetManager, etc.)
    ↓
External Services (Google Sheets, Jira, Errata Tool, GitLab)
```

### Caching Strategy

The dashboard uses a two-tier caching system for optimal performance:

1. **Streamlit Cache** (`@st.cache_data`, TTL=300s)
   - Function-level caching for individual releases
   - Automatically expires after 5 minutes
   - Cleared by "Refresh Data" button

2. **Session State Cache** (`st.session_state.release_data_cache`)
   - Persistent cache across page reruns
   - Stores loaded release data within the session
   - Cleared by "Refresh Data" button

This dual-tier approach enables:
- Fast incremental loading (only new releases fetched)
- Quick page reruns without re-fetching data
- Manual refresh capability

## Customization

### Changing Cache TTL

Modify the cache duration in `load_single_release_data`:

```python
@st.cache_data(ttl=300)  # Change 300 to desired seconds (default: 5 minutes)
def load_single_release_data(release: str) -> Dict[str, Any]:
    ...
```

### Customizing Task Order

Update the `task_order` list in `create_progress_heatmap` to change workflow sequence:

```python
task_order = [
    "take-ownership",
    "image-consistency-check",
    "analyze-candidate-build",
    "analyze-promoted-build",
    "check-cve-tracker-bug",
    "push-to-cdn-staging",
    "stage-testing",
    "image-signed-check",
    "change-advisory-status"
]
```

### Customizing MCP Server Timeouts

Edit `mcp_data_collector.py` to adjust timeout values:

```python
def __init__(self, server_url: Optional[str] = None):
    self.timeout = 120  # HTTP request timeout (seconds)
    self.sse_read_timeout = 600  # SSE read timeout (seconds)
```

## Troubleshooting

### Common Issues

**Problem: "Failed to load data for release X"**

**Solutions:**
1. Check MCP server is running (`http://localhost:8000`)
2. Verify release exists in ConfigStore (`config_store.json`)
3. Check OAR environment variables are set in MCP server
4. Ensure MCP server can access Google Sheets
5. Verify Kerberos ticket is valid (`klist`)

---

**Problem: "ModuleNotFoundError: No module named 'mcp_data_collector'"**

**Solution:**
Run the dashboard from the release-tests root directory:
```bash
cd /path/to/release-tests
streamlit run tools/release_progress_dashboard/release_progress_dashboard.py
```

---

**Problem: "No data available / Empty dashboard"**

**Solutions:**
1. Verify MCP server is running and accessible
2. Check MCP server URL (default: `http://localhost:8000`)
3. Set `MCP_SERVER_URL` environment variable if using custom URL
4. Check if test report exists for the release
5. Run `oar -r <release> create-test-report` to initialize
6. Verify network connectivity to external services
7. Check MCP server logs for specific errors

---

**Problem: "Cached data is stale"**

**Solution:**
Click the "🔄 Refresh Data" button in the sidebar to clear both cache layers

---

**Problem: "MCP server timeout / peer closed connection"**

**Solutions:**
1. Check MCP server logs for errors
2. Verify MCP server has valid Kerberos ticket (`klist`)
3. Increase timeout values in `mcp_data_collector.py` if needed
4. Check network connectivity to MCP server
5. Verify all OAR environment variables are set in MCP server

## Performance Considerations

- **Dual-Tier Caching**: Combines Streamlit cache (5min TTL) with session state cache
- **Incremental Loading**: Only fetches new releases, reuses cached data
- **Sequential Loading**: Displays progress bar while loading multiple releases
- **MCP Server Timeouts**: HTTP 120s, SSE 600s (10 minutes for slow operations)
- **Optimal Load**: 3-5 releases recommended for best performance
- **Memory Management**: Removing releases clears both data and cache

## Future Enhancements

Potential features for future development:

1. **Historical Trending**
   - Track task completion time over multiple releases
   - Build acceptance rate trends
   - Bug verification velocity

2. **Test Results Integration**
   - Link to test result files from GitHub
   - Display test pass/fail metrics
   - Prow job status integration

3. **Notifications**
   - Slack alerts when release status changes to Red
   - Email notifications for task failures
   - Custom alert rules

4. **Export & Reporting**
   - Export dashboard data to CSV/Excel
   - Generate PDF reports
   - Custom date range filtering

5. **Advanced Filtering**
   - Filter by flow type (Errata vs Konflux)
   - Filter by architecture
   - Search by Jira ticket or advisory ID

## Related Tools

- **auto_release_test_dashboard.py** - Test results dashboard (GitHub-based)
- **auto_release_test_result_checker.py** - Automated result checker
- **slack_message_receiver.py** - Slack bot for OAR commands

## Support

For issues or questions:
1. Check the main project README.md
2. Review AGENTS.md for OAR workflow details
3. Consult CLAUDE.md for development guidelines
4. File an issue in the openshift/release-tests repository

## License

This dashboard is part of the openshift/release-tests project.
