#!/usr/bin/env python3
"""
Release Tests MCP Server

Exposes OAR, oarctl, job, and jobctl commands as MCP tools for use by AI agents.
Runs in SSE mode - accessible as HTTP server for remote access.

Performance: Direct Click invocation (NO subprocess overhead)
- 70-90% faster than subprocess-based approach
- ConfigStore caching (TTL=7 days)
- All CLI commands optimized

Async Architecture:
- FastMCP async tool handlers run in asyncio event loop (main thread)
- Blocking CLI operations execute in ThreadPoolExecutor worker threads
- Auto-scaling thread pool: 2x CPU count (scales with hardware)
- Concurrent request handling: Multiple AI agents can call tools simultaneously
- Thread-safe log capture: ThreadFilter isolates logs per worker thread
- Non-blocking I/O: Event loop remains responsive during CLI execution

Concurrency Model:
1. AI agent sends MCP tool request → FastMCP async handler (asyncio event loop)
2. Async handler calls invoke_*_async() wrapper → Runs in event loop
3. Wrapper uses loop.run_in_executor() → Submits work to ThreadPoolExecutor
4. CLI operation executes in worker thread → Blocking operations don't block event loop
5. Worker completes → asyncio.Future resolves → Result returned to AI agent

Thread Pool Configuration:
- Size: get_optimal_thread_pool_size() calculates 2x CPU count (no cap)
- Override: MCP_THREAD_POOL_SIZE environment variable (no cap applied)
- Workers: Named 'cli-worker-N' for debugging
- Shutdown: Graceful shutdown with wait=True on Ctrl+C

Async Wrappers:
- invoke_oar_command_async(release, command_func, args) → For OAR commands with ConfigStore
- invoke_cli_command_async(command_func, args) → For oarctl/job/jobctl commands

Log Isolation:
- ThreadFilter ensures each worker only captures logs from its own thread
- Prevents log mixing when multiple AI agents send concurrent requests
- Each request gets isolated log output even under high load

Tools exposed:
- 11 OAR CLI commands (create-test-report, take-ownership, update-bug-list, etc.)
- 2 oarctl commands (start-release-detector, jira-notificator)
- 6 jobctl commands (start-controller, trigger-jobs-for-build, start-aggregator, etc.)
- 1 job command (run)
- 4 configuration tools (get-release-metadata, is-release-shipped, get-release-status, update-task-status)
- 4 issue management tools (add-issue, resolve-issue, get-issues, get-task-blocker)
- 3 cache management tools (mcp_cache_stats, mcp_cache_invalidate, mcp_cache_warm)

Total: 31 tools (100% optimized - all CLI commands use direct Click invocation)

Performance Characteristics:
- ConfigStore cache hit: <10ms (3x-100x faster than miss)
- ConfigStore cache miss: ~1000ms (JWE decrypt + GitHub HTTP + YAML parse)
- Thread pool overhead: <1ms per request (minimal)
- Concurrent requests: Linear scaling up to thread pool size
- Memory: Shared ConfigStore instances across workers (cache efficiency)
"""

import sys
import os
import logging
import json
import time
import threading
import io
import asyncio
from typing import Optional
from threading import RLock
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from fastmcp import FastMCP
from cachetools import TTLCache
from click.testing import CliRunner

# Import OAR validation
# Add parent directory to path to import oar modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from oar.core.configstore import ConfigStore
from oar.core.operators import ReleaseShipmentOperator
from oar.core.worksheet import WorksheetManager
from oar.core.statebox import StateBox
from oar.core.exceptions import StateBoxException
from oar.core.log_capture import capture_logs, merge_output
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
    TASK_STATUS_NOT_STARTED,
    TASK_STATUS_INPROGRESS,
    TASK_STATUS_PASS,
    TASK_STATUS_FAIL,
    WORKFLOW_TASK_NAMES,
)

# Import CLI group for invoking commands (to enable result_callback for StateBox updates)
from oar.cli.cmd_group import cli as oar_cli_group

# oarctl commands (2 total)
from oar.controller.detector import start_release_detector
from oar.notificator.jira_notificator import jira_notificator

# Add prow/job to path for imports
prow_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'prow')
if prow_path not in sys.path:
    sys.path.insert(0, prow_path)

# job/jobctl commands (6 total)
from job.job import run_cmd as job_run_cmd
from job.controller import (
    start_controller as jobctl_start_controller_cmd,
    trigger_jobs_for_build as jobctl_trigger_jobs_cmd,
    start_aggregator as jobctl_start_aggregator_cmd,
    promote_test_results as jobctl_promote_results_cmd,
    update_retried_job_run as jobctl_update_retried_cmd
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
# Thread Pool for CLI Operations (Async Support)
# ============================================================================

def get_optimal_thread_pool_size() -> int:
    """
    Calculate optimal thread pool size based on system resources.

    Strategy:
    - OAR CLI operations are I/O-bound (HTTP requests, file I/O, subprocess calls)
    - Use 2x CPU count for I/O-bound workloads (no arbitrary cap)
    - Allow override via MCP_THREAD_POOL_SIZE environment variable

    Returns:
        Optimal number of worker threads

    Examples:
        - 4-core system: 8 workers (4 * 2)
        - 8-core system: 16 workers (8 * 2)
        - 16-core system: 32 workers (16 * 2) - scales with hardware
        - Environment override: MCP_THREAD_POOL_SIZE=50 → 50 workers
    """
    # Check environment variable first - respect user's explicit choice
    env_size = os.getenv("MCP_THREAD_POOL_SIZE")
    if env_size:
        try:
            size = int(env_size)
            if size < 1:
                logger.warning(f"Invalid MCP_THREAD_POOL_SIZE={env_size}, using default calculation")
            else:
                logger.info(f"Thread pool size from environment: {size} workers")
                return size  # No cap - user knows their system best
        except ValueError:
            logger.warning(f"Invalid MCP_THREAD_POOL_SIZE={env_size}, using default calculation")

    # Calculate based on CPU count
    cpu_count = os.cpu_count() or 4  # Fallback to 4 if cannot detect

    # For I/O-bound operations, use 2x CPU count
    # No artificial cap - let it scale with hardware capabilities
    optimal_size = cpu_count * 2

    return optimal_size


# Global thread pool for CLI command execution
# This enables non-blocking async MCP tool handlers
CLI_THREAD_POOL_SIZE = get_optimal_thread_pool_size()
CLI_THREAD_POOL = ThreadPoolExecutor(
    max_workers=CLI_THREAD_POOL_SIZE,
    thread_name_prefix="cli-worker-"
)

logger.info(f"ThreadPoolExecutor initialized: {CLI_THREAD_POOL_SIZE} workers (CPU count: {os.cpu_count() or 'unknown'})")


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

def invoke_oar_command(release: str, command_name: str, args: list[str]) -> dict:
    """
    Invoke OAR Click command through CLI group to trigger result_callback for StateBox updates.

    This is the core optimization that eliminates subprocess overhead while ensuring
    StateBox integration works properly by invoking through the CLI group.

    Args:
        release: Z-stream release version (e.g., "4.20.1")
        command_name: OAR command name (e.g., "image-signed-check", "update-bug-list")
        args: Command arguments (e.g., ['--no-notify'])

    Returns:
        dict with success, output, exit_code

    Performance:
        - First call: ~500ms (ConfigStore init, cached for next time)
        - Subsequent calls: <10ms (cache hit) + command execution time

    Thread Safety:
        - Uses shared capture_logs(thread_safe=True) to isolate logs per concurrent request
        - FastMCP runs each tool call in a new thread, ThreadFilter prevents log mixing

    StateBox Integration:
        - Invokes through CLI group (`oar -r <release> <command>`) so result_callback gets called
        - CLI layer's result_callback (cmd_group.py) handles StateBox updates automatically
        - Command name is derived from ctx.invoked_subcommand
        - Result and timestamps are captured and saved to StateBox

    Note:
        This function is specifically for OAR commands that require ConfigStore.
        For oarctl/job/jobctl commands, use CliRunner directly without ConfigStore injection.
    """
    runner = CliRunner()

    # Get cached ConfigStore (10ms after first call)
    cs = get_cached_configstore(release)

    # Use shared capture_logs with thread safety for concurrent MCP requests
    # ThreadFilter isolates logs between concurrent thread pool workers
    with capture_logs(thread_safe=True) as log_buffer:
        # Build command arguments: -r <release> <command> [args...]
        # This invokes through the CLI group so result_callback gets triggered
        cli_args = ['-r', release, command_name] + args

        # Invoke Click command through CLI group with cached ConfigStore and log buffer
        # The CLI layer's result_callback will handle StateBox updates automatically
        # CRITICAL: We pass standalone_mode=False to prevent Click from calling sys.exit()
        # on errors, which would crash the MCP server thread
        result = runner.invoke(oar_cli_group, cli_args, obj={
            "cs": cs,
            "_log_buffer": log_buffer,
        }, standalone_mode=False)

        # Combine Click output with captured logs using shared utility
        combined_output = merge_output(result.output, log_buffer.getvalue())

        return {
            "success": result.exit_code == 0,
            "output": combined_output,
            "exit_code": result.exit_code
        }


def format_result(result: dict) -> str:
    """
    Format command result for display to user.

    Args:
        result: Command result dict with success, output, exit_code keys

    Returns:
        Formatted string with success indicator and output
    """
    if result["success"]:
        output = result["output"].strip()
        return f"✓ Command succeeded\n\n{output}" if output else "✓ Command succeeded"
    else:
        error = result["output"].strip() or "Unknown error"
        return f"✗ Command failed (exit code {result['exit_code']})\n\n{error}"


# ============================================================================
# Async Wrappers for Thread Pool Execution
# ============================================================================

async def invoke_oar_command_async(release: str, command_name: str, args: list[str]) -> dict:
    """
    Async wrapper for invoke_oar_command that runs in thread pool.

    This enables non-blocking execution of OAR CLI commands in FastMCP's
    asyncio event loop. The blocking invoke_oar_command() runs in a
    ThreadPoolExecutor worker while the event loop remains responsive.

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        command_name: OAR command name (e.g., "image-signed-check", "update-bug-list")
        args: Command arguments

    Returns:
        dict with success, output, exit_code

    Concurrency:
        Multiple concurrent requests can execute in parallel via thread pool.
        Each runs in its own worker thread with isolated log capture.

    Example:
        >>> result = await invoke_oar_command_async("4.19.1", "update-bug-list", [])
        >>> print(result["output"])
    """
    loop = asyncio.get_event_loop()

    # Run blocking operation in thread pool
    return await loop.run_in_executor(
        CLI_THREAD_POOL,
        invoke_oar_command,
        release,
        command_name,
        args
    )


async def invoke_cli_command_async(command_func, args: list[str]) -> dict:
    """
    Async wrapper for oarctl/job/jobctl CLI commands.

    Similar to invoke_oar_command_async but for commands that don't
    require ConfigStore injection.

    Args:
        command_func: Click command function (e.g., start_release_detector)
        args: Command arguments

    Returns:
        dict with success, output, exit_code

    Example:
        >>> result = await invoke_cli_command_async(start_release_detector, ["-r", "4.19"])
    """
    def _run_cli_command():
        """Synchronous wrapper executed in thread pool."""
        runner = CliRunner()
        result = runner.invoke(command_func, args)
        return {
            "success": result.exit_code == 0,
            "output": result.output,
            "exit_code": result.exit_code
        }

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(CLI_THREAD_POOL, _run_cli_command)


# ============================================================================
# Read-Only Tools (Safe Operations)
# ============================================================================

@mcp.tool()
async def oar_check_greenwave_cvp_tests(release: str) -> str:
    """
    Check Greenwave CVP test status for a z-stream release.

    This is a READ-ONLY operation - it only queries test status.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        Test status information from Greenwave
    """
    result = await invoke_oar_command_async(release, "check-greenwave-cvp-tests", [])
    return format_result(result)


@mcp.tool()
async def oar_check_cve_tracker_bug(release: str, notify: bool = False) -> str:
    """
    Check CVE tracker bug coverage for a z-stream release.

    This is a READ-ONLY operation (when notify=False) - it only checks bug status.

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        notify: Send notifications (default: False for read-only behavior)

    Returns:
        CVE tracker bug analysis
    """
    args = [] if notify else ["--no-notify"]
    result = await invoke_oar_command_async(release, "check-cve-tracker-bug", args)
    return format_result(result)


@mcp.tool()
async def oar_image_signed_check(release: str) -> str:
    """
    Check if release images are properly signed.

    This is a READ-ONLY operation - it only verifies signatures.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        Image signature verification results
    """
    result = await invoke_oar_command_async(release, "image-signed-check", [])
    return format_result(result)


# ============================================================================
# Status Check Tools (Query Operations)
# ============================================================================

@mcp.tool()
async def oar_image_consistency_check(release: str, build_number: str = None) -> str:
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
    args = []
    if build_number is not None and build_number != "":
        args.extend(["-n", build_number])

    result = await invoke_oar_command_async(release, "image-consistency-check", args)
    return format_result(result)


@mcp.tool()
async def oar_stage_testing(release: str, build_number: str = None) -> str:
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
    args = []
    if build_number is not None and build_number != "":
        args.extend(["-n", build_number])

    result = await invoke_oar_command_async(release, "stage-testing", args)
    return format_result(result)


# ============================================================================
# Write Operations (Modify State - Use with Caution)
# ============================================================================

@mcp.tool()
async def oar_create_test_report(release: str) -> str:
    """
    Create new Google Sheets test report for z-stream release.

    ⚠️ WRITE OPERATION: Creates new Google Sheet and sends notifications.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        URL of created test report
    """
    result = await invoke_oar_command_async(release, "create-test-report", [])
    return format_result(result)


@mcp.tool()
async def oar_take_ownership(release: str, email: str) -> str:
    """
    Assign release ownership to a QE team member.

    ⚠️ WRITE OPERATION: Updates Google Sheets and sends notifications.

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        email: Email address of owner (e.g., "user@redhat.com")

    Returns:
        Ownership assignment confirmation
    """
    result = await invoke_oar_command_async(release, "take-ownership", ["-e", email])
    return format_result(result)


@mcp.tool()
async def oar_update_bug_list(release: str, notify: bool = True) -> str:
    """
    Synchronize bug list from advisory to Jira and Google Sheets.

    ⚠️ WRITE OPERATION: Updates Jira issues and Google Sheets.

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        notify: Send notifications to bug owners (default: True)

    Returns:
        Bug synchronization results
    """
    args = [] if notify else ["--no-notify"]
    result = await invoke_oar_command_async(release, "update-bug-list", args)
    return format_result(result)


@mcp.tool()
async def oar_push_to_cdn_staging(release: str) -> str:
    """
    Push release to CDN staging environment.

    ⚠️ CRITICAL OPERATION: Triggers production deployment workflow.
    This operation should only be used after all QE checks pass.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        CDN push operation results
    """
    result = await invoke_oar_command_async(release, "push-to-cdn-staging", [])
    return format_result(result)


@mcp.tool()
async def oar_drop_bugs(release: str) -> str:
    """
    Remove unverified bugs from advisory.

    ⚠️ WRITE OPERATION: Modifies advisory bug list.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        List of dropped bugs
    """
    result = await invoke_oar_command_async(release, "drop-bugs", [])
    return format_result(result)


@mcp.tool()
async def oar_change_advisory_status(release: str) -> str:
    """
    Change advisory status (typically to QE/PUSH_READY).

    ⚠️ CRITICAL OPERATION: Changes advisory state in Errata Tool.
    This is typically the final step before release approval.

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        Advisory status change confirmation
    """
    result = await invoke_oar_command_async(release, "change-advisory-status", [])
    return format_result(result)


# ============================================================================
# Controller Tools (oarctl)
# ============================================================================

@mcp.tool()
async def oarctl_start_release_detector(release: str) -> str:
    """
    Start release detector agent for monitoring new builds.

    ⚠️ BACKGROUND PROCESS: Starts a long-running agent.

    Args:
        release: Major.minor release version (e.g., "4.19")

    Returns:
        Agent startup confirmation
    """
    result = await invoke_cli_command_async(start_release_detector, ["-r", release])
    return format_result(result)


@mcp.tool()
async def oarctl_jira_notificator(dry_run: bool = False, from_date: Optional[str] = None) -> str:
    """
    Run Jira notificator to escalate unverified bugs.

    Args:
        dry_run: If True, runs in dry-run mode without sending notifications
        from_date: Optional start date for scanning (YYYY-MM-DD format)

    Returns:
        Notificator execution results
    """
    args = []
    if dry_run:
        args.append("--dry-run")
    if from_date:
        args.extend(["--from-date", from_date])

    result = await invoke_cli_command_async(jira_notificator, args)


    return format_result(result)


# ============================================================================
# Job Controller Tools (job/jobctl)
# ============================================================================

@mcp.tool()
async def job_run(job_name: str, payload: str) -> str:
    """
    Run a specific Prow job with payload.

    ⚠️ WRITE OPERATION: Triggers CI job execution.

    Args:
        job_name: Name of the Prow job to run
        payload: Image pullspec for the payload

    Returns:
        Job execution confirmation
    """
    result = await invoke_cli_command_async(job_run_cmd, [job_name, "--payload", payload])

    return format_result(result)


@mcp.tool()
async def jobctl_start_controller(
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
    args = ["-r", release]
    if nightly:
        args.append("--nightly")
    else:
        args.append("--no-nightly")
    if trigger_prow_job:
        args.extend(["--trigger-prow-job", "True"])
    args.extend(["--arch", arch])

    result = await invoke_cli_command_async(jobctl_start_controller_cmd, args)


    return format_result(result)


@mcp.tool()
async def jobctl_trigger_jobs_for_build(build: str, arch: str = "amd64") -> str:
    """
    Trigger Prow jobs for a specific build.

    ⚠️ WRITE OPERATION: Triggers CI jobs for the specified build.

    Args:
        build: Build version (e.g., "4.16.20" or "4.16.0-0.nightly-2024-01-15-123456")
        arch: Architecture (amd64, arm64, ppc64le, s390x)

    Returns:
        Job trigger confirmation
    """
    result = await invoke_cli_command_async(jobctl_trigger_jobs_cmd, ["--build", build, "--arch", arch])

    return format_result(result)


@mcp.tool()
async def jobctl_start_aggregator(arch: str = "amd64") -> str:
    """
    Start test result aggregator for processing CI test results.

    ⚠️ BACKGROUND PROCESS: Starts a long-running aggregator agent.

    Args:
        arch: Architecture to filter test results (amd64, arm64, ppc64le, s390x)

    Returns:
        Aggregator startup confirmation
    """
    result = await invoke_cli_command_async(jobctl_start_aggregator_cmd, ["--arch", arch])

    return format_result(result)


@mcp.tool()
async def jobctl_promote_test_results(build: str, arch: str = "amd64") -> str:
    """
    Promote test results for a build (mark as official/aggregated).

    ⚠️ WRITE OPERATION: Updates test result status in GitHub.

    Args:
        build: Build version (e.g., "4.16.20")
        arch: Architecture (amd64, arm64, ppc64le, s390x)

    Returns:
        Promotion confirmation
    """
    result = await invoke_cli_command_async(jobctl_promote_results_cmd, ["--build", build, "--arch", arch])

    return format_result(result)


@mcp.tool()
async def jobctl_update_retried_job_run(
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
    result = await invoke_cli_command_async(jobctl_update_retried_cmd, [
        "--build", build,
        "--job-name", job_name,
        "--current-job-id", current_job_id,
        "--new-job-id", new_job_id,
        "--arch", arch
    ])

    return format_result(result)


# ============================================================================
# Configuration Tools (Read-Only)
# ============================================================================

@mcp.tool()
async def oar_get_release_metadata(release: str) -> str:
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

        return json.dumps(metadata)

    except Exception as e:
        logger.error(f"Failed to get release metadata: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
async def oar_is_release_shipped(release: str) -> str:
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

        return json.dumps(result)

    except Exception as e:
        logger.error(f"Failed to check release shipment status: {e}")
        return json.dumps({
            "error": str(e),
            "shipped": False,
            "details": {}
        })


@mcp.tool()
async def oar_get_release_status(release: str) -> str:
    """
    Get complete release state from StateBox (primary) or Google Sheets (fallback).

    This is a READ-ONLY operation - retrieves full release context for AI decision making and resumability.

    Data Source Priority:
    1. StateBox (GitHub-backed YAML) - Returns complete state (metadata, tasks with results, issues)
    2. Google Sheets - Fallback when StateBox doesn't exist (limited to task status only)

    Args:
        release: Z-stream release version (e.g., "4.19.1")

    Returns:
        JSON string with complete release state from StateBox or limited status from Google Sheets.
    """
    try:
        cs = get_cached_configstore(release)

        # Try StateBox first
        try:
            statebox = StateBox(cs)

            if statebox.exists():
                logger.info(f"Using StateBox for release status (release: {release})")
                # Return complete state as JSON using StateBox.to_json()
                return statebox.to_json()

        except StateBoxException as e:
            logger.warning(f"StateBox access failed, falling back to Google Sheets: {e}")

        # Fallback to Google Sheets (status only, no detailed info)
        logger.info(f"Using Google Sheets for release status (release: {release})")
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
            tasks[task_name] = status if status else TASK_STATUS_NOT_STARTED

        result = {
            "source": "worksheet",
            "release": release,
            "overall_status": overall_status if overall_status else "Green",
            "tasks": tasks
        }

        return json.dumps(result)

    except Exception as e:
        logger.error(f"Failed to get release status: {e}")
        return json.dumps({
            "source": "error",
            "error": str(e),
            "release": release,
            "overall_status": "Unknown",
            "tasks": {}
        })


@mcp.tool()
async def oar_update_task_status(release: str, task_name: str, status: str, result: Optional[str] = None) -> str:
    """
    Update specific task status in StateBox (primary) or Google Sheets (fallback).

    ⚠️ WRITE OPERATION: Updates task status in StateBox and/or Google Sheets.

    Data Source Priority:
    1. StateBox (GitHub-backed YAML) - Primary source, updated if exists
    2. Google Sheets - Updated regardless for backwards compatibility

    This allows AI to mark tasks as Pass/Fail/In Progress based on analysis.
    For example, after analyzing blocking test results, AI can mark the task as Pass if results look acceptable.

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        task_name: Task name (e.g., "analyze-candidate-build", "analyze-promoted-build", "image-consistency-check")
        status: Task status - must be one of: "Pass", "Fail", "In Progress"
        result: Optional task execution result summary (AI-readable text, stored in StateBox only)

    Returns:
        JSON string with update confirmation including which systems were updated

    Valid task names: See WORKFLOW_TASK_NAMES in oar/core/const.py
    (Excludes one-time/optional tasks: create-test-report, update-bug-list, drop-bugs)

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
        })

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

    if task_name not in WORKFLOW_TASK_NAMES:
        return json.dumps({
            "success": False,
            "error": f"Invalid task name: {task_name}. Must be one of: {', '.join(WORKFLOW_TASK_NAMES)}"
        })

    try:
        cs = get_cached_configstore(release)
        updated_systems = []

        # Normalize empty/whitespace result to None (treat as not provided)
        if result is not None and not result.strip():
            result = None

        # Try to update StateBox first
        try:
            statebox = StateBox(cs)
            if statebox.exists():
                # StateBox exists, update it
                # Only pass result if it has actual content
                if result is not None:
                    statebox.update_task(task_name, status=status, result=result)
                else:
                    statebox.update_task(task_name, status=status)
                updated_systems.append("statebox")
                logger.info(f"Updated StateBox for task '{task_name}' to '{status}'" +
                          (f" with result summary ({len(result)} chars)" if result else ""))
        except StateBoxException as e:
            logger.warning(f"StateBox update failed (will update Google Sheets): {e}")

        # Always update Google Sheets for backwards compatibility
        wm = WorksheetManager(cs)
        report = wm.get_test_report()
        label = task_to_label[task_name]
        report.update_task_status(label, status)
        updated_systems.append("worksheet")
        logger.info(f"Updated Google Sheets for task '{task_name}' to '{status}'")

        result_info = {}
        if result:
            result_info = {
                "result_length": len(result),
                "result_preview": result[:200] + "..." if len(result) > 200 else result
            }

        return json.dumps({
            "success": True,
            "release": release,
            "task": task_name,
            "status": status,
            "updated_systems": updated_systems,
            "message": f"Successfully updated task '{task_name}' to '{status}' in {', '.join(updated_systems)}",
            **result_info
        })

    except Exception as e:
        logger.error(f"Failed to update task status: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "release": release,
            "task": task_name,
            "status": status
        })


# ============================================================================
# Cache Management Tools
# ============================================================================

@mcp.tool()
async def mcp_cache_stats() -> str:
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
        return json.dumps(stats)
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def mcp_cache_invalidate(release: Optional[str] = None) -> str:
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
        })
    except Exception as e:
        logger.error(f"Failed to invalidate cache: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "release": release if release else "all"
        })


@mcp.tool()
async def mcp_cache_warm(releases: str) -> str:
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
            })

        # Warm cache
        _configstore_cache.warm(release_list)

        return json.dumps({
            "success": True,
            "message": f"Cache warmed with {len(release_list)} releases",
            "releases": release_list
        })
    except Exception as e:
        logger.error(f"Failed to warm cache: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "releases": release_list if 'release_list' in locals() else []
        })


# ============================================================================
# StateBox Issue Management Tools
# ============================================================================

@mcp.tool()
async def oar_add_issue(
    release: str,
    issue: str,
    blocker: bool = True,
    related_tasks: Optional[str] = None
) -> str:
    """
    Add an issue to StateBox for tracking release problems.

    ⚠️ WRITE OPERATION: Creates new issue entry in StateBox.

    Use this tool to track both blocking and non-blocking issues during release workflow.
    AI should analyze task failures to identify root causes before creating issues.

    Issue Types:
    - Blocking issues (blocker=True): Critical problems that prevent release from proceeding
      Examples: CVE not covered, advisory in wrong state, ART pipeline down
    - Non-blocking issues (blocker=False): Problems to track but don't stop release
      Examples: Automation failures, test flakiness, tool improvements needed

    Issue Scopes:
    - Task-specific issues: Problems related to specific tasks (provide related_tasks)
      Example: "CVE-2024-12345 not covered" blocks check-cve-tracker-bug task
    - General issues: Problems affecting entire release (related_tasks=None or empty)
      Example: "ART build pipeline down - ETA: 2025-01-16"

    Constraints:
    - Only ONE unresolved blocker per task allowed (prevents duplicate blocking issues)
    - Multiple non-blocking issues per task allowed (for tracking improvements)
    - Automatic deduplication: Won't create duplicate issues with same description

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        issue: Issue description (human-readable root cause)
        blocker: Is this a blocking issue? (default: True)
        related_tasks: Comma-separated task names (e.g., "check-cve-tracker-bug,take-ownership")
                      Leave None or empty for general issues affecting entire release

    Returns:
        JSON string with issue entry details

    Examples:
        # Blocking issue for specific task
        oar_add_issue("4.19.1", "CVE-2024-12345 not covered in advisory", True, "check-cve-tracker-bug")

        # General blocking issue
        oar_add_issue("4.19.1", "ART build pipeline down - ETA: 2025-01-16", True, None)

        # Non-blocking issue (automation improvement)
        oar_add_issue("4.19.1", "Jenkins job timeout - retry succeeded", False, "image-consistency-check")
    """
    try:
        cs = get_cached_configstore(release)
        statebox = StateBox(cs)

        # Parse related_tasks
        task_list = None
        if related_tasks:
            task_list = [t.strip() for t in related_tasks.split(",") if t.strip()]

        # Add issue
        issue_entry = statebox.add_issue(
            issue=issue,
            blocker=blocker,
            related_tasks=task_list,
            auto_save=True
        )

        logger.info(f"Added issue to StateBox (release: {release}, blocker: {blocker})")

        return json.dumps({
            "success": True,
            "message": f"Added {'blocking' if blocker else 'non-blocking'} issue",
            "issue": issue_entry,
            "release": release
        })

    except StateBoxException as e:
        logger.error(f"Failed to add issue: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "release": release
        })
    except Exception as e:
        logger.error(f"Unexpected error adding issue: {e}")
        return json.dumps({
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "release": release
        })


@mcp.tool()
async def oar_resolve_issue(
    release: str,
    issue: str,
    resolution: str
) -> str:
    """
    Resolve an issue in StateBox when problem is fixed.

    ⚠️ WRITE OPERATION: Updates issue resolution status in StateBox.

    Use this tool to mark issues as resolved after problems are fixed.
    Supports fuzzy matching - you can provide partial issue description.

    Matching Logic:
    1. Try exact match (case-insensitive)
    2. Try partial match (input is substring of existing issue)

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        issue: Issue description (can be partial, case-insensitive)
        resolution: Resolution description (how the problem was fixed)

    Returns:
        JSON string with resolved issue details

    Examples:
        # Exact match
        oar_resolve_issue("4.19.1", "CVE-2024-12345 not covered", "CVE added to advisory 156789")

        # Partial match
        oar_resolve_issue("4.19.1", "pipeline down", "Pipeline restored at 14:30 UTC")

        # General blocker resolved
        oar_resolve_issue("4.19.1", "ART build", "Build pipeline operational again")
    """
    try:
        cs = get_cached_configstore(release)
        statebox = StateBox(cs)

        # Resolve issue
        resolved_issue = statebox.resolve_issue(
            issue=issue,
            resolution=resolution,
            auto_save=True
        )

        logger.info(f"Resolved issue in StateBox (release: {release})")

        return json.dumps({
            "success": True,
            "message": "Issue resolved successfully",
            "issue": resolved_issue,
            "release": release
        })

    except StateBoxException as e:
        logger.error(f"Failed to resolve issue: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "release": release
        })
    except Exception as e:
        logger.error(f"Unexpected error resolving issue: {e}")
        return json.dumps({
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "release": release
        })


@mcp.tool()
async def oar_get_issues(
    release: str,
    unresolved_only: bool = False,
    blockers_only: bool = False,
    task_name: Optional[str] = None
) -> str:
    """
    Get issues from StateBox with optional filtering.

    This is a READ-ONLY operation - retrieves issues for analysis.

    Use this tool to:
    - Understand what's blocking release progress
    - Get context on problems that need attention
    - Check if specific task has blockers
    - Review resolved issues for historical context

    Filter combinations:
    - No filters: Get all issues (resolved + unresolved, blockers + non-blockers)
    - unresolved_only=True: Get only active issues
    - blockers_only=True: Get only blocking issues
    - task_name="xxx": Get issues related to specific task
    - Combine filters: e.g., unresolved blockers for specific task

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        unresolved_only: Only return unresolved issues (default: False)
        blockers_only: Only return blocking issues (default: False)
        task_name: Only return issues related to specific task (default: None)

    Returns:
        JSON string with list of issues matching filters

    Examples:
        # Get all unresolved blockers (what's stopping release?)
        oar_get_issues("4.19.1", unresolved_only=True, blockers_only=True)

        # Get issues for specific task
        oar_get_issues("4.19.1", task_name="check-cve-tracker-bug")

        # Get all issues (historical view)
        oar_get_issues("4.19.1")
    """
    try:
        cs = get_cached_configstore(release)
        statebox = StateBox(cs)

        # Get issues with filters
        issues = statebox.get_issues(
            unresolved_only=unresolved_only,
            blockers_only=blockers_only,
            task_name=task_name
        )

        logger.info(f"Retrieved {len(issues)} issues from StateBox (release: {release})")

        return json.dumps({
            "success": True,
            "count": len(issues),
            "issues": issues,
            "filters": {
                "unresolved_only": unresolved_only,
                "blockers_only": blockers_only,
                "task_name": task_name
            },
            "release": release
        })

    except StateBoxException as e:
        logger.error(f"Failed to get issues: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "release": release,
            "count": 0,
            "issues": []
        })
    except Exception as e:
        logger.error(f"Unexpected error getting issues: {e}")
        return json.dumps({
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "release": release,
            "count": 0,
            "issues": []
        })


@mcp.tool()
async def oar_get_task_blocker(
    release: str,
    task_name: str
) -> str:
    """
    Get unresolved blocking issue for a specific task.

    This is a READ-ONLY operation - checks if task is blocked.

    Use this tool to:
    - Check if task has a blocker before starting work
    - Understand why task is blocked
    - Validate that blocker was resolved before retrying task

    Note: Only returns ONE blocker per task (enforced by StateBox constraint).
    If task has no blocker, returns None.

    Args:
        release: Z-stream release version (e.g., "4.19.1")
        task_name: Task name (e.g., "check-cve-tracker-bug", "image-consistency-check")

    Returns:
        JSON string with blocker details or None if task not blocked

    Examples:
        # Check if task is blocked
        oar_get_task_blocker("4.19.1", "check-cve-tracker-bug")

        # Returns:
        # {
        #   "success": true,
        #   "blocked": true,
        #   "blocker": {
        #     "issue": "CVE-2024-12345 not covered in advisory",
        #     "reported_at": "2025-01-15T10:00:00Z",
        #     "resolved": false,
        #     "blocker": true,
        #     "related_tasks": ["check-cve-tracker-bug"]
        #   }
        # }

        # If not blocked:
        # {
        #   "success": true,
        #   "blocked": false,
        #   "blocker": null
        # }
    """
    try:
        cs = get_cached_configstore(release)
        statebox = StateBox(cs)

        # Get task blocker
        blocker = statebox.get_task_blocker(task_name)

        if blocker:
            logger.info(f"Task '{task_name}' is blocked (release: {release})")
        else:
            logger.info(f"Task '{task_name}' has no blocker (release: {release})")

        return json.dumps({
            "success": True,
            "blocked": blocker is not None,
            "blocker": blocker,
            "task_name": task_name,
            "release": release
        })

    except StateBoxException as e:
        logger.error(f"Failed to get task blocker: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "release": release,
            "task_name": task_name,
            "blocked": False,
            "blocker": None
        })
    except Exception as e:
        logger.error(f"Unexpected error getting task blocker: {e}")
        return json.dumps({
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "release": release,
            "task_name": task_name,
            "blocked": False,
            "blocker": None
        })


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
    logger.info("Starting Release Tests MCP Server (Optimized)")
    logger.info("=" * 60)
    logger.info(f"✓ Environment validation: PASSED")
    logger.info(f"✓ Transport: SSE (HTTP)")
    logger.info(f"✓ All required credentials configured")
    logger.info(f"✓ Performance: 100% optimized (NO subprocess)")
    logger.info(f"✓ ConfigStore caching: Enabled (TTL=7 days)")
    logger.info(f"✓ Total tools: 31 (20 CLI + 11 direct API)")
    logger.info(f"✓ CLI tools: 11 OAR + 2 oarctl + 6 jobctl + 1 job")
    logger.info(f"✓ Direct API tools: 4 config + 4 issue + 3 cache")
    logger.info(f"✓ Thread pool: {CLI_THREAD_POOL_SIZE} workers")
    logger.info("=" * 60)

    # Run MCP server with graceful shutdown handling
    # Default: host=127.0.0.1, port=8000
    # For remote access, override with: mcp.run(transport="sse", host="0.0.0.0", port=8080)
    try:
        mcp.run(transport="sse")
    except KeyboardInterrupt:
        logger.info("Received shutdown signal (Ctrl+C)")
    finally:
        # Graceful shutdown of thread pool
        logger.info("Shutting down thread pool...")
        CLI_THREAD_POOL.shutdown(wait=True, cancel_futures=False)
        logger.info("✓ Thread pool shutdown complete")
        logger.info("✓ Server stopped gracefully")
