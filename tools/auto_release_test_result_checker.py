import os
import time
import re
import click
import json
from github import Github
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


class TestResultChecker:
    def __init__(self, github_token, repo_name, slack_token, slack_channel, notified_file_path,
                 time_threshold=3600, grace_limit=5, path="_releases", branch="record"):
        self.github = Github(github_token)
        self.repo = self.github.get_repo(repo_name)
        self.slack_client = WebClient(token=slack_token)
        self.slack_channel = slack_channel
        self.notified_file_path = notified_file_path
        self.time_threshold = time_threshold
        self.grace_limit = grace_limit
        self.path = path
        self.branch = branch
        self.notified_files_per_release = {}
        self.grace_counters_per_release = {}
        self.load_notified_files()

    def load_notified_files(self):
        if os.path.exists(self.notified_file_path):
            with open(self.notified_file_path, 'r') as f:
                for line in f:
                    release, file_name, timestamp = line.strip().split(',')
                    if release not in self.notified_files_per_release:
                        self.notified_files_per_release[release] = {}
                        self.grace_counters_per_release[release] = 0
                    self.notified_files_per_release[release][file_name] = float(timestamp)

    def save_notified_files(self):
        with open(self.notified_file_path, 'w') as f:
            for release, files in self.notified_files_per_release.items():
                for file_name, timestamp in files.items():
                    f.write(f"{release},{file_name},{timestamp}\n")

    def extract_release_and_timestamp(self, file_name):
        match = re.search(r'(\d+\.\d+)\.\d+.*-(\d{4}-\d{2}-\d{2}-\d{6})', file_name)
        if match:
            release = match.group(1)
            timestamp_str = match.group(2)
            timestamp = int(timestamp_str.replace('-', ''))
            return release, timestamp
        return None, None

    def iterate_test_result_files(self):
        try:
            files = self.repo.get_contents(self.path, ref=self.branch)
            json_files_with_info = []
            for file in files:
                if file.name.endswith('.json'):
                    release, timestamp = self.extract_release_and_timestamp(file.name)
                    if release and timestamp:
                        json_files_with_info.append((file, release, timestamp))
            json_files_with_info.sort(key=lambda x: x[2], reverse=True)
            current_time = time.time()
            for file, release, _ in json_files_with_info:
                self.check_file(file, release, current_time)
            self.save_notified_files()
        except Exception as e:
            print(f"An error occurred while getting files: {e}")

    def check_file(self, file, release, current_time):
        content = file.decoded_content.decode('utf-8')
        try:
            data = json.loads(content)
            if 'accepted' in data and not data['accepted']:
                if release not in self.notified_files_per_release:
                    self.notified_files_per_release[release] = {}
                    self.grace_counters_per_release[release] = 0
                last_notified_time = self.notified_files_per_release[release].get(file.name)
                if last_notified_time is None or (current_time - last_notified_time) > self.time_threshold:
                    grace_counter = self.grace_counters_per_release[release]
                    if grace_counter < self.grace_limit:
                        self.send_slack_notification(file)
                        self.notified_files_per_release[release][file.name] = current_time
                        self.grace_counters_per_release[release] += 1
                    else:
                        self.send_slack_notification(file)
                        self.notified_files_per_release[release][file.name] = current_time
        except json.JSONDecodeError:
            print(f"Error decoding JSON in file {file.name}")

    def send_slack_notification(self, file):
        file_url = f"https://github.com/{self.repo.full_name}/blob/{self.branch}/{file.path}"
        message = f"Rejected build detected in test result file: <{file_url}|{file.name}>. ERT CI watchers please check!"
        try:
            response = self.slack_client.chat_postMessage(
                channel=self.slack_channel,
                text=message
            )
            print(f"Slack notification sent: {response['ts']}")
        except SlackApiError as e:
            print(f"Error sending Slack notification: {e}")


@click.command()
@click.option('--repo-name', required=True, help='Name of the GitHub repository in the format "owner/repo"')
@click.option('--slack-channel', required=True, help='Name of the Slack channel to send notifications to')
@click.option('--notified-file-path', default='notified_files.txt', help='Path to the file storing notified file names')
@click.option('--time-threshold', default=3600, type=int, help='Time threshold in seconds for re - notification')
@click.option('--grace-limit', default=3, type=int, help='Grace limit for initial notifications')
@click.option('--path', default="_releases", help='Path in the GitHub repository where test result files are located')
@click.option('--branch', default="record", help='Branch in the GitHub repository where test result files are located')
def main(repo_name, slack_channel, notified_file_path,
         time_threshold, grace_limit, path, branch):
    github_token = os.getenv('GITHUB_TOKEN')
    slack_token = os.getenv('SLACK_BOT_TOKEN')

    if not github_token:
        raise click.ClickException("GITHUB_TOKEN environment variable is not set.")
    if not slack_token:
        raise click.ClickException("SLACK_BOT_TOKEN environment variable is not set.")

    checker = TestResultChecker(github_token, repo_name, slack_token, slack_channel, notified_file_path,
                                time_threshold, grace_limit, path, branch)
    checker.iterate_test_result_files()


if __name__ == '__main__':
    main()
