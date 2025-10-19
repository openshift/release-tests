---
description: Add /approve comment to a PR
---

You are helping the user add an /approve comment to a pull request.

Follow these steps:
1. If no PR number is provided in the args, ask the user which PR number
2. Add a comment to the PR with "/approve" using: `gh pr comment <PR_NUMBER> --body "/approve"`
3. Confirm to the user that the comment was added

The GitHub bot will automatically add the approved label when it sees this comment.

PR number from args: {{args}}
