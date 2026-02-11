#!/bin/bash
# Install the SHIP Status Dashboard component-monitor binary from the
# pre-built container image. Requires podman and sudo.

set -euo pipefail

IMAGE="quay.io/openshiftci/component-monitor:latest"
INSTALL_PATH="/usr/local/bin/component-monitor"

echo "==> Pulling component-monitor image..."
sudo podman pull "${IMAGE}"

echo "==> Extracting binary from image..."
CONTAINER=$(sudo podman create "${IMAGE}")
trap "sudo podman rm ${CONTAINER} > /dev/null" EXIT
sudo podman cp "${CONTAINER}:./component-monitor" /tmp/component-monitor

echo "==> Installing to ${INSTALL_PATH}..."
sudo install -m 0755 /tmp/component-monitor "${INSTALL_PATH}"
rm -f /tmp/component-monitor

echo "==> Installed successfully:"
ls -lh "${INSTALL_PATH}"
component-monitor --help 2>&1 | head -1 || true
