"""GitHub API integration for claim notifications (Issue #16).

Posts comments on GitHub issues when bounties are claimed or released.
Requires GITHUB_TOKEN environment variable with repo scope.
Gracefully no-ops if token is not configured.
"""

import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_API_BASE = "https://api.github.com"


def _parse_issue_url(github_issue_url: str) -> Optional[tuple[str, str, int]]:
    """
    Extract owner, repo, and issue number from a GitHub issue URL.

    Example: "https://github.com/org/repo/issues/42" -> ("org", "repo", 42)
    Returns None if the URL cannot be parsed.
    """
    match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)",
        github_issue_url,
    )
    if not match:
        return None
    return match.group(1), match.group(2), int(match.group(3))


async def post_claim_comment(
    github_issue_url: str,
    username: str,
    deadline: str,
) -> bool:
    """
    Post a comment on a GitHub issue when a bounty is claimed.

    Args:
        github_issue_url: Full GitHub issue URL
        username: GitHub username of the claimer
        deadline: Formatted deadline string

    Returns:
        True if comment was posted successfully, False otherwise.
    """
    if not GITHUB_TOKEN:
        logger.debug("GITHUB_TOKEN not set, skipping claim comment")
        return False

    parsed = _parse_issue_url(github_issue_url)
    if not parsed:
        logger.warning("Could not parse GitHub issue URL: %s", github_issue_url)
        return False

    owner, repo, issue_number = parsed
    body = f"🔒 **Claimed by @{username}** — deadline: {deadline}"

    return await _post_comment(owner, repo, issue_number, body)


async def post_release_comment(
    github_issue_url: str,
    username: str,
    reason: str,
) -> bool:
    """
    Post a comment on a GitHub issue when a claim is released.

    Args:
        github_issue_url: Full GitHub issue URL
        username: GitHub username of the claimer
        reason: Why the claim was released (e.g., "voluntary", "expired")

    Returns:
        True if comment was posted successfully, False otherwise.
    """
    if not GITHUB_TOKEN:
        logger.debug("GITHUB_TOKEN not set, skipping release comment")
        return False

    parsed = _parse_issue_url(github_issue_url)
    if not parsed:
        logger.warning("Could not parse GitHub issue URL: %s", github_issue_url)
        return False

    owner, repo, issue_number = parsed
    body = f"🔓 **Released by @{username}** ({reason})"

    return await _post_comment(owner, repo, issue_number, body)


async def _post_comment(
    owner: str,
    repo: str,
    issue_number: int,
    body: str,
) -> bool:
    """Post a comment on a GitHub issue via the API."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={"body": body},
                headers=headers,
                timeout=10.0,
            )
            if response.status_code == 201:
                logger.info(
                    "Posted comment on %s/%s#%d",
                    owner, repo, issue_number,
                )
                return True
            else:
                logger.error(
                    "Failed to post comment on %s/%s#%d: %d %s",
                    owner, repo, issue_number,
                    response.status_code, response.text,
                )
                return False
    except httpx.HTTPError as e:
        logger.error("HTTP error posting comment: %s", e)
        return False
