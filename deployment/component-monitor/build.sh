#!/bin/bash
# Build the SHIP Status Dashboard component-monitor binary from source
# and install it to /usr/local/bin (requires sudo).

set -euo pipefail

REPO_URL="https://github.com/openshift-eng/ship-status-dash.git"
CLONE_DIR=$(mktemp -d)
INSTALL_PATH="/usr/local/bin/component-monitor"

trap "rm -rf ${CLONE_DIR}" EXIT

echo "==> Cloning ship-status-dash into temp directory..."
git clone --depth 1 "${REPO_URL}" "${CLONE_DIR}"

echo "==> Building component-monitor binary..."
cd "${CLONE_DIR}"
go build -mod=vendor -o component-monitor ./cmd/component-monitor

echo "==> Installing to ${INSTALL_PATH} (requires sudo)..."
sudo install -m 0755 component-monitor "${INSTALL_PATH}"

echo "==> Installed successfully:"
ls -lh "${INSTALL_PATH}"
component-monitor --help 2>&1 | head -1 || true
