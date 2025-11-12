#!/usr/bin/env python3
"""
Release Tests MCP Server

Exposes OAR, oarctl, job, and jobctl commands as MCP tools for use by AI agents.
Runs in SSE mode - accessible as HTTP server for remote access.

Tools exposed:
- 14 OAR CLI commands (create-test-report, take-ownership, update-bug-list, etc.)
- 2 OAR controller commands (start-release-detector, jira-notificator)
- 1 job command (run)
- 5 jobctl commands (start-controller, trigger-jobs-for-build, start-aggregator, etc.)
- 4 configuration tools (get-release-metadata, is-release-shipped, get-release-status, update-task-status)
- 3 cache management tools (mcp_cache_stats, mcp_cache_invalidate, mcp_cache_warm)
- 3 generic command runners (oar_run_command, oarctl_run_command, jobctl_run_command)
- 1 help/discovery tool (get_command_help)

Total: 33 tools
"""

import subprocess
import sys
import os
import logging
import json
import shlex
import time
from typing import Optional
from threading import RLock
from dataclasses import dataclass, field
from datetime import datetime
from fastmcp import FastMCP
from cachetools import TTLCache

# Import OAR validation
# Add parent directory to path to import oar modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from oar.core.configstore import ConfigStore
from oar.core.operators import ReleaseShipmentOperator
from oar.core.worksheet import WorksheetManager
from oar.core.const import (
    LABEL_OVERALL_STATUS,
    LABEL_TASK_OWNERSHIP,
    LABEL_TASK_IMAGE_CONSISTENCY_TEST,
    LABEL_TASK_NIGHTLY_BUILD_TEST,
    LABEL_TASK_SIGNED_BUILD_TEST,
    LABEL_TASK_CHECK_CVE_TRACKERS,
    LABEL_TASK_PUSH_TO_CDN,
    LABEL_TASK_STAGE_TEST,
    LABEL_TASK_PAYLOAD_IMAGE_VERIFY,
    LABEL_TASK_CHANGE_AD_STATUS,
    TASK_STATUS_INPROGRESS,
    TASK_STATUS_PASS,
    TASK_STATUS_FAIL,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create MCP server with SSE transport
mcp = FastMCP("release-tests")


# ============================================================================
# ConfigStore Cache Implementation
# ============================================================================

@dataclass
class CacheMetrics:
    """
    Tracks cache performance metrics.

    Attributes:
        hits: Number of cache hits
        misses: Number of cache misses
        evictions: Number of TTL-based evictions
        manual_invalidations: Number of manual invalidations
    """
    hits: int = field(default=0)
    misses: int = field(default=0)
    evictions: int = field(default=0)
    manual_invalidations: int = field(default=0)

    def hit_rate(self) -> float:
        """Calculate cache hit rate as a percentage."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def to_dict(self) -> dict:
        """Convert metrics to dictionary for JSON serialization."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "manual_invalidations": self.manual_invalidations,
            "hit_rate": f"{self.hit_rate():.2f}%",
            "total_requests": self.hits + self.misses
        }


class ConfigStoreCache:
    """
    Thread-safe TTL cache for ConfigStore instances using cachetools.

    Design:
    - Cache scope: Per z-stream release (e.g., "4.19.1")
    - TTL: 7 days (aligns with weekly release schedule)
    - Max size: 50 entries (LRU eviction via TTLCache)
    - Thread-safe: Uses RLock for concurrent access

    Performance:
    - Cache hit: <10ms (no JWE decryption, no GitHub HTTP request)
    - Cache miss: ~1000ms (full ConfigStore initialization)

    Implementation:
    - Uses cachetools.TTLCache for built-in TTL + LRU support
    - Tracks custom metrics (hits, misses, evictions, invalidations)
    - ConfigStore instances are immutable after ART announces release

    Usage:
        cache = ConfigStoreCache()
        cs = cache.get("4.19.1")  # Returns cached or creates new
        cache.invalidate("4.19.1")  # Remove specific entry
        cache.clear()  # Remove all entries
        stats = cache.stats()  # Get cache statistics
    """

    def __init__(self, max_size: int = 50, ttl_seconds: int = 7 * 24 * 60 * 60):
        """
        Initialize ConfigStore cache.

        Args:
            max_size: Maximum number of cached entries (default: 50)
            ttl_seconds: Time-to-live in seconds (default: 7 days = 604800s)
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache = TTLCache(maxsize=max_size, ttl=ttl_seconds)
        self._lock = RLock()
        self.metrics = CacheMetrics()

        logger.info(f"ConfigStoreCache initialized: max_size={max_size}, ttl={ttl_seconds}s ({ttl_seconds // 86400} days)")

    def get(self, release: str) -> ConfigStore:
        """
        Get ConfigStore for a release (cached or create new).

        Args:
            release: Z-stream release version (e.g., "4.19.1")

        Returns:
            ConfigStore instance

        This method is thread-safe and implements TTL-based expiration + LRU eviction.
        """
        with self._lock:
            # Check if entry exists in cache
            if release in self._cache:
                # Cache hit
                self.metrics.hits += 1
                logger.debug(f"Cache HIT for release {release}")
                return self._cache[release]

            # Cache miss - create new ConfigStore
            logger.info(f"Cache MISS for release {release}, creating new ConfigStore")
            self.metrics.misses += 1

            # Track cache size before adding (to detect evictions)
            size_before = len(self._cache)

            start_time = time.time()
            configstore = ConfigStore(release)
            elapsed = time.time() - start_time

            logger.info(f"ConfigStore created for {release} in {elapsed:.2f}s")

            # Add to cache (TTLCache handles TTL and LRU automatically)
            self._cache[release] = configstore

            # Check if eviction occurred (size didn't increase when at max)
            if size_before == self.max_size and len(self._cache) == self.max_size:
                self.metrics.evictions += 1
                logger.info(f"Cache full, LRU entry evicted (max_size={self.max_size})")

            return configstore

    def invalidate(self, release: Optional[str] = None):
        """
        Invalidate cache entry for a specific release or all entries.

        Args:
            release: Release to invalidate (None = invalidate all)
        """
        with self._lock:
            if release is None:
                # Clear all cache
                count = len(self._cache)
                self._cache.clear()
                self.metrics.manual_invalidations += count
                logger.info(f"Cache cleared: {count} entries invalidated")
            elif release in self._cache:
                del self._cache[release]
                self.metrics.manual_invalidations += 1
                logger.info(f"Cache entry invalidated: {release}")
            else:
                logger.warning(f"Cache invalidation requested for non-existent release: {release}")

    def warm(self, releases: list[str]):
        """
        Pre-populate cache with ConfigStore instances for multiple releases.

        Args:
            releases: List of release versions to warm cache with
        """
        logger.info(f"Warming cache with {len(releases)} releases: {releases}")

        for release in releases:
            try:
                self.get(release)  # This will cache it if not already cached
                logger.info(f"Cache warmed: {release}")
            except Exception as e:
                logger.error(f"Failed to warm cache for release {release}: {e}")

    def stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache metrics and entry details
        """
        with self._lock:
            entries = []
            current_time = datetime.now()

            for release in self._cache.keys():
                # TTLCache doesn't expose timestamps, so we can't show age
                # We can only show that the entry exists and is valid
                entries.append({
                    "release": release,
                    "cached": True,
                    "ttl_human": f"{self.ttl_seconds // 86400} days"
                })

            return {
                "metrics": self.metrics.to_dict(),
                "cache_size": len(self._cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "ttl_human": f"{self.ttl_seconds // 86400} days",
                "entries": entries
            }


# Global cache instance
_configstore_cache = ConfigStoreCache()


def get_cached_configstore(release: str) -> ConfigStore:
    """
    Get ConfigStore instance for a release (cached or create new).

    This is the main entry point for accessing ConfigStore in MCP tools.
    Uses global cache instance to avoid repeated JWE decryption and GitHub requests.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        ConfigStore instance (cached or newly created)

    Performance:
        - First call (cache miss): ~1000ms (full initialization)
          - JWE decryption: ~5-10ms
          - GitHub HTTP request: ~300-800ms
          - YAML parsing: ~10-50ms
        - Subsequent calls (cache hit): <10ms (direct memory access)

    Example:
        >>> cs = get_cached_configstore("4.19.1")
        >>> advisories = cs.get_advisories()
    """
    return _configstore_cache.get(release)


# ============================================================================
# Helper Functions
# ============================================================================

def run_cli_command(cli: str, args: list[str], timeout: int = 600) -> dict:
    """
    Run a CLI command and return structured result.

    This is a generic command runner for all CLI tools (oar, oarctl, job, jobctl).

    Args:
        cli: CLI tool name (e.g., "oar", "oarctl", "job", "jobctl")
        args: Command arguments
        timeout: Command timeout in seconds (default: 10 minutes)

    Returns:
        dict with keys: success, stdout, stderr, exit_code
    """
    cmd = [cli] + args
    logger.info(f"Executing: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Redirect stderr to stdout
            text=True,
            timeout=timeout,
            env=os.environ.copy()  # Inherit all environment variables
        )

        logger.info(f"Command completed with exit code: {result.returncode}")

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": "",  # Empty since stderr is redirected to stdout
            "exit_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after {timeout} seconds")
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "exit_code": -1
        }
    except Exception as e:
        logger.error(f"Command failed with exception: {e}")
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1
        }


def run_oar_command(args: list[str], timeout: int = 600) -> dict:
    """Run OAR CLI command."""
    return run_cli_command("oar", args, timeout)


def run_oarctl_command(args: list[str], timeout: int = 600) -> dict:
    """Run oarctl command."""
    return run_cli_command("oarctl", args, timeout)


def run_job_command(args: list[str], timeout: int = 600) -> dict:
    """Run job command."""
    return run_cli_command("job", args, timeout)


def run_jobctl_command(args: list[str], timeout: int = 600) -> dict:
    """Run jobctl command."""
    return run_cli_command("jobctl", args, timeout)


def format_result(result: dict) -> str:
    """
    Format command result for display to user.

    Args:
        result: Command result dict with success, stdout, stderr, exit_code keys

    Returns:
        Formatted string with success indicator and output
    """
    if result["success"]:
        output = result["stdout"].strip()
        return f"✓ Command succeeded\n\n{output}" if output else "✓ Command succeeded"
    else:
        # Since stderr is redirected to stdout, check stdout first, then stderr (for exceptions)
        error = result["stdout"].strip() or result["stderr"].strip() or "Unknown error"
        return f"✗ Command failed (exit code {result['exit_code']})\n\n{error}"


# ============================================================================
# Read-Only Tools (Safe Operations)
# ============================================================================

@mcp.tool()
def oar_check_greenwave_cvp_tests(release: str) -> str:
    """
    Check Greenwave CVP test status for a z-stream release.

    This is a READ-ONLY operation - it only queries test status.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        Test status information from Greenwave
    """
    result = run_oar_command(["-r", release, "check-greenwave-cvp-tests"])
    return format_result(result)


@mcp.tool()
def oar_check_cve_tracker_bug(release: str) -> str:
    """
    Check CVE tracker bug coverage for a z-stream release.

    This is a READ-ONLY operation - it only checks bug status.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        CVE tracker bug analysis
    """
    result = run_oar_command(["-r", release, "check-cve-tracker-bug"])
    return format_result(result)


@mcp.tool()
def oar_image_signed_check(release: str) -> str:
    """
    Check if release images are properly signed.

    This is a READ-ONLY operation - it only verifies signatures.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        Image signature verification results
    """
    result = run_oar_command(["-r", release, "image-signed-check"])
    return format_result(result)


# ============================================================================
# Status Check Tools (Query Operations)
# ============================================================================

@mcp.tool()
def oar_image_consistency_check(release: str, build_number: str = None) -> str:
    """
    Check status of image consistency check or start new check.

    If build_number is provided, queries existing job status (READ-ONLY).
    If build_number is not provided, starts new consistency check (WRITE).

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        build_number: Optional specific build number to check status

    Returns:
        Job status information or new job details
    """
    args = ["-r", release, "image-consistency-check"]
    if build_number is not None and build_number != "":
        args.extend(["-n", build_number])

    result = run_oar_command(args)
    return format_result(result)


@mcp.tool()
def oar_stage_testing(release: str, build_number: str = None) -> str:
    """
    Check status of stage testing or start new tests.

    If build_number is provided, queries existing job status (READ-ONLY).
    If build_number is not provided, starts new stage tests (WRITE).

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        build_number: Optional specific build number to check status

    Returns:
        Stage testing job status or new job details
    """
    args = ["-r", release, "stage-testing"]
    if build_number is not None and build_number != "":
        args.extend(["-n", build_number])

    result = run_oar_command(args)
    return format_result(result)


# ============================================================================
# Write Operations (Modify State - Use with Caution)
# ============================================================================

@mcp.tool()
def oar_create_test_report(release: str) -> str:
    """
    Create new Google Sheets test report for z-stream release.

    ⚠️ WRITE OPERATION: Creates new Google Sheet and sends notifications.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        URL of created test report
    """
    result = run_oar_command(["-r", release, "create-test-report"])
    return format_result(result)


@mcp.tool()
def oar_take_ownership(release: str, email: str) -> str:
    """
    Assign release ownership to a QE team member.

    ⚠️ WRITE OPERATION: Updates Google Sheets and sends notifications.

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        email: Email address of owner (e.g., "user@redhat.com")

    Returns:
        Ownership assignment confirmation
    """
    result = run_oar_command(["-r", release, "take-ownership", "-e", email])
    return format_result(result)


@mcp.tool()
def oar_update_bug_list(release: str) -> str:
    """
    Synchronize bug list from advisory to Jira and Google Sheets.

    ⚠️ WRITE OPERATION: Updates Jira issues and Google Sheets.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        Bug synchronization results
    """
    result = run_oar_command(["-r", release, "update-bug-list"])
    return format_result(result)


@mcp.tool()
def oar_push_to_cdn_staging(release: str) -> str:
    """
    Push release to CDN staging environment.

    ⚠️ CRITICAL OPERATION: Triggers production deployment workflow.
    This operation should only be used after all QE checks pass.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        CDN push operation results
    """
    result = run_oar_command(["-r", release, "push-to-cdn-staging"])
    return format_result(result)


@mcp.tool()
def oar_drop_bugs(release: str) -> str:
    """
    Remove unverified bugs from advisory.

    ⚠️ WRITE OPERATION: Modifies advisory bug list.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        List of dropped bugs
    """
    result = run_oar_command(["-r", release, "drop-bugs"])
    return format_result(result)


@mcp.tool()
def oar_change_advisory_status(release: str) -> str:
    """
    Change advisory status (typically to QE/PUSH_READY).

    ⚠️ CRITICAL OPERATION: Changes advisory state in Errata Tool.
    This is typically the final step before release approval.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        Advisory status change confirmation
    """
    result = run_oar_command(["-r", release, "change-advisory-status"])
    return format_result(result)


# ============================================================================
# Controller Tools (oarctl)
# ============================================================================

@mcp.tool()
def oarctl_start_release_detector(release: str) -> str:
    """
    Start release detector agent for monitoring new builds.

    ⚠️ BACKGROUND PROCESS: Starts a long-running agent.

    Args:
        release: Major.minor release version (e.g., "4.19")

    Returns:
        Agent startup confirmation
    """
    result = run_oarctl_command(["start-release-detector", "-r", release])
    return format_result(result)


@mcp.tool()
def oarctl_jira_notificator(dry_run: bool = False, from_date: Optional[str] = None) -> str:
    """
    Run Jira notificator to escalate unverified bugs.

    Args:
        dry_run: If True, runs in dry-run mode without sending notifications
        from_date: Optional start date for scanning (YYYY-MM-DD format)

    Returns:
        Notificator execution results
    """
    args = ["jira-notificator"]
    if dry_run:
        args.append("--dry-run")
    if from_date:
        args.extend(["--from-date", from_date])

    result = run_oarctl_command(args)
    return format_result(result)


# ============================================================================
# Job Controller Tools (job/jobctl)
# ============================================================================

@mcp.tool()
def job_run(job_name: str, payload: str) -> str:
    """
    Run a specific Prow job with payload.

    ⚠️ WRITE OPERATION: Triggers CI job execution.

    Args:
        job_name: Name of the Prow job to run
        payload: Image pullspec for the payload

    Returns:
        Job execution confirmation
    """
    result = run_job_command(["run", job_name, "--payload", payload])
    return format_result(result)


@mcp.tool()
def jobctl_start_controller(
    release: str,
    nightly: bool = True,
    trigger_prow_job: bool = True,
    arch: str = "amd64"
) -> str:
    """
    Start job controller for monitoring builds and triggering tests.

    ⚠️ BACKGROUND PROCESS: Starts a long-running controller agent.

    Args:
        release: Y-stream release number (e.g., "4.19")
        nightly: Run controller for nightly builds (default: True, False for stable)
        trigger_prow_job: Trigger Prow jobs when new build found (default: True)
        arch: Architecture to filter builds (amd64, arm64, ppc64le, s390x)

    Returns:
        Controller startup confirmation
    """
    args = ["start-controller", "-r", release]
    if nightly:
        args.append("--nightly")
    else:
        args.append("--no-nightly")
    if trigger_prow_job:
        args.extend(["--trigger-prow-job", "True"])
    args.extend(["--arch", arch])

    result = run_jobctl_command(args)
    return format_result(result)


@mcp.tool()
def jobctl_trigger_jobs_for_build(build: str, arch: str = "amd64") -> str:
    """
    Trigger Prow jobs for a specific build.

    ⚠️ WRITE OPERATION: Triggers CI jobs for the specified build.

    Args:
        build: Build version (e.g., "4.16.20" or "4.16.0-0.nightly-2024-01-15-123456")
        arch: Architecture (amd64, arm64, ppc64le, s390x)

    Returns:
        Job trigger confirmation
    """
    result = run_jobctl_command(["trigger-jobs-for-build", "--build", build, "--arch", arch])
    return format_result(result)


@mcp.tool()
def jobctl_start_aggregator(arch: str = "amd64") -> str:
    """
    Start test result aggregator for processing CI test results.

    ⚠️ BACKGROUND PROCESS: Starts a long-running aggregator agent.

    Args:
        arch: Architecture to filter test results (amd64, arm64, ppc64le, s390x)

    Returns:
        Aggregator startup confirmation
    """
    result = run_jobctl_command(["start-aggregator", "--arch", arch])
    return format_result(result)


@mcp.tool()
def jobctl_promote_test_results(build: str, arch: str = "amd64") -> str:
    """
    Promote test results for a build (mark as official/aggregated).

    ⚠️ WRITE OPERATION: Updates test result status in GitHub.

    Args:
        build: Build version (e.g., "4.16.20")
        arch: Architecture (amd64, arm64, ppc64le, s390x)

    Returns:
        Promotion confirmation
    """
    result = run_jobctl_command(["promote-test-results", "--build", build, "--arch", arch])
    return format_result(result)


@mcp.tool()
def jobctl_update_retried_job_run(
    build: str,
    job_name: str,
    current_job_id: str,
    new_job_id: str,
    arch: str = "amd64"
) -> str:
    """
    Update retried job run information in test results.

    ⚠️ WRITE OPERATION: Updates job run IDs in GitHub test result tracking.

    Args:
        build: Build version (e.g., "4.16.20")
        job_name: Prow job name from test job registry
        current_job_id: Current job run ID to replace
        new_job_id: New job run ID (from retry)
        arch: Architecture (amd64, arm64, ppc64le, s390x)

    Returns:
        Update confirmation
    """
    result = run_jobctl_command([
        "update-retried-job-run",
        "--build", build,
        "--job-name", job_name,
        "--current-job-id", current_job_id,
        "--new-job-id", new_job_id,
        "--arch", arch
    ])
    return format_result(result)


# ============================================================================
# Help/Discovery Tools
# ============================================================================

@mcp.tool()
def get_command_help(cli: str, command: str = "") -> str:
    """
    Get help information for any CLI command (oar, oarctl, job, jobctl).

    Use this to discover available commands and their usage before running them.

    Args:
        cli: CLI name - "oar", "oarctl", "job", or "jobctl"
        command: Specific command name (optional). Leave empty to list all commands.

    Returns:
        Command help text showing usage, flags, and options

    Examples:
        - get_command_help("oar", "") - List all OAR commands
        - get_command_help("oar", "update-bug-list") - Get help for update-bug-list
        - get_command_help("jobctl", "start-controller") - Get help for start-controller
    """
    # Build help command
    if command:
        cmd = [cli, command, "--help"]
    else:
        cmd = [cli, "--help"]

    logger.info(f"Getting help: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Redirect stderr to stdout
            text=True,
            timeout=30,
            env=os.environ.copy()
        )
        return result.stdout if result.stdout else "(No help output)"
    except Exception as e:
        return f"Error getting help: {str(e)}"


# ============================================================================
# Generic Command Tools (Advanced Usage)
# ============================================================================

@mcp.tool()
def oar_run_command(release: str, command: str, args: str = "") -> str:
    """
    Run any OAR command with custom arguments.

    This is a flexible tool for running OAR commands that may not have
    dedicated tool wrappers or need additional flags.

    💡 TIP: Use get_command_help("oar", command) first to see available options!

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        command: OAR command name (e.g., "update-bug-list", "check-greenwave-cvp-tests")
        args: Additional command arguments as a string (e.g., "--no-notify")

    Returns:
        Command execution results

    Examples:
        - oar_run_command("4.19.1", "update-bug-list", "--no-notify")
        - oar_run_command("4.19.1", "stage-testing", "-n 123")
    """
    # Build command args
    cmd_args = ["-r", release, command]

    # Parse and add additional arguments if provided
    if args.strip():
        cmd_args.extend(shlex.split(args))

    result = run_oar_command(cmd_args)
    return format_result(result)


@mcp.tool()
def oarctl_run_command(command: str, args: str = "") -> str:
    """
    Run any oarctl command with custom arguments.

    Args:
        command: oarctl command name (e.g., "start-release-detector", "jira-notificator")
        args: Additional command arguments as a string (e.g., "-r 4.19 --dry-run")

    Returns:
        Command execution results

    Examples:
        - oarctl_run_command("start-release-detector", "-r 4.19")
        - oarctl_run_command("jira-notificator", "--dry-run --from-date 2025-01-15")
    """
    cmd_args = [command]
    if args.strip():
        cmd_args.extend(shlex.split(args))

    result = run_oarctl_command(cmd_args)
    return format_result(result)


@mcp.tool()
def jobctl_run_command(command: str, args: str = "") -> str:
    """
    Run any jobctl command with custom arguments.

    Args:
        command: jobctl command name (e.g., "start-controller", "trigger-jobs-for-build")
        args: Additional command arguments as a string (e.g., "-r 4.19 --arch amd64")

    Returns:
        Command execution results

    Examples:
        - jobctl_run_command("start-controller", "-r 4.19 --nightly --arch amd64")
        - jobctl_run_command("trigger-jobs-for-build", "--build 4.19.1 --arch arm64")
    """
    cmd_args = [command]
    if args.strip():
        cmd_args.extend(shlex.split(args))

    result = run_jobctl_command(cmd_args)
    return format_result(result)


# ============================================================================
# Configuration Tools (Read-Only)
# ============================================================================

@mcp.tool()
def oar_get_release_metadata(release: str) -> str:
    """
    Get release metadata from ConfigStore.

    This is a READ-ONLY operation - retrieves release configuration data.
    Does NOT expose sensitive data like Slack contacts or credentials.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        JSON string with release metadata:
        - advisories: Advisory IDs (extras, image, metadata, rpm, rhcos, microshift)
        - jira_ticket: Jira ticket created by ART team
        - candidate_builds: Candidate nightly builds by architecture
        - shipment_mr: GitLab shipment MR URL (empty if using Errata flow)
        - release_date: Planned release date in YYYY-MMM-DD format (e.g., "2025-Nov-04")
    """
    try:
        cs = get_cached_configstore(release)

        metadata = {
            "release": release,
            "advisories": cs.get_advisories() or {},
            "jira_ticket": cs.get_jira_ticket() or "",
            "candidate_builds": cs.get_candidate_builds() or {},
            "shipment_mr": cs.get_shipment_mr() or "",
            "release_date": cs.get_release_date(),
        }

        return json.dumps(metadata, indent=2)

    except Exception as e:
        logger.error(f"Failed to get release metadata: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
def oar_is_release_shipped(release: str) -> str:
    """
    Check if a release is fully shipped (both Errata and Konflux flows).

    This is a READ-ONLY operation - it only queries shipment status.

    For Konflux flow, checks:
    - Shipment MR is either merged OR prod-release pipeline succeeded
    - rpm advisory in REL_PREP or higher state
    - rhcos advisory in REL_PREP or higher state

    For Errata flow, checks:
    - All advisories in REL_PREP or higher state

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        JSON string with shipment status:
        {
            "shipped": bool,
            "flow_type": "errata" or "konflux",
            "details": {
                // status for each checked component
            }
        }
    """
    try:
        cs = get_cached_configstore(release)
        operator = ReleaseShipmentOperator(cs)
        result = operator.is_release_shipped()

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Failed to check release shipment status: {e}")
        return json.dumps({
            "error": str(e),
            "shipped": False,
            "details": {}
        }, indent=2)


@mcp.tool()
def oar_get_release_status(release: str) -> str:
    """
    Get task execution status from Google Sheets test report.

    This is a READ-ONLY operation - retrieves current task status for AI decision making.

    Returns task status for all OAR workflow tasks including:
    - Overall status (Green/Red)
    - Individual task statuses (Pass/Fail/In Progress/Not Started)

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        JSON string with task execution status:
        {
            "release": "4.19.1",
            "overall_status": "Green",
            "tasks": {
                "take-ownership": "Pass",
                "image-consistency-check": "Not Started",
                "analyze-candidate-build": "In Progress",
                "analyze-promoted-build": "In Progress",
                "check-cve-tracker-bug": "Pass",
                "push-to-cdn-staging": "In Progress",
                "stage-testing": "Not Started",
                "image-signed-check": "Not Started",
                "change-advisory-status": "Not Started"
            }
        }

    Note: analyze-candidate-build and analyze-promoted-build always show "In Progress"
    in M1. AI must check test result files from GitHub to determine actual analysis status.
    """
    try:
        cs = get_cached_configstore(release)
        wm = WorksheetManager(cs)
        report = wm.get_test_report()

        # Map Google Sheets labels to task names from Konflux release flow spec
        task_mapping = {
            LABEL_TASK_OWNERSHIP: "take-ownership",
            LABEL_TASK_IMAGE_CONSISTENCY_TEST: "image-consistency-check",
            LABEL_TASK_NIGHTLY_BUILD_TEST: "analyze-candidate-build",
            LABEL_TASK_SIGNED_BUILD_TEST: "analyze-promoted-build",
            LABEL_TASK_CHECK_CVE_TRACKERS: "check-cve-tracker-bug",
            LABEL_TASK_PUSH_TO_CDN: "push-to-cdn-staging",
            LABEL_TASK_STAGE_TEST: "stage-testing",
            LABEL_TASK_PAYLOAD_IMAGE_VERIFY: "image-signed-check",
            LABEL_TASK_CHANGE_AD_STATUS: "change-advisory-status",
        }

        # Get overall status
        overall_status = report.get_overall_status()

        # Get all task statuses
        tasks = {}
        for label, task_name in task_mapping.items():
            status = report.get_task_status(label)
            tasks[task_name] = status if status else "Not Started"

        result = {
            "release": release,
            "overall_status": overall_status if overall_status else "Green",
            "tasks": tasks
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Failed to get release status: {e}")
        return json.dumps({
            "error": str(e),
            "release": release,
            "overall_status": "Unknown",
            "tasks": {}
        }, indent=2)


@mcp.tool()
def oar_update_task_status(release: str, task_name: str, status: str) -> str:
    """
    Update specific task status in Google Sheets test report.

    ⚠️ WRITE OPERATION: Updates task status in Google Sheets.

    This allows AI to mark tasks as Pass/Fail/In Progress based on analysis.
    For example, after analyzing blocking test results, AI can mark the task as Pass if results look acceptable.

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        task_name: Task name (e.g., "analyze-candidate-build", "analyze-promoted-build", "image-consistency-check")
        status: Task status - must be one of: "Pass", "Fail", "In Progress"

    Returns:
        JSON string with update confirmation

    Valid task names:
    - take-ownership
    - image-consistency-check
    - analyze-candidate-build
    - analyze-promoted-build
    - check-cve-tracker-bug
    - push-to-cdn-staging
    - stage-testing
    - image-signed-check
    - change-advisory-status

    Valid status values:
    - Pass: Task completed successfully
    - Fail: Task failed (will set overall status to Red)
    - In Progress: Task is currently being worked on
    """
    # Validate status
    valid_statuses = [TASK_STATUS_PASS, TASK_STATUS_FAIL, TASK_STATUS_INPROGRESS]
    if status not in valid_statuses:
        return json.dumps({
            "success": False,
            "error": f"Invalid status: {status}. Must be one of: {', '.join(valid_statuses)}"
        }, indent=2)

    # Map task names to Google Sheets labels
    task_to_label = {
        "take-ownership": LABEL_TASK_OWNERSHIP,
        "image-consistency-check": LABEL_TASK_IMAGE_CONSISTENCY_TEST,
        "analyze-candidate-build": LABEL_TASK_NIGHTLY_BUILD_TEST,
        "analyze-promoted-build": LABEL_TASK_SIGNED_BUILD_TEST,
        "check-cve-tracker-bug": LABEL_TASK_CHECK_CVE_TRACKERS,
        "push-to-cdn-staging": LABEL_TASK_PUSH_TO_CDN,
        "stage-testing": LABEL_TASK_STAGE_TEST,
        "image-signed-check": LABEL_TASK_PAYLOAD_IMAGE_VERIFY,
        "change-advisory-status": LABEL_TASK_CHANGE_AD_STATUS,
    }

    if task_name not in task_to_label:
        return json.dumps({
            "success": False,
            "error": f"Invalid task name: {task_name}. Must be one of: {', '.join(task_to_label.keys())}"
        }, indent=2)

    try:
        cs = get_cached_configstore(release)
        wm = WorksheetManager(cs)
        report = wm.get_test_report()

        # Update task status
        label = task_to_label[task_name]
        report.update_task_status(label, status)

        return json.dumps({
            "success": True,
            "release": release,
            "task": task_name,
            "status": status,
            "message": f"Successfully updated task '{task_name}' to '{status}'"
        }, indent=2)

    except Exception as e:
        logger.error(f"Failed to update task status: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "release": release,
            "task": task_name,
            "status": status
        }, indent=2)


# ============================================================================
# Cache Management Tools
# ============================================================================

@mcp.tool()
def mcp_cache_stats() -> str:
    """
    Get ConfigStore cache statistics and performance metrics.

    This is a READ-ONLY operation - retrieves cache usage information.

    Returns:
        JSON string with cache statistics:
        - metrics: Hit rate, hits, misses, evictions, invalidations
        - cache_size: Current number of cached entries
        - max_size: Maximum cache capacity
        - ttl_seconds: Time-to-live for cache entries
        - entries: List of currently cached releases

    Use this tool to monitor cache performance and identify optimization opportunities.
    """
    try:
        stats = _configstore_cache.stats()
        return json.dumps(stats, indent=2)
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return json.dumps({"error": str(e)}, indent=2)


@mcp.tool()
def mcp_cache_invalidate(release: Optional[str] = None) -> str:
    """
    Invalidate (remove) cache entries manually.

    Use this when ART updates build data for a release and you need to refresh the cache.

    Args:
        release: Specific release to invalidate (e.g., "4.19.1"), or None to clear all cache

    Returns:
        JSON string with invalidation confirmation

    Examples:
        - mcp_cache_invalidate("4.19.1") - Invalidate cache for release 4.19.1
        - mcp_cache_invalidate() - Clear all cache entries

    Note: This is rarely needed since ConfigStore data is immutable after ART announces a release.
    """
    try:
        _configstore_cache.invalidate(release)

        if release:
            message = f"Cache entry for release {release} invalidated"
        else:
            message = "All cache entries invalidated"

        return json.dumps({
            "success": True,
            "message": message,
            "release": release if release else "all"
        }, indent=2)
    except Exception as e:
        logger.error(f"Failed to invalidate cache: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "release": release if release else "all"
        }, indent=2)


@mcp.tool()
def mcp_cache_warm(releases: str) -> str:
    """
    Pre-populate cache with ConfigStore instances for multiple releases.

    Use this to warm up the cache before running multiple operations,
    reducing latency for subsequent requests.

    Args:
        releases: Comma-separated list of release versions (e.g., "4.19.1,4.18.5,4.17.10")

    Returns:
        JSON string with warming results

    Example:
        mcp_cache_warm("4.19.1,4.18.5") - Warm cache for releases 4.19.1 and 4.18.5

    Performance benefit:
        - First access per release: ~1000ms (cache miss + warming)
        - Subsequent accesses: <10ms (cache hit)
    """
    try:
        release_list = [r.strip() for r in releases.split(",") if r.strip()]

        if not release_list:
            return json.dumps({
                "success": False,
                "error": "No releases provided. Expected comma-separated list (e.g., '4.19.1,4.18.5')"
            }, indent=2)

        # Warm cache
        _configstore_cache.warm(release_list)

        return json.dumps({
            "success": True,
            "message": f"Cache warmed with {len(release_list)} releases",
            "releases": release_list
        }, indent=2)
    except Exception as e:
        logger.error(f"Failed to warm cache: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "releases": release_list if 'release_list' in locals() else []
        }, indent=2)


# ============================================================================
# Server Entry Point
# ============================================================================

if __name__ == "__main__":
    # Validate environment using centralized ConfigStore validation
    validation_result = ConfigStore.validate_environment()

    if not validation_result['valid']:
        logger.error("=" * 60)
        logger.error("Environment validation FAILED!")
        logger.error("=" * 60)
        logger.error("Missing required environment variables for OAR CLI:")
        logger.error("")
        for error in validation_result['errors']:
            logger.error(f"  ❌ {error}")
        logger.error("")
        logger.error("Fix:")
        logger.error("  1. Add these variables to ~/.bash_profile or ~/.bashrc:")
        logger.error("     export OAR_JWK=\"...\"")
        logger.error("     export JIRA_TOKEN=\"...\"")
        logger.error("     # ... etc")
        logger.error("  2. Run: source ~/.bash_profile")
        logger.error("  3. Restart the MCP server")
        logger.error("")
        logger.error("Or run the environment checker: ./mcp_server/check_env.sh")
        logger.error("=" * 60)
        sys.exit(1)

    # Log info for missing optional variables
    if validation_result['missing_optional']:
        logger.info("Optional environment variables (not required):")
        for var in validation_result['missing_optional']:
            logger.info(f"  - {var}")
        logger.info("These are only needed for specific use cases")

    # Log startup
    logger.info("=" * 60)
    logger.info("Starting Release Tests MCP Server")
    logger.info("=" * 60)
    logger.info(f"✓ Environment validation: PASSED")
    logger.info(f"✓ Transport: SSE (HTTP)")
    logger.info(f"✓ All required credentials configured")
    logger.info("=" * 60)

    # Run MCP server in SSE mode
    # Default: host=127.0.0.1, port=8000
    # For remote access, override with: mcp.run(transport="sse", host="0.0.0.0", port=8080)
    mcp.run(transport="sse")
