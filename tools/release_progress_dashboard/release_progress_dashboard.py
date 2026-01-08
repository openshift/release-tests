#!/usr/bin/env python3
"""
Release Progress Dashboard

A streamlined Streamlit dashboard for tracking OpenShift z-stream release progress.
Provides release comparison via line graphs and detailed metadata tabs.

Usage:
    streamlit run tools/release_progress_dashboard_new.py
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import logging
from typing import Dict, List, Any

import sys
import os

# Add parent directory to path to import mcp_data_collector from tools/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_data_collector import MCPDataCollector

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="Release Progress Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': "OpenShift Release Progress Dashboard"
    }
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5em;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 20px;
    }
    .status-badge {
        padding: 5px 10px;
        border-radius: 5px;
        font-weight: bold;
        display: inline-block;
    }
    .status-green {
        background-color: #28a745;
        color: white;
    }
    .status-red {
        background-color: #dc3545;
        color: white;
    }
    .status-yellow {
        background-color: #ffc107;
        color: white;
    }
</style>
""", unsafe_allow_html=True)


# Initialize data collector
@st.cache_resource
def get_data_collector():
    """Initialize MCP data collector (cached)"""
    return MCPDataCollector()


# Load individual release data with caching
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_single_release_data(release: str) -> Dict[str, Any]:
    """
    Load data for a single release from MCP server

    Args:
        release: Release version

    Returns:
        Dictionary with release data
    """
    collector = get_data_collector()
    try:
        return collector.get_all_release_data(release)
    except Exception as e:
        logger.error(f"Failed to load data for {release}: {str(e)}")
        st.error(f"Failed to load data for {release}: {str(e)}")
        return None


def load_release_data(releases: List[str], cached_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Load data for multiple releases, using cache when available

    Args:
        releases: List of release versions
        cached_data: Previously loaded data (from session state)

    Returns:
        Dictionary with release data
    """
    if cached_data is None:
        cached_data = {}

    data = {}
    new_releases = [r for r in releases if r not in cached_data]

    # Use cached data for existing releases
    for release in releases:
        if release in cached_data:
            data[release] = cached_data[release]

    # Load only new releases
    if new_releases:
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, release in enumerate(new_releases):
            status_text.text(f"Loading data for {release}...")
            data[release] = load_single_release_data(release)
            progress_bar.progress((idx + 1) / len(new_releases))

        progress_bar.empty()
        status_text.empty()

    return data


def format_timestamp(timestamp_str: str) -> str:
    """
    Format ISO timestamp to human-readable format

    Args:
        timestamp_str: ISO format timestamp

    Returns:
        Formatted timestamp string
    """
    if not timestamp_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return timestamp_str


def calculate_duration(started_at: str, completed_at: str) -> str:
    """
    Calculate duration between two timestamps

    Args:
        started_at: Start timestamp
        completed_at: End timestamp

    Returns:
        Human-readable duration string
    """
    if not started_at or not completed_at:
        return "N/A"
    try:
        start = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
        end = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
        duration = end - start

        total_seconds = duration.total_seconds()

        # Handle different time scales
        if total_seconds < 60:
            # Less than 1 minute - show seconds
            return f"{int(total_seconds)} sec"
        elif total_seconds < 3600:
            # Less than 1 hour - show minutes
            minutes = total_seconds / 60
            return f"{round(minutes)} min"
        elif total_seconds < 86400:
            # Less than 1 day - show hours
            hours = total_seconds / 3600
            return f"{hours:.1f} hours"
        else:
            # 1 day or more - show days
            days = total_seconds / 86400
            return f"{days:.1f} days"
    except Exception:
        return "N/A"


def create_progress_heatmap(all_release_data: Dict[str, Any], theme: str = 'plotly_white') -> go.Figure:
    """
    Create heatmap showing task-by-task status for each release

    Args:
        all_release_data: Dictionary with data for all releases
        theme: Plotly theme to use

    Returns:
        Plotly figure
    """
    # Task order (workflow sequence)
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

    # Status to numeric mapping for color scale
    status_map = {
        "Pass": 4,
        "In Progress": 3,
        "Fail": 2,
        "Not Started": 1
    }

    # Status abbreviations for display
    status_abbrev = {
        "Pass": "✓",
        "In Progress": "▶",
        "Fail": "✗",
        "Not Started": "○"
    }

    # Prepare data
    releases = sorted([r for r in all_release_data.keys() if all_release_data[r] is not None], reverse=True)
    task_labels = [t.replace("-", " ").title() for t in task_order]

    z_data = []
    hover_text = []
    text_labels = []

    for release in releases:
        data = all_release_data[release]
        status_data = data['status']

        # Build task lookup by name (StateBox returns list of task dicts)
        tasks_list = status_data.get('tasks', [])
        tasks_by_name = {}

        # Handle both dict and list formats
        if isinstance(tasks_list, dict):
            # Old format: task_name -> status string
            tasks_by_name = {name: {"status": status, "started_at": None, "completed_at": None}
                            for name, status in tasks_list.items()}
        elif isinstance(tasks_list, list):
            # New StateBox format: list of task objects
            tasks_by_name = {task['name']: task for task in tasks_list}

        row_data = []
        hover_row = []
        text_row = []

        for task_name in task_order:
            task_info = tasks_by_name.get(task_name, {})
            status = task_info.get('status', 'Not Started')
            started_at = task_info.get('started_at')
            completed_at = task_info.get('completed_at')

            row_data.append(status_map.get(status, 1))

            # Enhanced hover text with timestamps and duration
            hover_parts = [
                f"<b>{release}</b>",
                f"{task_name.replace('-', ' ').title()}",
                f"Status: <b>{status}</b>"
            ]

            if started_at:
                hover_parts.append(f"Started: {format_timestamp(started_at)}")
            if completed_at:
                hover_parts.append(f"Completed: {format_timestamp(completed_at)}")
            if started_at and completed_at:
                duration = calculate_duration(started_at, completed_at)
                hover_parts.append(f"Duration: {duration}")

            # Check for blockers
            issues = status_data.get('issues', [])
            has_blocker = any(
                issue.get('blocker', False) and
                not issue['resolved'] and
                task_name in issue.get('related_tasks', [])
                for issue in issues
            )
            if has_blocker:
                hover_parts.append("⚠️ <b>Has blocker</b>")

            hover_row.append("<br>".join(hover_parts))
            text_row.append(status_abbrev.get(status, "○"))

        z_data.append(row_data)
        hover_text.append(hover_row)
        text_labels.append(text_row)

    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=z_data,
        x=task_labels,
        y=releases,
        colorscale=[
            [0, '#6c757d'],      # Not Started - gray
            [0.33, '#dc3545'],   # Fail - red
            [0.66, '#ffc107'],   # In Progress - yellow
            [1, '#28a745']       # Pass - green
        ],
        text=text_labels,
        texttemplate="<b>%{text}</b>",
        textfont={"size": 16, "color": "white"},
        hovertext=hover_text,
        hoverinfo='text',
        showscale=False
    ))

    # Update layout
    fig.update_layout(
        title={
            'text': "Release Progress - Task by Task",
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 20}
        },
        xaxis=dict(
            title="",
            tickangle=-45,
            side='bottom',
            showgrid=False
        ),
        yaxis=dict(
            title="Release Version",
            automargin=True,
            showgrid=False
        ),
        height=max(400, len(releases) * 50 + 150),
        margin=dict(l=100, r=20, t=80, b=150),
        template=theme
    )

    return fig


def render_issues_section(release: str, status_data: Dict[str, Any]):
    """
    Render issues section with blockers and non-blocking issues

    Args:
        release: Release version
        status_data: Status data containing issues
    """
    st.header("🚨 Issues & Blockers")

    issues = status_data.get('issues', [])

    if not issues:
        st.success("✅ No issues reported for this release")
        return

    # Filter issues by type and resolution status
    active_blockers = [i for i in issues if i.get('blocker', False) and not i['resolved']]
    active_non_blockers = [i for i in issues if not i.get('blocker', False) and not i['resolved']]
    resolved_issues = [i for i in issues if i['resolved']]

    # Show issue statistics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if active_blockers:
            st.metric("🛑 Active Blockers", len(active_blockers), delta=None, delta_color="inverse")
        else:
            st.metric("🛑 Active Blockers", 0)

    with col2:
        if active_non_blockers:
            st.metric("⚠️ Non-blocking Issues", len(active_non_blockers))
        else:
            st.metric("⚠️ Non-blocking Issues", 0)

    with col3:
        st.metric("✅ Resolved Issues", len(resolved_issues))

    with col4:
        st.metric("📊 Total Issues", len(issues))

    st.divider()

    # Active Blockers Section (Critical - Always Expanded)
    if active_blockers:
        st.error(f"🛑 **{len(active_blockers)} Active Blocker(s)** - Release is blocked!")
        for idx, issue in enumerate(active_blockers):
            with st.expander(f"🛑 Blocker #{idx + 1}: {issue['issue'][:80]}...", expanded=True):
                st.markdown(f"**Issue Description:**")
                st.markdown(f"> {issue['issue']}")

                st.markdown(f"**Reported:** {format_timestamp(issue['reported_at'])}")

                if issue.get('related_tasks'):
                    tasks_str = ', '.join([f"`{t}`" for t in issue['related_tasks']])
                    st.markdown(f"**Affects Tasks:** {tasks_str}")
                else:
                    st.warning("**Scope:** General (affects entire release)")
    else:
        st.success("✅ No active blockers - Release can proceed")

    # Non-blocking Issues Section
    if active_non_blockers:
        st.divider()
        st.warning(f"⚠️ **{len(active_non_blockers)} Non-blocking Issue(s)**")
        for idx, issue in enumerate(active_non_blockers):
            with st.expander(f"⚠️ Issue #{idx + 1}: {issue['issue'][:80]}...", expanded=False):
                st.markdown(f"**Issue Description:**")
                st.markdown(f"> {issue['issue']}")

                st.markdown(f"**Reported:** {format_timestamp(issue['reported_at'])}")

                if issue.get('related_tasks'):
                    tasks_str = ', '.join([f"`{t}`" for t in issue['related_tasks']])
                    st.markdown(f"**Affects Tasks:** {tasks_str}")
                else:
                    st.info("**Scope:** General (tracked for visibility)")

    # Resolved Issues Section (Collapsed by default)
    if resolved_issues:
        st.divider()
        with st.expander(f"✅ {len(resolved_issues)} Resolved Issue(s) - Click to expand", expanded=False):
            for idx, issue in enumerate(resolved_issues):
                st.markdown(f"**{idx + 1}. {issue['issue']}**")

                col1, col2 = st.columns(2)
                with col1:
                    st.caption(f"Reported: {format_timestamp(issue['reported_at'])}")
                with col2:
                    st.caption(f"Resolved: {format_timestamp(issue.get('resolved_at', 'N/A'))}")

                if issue.get('resolution'):
                    st.info(f"**Resolution:** {issue['resolution']}")

                if idx < len(resolved_issues) - 1:
                    st.markdown("---")


def render_metadata_tabs(release: str, metadata: Dict[str, Any], shipped_data: Dict[str, Any], status_data: Dict[str, Any]):
    """
    Render tabbed pane with release metadata

    Args:
        release: Release version
        metadata: Release metadata dictionary
        shipped_data: Shipment status dictionary
        status_data: Status data containing tasks and issues
    """
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📋 Advisories",
        "📦 Candidate Builds",
        "🎫 Jira Ticket",
        "🚢 Shipment Data",
        "📅 Release Info",
        "🧪 QE Test Results",
        "🔍 Task Details"
    ])

    with tab1:
        advisories = metadata.get('advisories', {})
        shipped_details = shipped_data.get('details', {})

        if advisories:
            adv_data = []
            for adv_type, adv_id in advisories.items():
                if adv_id:
                    # Get status from shipped_data details (e.g., "image_advisory": "SHIPPED_LIVE")
                    status_key = f"{adv_type}_advisory"
                    status = shipped_details.get(status_key, "Unknown")

                    # Create clickable link to errata.devel.redhat.com
                    advisory_url = f"https://errata.devel.redhat.com/advisory/{adv_id}"
                    adv_data.append({
                        "Type": adv_type.upper(),
                        "Advisory ID": f"[{adv_id}]({advisory_url})",
                        "Status": status
                    })

            if adv_data:
                adv_df = pd.DataFrame(adv_data)
                # Use markdown rendering to support clickable links
                st.markdown(adv_df.to_markdown(index=False))
            else:
                st.info("No advisories configured for this release")
        else:
            st.info("No advisories data available")

    with tab2:
        builds = metadata.get('candidate_builds', {})
        if builds:
            build_df = pd.DataFrame([
                {"Architecture": arch, "Build": build}
                for arch, build in builds.items()
                if build
            ])
            if not build_df.empty:
                st.dataframe(build_df, use_container_width=True, hide_index=True)
            else:
                st.info("No candidate builds available")
        else:
            st.info("No candidate builds data available")

    with tab3:
        jira_ticket = metadata.get('jira_ticket', '')
        if jira_ticket and jira_ticket != 'N/A':
            jira_url = f"https://issues.redhat.com/browse/{jira_ticket}"
            jira_df = pd.DataFrame([
                {"Field": "Jira Ticket", "Value": f"[{jira_ticket}]({jira_url})"}
            ])
            st.markdown(jira_df.to_markdown(index=False))
        else:
            st.info("No Jira ticket configured for this release")

    with tab4:
        shipment_mr = metadata.get('shipment_mr', '')
        details = shipped_data.get('details', {})

        # Build shipment data table
        shipment_data = []

        # Add shipment MR if available
        if shipment_mr:
            # Make it a clickable link (GitLab MR URL)
            shipment_data.append({
                "Field": "Shipment MR",
                "Value": f"[{shipment_mr}]({shipment_mr})"
            })

            # Add MR-related details
            if 'shipment_mr_merged' in details:
                shipment_data.append({
                    "Field": "MR Merged",
                    "Value": "✅ Yes" if details['shipment_mr_merged'] == "yes" else "❌ No"
                })
            if 'shipment_mr_status' in details:
                shipment_data.append({
                    "Field": "MR Status",
                    "Value": str(details['shipment_mr_status'])
                })
            if 'prod_release' in details:
                shipment_data.append({
                    "Field": "Prod Release Pipeline",
                    "Value": str(details['prod_release'])
                })

        if shipment_data:
            shipment_df = pd.DataFrame(shipment_data)
            # Use markdown rendering to support clickable links
            st.markdown(shipment_df.to_markdown(index=False))
        else:
            st.info("No shipment information available")

    with tab5:
        release_date = metadata.get('release_date', 'N/A')

        release_info_df = pd.DataFrame([
            {"Field": "Release Version", "Value": release},
            {"Field": "Target Release Date", "Value": release_date}
        ])

        st.dataframe(release_info_df, use_container_width=True, hide_index=True)

    with tab6:
        # QE Test Results Tab - Show test result file links
        st.info("ℹ️ **Note:** Blocking test jobs are only triggered for x86_64 (amd64) architecture. Test result files for some old releases may have been recycled and are no longer available.")

        # GitHub blob URL for record branch (better for viewing in browser)
        github_base_url = "https://github.com/openshift/release-tests/blob/record/_releases"

        # Collect all test results in one table
        test_results_data = []
        builds = metadata.get('candidate_builds', {})

        # Add candidate nightly build test results (x86_64 only)
        # Check if builds dict exists and has non-empty amd64/x86_64 values
        has_candidate_build = False
        if builds:
            # Only show x86_64 (amd64) since that's the only arch we test
            for arch in ['amd64', 'x86_64']:  # Try both naming conventions
                build = builds.get(arch)
                if build and build.strip():  # Check for non-empty string
                    # Use amd64 for file name (standard naming)
                    test_result_file = f"ocp-test-result-{build}-amd64.json"
                    test_result_url = f"{github_base_url}/{test_result_file}"

                    test_results_data.append({
                        "Build Type": "Candidate Nightly",
                        "Build": build,
                        "Test Result": f"[{test_result_file}]({test_result_url})"
                    })
                    has_candidate_build = True
                    break  # Only need one entry

        # Add promoted build test results (stable z-stream release)
        promoted_build = release
        test_result_file = f"ocp-test-result-{promoted_build}-amd64.json"
        test_result_url = f"{github_base_url}/{test_result_file}"

        test_results_data.append({
            "Build Type": "Stable",
            "Build": promoted_build,
            "Test Result": f"[{test_result_file}]({test_result_url})"
        })

        # Display combined table or info message
        if test_results_data:
            # Show warning if no candidate build configured
            if not has_candidate_build:
                st.warning("⚠️ No candidate nightly build configured for this release. Only stable build test results are available.")

            test_df = pd.DataFrame(test_results_data)
            st.markdown(test_df.to_markdown(index=False))
        else:
            st.info("No test results available for this release")

    with tab7:
        # Task Details Tab - Show detailed task execution information
        tasks_list = status_data.get('tasks', [])

        if not tasks_list:
            st.info("No task execution data available yet")
        else:
            # Handle both dict and list formats
            if isinstance(tasks_list, dict):
                # Old format: Convert to list for consistent handling
                tasks = [{"name": name, "status": status, "started_at": None, "completed_at": None, "result": None}
                        for name, status in tasks_list.items()]
            else:
                # New StateBox format: Already a list
                tasks = tasks_list

            # Sort tasks by workflow order
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

            # Create ordered task list
            ordered_tasks = []
            task_by_name = {t['name']: t for t in tasks}
            for task_name in task_order:
                if task_name in task_by_name:
                    ordered_tasks.append(task_by_name[task_name])

            if not ordered_tasks:
                st.info("No task details available")
            else:
                for task in ordered_tasks:
                    task_name = task['name']
                    status = task.get('status', 'Not Started')
                    started_at = task.get('started_at')
                    completed_at = task.get('completed_at')
                    result = task.get('result')

                    # Status emoji
                    status_emoji = {
                        "Pass": "✅",
                        "Fail": "❌",
                        "In Progress": "🔄",
                        "Not Started": "⭕"
                    }.get(status, "❓")

                    # Expandable task section
                    with st.expander(f"{status_emoji} {task_name.replace('-', ' ').title()} - {status}", expanded=(status == "Fail")):
                        # Task metadata - use consistent info boxes
                        col1, col2, col3 = st.columns(3)

                        with col1:
                            if status == "Pass":
                                st.success(f"**Status:** {status}")
                            elif status == "Fail":
                                st.error(f"**Status:** {status}")
                            elif status == "In Progress":
                                st.warning(f"**Status:** {status}")
                            else:
                                st.info(f"**Status:** {status}")

                        with col2:
                            st.info(f"**Started:** {format_timestamp(started_at)}")

                        with col3:
                            st.info(f"**Completed:** {format_timestamp(completed_at)}")

                        # Duration
                        if started_at and completed_at:
                            duration = calculate_duration(started_at, completed_at)
                            st.info(f"**Duration:** {duration}")

                        st.divider()

                        # Task result (CLI output)
                        if result:
                            st.caption("**Execution Result:**")
                            st.code(result, language="text")
                        else:
                            st.caption("*No execution result recorded*")


def main():
    """Main dashboard application"""

    # Header
    st.markdown('<div class="main-header">📊 Release Progress Dashboard</div>', unsafe_allow_html=True)
    st.markdown("**Track and compare OpenShift z-stream release progress**")
    st.divider()

    # Sidebar - Release Management
    st.sidebar.header("⚙️ Release Management")

    # Initialize session state for releases, input counter, and cached data
    if 'releases' not in st.session_state:
        st.session_state.releases = []
    if 'input_counter' not in st.session_state:
        st.session_state.input_counter = 0
    if 'release_data_cache' not in st.session_state:
        st.session_state.release_data_cache = {}

    # Define callback for adding release
    def add_release_callback():
        new_release = st.session_state.get(f"release_input_field_{st.session_state.input_counter}", "").strip()
        if new_release:
            if new_release not in st.session_state.releases:
                st.session_state.releases.append(new_release)
                # Increment counter to force widget recreation with new key (clearing the value)
                st.session_state.input_counter += 1

    # Add release input with on_change callback
    new_release = st.sidebar.text_input(
        "Release version:",
        placeholder="e.g., 4.19.1",
        help="Enter a z-stream release version (format: X.Y.Z) and press Enter",
        key=f"release_input_field_{st.session_state.input_counter}",
        on_change=add_release_callback
    )

    if st.sidebar.button("➕ Add Release", use_container_width=True):
        if new_release:
            if new_release not in st.session_state.releases:
                st.session_state.releases.append(new_release)
                # Increment counter to force widget recreation with new key (clearing the value)
                st.session_state.input_counter += 1
                st.sidebar.success(f"Added {new_release}")
                st.rerun()
            else:
                st.sidebar.warning(f"{new_release} already added")

    # Show current releases
    st.sidebar.divider()
    st.sidebar.subheader("📋 Tracked Releases")

    if st.session_state.releases:
        # Track which release to remove (if any)
        release_to_remove = None

        for idx, release in enumerate(st.session_state.releases):
            col1, col2 = st.sidebar.columns([3, 1])
            with col1:
                st.write(f"**{release}**")
            with col2:
                if st.button("❌", key=f"remove_{idx}", help=f"Remove {release}"):
                    release_to_remove = release

        # Remove release from tracking and cache
        if release_to_remove:
            st.session_state.releases.remove(release_to_remove)
            # Also remove from cache to free memory
            if release_to_remove in st.session_state.release_data_cache:
                del st.session_state.release_data_cache[release_to_remove]
            st.rerun()
    else:
        st.sidebar.info("No releases added yet")

    # Refresh controls
    st.sidebar.divider()
    st.sidebar.subheader("🔄 Refresh Controls")

    if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
        # Clear both Streamlit cache and session state cache
        st.cache_data.clear()
        st.session_state.release_data_cache = {}
        st.rerun()

    # Clear all releases
    if st.sidebar.button("🗑️ Clear All Releases", use_container_width=True):
        st.session_state.releases = []
        st.session_state.release_data_cache = {}
        st.rerun()

    # Main content
    if not st.session_state.releases:
        st.info("👈 Please add releases using the sidebar to get started")
        st.stop()

    # Load release data (only loads new releases, reuses cached data)
    with st.spinner("🔄 Loading release data from MCP server..."):
        all_release_data = load_release_data(
            st.session_state.releases,
            st.session_state.release_data_cache
        )

    # Update session cache with loaded data
    st.session_state.release_data_cache = all_release_data

    # Filter out failed loads
    valid_releases = {k: v for k, v in all_release_data.items() if v is not None}

    if not valid_releases:
        st.error("❌ Failed to load data for any releases. Please check:")
        st.markdown("""
        1. MCP server is running
        2. Release versions are valid
        3. Network connectivity
        """)
        st.stop()

    # Success message
    st.success(f"✅ Loaded data for {len(valid_releases)} release(s)")

    # Section 1: Release Progress Overview
    st.header("📊 Release Progress Overview")

    progress_fig = create_progress_heatmap(valid_releases, theme='plotly_white')
    st.plotly_chart(progress_fig, use_container_width=True)

    st.info("💡 **Legend:** ✓ = Pass, ▶ = In Progress, ✗ = Fail, ○ = Not Started. Hover over cells to see task details.")

    st.divider()

    # Section 2: Issues & Blockers (New - Phase 1)
    st.divider()

    # Select release to view details
    selected_release = st.selectbox(
        "Select a release to view details:",
        options=list(valid_releases.keys()),
        index=0
    )

    if selected_release:
        release_data = valid_releases[selected_release]
        status_data = release_data['status']

        # Render Issues Section
        render_issues_section(selected_release, status_data)

        st.divider()

        # Section 3: Release Metadata Tabs
        st.header("📋 Release Details")

        # Show overall status and shipment status
        overall_status = status_data.get('overall_status', 'Unknown')
        shipped_status = release_data['shipped'].get('shipped', False)

        # Build status badges HTML
        task_badge = ""
        if overall_status == "Green":
            task_badge = f'<span class="status-badge status-green">Task Status: {overall_status}</span>'
        elif overall_status == "Red":
            task_badge = f'<span class="status-badge status-red">Task Status: {overall_status}</span>'
        else:
            task_badge = f'<span class="status-badge">Task Status: {overall_status}</span>'

        if shipped_status:
            shipment_badge = '<span class="status-badge status-green">Shipment Status: ✅ Shipped</span>'
        else:
            shipment_badge = '<span class="status-badge status-yellow">Shipment Status: ⏳ Not Shipped</span>'

        # Display badges side by side with some spacing
        st.markdown(f'{task_badge}&nbsp;&nbsp;&nbsp;&nbsp;{shipment_badge}', unsafe_allow_html=True)

        st.markdown("---")

        # Render metadata tabs (including new Task Details tab)
        render_metadata_tabs(
            selected_release,
            release_data['metadata'],
            release_data['shipped'],
            status_data
        )

    # Footer
    st.divider()
    st.caption(f"📅 Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    st.caption("📡 Data source: release-tests MCP Server")


if __name__ == "__main__":
    main()
