"""GitHub App auth utilities for prow/job.

This module intentionally lives under ``prow/job`` so the prow "job/jobctl"
package can be installed standalone (without depending on the full ``oar`` app).
"""

from pathlib import Path

from github import Auth, Github, GithubIntegration


class GitHubApp:
    """PyGithub client via GitHub App installation token."""

    def __init__(self, app_id: str, private_key_path: str):
        if "\n" in private_key_path or "-----BEGIN" in private_key_path:
            raise ValueError(
                "private_key_path must be a path to a .pem file, not inline key content"
            )
        key_file = Path(private_key_path).expanduser()
        if not key_file.is_file():
            raise FileNotFoundError("GitHub App private key file not found")
        key = key_file.read_text()
        auth = Auth.AppAuth(app_id, key)
        self._integration = GithubIntegration(auth=auth)

    def installation_token(self, owner: str, repo: str) -> str:
        installation = self._integration.get_repo_installation(owner, repo)
        return self._integration.get_access_token(installation.id).token

    def client_for_repo(self, owner: str, repo: str) -> Github:
        installation = self._integration.get_repo_installation(owner, repo)
        return self._integration.get_github_for_installation(installation.id)

