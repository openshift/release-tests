---
description: Retrieve and display a Confluence page by ID, title, or URL
---

You are helping the user retrieve a Confluence page.

The user has provided: {{args}}

**IMPORTANT**: Before proceeding, check if the input is empty or missing:
- If `{{args}}` is empty, blank, or literally "{{args}}", show usage help (see "If no input provided" section below)
- Otherwise, proceed with parsing and fetching the page

Follow these steps:

1. **Parse the input**:
   - **If URL provided**: Extract page ID from URL
     - Pattern: `https://...atlassian.net/wiki/spaces/{SPACE}/pages/{PAGE_ID}/...`
     - Extract the {PAGE_ID} (numeric)
   - **If page ID provided**: Use directly (numeric ID)
   - **If title + space provided**: Parse format like `"Page Title" in SPACE`
   - **If only title**: Ask user for space key

2. **Fetch the page** using Confluence MCP tool:
   ```
   mcp__mcp-atlassian__confluence_get_page
   ```

   Parameters:
   - If page ID known: `page_id={id}`
   - If title/space: `title={title}` and `space_key={space}`
   - `include_metadata=true` (get creation date, labels, etc.)
   - `convert_to_markdown=true` (easier to read)

3. **Display the page** in a well-formatted way:
   ```markdown
   # {page_title}

   **Space**: {space_key}
   **Created**: {created_date}
   **Last Updated**: {updated_date}
   **Version**: {version_number}
   **Labels**: {labels_list}
   **URL**: {page_url}

   ---

   ## Content

   {markdown_content}

   ---

   ## Metadata
   - **Author**: {creator}
   - **Last Modified By**: {last_modifier}
   - **Page ID**: {page_id}
   ```

4. **If page has child pages**:
   - Mention that child pages exist
   - Offer to list them using `/confluence:list-children` or fetch directly

5. **If page not found**:
   - Suggest using `/confluence:search` to find the page
   - Check if space key is correct
   - Verify user has access to the page

## Input Examples

- `/confluence:get-page 123456789` - By page ID
- `/confluence:get-page https://company.atlassian.net/wiki/spaces/DEV/pages/123456789/My+Page` - By URL
- `/confluence:get-page "Release Notes" in DEV` - By title and space
- `/confluence:get-page "Release Notes"` - Will ask for space key

## Options

If user wants:
- **Raw HTML**: Set `convert_to_markdown=false`
- **No metadata**: Set `include_metadata=false`
- **Child pages**: Use `/confluence:list-children {page_id}`

## If no input provided

If the input is empty or missing, display this help message:

```markdown
# Confluence Get Page

You need to provide a page identifier to retrieve a Confluence page.

## Usage

```
/confluence:get-page <page_identifier>
```

## Examples

**By page ID:**
```
/confluence:get-page 123456789
```

**By URL:**
```
/confluence:get-page https://company.atlassian.net/wiki/spaces/DEV/pages/123456789/My+Page
```

**By title and space:**
```
/confluence:get-page "Release Notes" in DEV
/confluence:get-page "MCP Server Documentation" in OCPERT
```

**By title only (will ask for space):**
```
/confluence:get-page "Release Notes"
```

## Page Identifiers

You can identify a page using:
- **Page ID**: Numeric identifier (e.g., `123456789`)
- **URL**: Full Confluence page URL
- **Title + Space**: Format: `"Page Title" in SPACE_KEY`
- **Title only**: Will prompt for space key

## Need help?

Tell me which page you want to retrieve, and I can help you find it!
You can also use `/confluence:search` to find pages by keyword.
```
