#!/usr/bin/env python3
"""
Development entry point for MCP server with Inspector.
Use this with `fastmcp dev server_dev.py`.
"""

import os
import sys

# Ensure all required environment variables are set before importing
# This allows fastmcp dev to work even without full validation
os.environ.setdefault('OAR_JWK', 'dummy_key_for_dev')
os.environ.setdefault('JIRA_TOKEN', 'dummy_token_for_dev')
os.environ.setdefault('GCP_SA_FILE', '/tmp/dummy_gcp_sa.json')

# Import the mcp object from server.py
from server import mcp

# The mcp object is automatically discovered by fastmcp dev
# No need to call mcp.run() - fastmcp handles that
