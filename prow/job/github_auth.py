"""GitHub App auth helpers for prow/job (Writer and Reader)."""

import os
import sys

from github import Github

from .github_app import GitHubApp

# Keep prow/job installable as a standalone package (do not depend on oar.*).
ENV_VAR_GITHUB_APP_WRITER_ID = "GITHUB_APP_WRITER_ID"
ENV_VAR_GITHUB_APP_WRITER_PRIVATE_KEY = "GITHUB_APP_WRITER_PRIVATE_KEY"
ENV_VAR_GITHUB_APP_READER_ID = "GITHUB_APP_READER_ID"
ENV_VAR_GITHUB_APP_READER_PRIVATE_KEY = "GITHUB_APP_READER_PRIVATE_KEY"

OPENSHIFT_OWNER = "openshift"
RELEASE_REPO = "release"
RELEASE_TESTS_REPO = "release-tests"
REPO_OPENSHIFT_RELEASE = f"{OPENSHIFT_OWNER}/{RELEASE_REPO}"
REPO_RELEASE_TESTS = f"{OPENSHIFT_OWNER}/{RELEASE_TESTS_REPO}"


def _github_app(app_id_env: str, key_env: str) -> GitHubApp:
    app_id = os.environ.get(app_id_env)
    private_key_path = os.environ.get(key_env)
    if not app_id or not private_key_path:
        print(f"Missing {app_id_env} or {key_env}, exit...")
        sys.exit(1)
    try:
        return GitHubApp(app_id, private_key_path)
    except Exception as e:
        print(f"Failed to initialize GitHub App ({type(e).__name__}), exit...")
        sys.exit(1)


def _installation_token(app_id_env: str, key_env: str, owner: str, repo: str) -> str:
    try:
        return _github_app(app_id_env, key_env).installation_token(owner, repo)
    except Exception as e:
        print(f"Failed to get GitHub App installation token ({type(e).__name__}), exit...")
        sys.exit(1)


def _github_client(app_id_env: str, key_env: str, owner: str, repo: str) -> Github:
    try:
        return _github_app(app_id_env, key_env).client_for_repo(owner, repo)
    except Exception as e:
        print(f"Failed to initialize GitHub App client ({type(e).__name__}), exit...")
        sys.exit(1)


def release_tests_github_client() -> Github:
    """Return PyGithub client for ``openshift/release-tests`` (Writer App)."""
    return _github_client(
        ENV_VAR_GITHUB_APP_WRITER_ID,
        ENV_VAR_GITHUB_APP_WRITER_PRIVATE_KEY,
        OPENSHIFT_OWNER,
        RELEASE_TESTS_REPO,
    )


def openshift_release_github_client() -> Github:
    """Return PyGithub client for ``openshift/release`` (Reader App)."""
    return _github_client(
        ENV_VAR_GITHUB_APP_READER_ID,
        ENV_VAR_GITHUB_APP_READER_PRIVATE_KEY,
        OPENSHIFT_OWNER,
        RELEASE_REPO,
    )


def github_client_for_repo(repo: str) -> Github:
    """Return PyGithub client for a supported repository."""
    if repo == REPO_RELEASE_TESTS:
        return release_tests_github_client()
    if repo == REPO_OPENSHIFT_RELEASE:
        return openshift_release_github_client()
    raise ValueError(
        f"Unsupported repo {repo!r}; expected {REPO_RELEASE_TESTS} or {REPO_OPENSHIFT_RELEASE}"
    )


def _bearer_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def release_tests_github_headers() -> dict:
    """HTTP headers with Writer App token for ``openshift/release-tests`` API calls."""
    token = _installation_token(
        ENV_VAR_GITHUB_APP_WRITER_ID,
        ENV_VAR_GITHUB_APP_WRITER_PRIVATE_KEY,
        OPENSHIFT_OWNER,
        RELEASE_TESTS_REPO,
    )
    return _bearer_headers(token)


def openshift_release_github_headers() -> dict:
    """HTTP headers with Reader App token for ``openshift/release`` API calls."""
    token = _installation_token(
        ENV_VAR_GITHUB_APP_READER_ID,
        ENV_VAR_GITHUB_APP_READER_PRIVATE_KEY,
        OPENSHIFT_OWNER,
        RELEASE_REPO,
    )
    return _bearer_headers(token)


def release_tests_clone_url() -> str:
    """Authenticated git clone URL for ``openshift/release-tests`` (Writer App)."""
    token = _installation_token(
        ENV_VAR_GITHUB_APP_WRITER_ID,
        ENV_VAR_GITHUB_APP_WRITER_PRIVATE_KEY,
        OPENSHIFT_OWNER,
        RELEASE_TESTS_REPO,
    )
    return f"https://x-access-token:{token}@github.com/{REPO_RELEASE_TESTS}.git"


def release_tests_bot_email() -> str:
    """Commit email for the Writer GitHub App bot on ``openshift/release-tests``."""
    app_id = os.environ.get(ENV_VAR_GITHUB_APP_WRITER_ID, "")
    return f"{app_id}+release-tests-github-app-openshift[bot]@users.noreply.github.com"


def create_release_tests_pr_with_approval(
    title: str, body: str, head_branch: str, base: str = "main"
) -> None:
    """Open a PR on ``openshift/release-tests`` and add ``lgtm`` / ``approved`` labels."""
    repo = release_tests_github_client().get_repo(REPO_RELEASE_TESTS)
    pr = repo.create_pull(
        title=title,
        body=body,
        base=base,
        head=head_branch,
        maintainer_can_modify=False,
    )
    pr.add_to_labels("lgtm", "approved")
