#!/usr/bin/env python3
"""
Unit tests for ConfigStore cache implementation.

Tests the caching behavior, TTL expiration, LRU eviction, and metrics tracking.
"""

import unittest
import time
import sys
import os
from unittest.mock import Mock, patch
from threading import Thread

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the actual cache implementation from server.py
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mcp_server'))
from server import ConfigStoreCache, CacheMetrics


# Mock ConfigStore for testing without external dependencies
class MockConfigStore:
    """Mock ConfigStore for testing without external dependencies."""
    def __init__(self, release: str):
        self.release = release
        # Simulate some initialization time
        time.sleep(0.01)  # 10ms


class TestConfigStoreCache(unittest.TestCase):
    """Test cases for ConfigStore cache implementation."""

    def setUp(self):
        """Set up test fixtures."""
        # Create cache with short TTL for testing
        self.cache = ConfigStoreCache(max_size=3, ttl_seconds=1)

    @patch('server.ConfigStore', MockConfigStore)
    def test_cache_miss_creates_entry(self):
        """Test that cache miss creates new entry and increments miss counter."""
        cs = self.cache.get("4.19.1")

        self.assertIsNotNone(cs)
        self.assertEqual(cs.release, "4.19.1")
        self.assertEqual(self.cache.metrics.misses, 1)
        self.assertEqual(self.cache.metrics.hits, 0)

    @patch('server.ConfigStore', MockConfigStore)
    def test_cache_hit_returns_cached_entry(self):
        """Test that subsequent access returns cached entry and increments hit counter."""
        # First access - miss
        cs1 = self.cache.get("4.19.1")

        # Second access - hit
        cs2 = self.cache.get("4.19.1")

        self.assertIs(cs1, cs2)  # Same object
        self.assertEqual(self.cache.metrics.misses, 1)
        self.assertEqual(self.cache.metrics.hits, 1)

    @patch('server.ConfigStore', MockConfigStore)
    def test_cache_hit_rate_calculation(self):
        """Test that hit rate is calculated correctly."""
        # 1 miss
        self.cache.get("4.19.1")
        self.assertEqual(self.cache.metrics.hit_rate(), 0.0)

        # 1 hit
        self.cache.get("4.19.1")
        self.assertEqual(self.cache.metrics.hit_rate(), 50.0)

        # 2 more hits
        self.cache.get("4.19.1")
        self.cache.get("4.19.1")
        self.assertEqual(self.cache.metrics.hit_rate(), 75.0)

    @patch('server.ConfigStore', MockConfigStore)
    def test_ttl_expiration(self):
        """Test that entries expire after TTL."""
        # Add entry
        cs1 = self.cache.get("4.19.1")

        # Wait for TTL to expire (1 second + buffer)
        time.sleep(1.2)

        # Access again - should be miss (expired)
        cs2 = self.cache.get("4.19.1")

        self.assertIsNot(cs1, cs2)  # Different objects
        self.assertEqual(self.cache.metrics.misses, 2)  # Both were misses
        self.assertEqual(self.cache.metrics.hits, 0)

    @patch('server.ConfigStore', MockConfigStore)
    def test_lru_eviction(self):
        """Test that LRU eviction works when cache is full."""
        # Fill cache (max_size=3)
        self.cache.get("4.19.1")
        self.cache.get("4.18.5")
        self.cache.get("4.17.10")

        # Add 4th entry - should evict oldest (4.19.1)
        self.cache.get("4.16.15")

        self.assertEqual(self.cache.metrics.evictions, 1)
        self.assertEqual(len(self.cache._cache), 3)

        # Verify 4.19.1 was evicted (access should be miss)
        initial_misses = self.cache.metrics.misses
        self.cache.get("4.19.1")
        self.assertEqual(self.cache.metrics.misses, initial_misses + 1)

    def test_manual_invalidation_specific_release(self):
        """Test manual invalidation of specific release."""
        # Manually add entries to cache (bypass ConfigStore creation)
        self.cache._cache["4.19.1"] = MockConfigStore("4.19.1")
        self.cache._cache["4.18.5"] = MockConfigStore("4.18.5")

        # Invalidate specific release
        self.cache.invalidate("4.19.1")

        self.assertEqual(self.cache.metrics.manual_invalidations, 1)
        self.assertEqual(len(self.cache._cache), 1)

    def test_manual_invalidation_all_releases(self):
        """Test manual invalidation of all releases."""
        # Manually add entries to cache
        self.cache._cache["4.19.1"] = MockConfigStore("4.19.1")
        self.cache._cache["4.18.5"] = MockConfigStore("4.18.5")
        self.cache._cache["4.17.10"] = MockConfigStore("4.17.10")

        # Invalidate all
        self.cache.invalidate(None)

        self.assertEqual(self.cache.metrics.manual_invalidations, 3)
        self.assertEqual(len(self.cache._cache), 0)

    @patch('server.ConfigStore', MockConfigStore)
    def test_cache_warming(self):
        """Test cache warming with multiple releases."""
        releases = ["4.19.1", "4.18.5", "4.17.10"]

        # Warm cache
        self.cache.warm(releases)

        # All should be cached now
        self.assertEqual(len(self.cache._cache), 3)
        self.assertEqual(self.cache.metrics.misses, 3)

        # Accessing them should be hits
        for release in releases:
            self.cache.get(release)

        self.assertEqual(self.cache.metrics.hits, 3)

    @patch('server.ConfigStore', MockConfigStore)
    def test_cache_stats(self):
        """Test cache statistics reporting."""
        self.cache.get("4.19.1")
        self.cache.get("4.18.5")
        self.cache.get("4.19.1")  # Hit

        stats = self.cache.stats()

        self.assertEqual(stats["cache_size"], 2)
        self.assertEqual(stats["max_size"], 3)
        self.assertEqual(stats["metrics"]["hits"], 1)
        self.assertEqual(stats["metrics"]["misses"], 2)
        self.assertEqual(stats["metrics"]["hit_rate"], "33.33%")
        self.assertEqual(len(stats["entries"]), 2)

    @patch('server.ConfigStore', MockConfigStore)
    def test_thread_safety(self):
        """Test that cache is thread-safe under concurrent access."""
        results = []

        def worker(release: str):
            """Worker thread that accesses cache."""
            for _ in range(10):
                cs = self.cache.get(release)
                results.append(cs)

        # Create multiple threads accessing same release
        threads = [Thread(target=worker, args=("4.19.1",)) for _ in range(5)]

        # Start all threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # All results for same release should be same object
        first_result = results[0]
        for result in results:
            if result.release == "4.19.1":
                self.assertIs(result, first_result)

        # Should only have 1 miss (first access creates it)
        self.assertEqual(self.cache.metrics.misses, 1)

    @patch('server.ConfigStore', MockConfigStore)
    def test_multiple_releases(self):
        """Test caching multiple different releases."""
        releases = ["4.19.1", "4.18.5", "4.17.10"]

        # Cache all releases
        for release in releases:
            self.cache.get(release)

        # All should be cached
        self.assertEqual(len(self.cache._cache), 3)

        # Access all again - all hits
        for release in releases:
            self.cache.get(release)

        self.assertEqual(self.cache.metrics.hits, 3)
        self.assertEqual(self.cache.metrics.misses, 3)


class TestCacheMetrics(unittest.TestCase):
    """Test cases for CacheMetrics class."""

    def test_initial_state(self):
        """Test initial metrics state."""
        metrics = CacheMetrics()

        self.assertEqual(metrics.hits, 0)
        self.assertEqual(metrics.misses, 0)
        self.assertEqual(metrics.evictions, 0)
        self.assertEqual(metrics.manual_invalidations, 0)
        self.assertEqual(metrics.hit_rate(), 0.0)

    def test_hit_rate_zero_requests(self):
        """Test hit rate with zero requests."""
        metrics = CacheMetrics()
        self.assertEqual(metrics.hit_rate(), 0.0)

    def test_hit_rate_all_hits(self):
        """Test hit rate with all hits."""
        metrics = CacheMetrics(hits=10, misses=0)
        self.assertEqual(metrics.hit_rate(), 100.0)

    def test_hit_rate_all_misses(self):
        """Test hit rate with all misses."""
        metrics = CacheMetrics(hits=0, misses=10)
        self.assertEqual(metrics.hit_rate(), 0.0)

    def test_hit_rate_mixed(self):
        """Test hit rate with mixed hits and misses."""
        metrics = CacheMetrics(hits=7, misses=3)
        self.assertEqual(metrics.hit_rate(), 70.0)

    def test_to_dict(self):
        """Test metrics to_dict conversion."""
        metrics = CacheMetrics(hits=7, misses=3, evictions=2, manual_invalidations=1)
        d = metrics.to_dict()

        self.assertEqual(d["hits"], 7)
        self.assertEqual(d["misses"], 3)
        self.assertEqual(d["evictions"], 2)
        self.assertEqual(d["manual_invalidations"], 1)
        self.assertEqual(d["hit_rate"], "70.00%")
        self.assertEqual(d["total_requests"], 10)


if __name__ == "__main__":
    unittest.main()