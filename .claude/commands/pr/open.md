---
description: Show open pull requests in the repository
---

## Usage

List open pull requests in the repository with various filtering options.

**Basic usage:**
```bash
/pr:open
```

**Filter by author:**
```bash
/pr:open --author @me
/pr:open --author username
```

**Filter by label:**
```bash
/pr:open --label bug
/pr:open --label do-not-merge/hold
```

**Filter by assignee:**
```bash
/pr:open --assignee username
```

**Change state filter:**
```bash
/pr:open --state all
/pr:open --state closed
/pr:open --state merged
```

**Limit results:**
```bash
/pr:open --limit 10
```

**Combine filters:**
```bash
/pr:open --author @me --state all --limit 5
/pr:open --label bug --assignee username
```

---

You are helping the user list open pull requests in this repository.

Follow these steps:
1. Parse the args to check for any filters (author, label, etc.)
2. Use `gh pr list` to get open PRs with relevant information
3. Display the results in a clear, readable format

Available filters from args:
- `--author <username>` - Filter by author
- `--label <label>` - Filter by label
- `--limit <number>` - Limit number of results (default: 30)
- `--assignee <username>` - Filter by assignee
- `--state <state>` - Filter by state (open, closed, merged, all)

Example commands:
- List all open PRs: `gh pr list --state open`
- List my PRs: `gh pr list --author @me`
- List PRs with specific label: `gh pr list --label bug`
- Show more details: `gh pr list --state open --json number,title,author,updatedAt,labels,state,isDraft,statusCheckRollup`

The output should show:
- PR number
- Title
- Author
- Status (draft, checks passing/failing)
- Labels
- Last updated

Args from user: {{args}}
