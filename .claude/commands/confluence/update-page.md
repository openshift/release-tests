---
description: Update an existing Confluence page content
---

You are helping the user update an existing Confluence page.

The user has provided: {{args}}

**IMPORTANT**: Before proceeding, check if the input is empty or missing:
- If `{{args}}` is empty, blank, or literally "{{args}}", show usage help (see "If no input provided" section below)
- Otherwise, proceed with parsing and updating the page

Follow these steps:

1. **Parse the input**:
   - **If page ID provided**: Use directly
   - **If URL provided**: Extract page ID from URL
   - **If title + space**: Search for page first to get ID
   - **If only title**: Ask for space key

2. **Fetch current page content** first:
   - Use `mcp__mcp-atlassian__confluence_get_page` to get existing content
   - Show current content to user
   - This ensures we have the latest version and user can review

3. **Ask for update approach**:
   - **Full replacement**: New content replaces everything
   - **Append**: Add new content to the end
   - **Prepend**: Add new content to the beginning
   - **Section update**: Update specific section (if user specifies)

4. **Get new content**:
   - Ask user to provide the new/additional content
   - Confirm the changes before applying
   - Show a diff if possible (old vs new)

5. **Update the page** using Confluence MCP tool:
   ```
   mcp__mcp-atlassian__confluence_update_page
   ```

   Parameters:
   - `page_id`: The page ID
   - `title`: Page title (can keep same or change)
   - `content`: The updated content
   - `content_format`: "markdown" (default), "wiki", or "storage"
   - `is_minor_edit`: false (default), true for minor changes
   - `version_comment`: Optional comment explaining the change

6. **Confirm update**:
   ```markdown
   # ✅ Page Updated Successfully

   **Page**: {title}
   **Page ID**: {page_id}
   **New Version**: {new_version}
   **URL**: {page_url}
   {if version_comment:}
   **Change Comment**: {version_comment}

   ## Changes Made
   {summary of what changed}

   You can:
   - View updated page: {page_url}
   - View page history for version comparison
   - Rollback if needed using Confluence UI
   ```

7. **If update fails**:
   - Check if user has edit permission
   - Verify page wasn't edited by someone else (version conflict)
   - Check content format is valid
   - Provide error details and resolution steps

## Example Usage

```bash
# Update by page ID
/confluence:update-page 123456789

# Update by URL
/confluence:update-page https://company.atlassian.net/wiki/spaces/DEV/pages/123456789/My+Page

# Update by title and space
/confluence:update-page "Release Notes" in DEV
```

## Update Strategies

**Full Replacement**:
- Completely replaces page content
- Good for major rewrites
- **Warning**: Old content is lost (but kept in version history)

**Append**:
- Adds new content after existing content
- Good for adding new sections
- Preserves all existing content

**Prepend**:
- Adds new content before existing content
- Good for adding notices or updates at top
- Preserves all existing content

**Section Update**:
- Updates specific heading/section
- Requires parsing markdown to identify section
- Most complex but most precise

## Best Practices

- **Always review current content first** before updating
- **Use version comments** to track why changes were made
- **Mark as minor edit** for typo fixes, formatting
- **Use major edit** (default) for content changes
- **Test updates** on test pages first if unsure
- **Keep backups** of important content before major changes

## Version Comments

Good version comment examples:
- "Added Q4 2024 release notes"
- "Updated API endpoint documentation"
- "Fixed typos in installation section"
- "Removed outdated information about v1.0"

## Safety Features

- Page version is tracked - can always revert
- Version history preserved in Confluence
- Can preview changes before confirming
- Warns if content might be lost

## If no input provided

If the input is empty or missing, display this help message:

```markdown
# Confluence Update Page

You need to provide a page identifier to update an existing Confluence page.

## Usage

```
/confluence:update-page <page_identifier>
```

## Examples

**Update by page ID:**
```
/confluence:update-page 123456789
```

**Update by URL:**
```
/confluence:update-page https://company.atlassian.net/wiki/spaces/DEV/pages/123456789/My+Page
```

**Update by title and space:**
```
/confluence:update-page "Release Notes" in DEV
/confluence:update-page "MCP Server Documentation" in OCPERT
```

## Workflow

After providing the page identifier, I will:
1. Fetch the current page content
2. Show you the existing content
3. Ask how you want to update it (replace, append, prepend, or section update)
4. Get your new content
5. Confirm changes before applying
6. Update the page with optional version comment

## Update Strategies

- **Full replacement**: Replace all content (old content in version history)
- **Append**: Add new content at the end
- **Prepend**: Add new content at the beginning
- **Section update**: Update specific section only

## Need help?

Tell me which page you want to update, and I'll guide you through the process!
You can also use `/confluence:search` to find pages by keyword.
```
