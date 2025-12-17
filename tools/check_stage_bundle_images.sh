#!/bin/bash
#
# check_stage_bundle_images.sh - Troubleshooting tool for stage testing failures
#
# This script verifies that the latest operator bundle images (channel heads)
# from the FBC catalog are available in registry.stage.redhat.io
#
# NOTE: Only checks the latest bundle for each operator channel, not all
#       historical versions, as OLM only installs the latest bundles.
#
# WHEN TO USE:
#   Run this script when stage testing job fails to check if missing bundle
#   images are the root cause. If bundles are missing, report to ART team.
#
# USAGE:
#   ./check_stage_bundle_images.sh <ocp-version>
#
# EXAMPLES:
#   ./check_stage_bundle_images.sh 4.19
#   ./check_stage_bundle_images.sh 4.20
#
# PREREQUISITES:
#   - opm (OpenShift Package Manager)
#   - oc (OpenShift CLI)
#   - jq (JSON processor)
#

set -e

# Check if version argument is provided
if [ -z "$1" ]; then
  echo "Error: OCP version is required"
  echo ""
  echo "Usage: $0 <ocp-version>"
  echo ""
  echo "Examples:"
  echo "  $0 4.19"
  echo "  $0 4.20"
  echo "  $0 4.21"
  echo ""
  exit 1
fi

OCP_VERSION="$1"

# Validate version format (should be like 4.19, 4.20, etc.)
if ! echo "$OCP_VERSION" | grep -qE '^4\.[0-9]+$'; then
  echo "Error: Invalid OCP version format: $OCP_VERSION"
  echo "Expected format: 4.XX (e.g., 4.19, 4.20)"
  exit 1
fi

INDEX_IMAGE="quay.io/openshift-art/stage-fbc-fragments:ocp-${OCP_VERSION}"
OUTPUT_DIR="/tmp/stage-bundle-check-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "Checking bundle images availability"
echo "OCP Version: $OCP_VERSION"
echo "Index: $INDEX_IMAGE"
echo "Target: registry.stage.redhat.io"
echo "=========================================="
echo ""

# Check if required commands are available
MISSING_TOOLS=()
command -v opm &> /dev/null || MISSING_TOOLS+=("opm")
command -v oc &> /dev/null || MISSING_TOOLS+=("oc")
command -v jq &> /dev/null || MISSING_TOOLS+=("jq")

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
  echo "Error: Required tools are missing: ${MISSING_TOOLS[*]}"
  echo ""
  echo "Installation instructions:"
  echo ""

  for tool in "${MISSING_TOOLS[@]}"; do
    case $tool in
      opm)
        echo "• opm (OpenShift Package Manager):"
        echo "  Download from: https://github.com/operator-framework/operator-registry/releases"
        echo "  Example:"
        echo "    VERSION=v1.43.0"
        echo "    curl -LO https://github.com/operator-framework/operator-registry/releases/download/\${VERSION}/linux-amd64-opm"
        echo "    chmod +x linux-amd64-opm"
        echo "    sudo mv linux-amd64-opm /usr/local/bin/opm"
        echo ""
        ;;
      oc)
        echo "• oc (OpenShift CLI):"
        echo "  Download from: https://mirror.openshift.com/pub/openshift-v4/clients/ocp/"
        echo "  Example:"
        echo "    curl -LO https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/openshift-client-linux.tar.gz"
        echo "    tar xvf openshift-client-linux.tar.gz"
        echo "    sudo mv oc /usr/local/bin/"
        echo ""
        ;;
      jq)
        echo "• jq (JSON processor):"
        echo "  Install via package manager:"
        echo "    macOS:  brew install jq"
        echo "    RHEL:   sudo yum install jq"
        echo "    Ubuntu: sudo apt-get install jq"
        echo ""
        ;;
    esac
  done

  exit 1
fi

# Step 1: Render FBC catalog and extract latest bundle images from each channel
echo "[1/4] Extracting latest bundle images from FBC catalog..."
if ! opm render "$INDEX_IMAGE" > "$OUTPUT_DIR/catalog.json" 2>"$OUTPUT_DIR/opm_error.log"; then
  echo "Error: Failed to render FBC catalog"
  echo "Details:"
  cat "$OUTPUT_DIR/opm_error.log"
  exit 1
fi

# Extract channel heads (latest bundles) from FBC catalog
# For each channel, find the head bundle (not replaced by any other)
cat "$OUTPUT_DIR/catalog.json" | jq -r '
  # First pass: collect all bundles with their images
  [.[] | select(.schema == "olm.bundle") | {name: .name, image: .image}] as $bundles |

  # Second pass: for each channel, find head bundles
  [.[] | select(.schema == "olm.channel") |
    # Get all bundle names that replace others
    (.entries // [] | map(.replaces // empty)) as $replaced |
    # Find bundles not in the replaced list (these are heads)
    .entries // [] | map(select(.name as $n | $replaced | index($n) | not)) | .[].name
  ] as $heads |

  # Map head bundle names to images
  $bundles[] | select(.name as $n | $heads | index($n)) | .image
' | grep 'registry.redhat.io' | sort -u > "$OUTPUT_DIR/all_bundles.txt"

TOTAL_BUNDLES=$(wc -l < "$OUTPUT_DIR/all_bundles.txt")
echo "✓ Found $TOTAL_BUNDLES latest bundle images (channel heads)"
echo ""

if [ "$TOTAL_BUNDLES" -eq 0 ]; then
  echo "Warning: No latest bundle images found in FBC catalog"
  echo "This might indicate an issue with the index image or FBC catalog"
  exit 0
fi

# Step 2: Check each bundle in stage registry
echo "[2/4] Checking bundle availability in registry.stage.redhat.io..."
echo ""

MISSING_FILE="$OUTPUT_DIR/missing_bundles.txt"
AVAILABLE_FILE="$OUTPUT_DIR/available_bundles.txt"
ALL_BUNDLES_FILE="$OUTPUT_DIR/all_bundles.txt"
> "$MISSING_FILE"
> "$AVAILABLE_FILE"

CHECKED=0
MISSING_COUNT=0
AVAILABLE_COUNT=0

while IFS= read -r original_image; do
  CHECKED=$((CHECKED + 1))

  # Replace registry.redhat.io with registry.stage.redhat.io
  stage_image=$(echo "$original_image" | sed 's|registry\.redhat\.io|registry.stage.redhat.io|')

  # Extract package name for display
  package_name=$(echo "$original_image" | sed 's|.*ose-\(.*\)-bundle@.*|\1|')

  printf "[%d/%d] %s\n" "$CHECKED" "$TOTAL_BUNDLES" "$package_name"
  printf "  Original: %s\n" "$original_image"
  printf "  Stage:    %s\n" "$stage_image"

  # Check if image exists in stage registry
  if oc image info "$stage_image" &>/dev/null; then
    echo "  Status:   ✓ Available"
    echo "$original_image|$stage_image|AVAILABLE" >> "$AVAILABLE_FILE"
    AVAILABLE_COUNT=$((AVAILABLE_COUNT + 1))
  else
    echo "  Status:   ✗ MISSING"
    echo "$original_image|$stage_image|MISSING" >> "$MISSING_FILE"
    MISSING_COUNT=$((MISSING_COUNT + 1))
  fi
  echo ""
done < "$ALL_BUNDLES_FILE"

# Step 3: Generate summary
echo "[3/4] Summary"
echo "=========================================="
echo "Total bundles checked: $TOTAL_BUNDLES"
echo "Available in stage:    $AVAILABLE_COUNT"
echo "Missing from stage:    $MISSING_COUNT"
echo ""

# Step 4: Generate reports
echo "[4/4] Generating reports..."

if [ "$MISSING_COUNT" -gt 0 ]; then
  echo ""
  echo "Missing bundle images (original registry.redhat.io references):"
  echo "-----------------------------------------------------------"
  cat "$MISSING_FILE" | cut -d'|' -f1

  echo ""
  echo "Missing packages by operator:"
  echo "-----------------------------------------------------------"
  cat "$MISSING_FILE" | cut -d'|' -f1 | sed 's|.*ose-\(.*\)-bundle@.*|\1|' | sort -u

  echo ""
  echo "Detailed report saved to:"
  echo "  Latest bundles:   $ALL_BUNDLES_FILE"
  echo "  Available:        $AVAILABLE_FILE"
  echo "  Missing:          $MISSING_FILE"
  echo ""

  # Create human-readable missing report
  echo "# Missing Bundle Images from registry.stage.redhat.io" > "$OUTPUT_DIR/MISSING_REPORT.txt"
  echo "# Generated: $(date)" >> "$OUTPUT_DIR/MISSING_REPORT.txt"
  echo "# OCP Version: $OCP_VERSION" >> "$OUTPUT_DIR/MISSING_REPORT.txt"
  echo "# Total missing: $MISSING_COUNT" >> "$OUTPUT_DIR/MISSING_REPORT.txt"
  echo "" >> "$OUTPUT_DIR/MISSING_REPORT.txt"

  while IFS='|' read -r original stage status; do
    package=$(echo "$original" | sed 's|.*ose-\(.*\)-bundle@.*|\1|')
    digest=$(echo "$original" | sed 's|.*@\(sha256:.*\)|\1|')
    echo "Operator: $package" >> "$OUTPUT_DIR/MISSING_REPORT.txt"
    echo "  Original: $original" >> "$OUTPUT_DIR/MISSING_REPORT.txt"
    echo "  Stage:    $stage" >> "$OUTPUT_DIR/MISSING_REPORT.txt"
    echo "  Digest:   $digest" >> "$OUTPUT_DIR/MISSING_REPORT.txt"
    echo "" >> "$OUTPUT_DIR/MISSING_REPORT.txt"
  done < "$MISSING_FILE"

  echo "  Human report:     $OUTPUT_DIR/MISSING_REPORT.txt"
  echo ""
  echo "✗ FAILED: Some bundle images are missing from stage registry"
  echo ""
  echo "Action required:"
  echo "  1. Report to ART team - bundle images not mirrored to registry.stage.redhat.io"
  echo "  2. File ticket with list of missing digests"
  echo "  3. Share the report: $OUTPUT_DIR/MISSING_REPORT.txt"
  exit 1
else
  echo "✓ SUCCESS: All bundle images are available in registry.stage.redhat.io"
  echo ""
  echo "Report saved to: $OUTPUT_DIR"
fi
