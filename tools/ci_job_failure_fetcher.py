#!/usr/bin/env python3
"""
CI Job Failure Fetcher

Fetches detailed test failure information from OpenShift CI Prow jobs
for AI-powered analysis by Claude Code.

Usage:
    python ci_job_failure_fetcher.py <prow_deck_url>

Example:
    python ci_job_failure_fetcher.py https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/qe-private-deck/logs/periodic-ci-openshift-openshift-tests-private-release-4.20-automated-release-aws-ipi-f999/1979765746749673472
"""

import json
import logging
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Tuple
from xml.etree import ElementTree

# Add parent directory to path to import from prow package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from prow.job.artifacts import Artifacts

logger = logging.getLogger(__name__)

# Configuration for AI token limit management
MAX_FAILURES_FOR_AI = int(os.getenv('MAX_FAILURES_FOR_AI', '50'))  # Configurable via env var
MAX_MESSAGE_LENGTH = 500  # Characters for error message
MAX_DETAILS_LENGTH = 2000  # Characters for stack trace


class DetailedJunitTestCase:
    """Extended JUnit test case parser that extracts failure messages and stack traces"""

    def __init__(self, element):
        self._element = element

    @property
    def name(self):
        return self._element.attrib.get("name", "Unknown")

    @property
    def classname(self):
        return self._element.attrib.get("classname", "")

    @property
    def time(self):
        return self._element.attrib.get("time", "0")

    def is_failure(self):
        return self._element.find("failure") is not None

    def is_error(self):
        return self._element.find("error") is not None

    def get_failure_info(self) -> Dict:
        """Extract detailed failure information including message and stack trace"""
        failure_elem = self._element.find("failure")
        error_elem = self._element.find("error")

        if failure_elem is not None:
            elem = failure_elem
            failure_type = "failure"
        elif error_elem is not None:
            elem = error_elem
            failure_type = "error"
        else:
            return None

        # Truncate message and details to reduce token usage
        message = elem.attrib.get("message", "")
        details = elem.text or ""

        return {
            "type": failure_type,
            "message": message[:MAX_MESSAGE_LENGTH] + ("..." if len(message) > MAX_MESSAGE_LENGTH else ""),
            "details": details[:MAX_DETAILS_LENGTH] + ("..." if len(details) > MAX_DETAILS_LENGTH else ""),
            "error_type": elem.attrib.get("type", "")
        }


class CIJobFailureFetcher:
    """Fetches and parses CI job failures with detailed information for AI analysis"""

    def __init__(self, prow_deck_url: str, gcs_cred_file: str = None):
        self.prow_deck_url = prow_deck_url
        self.gcs_cred_file = gcs_cred_file or os.getenv('GCS_CRED_FILE')

        if not self.gcs_cred_file:
            raise ValueError("GCS_CRED_FILE environment variable must be set")

        if not os.path.exists(self.gcs_cred_file):
            raise FileNotFoundError(f"GCS credentials file not found: {self.gcs_cred_file}")

        # Parse job info from URL
        self.job_name, self.job_run_id, self.bucket = self._parse_prow_url(prow_deck_url)

        # Initialize artifacts client
        self.artifacts = Artifacts(
            cred_file=self.gcs_cred_file,
            job_name=self.job_name,
            job_run_id=self.job_run_id,
            bucket=self.bucket
        )

    def _group_failures_by_pattern(self, failures: List[Dict]) -> List[Dict]:
        """
        Group failures with similar error signatures to identify patterns.

        Returns:
            List of grouped failure patterns with representative examples
        """
        if not failures:
            return []

        # Group by error signature (message + error_type)
        groups = defaultdict(list)
        for failure in failures:
            # Create signature from error message (first 200 chars) + error type
            signature = f"{failure['error_type']}:{failure['message'][:200]}"
            groups[signature].append(failure)

        # Convert to grouped format with representative samples
        grouped_failures = []
        for signature, items in sorted(groups.items(), key=lambda x: len(x[1]), reverse=True):
            # Take the first item as representative
            representative = items[0].copy()

            grouped_failures.append({
                "pattern_signature": signature[:100],  # Truncate for readability
                "occurrence_count": len(items),
                "representative_failure": representative,
                "affected_tests": [f['test_name'] for f in items[:10]],  # Max 10 examples
                "all_test_count": len(items),
                "suites": list(set(f['suite'] for f in items))[:5]  # Up to 5 unique suites
            })

        return grouped_failures

    def _parse_prow_url(self, url: str) -> Tuple[str, str, str]:
        """Parse Prow deck URL to extract job name, run ID, and bucket"""
        # Pattern: /view/gs/{bucket}/logs/{job_name}/{job_run_id}
        pattern = r'/view/gs/([^/]+)/logs/([^/]+)/(\d+)'
        match = re.search(pattern, url)

        if not match:
            raise ValueError(f"Invalid Prow deck URL format: {url}")

        bucket = match.group(1)
        job_name = match.group(2)
        job_run_id = match.group(3)

        return job_name, job_run_id, bucket

    def fetch_failures(self) -> Dict:
        """
        Fetch detailed failure information from JUnit XML files

        Returns:
            Dictionary with comprehensive failure data for AI analysis
        """
        logger.info(f"Fetching test results for job {self.job_name}, run ID {self.job_run_id}")

        # Fetch JUnit files from GCS
        junit_files = self.artifacts.get_junit_files()
        logger.info(f"Found {len(junit_files)} JUnit XML files" if junit_files else "No JUnit XML files found")

        if not junit_files:
            # No JUnit files - likely infrastructure/setup failure
            # Fetch build log for analysis
            logger.info("Attempting to fetch build log for infrastructure failure analysis")
            build_log = None
            try:
                build_log = self.artifacts.get_build_log()
                logger.info(f"Successfully fetched build log ({len(build_log)} bytes)")
            except Exception as e:
                logger.warning(f"Could not fetch build log: {e}")

            return {
                'job_name': self.job_name,
                'job_run_id': self.job_run_id,
                'error': 'No JUnit XML files found - likely infrastructure or setup failure',
                'build_log_url': self._get_build_log_url(),
                'build_log_snippet': build_log[-20000:] if build_log else None,  # Last 20KB for errors
                'gcsweb_url': self._get_gcsweb_url(),
                'analysis_type': 'infrastructure_failure'
            }

        # Parse all test results
        logger.info("Parsing JUnit XML files for test results")
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        error_tests = 0
        skipped_tests = 0
        failures = []
        suites_info = []

        for junit_blob in junit_files:
            # Parse XML
            xml_content = junit_blob.download_as_bytes().decode("utf-8")
            root = ElementTree.fromstring(xml_content)

            # Get suite info
            suite_name = root.attrib.get("name", "Unknown Suite")
            suite_tests = int(root.attrib.get("tests", "0"))
            suite_failures = int(root.attrib.get("failures", "0"))
            suite_errors = int(root.attrib.get("errors", "0"))
            suite_skipped = int(root.attrib.get("skipped", "0"))

            total_tests += suite_tests
            failed_tests += suite_failures
            error_tests += suite_errors
            skipped_tests += suite_skipped

            suites_info.append({
                "name": suite_name,
                "tests": suite_tests,
                "failures": suite_failures,
                "errors": suite_errors,
                "skipped": suite_skipped,
                "source_file": junit_blob.name
            })

            # Extract detailed failure information
            if suite_failures > 0 or suite_errors > 0:
                test_cases = root.findall(".//testcase")
                for tc_elem in test_cases:
                    tc = DetailedJunitTestCase(tc_elem)
                    if tc.is_failure() or tc.is_error():
                        failure_info = tc.get_failure_info()
                        failures.append({
                            "test_name": tc.name,
                            "classname": tc.classname,
                            "suite": suite_name,
                            "duration": tc.time,
                            "failure_type": failure_info["type"],
                            "error_type": failure_info["error_type"],
                            "message": failure_info["message"],
                            "details": failure_info["details"],
                            "source_file": junit_blob.name
                        })

        passed_tests = total_tests - failed_tests - error_tests - skipped_tests

        logger.info(f"Test result summary: {total_tests} total, {passed_tests} passed, {failed_tests} failed, {error_tests} errors, {skipped_tests} skipped")
        if failed_tests > 0 or error_tests > 0:
            logger.warning(f"Found {len(failures)} failed test case(s)")

        # Group failures by pattern to identify common issues
        failure_patterns = self._group_failures_by_pattern(failures)
        logger.info(f"Identified {len(failure_patterns)} unique failure patterns")

        # Determine if we need to truncate for AI analysis
        total_failure_count = len(failures)
        is_truncated = total_failure_count > MAX_FAILURES_FOR_AI

        # Select failures to send to AI
        if is_truncated:
            # Prioritize by pattern frequency - include representative failures from each pattern
            ai_failures = []
            remaining_quota = MAX_FAILURES_FOR_AI

            for pattern in failure_patterns:
                if remaining_quota <= 0:
                    break
                # Add representative failure from this pattern
                ai_failures.append(pattern['representative_failure'])
                remaining_quota -= 1

            logger.warning(f"Truncated from {total_failure_count} to {len(ai_failures)} failures for AI analysis")
        else:
            ai_failures = failures

        return {
            'job_name': self.job_name,
            'job_run_id': self.job_run_id,
            'prow_deck_url': self.prow_deck_url,
            'gcsweb_url': self._get_gcsweb_url(),
            'summary': {
                'total_tests': total_tests,
                'passed': passed_tests,
                'failed': failed_tests,
                'errors': error_tests,
                'skipped': skipped_tests,
                'junit_files': len(junit_files),
                'total_failures': total_failure_count,
                'unique_patterns': len(failure_patterns),
                'is_truncated': is_truncated
            },
            'suites': suites_info,
            'failure_patterns': failure_patterns,  # Grouped view for pattern analysis
            'failures': ai_failures,  # Individual failures (truncated if needed)
            'truncation_info': {
                'is_truncated': is_truncated,
                'original_count': total_failure_count,
                'analyzed_count': len(ai_failures),
                'max_limit': MAX_FAILURES_FOR_AI
            } if is_truncated else None
        }

    def _get_gcsweb_domain(self) -> str:
        """Get the GCS web domain based on bucket name"""
        if 'qe-private-deck' in self.bucket:
            return 'gcsweb-qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com'
        else:
            return 'gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com'

    def _get_gcsweb_url(self) -> str:
        """Get the GCS web URL for the job artifacts"""
        return f"https://{self._get_gcsweb_domain()}/gcs/{self.bucket}/logs/{self.job_name}/{self.job_run_id}/artifacts/"

    def _get_build_log_url(self) -> str:
        """Get the GCS web URL for the build log"""
        return f"https://{self._get_gcsweb_domain()}/gcs/{self.bucket}/logs/{self.job_name}/{self.job_run_id}/build-log.txt"


def main():
    """Main entry point for CLI usage"""
    # Initialize logging
    logging.basicConfig(
        format="%(asctime)s: %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        level=logging.WARNING,  # Only show warnings and errors to stderr
    )

    if len(sys.argv) < 2:
        print("Usage: python ci_job_failure_fetcher.py <prow_deck_url>", file=sys.stderr)
        print("", file=sys.stderr)
        print("Environment variables:", file=sys.stderr)
        print("  GCS_CRED_FILE: Path to Google Cloud Storage credentials file (required)", file=sys.stderr)
        sys.exit(1)

    prow_url = sys.argv[1]

    try:
        fetcher = CIJobFailureFetcher(prow_url)
        results = fetcher.fetch_failures()

        # Output JSON to stdout for Claude Code to consume
        print(json.dumps(results, indent=2))

    except Exception as e:
        error_output = {
            'error': str(e),
            'error_type': type(e).__name__
        }
        print(json.dumps(error_output, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
