#!/usr/bin/env python3
"""
Categorize OpenShift test failures using pattern matching.

Usage:
    python3 categorize-failure.py < failures.json

Input JSON format:
    [
        {
            "test_name": "...",
            "error_message": "...",
            "stack_trace": "..."
        },
        ...
    ]

Output: JSON with categorization added to each failure
"""

import json
import re
import sys
from typing import Dict, List, Optional

# Failure pattern database with regex, category, and confidence
FAILURE_PATTERNS = {
    # Infrastructure failures
    "image_pull_backoff": {
        "regex": r"(ImagePullBackOff|ErrImagePull|[Ff]ailed to pull image|[Bb]ack-off pulling image)",
        "category": "infrastructure",
        "subcategory": "image-registry",
        "confidence": 0.95,
        "description": "Container image pull failure"
    },
    "image_pull_auth": {
        "regex": r"(unauthorized.*pull|pull access denied|authentication required.*pull)",
        "category": "infrastructure",
        "subcategory": "image-registry-auth",
        "confidence": 0.98,
        "description": "Image pull authentication failure"
    },
    "crash_loop": {
        "regex": r"(CrashLoopBackOff|[Bb]ack-off restarting failed container)",
        "category": "application",
        "subcategory": "container-crash",
        "confidence": 0.90,
        "description": "Container repeatedly crashing"
    },
    "oom_killed": {
        "regex": r"(OOMKilled|[Oo]ut of memory|[Mm]emory limit exceeded|exit code 137)",
        "category": "resource",
        "subcategory": "memory",
        "confidence": 0.98,
        "description": "Container killed due to out of memory"
    },

    # Operator failures
    "operator_degraded": {
        "regex": r"clusteroperator[/\s]+(\w+)\s+is\s+degraded",
        "category": "operator",
        "subcategory": "$1",  # Capture group - operator name
        "confidence": 0.95,
        "description": "Cluster operator in degraded state"
    },
    "operator_unavailable": {
        "regex": r"clusteroperator[/\s]+(\w+).*[Aa]vailable[=:\s]+[Ff]alse",
        "category": "operator",
        "subcategory": "$1",
        "confidence": 0.92,
        "description": "Cluster operator not available"
    },
    "reconcile_error": {
        "regex": r"(failed to reconcile|error syncing|reconciliation failed)",
        "category": "operator",
        "subcategory": "reconciliation",
        "confidence": 0.85,
        "description": "Operator reconciliation error"
    },

    # Networking failures
    "dns_failure": {
        "regex": r"(no such host|DNS lookup failed|name resolution.*failed|lookup.*on.*53.*no such host)",
        "category": "networking",
        "subcategory": "dns",
        "confidence": 0.90,
        "description": "DNS resolution failure"
    },
    "connection_refused": {
        "regex": r"(connection refused|dial tcp.*connection refused)",
        "category": "networking",
        "subcategory": "connectivity",
        "confidence": 0.85,
        "description": "Connection refused (service not ready or blocked)"
    },
    "connection_timeout": {
        "regex": r"(i/o timeout|dial tcp.*timeout|context deadline exceeded|connection.*timed out)",
        "category": "networking",
        "subcategory": "timeout",
        "confidence": 0.80,
        "description": "Connection timeout"
    },
    "route_503": {
        "regex": r"(503 Service Unavailable|upstream connect error)",
        "category": "networking",
        "subcategory": "route",
        "confidence": 0.88,
        "description": "Route/Ingress backend unavailable"
    },

    # Storage failures
    "pvc_pending": {
        "regex": r"(PersistentVolumeClaim.*[Pp]ending|waiting for.*volume.*created|no persistent volumes available)",
        "category": "storage",
        "subcategory": "pvc",
        "confidence": 0.93,
        "description": "PVC stuck in pending state"
    },
    "storage_class_not_found": {
        "regex": r"StorageClass.*not found",
        "category": "storage",
        "subcategory": "storageclass",
        "confidence": 0.97,
        "description": "StorageClass does not exist"
    },
    "volume_mount_failed": {
        "regex": r"(failed to mount volume|AttachVolume\.Attach failed|MountVolume\.SetUp failed)",
        "category": "storage",
        "subcategory": "volume-mount",
        "confidence": 0.92,
        "description": "Volume mount failure"
    },

    # Scheduling failures
    "insufficient_resources": {
        "regex": r"(\d+/\d+ nodes are available.*Insufficient (cpu|memory)|insufficient (cpu|memory))",
        "category": "scheduling",
        "subcategory": "resources",
        "confidence": 0.95,
        "description": "Insufficient cluster resources"
    },
    "failed_scheduling": {
        "regex": r"(FailedScheduling|pod.*cannot be scheduled)",
        "category": "scheduling",
        "subcategory": "general",
        "confidence": 0.80,
        "description": "Pod scheduling failure"
    },

    # Auth failures
    "forbidden": {
        "regex": r"([Ff]orbidden.*cannot|User.*cannot.*resource|Error from server \(Forbidden\))",
        "category": "authorization",
        "subcategory": "rbac",
        "confidence": 0.93,
        "description": "RBAC permission denied"
    },
    "unauthorized": {
        "regex": r"([Uu]nauthorized|authentication.*failed|invalid.*token)",
        "category": "authentication",
        "subcategory": "auth",
        "confidence": 0.90,
        "description": "Authentication failure"
    },
    "scc_violation": {
        "regex": r"(unable to validate.*security context constraint|unable to admit.*violates.*SCC)",
        "category": "authorization",
        "subcategory": "scc",
        "confidence": 0.95,
        "description": "Security Context Constraint violation"
    },

    # Test timeouts
    "test_timeout": {
        "regex": r"(Test timed out|test.*timeout|FAIL:.*timed out after)",
        "category": "test",
        "subcategory": "timeout",
        "confidence": 0.70,  # Lower confidence - could be product or test issue
        "description": "Test timeout (could be infrastructure or product)"
    },
    "condition_timeout": {
        "regex": r"timeout waiting for condition",
        "category": "timeout",
        "subcategory": "condition",
        "confidence": 0.75,
        "description": "Timeout waiting for condition"
    },

    # Machine/Node failures
    "machine_provisioning_failed": {
        "regex": r"(Machine.*[Ff]ailed|failed to create machine|cloud provider.*error)",
        "category": "infrastructure",
        "subcategory": "machine-api",
        "confidence": 0.88,
        "description": "Machine provisioning failure"
    },
    "node_not_ready": {
        "regex": r"(node.*[Nn]ot[Rr]eady|node.*is not ready)",
        "category": "infrastructure",
        "subcategory": "node",
        "confidence": 0.85,
        "description": "Node in NotReady state"
    },
}

def categorize_failure(error_message: str, stack_trace: str = "") -> Optional[Dict]:
    """
    Categorize a failure based on error message and stack trace.

    Args:
        error_message: Error message from test failure
        stack_trace: Stack trace (optional)

    Returns:
        Dictionary with categorization info or None if no match
    """
    # Combine error message and stack trace for searching
    search_text = f"{error_message}\n{stack_trace}"

    # Try each pattern
    for pattern_name, pattern_info in FAILURE_PATTERNS.items():
        match = re.search(pattern_info["regex"], search_text, re.IGNORECASE | re.MULTILINE)
        if match:
            # Handle capture groups in subcategory (e.g., operator name)
            subcategory = pattern_info["subcategory"]
            if "$1" in subcategory and match.groups():
                subcategory = match.group(1)

            return {
                "pattern": pattern_name,
                "category": pattern_info["category"],
                "subcategory": subcategory,
                "confidence": pattern_info["confidence"],
                "description": pattern_info["description"],
                "matched_text": match.group(0)[:200]  # First 200 chars of match
            }

    return None

def determine_likely_cause(categorization: Dict) -> Dict:
    """
    Determine likely root cause based on categorization.

    Returns:
        Dictionary with cause assessment
    """
    if not categorization:
        return {
            "likely_cause": "unknown",
            "product_bug_probability": 0.5,
            "test_bug_probability": 0.3,
            "infrastructure_probability": 0.2
        }

    category = categorization["category"]
    subcategory = categorization["subcategory"]

    # Heuristics for cause determination
    if category in ["infrastructure", "scheduling"]:
        return {
            "likely_cause": "infrastructure",
            "product_bug_probability": 0.2,
            "test_bug_probability": 0.1,
            "infrastructure_probability": 0.7
        }
    elif category == "operator":
        return {
            "likely_cause": "product_bug",
            "product_bug_probability": 0.7,
            "test_bug_probability": 0.1,
            "infrastructure_probability": 0.2
        }
    elif category == "test" or subcategory == "timeout":
        return {
            "likely_cause": "test_automation_or_infrastructure",
            "product_bug_probability": 0.3,
            "test_bug_probability": 0.4,
            "infrastructure_probability": 0.3
        }
    elif category in ["networking", "storage", "authorization", "authentication"]:
        return {
            "likely_cause": "product_bug",
            "product_bug_probability": 0.6,
            "test_bug_probability": 0.1,
            "infrastructure_probability": 0.3
        }
    else:
        return {
            "likely_cause": "product_bug",
            "product_bug_probability": 0.6,
            "test_bug_probability": 0.2,
            "infrastructure_probability": 0.2
        }

def main():
    """Main entry point."""
    try:
        # Read failures from stdin
        failures = json.load(sys.stdin)

        if not isinstance(failures, list):
            failures = [failures]

        categorized = []

        for failure in failures:
            test_name = failure.get("test_name", "unknown")
            error_message = failure.get("error_message", "")
            stack_trace = failure.get("stack_trace", "")

            # Categorize
            categorization = categorize_failure(error_message, stack_trace)

            # Determine cause
            cause = determine_likely_cause(categorization)

            result = {
                "test_name": test_name,
                "error_message": error_message[:500],  # Truncate for output
                "categorization": categorization if categorization else {
                    "pattern": "unknown",
                    "category": "uncategorized",
                    "subcategory": "unknown",
                    "confidence": 0.0,
                    "description": "No matching pattern found"
                },
                "likely_cause": cause
            }

            categorized.append(result)

        # Output categorized failures
        print(json.dumps(categorized, indent=2))

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()