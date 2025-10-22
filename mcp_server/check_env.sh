#!/bin/bash
#
# Check OAR environment setup for MCP server
#
# Usage:
#   ./mcp_server/check_env.sh
#

echo "================================================"
echo "OAR Environment Validation"
echo "================================================"
echo

# Track status
ALL_GOOD=true

echo "Checking required environment variables (OAR CLI)..."
echo

# Required variables for OAR CLI commands
check_required() {
    local var_name="$1"
    local description="$2"
    if [ -z "${!var_name}" ]; then
        echo "  ❌ $var_name - NOT SET ($description)"
        ALL_GOOD=false
    else
        echo "  ✓ $var_name - set"
    fi
}

check_required "OAR_JWK" "ConfigStore - decrypt config"
check_required "JIRA_TOKEN" "JiraManager - Jira operations"
check_required "GCP_SA_FILE" "WorksheetManager - Google Sheets"
check_required "SLACK_BOT_TOKEN" "NotificationManager - Slack"
check_required "JENKINS_USER" "JenkinsHelper - Jenkins jobs"
check_required "JENKINS_TOKEN" "JenkinsHelper - Jenkins jobs"
check_required "GITLAB_TOKEN" "ShipmentData - GitLab/Konflux"

echo
echo "Checking optional environment variables (OAR CLI)..."
echo

# Optional variables
check_optional() {
    local var_name="$1"
    local description="$2"
    if [ -z "${!var_name}" ]; then
        echo "  ⚠️  $var_name - NOT SET ($description)"
    else
        echo "  ✓ $var_name - set"
    fi
}

check_optional "SLACK_APP_TOKEN" "Slack socket mode"

echo
echo "Checking controller/agent environment variables..."
echo "(These are not required for OAR CLI, but needed for separate components)"
echo

check_optional "GITHUB_TOKEN" "Release detector, job controller"
check_optional "APITOKEN" "Prow/Gangway job triggering"
check_optional "GCS_CRED_FILE" "GCS test result storage"

echo
echo "Checking Kerberos ticket..."
echo

if klist -s 2>/dev/null; then
    echo "  ✓ Kerberos ticket - valid"

    # Show ticket details
    echo
    echo "  Ticket details:"
    klist | grep -E "principal|Valid" | sed 's/^/    /'
else
    echo "  ❌ Kerberos ticket - MISSING or EXPIRED"
    echo
    echo "  Run: kinit your-username@DOMAIN"
    ALL_GOOD=false
fi

echo
echo "Checking CLI installations (required for MCP server)..."
echo

# oar - Main OAR CLI (required)
if command -v oar &> /dev/null; then
    OAR_VERSION=$(oar --version 2>&1 | head -1 || echo "unknown")
    echo "  ✓ oar - installed ($OAR_VERSION)"
else
    echo "  ❌ oar - NOT FOUND"
    echo "     Install: pip3 install -e ."
    ALL_GOOD=false
fi

# oarctl - OAR controller CLI (required - MCP exposes oarctl tools)
if command -v oarctl &> /dev/null; then
    echo "  ✓ oarctl - installed"
else
    echo "  ❌ oarctl - NOT FOUND"
    echo "     Install: pip3 install -e ."
    ALL_GOOD=false
fi

# job - Prow job CLI (required - MCP exposes job_run tool)
if command -v job &> /dev/null; then
    echo "  ✓ job - installed"
else
    echo "  ❌ job - NOT FOUND"
    echo "     Install: cd prow && pip3 install -e ."
    ALL_GOOD=false
fi

# jobctl - Prow controller CLI (required - MCP exposes jobctl tools)
if command -v jobctl &> /dev/null; then
    echo "  ✓ jobctl - installed"
else
    echo "  ❌ jobctl - NOT FOUND"
    echo "     Install: cd prow && pip3 install -e ."
    ALL_GOOD=false
fi

echo
echo "Checking Python dependencies..."
echo

if python3 -c "import fastmcp" 2>/dev/null; then
    echo "  ✓ fastmcp - installed"
else
    echo "  ❌ fastmcp - NOT INSTALLED"
    echo "  Install with: pip3 install fastmcp"
    ALL_GOOD=false
fi

echo
echo "================================================"

if [ "$ALL_GOOD" = true ]; then
    echo "✅ All critical checks passed!"
    echo "================================================"
    echo
    echo "You can now start the MCP server:"
    echo "  ./mcp_server/run_server.sh 0.0.0.0 8080"
    echo
    exit 0
else
    echo "❌ Some critical checks failed"
    echo "================================================"
    echo
    echo "Fix the issues above before starting the MCP server."
    echo
    echo "Common fixes:"
    echo "  1. Add credentials to ~/.bash_profile:"
    echo "     export OAR_JWK=\"your-key\""
    echo "     export JIRA_TOKEN=\"your-token\""
    echo "     # ... other variables ..."
    echo
    echo "  2. Reload environment:"
    echo "     source ~/.bash_profile"
    echo
    echo "  3. Get Kerberos ticket:"
    echo "     kinit your-username@DOMAIN"
    echo
    echo "  4. Install CLI tools:"
    echo "     pip3 install -e .                    # Installs oar, oarctl"
    echo "     cd prow && pip3 install -e . && cd .. # Installs job, jobctl"
    echo
    echo "  5. Install Python dependencies:"
    echo "     pip3 install fastmcp"
    echo
    exit 1
fi
