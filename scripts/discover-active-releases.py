#!/usr/bin/env python3
"""
Discover active z-stream releases from StateBox files.
Outputs JSON array of releases for further processing.
"""

import urllib.request
import urllib.error
import yaml
from datetime import datetime, timedelta
import json
import re

today = datetime.now().date()
# How many days after release_date to keep showing the release
keep_days_after_release = 1

print(f"Scanning for active releases (today <= release_date + {keep_days_after_release} days)...\n", flush=True)

active_releases = []

# Auto-discover y-streams by fetching the _releases directory listing from GitHub API
api_url = "https://api.github.com/repos/openshift/release-tests/contents/_releases?ref=z-stream"

try:
    req = urllib.request.Request(api_url)
    req.add_header('Accept', 'application/vnd.github.v3+json')

    with urllib.request.urlopen(req) as response:
        contents = json.loads(response.read())

    # Extract y-stream versions from directory names (e.g., "4.20", "4.21")
    y_streams = []
    pattern = re.compile(r'^4\.\d{1,2}$')

    for item in contents:
        if item['type'] == 'dir' and pattern.match(item['name']):
            y_streams.append(item['name'])

    y_streams.sort(key=lambda v: tuple(map(int, v.split('.'))))
    print(f"Discovered y-streams: {', '.join(y_streams)}\n", flush=True)

except Exception as e:
    print(f"Error discovering y-streams: {e}", flush=True)
    y_streams = []

for y_stream in y_streams:
    # Get the latest release from the tracking file
    tracking_url = f"https://raw.githubusercontent.com/openshift/release-tests/z-stream/_releases/{y_stream}/{y_stream}.z.yaml"

    try:
        with urllib.request.urlopen(tracking_url) as response:
            tracking_data = yaml.safe_load(response.read())

        # Get all releases and sort to find latest
        releases = sorted(tracking_data.get("releases", {}).keys(),
                         key=lambda v: tuple(map(int, v.split('.'))))

        if not releases:
            continue

        latest_release = releases[-1]

        # Fetch the StateBox for this release
        statebox_url = f"https://raw.githubusercontent.com/openshift/release-tests/z-stream/_releases/{y_stream}/statebox/{latest_release}.yaml"

        try:
            with urllib.request.urlopen(statebox_url) as response:
                statebox_data = yaml.safe_load(response.read())

            release_date_str = statebox_data.get("metadata", {}).get("release_date")

            if release_date_str:
                # Parse date in format: 2026-Mar-25
                release_date = datetime.strptime(release_date_str, "%Y-%b-%d").date()

                # Keep if today is within the visibility window after release
                if today <= release_date + timedelta(days=keep_days_after_release):
                    active_releases.append({
                        "version": latest_release,
                        "release_date": release_date,
                        "release_date_str": release_date_str,
                        "days_until_release": (release_date - today).days
                    })

        except urllib.error.HTTPError:
            # StateBox not found - skip this release
            pass

    except (urllib.error.HTTPError, Exception):
        # Tracking file not found or error - skip this y-stream
        pass

# Output as JSON for parsing
print(json.dumps(active_releases, default=str))