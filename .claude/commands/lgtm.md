---
description: Add /lgtm comment to a PR
---

You are helping the user add a /lgtm comment to a pull request.

Follow these steps:
1. If no PR number is provided in the args, ask the user which PR number
2. Add a comment to the PR with "/lgtm" using: `gh pr comment <PR_NUMBER> --body "/lgtm"`
3. Confirm to the user that the comment was added

The GitHub bot will automatically add the lgtm label when it sees this comment.

PR number from args: {{args}}
