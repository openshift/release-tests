#!/bin/bash
#
# Launch MCP server with configurable host and port
#
# Usage:
#   ./run_server.sh                    # Default: localhost:8000
#   ./run_server.sh 0.0.0.0 8080      # Listen on all interfaces, port 8080
#

set -e

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default values
HOST="${1:-127.0.0.1}"
PORT="${2:-8000}"

echo "==============================================="
echo "Release Tests MCP Server"
echo "==============================================="
echo "Host: $HOST"
echo "Port: $PORT"
echo "URL:  http://$HOST:$PORT/mcp"
echo "==============================================="
echo

echo "Validating environment..."
echo

# Note: Detailed validation is done by Python code using ConfigStore.validate_environment()
# The server.py will exit with error if critical variables are missing
# This is just a quick pre-flight check for better UX

# Check Kerberos ticket (not checked by Python validation)
if ! klist -s 2>/dev/null; then
    echo "⚠️  WARNING: Kerberos ticket missing or expired"
    echo "   Some OAR commands (Errata Tool, LDAP) require Kerberos"
    echo "   Run: kinit your-username@DOMAIN"
    echo
fi

echo "✓ Pre-flight check passed"
echo "✓ Starting server (full validation will run)..."
echo

# Run server with environment variable configuration
export MCP_HOST="$HOST"
export MCP_PORT="$PORT"

cd "$PROJECT_ROOT"
exec python3 -c "
import os
import sys
sys.path.insert(0, '$PROJECT_ROOT')

from mcp_server.server import mcp

# Get host and port from environment
host = os.environ.get('MCP_HOST', '127.0.0.1')
port = int(os.environ.get('MCP_PORT', '8000'))

print(f'Server starting on http://{host}:{port}')
mcp.run(transport='http', host=host, port=port)
"
