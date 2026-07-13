"""GitHub App auth for ERT (Writer: release-tests, Reader: openshift/*)."""

from pathlib import Path

from github import Auth, Github, GithubIntegration


class GitHubApp:
    """PyGithub client via GitHub App installation token."""

    def __init__(self, app_id: str, private_key_path: str):
        """
        Initialize GitHub App authentication.

        Args:
            app_id: Application ID (not Client ID).
            private_key_path: Path to the App private key ``.pem`` file.
        """
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
