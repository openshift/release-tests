"""GitHub App auth for ERT (Writer: release-tests, Reader: openshift/*)."""

from pathlib import Path

from github import Auth, Github, GithubIntegration


class GitHubApp:
    """PyGithub client via GitHub App installation token."""

    def __init__(self, app_id: str, private_key: str):
        """
        Initialize GitHub App authentication.

        Args:
            app_id: Application ID (not Client ID).
            private_key: PEM contents or path to a .pem file.
        """
        key = private_key
        key_path = Path(private_key).expanduser()
        if key_path.is_file():
            key = key_path.read_text()
        auth = Auth.AppAuth(app_id, key)
        self._integration = GithubIntegration(auth=auth)

    def client_for_repo(self, owner: str, repo: str) -> Github:
        """
        Return a Github client for ``owner/repo``.

        Args:
            owner: GitHub org or user (e.g. ``openshift``).
            repo: Repository name (e.g. ``release-tests``).

        Returns:
            Installation-scoped ``Github`` client.

        Raises:
            GithubException: App not installed on the repo or invalid credentials.
        """
        installation = self._integration.get_repo_installation(owner, repo)
        return self._integration.get_github_for_installation(installation.id)
