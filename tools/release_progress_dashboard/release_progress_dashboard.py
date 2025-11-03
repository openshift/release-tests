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
        tasks = data['status'].get('tasks', {})

        row_data = []
        hover_row = []
        text_row = []

        for task in task_order:
            status = tasks.get(task, "Not Started")
            row_data.append(status_map.get(status, 1))
            hover_row.append(f"<b>{release}</b><br>{task.replace('-', ' ').title()}<br>Status: <b>{status}</b>")
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


def render_metadata_tabs(release: str, metadata: Dict[str, Any], shipped_data: Dict[str, Any]):
    """
    Render tabbed pane with release metadata

    Args:
        release: Release version
        metadata: Release metadata dictionary
        shipped_data: Shipment status dictionary
    """
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 Advisories",
        "📦 Candidate Builds",
        "🎫 Jira Ticket",
        "🚢 Shipment",
        "📅 Release Info"
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
        shipped = shipped_data.get('shipped', False)
        shipment_mr = metadata.get('shipment_mr', '')
        details = shipped_data.get('details', {})

        # Build shipment data table
        shipment_data = []

        # Add shipped status
        shipment_data.append({
            "Field": "Shipped",
            "Value": "✅ Yes" if shipped else "⏳ No"
        })

        # Add shipment MR if available
        if shipment_mr:
            # Make it a clickable link (GitLab MR URL)
            shipment_data.append({
                "Field": "Shipment MR",
                "Value": f"[{shipment_mr}]({shipment_mr})"
            })

            # Add MR-related details
            if 'mr_merged' in details:
                shipment_data.append({
                    "Field": "MR Merged",
                    "Value": "✅ Yes" if details['mr_merged'] else "❌ No"
                })
            if 'mr_state' in details:
                shipment_data.append({
                    "Field": "MR State",
                    "Value": str(details['mr_state'])
                })
            if 'pipeline_status' in details:
                shipment_data.append({
                    "Field": "Pipeline Status",
                    "Value": str(details['pipeline_status'])
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

    # Add release input
    new_release = st.sidebar.text_input(
        "Release version:",
        placeholder="e.g., 4.19.1",
        help="Enter a z-stream release version (format: X.Y.Z)",
        key=f"release_input_field_{st.session_state.input_counter}"
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
        else:
            st.sidebar.error("Please enter a release version")

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

    # Section 2: Release Metadata Tabs
    st.header("📋 Release Details")

    # Select release to view
    selected_release = st.selectbox(
        "Select a release to view details:",
        options=list(valid_releases.keys()),
        index=0
    )

    if selected_release:
        release_data = valid_releases[selected_release]

        # Show overall status
        overall_status = release_data['status'].get('overall_status', 'Unknown')
        if overall_status == "Green":
            st.markdown(f'<span class="status-badge status-green">Overall Status: {overall_status}</span>',
                       unsafe_allow_html=True)
        elif overall_status == "Red":
            st.markdown(f'<span class="status-badge status-red">Overall Status: {overall_status}</span>',
                       unsafe_allow_html=True)
        else:
            st.info(f"Overall Status: {overall_status}")

        st.markdown("---")

        # Render metadata tabs
        render_metadata_tabs(
            selected_release,
            release_data['metadata'],
            release_data['shipped']
        )

    # Footer
    st.divider()
    st.caption(f"📅 Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    st.caption("📡 Data source: release-tests MCP Server")


if __name__ == "__main__":
    main()
