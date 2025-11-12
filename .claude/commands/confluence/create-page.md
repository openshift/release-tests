---
description: Create a new Confluence page with markdown content
---

You are helping the user create a new Confluence page.

The user has provided: {{args}}

Follow these steps:

1. **Gather required information**:
   - **Space key**: Which space to create the page in (e.g., "DEV", "TEAM")
   - **Page title**: The title of the new page
   - **Content**: The page content (can be markdown, wiki markup, or storage format)
   - **Parent page ID** (optional): If this should be a child page

2. **If information is missing from {{args}}**:
   - Ask the user for missing required fields (space key, title, content)
   - Suggest they can provide content inline or you can help draft it
   - Example: "I need the space key (e.g., DEV), page title, and content to create the page"

3. **Content format options**:
   - **Markdown** (recommended, default): Easy to write, converted automatically
   - **Wiki markup**: Confluence's native format
   - **Storage format**: For advanced users with pre-formatted HTML

4. **Create the page** using Confluence MCP tool:
   ```
   mcp__mcp-atlassian__confluence_create_page
   ```

   Parameters:
   - `space_key`: The space key (uppercase, e.g., "DEV")
   - `title`: Page title
   - `content`: The page content
   - `content_format`: "markdown" (default), "wiki", or "storage"
   - `parent_id` (optional): Parent page ID if creating a child page
   - `enable_heading_anchors`: false (default), set true for automatic anchor links

5. **Confirm creation**:
   ```markdown
   # ✅ Confluence Page Created Successfully

   **Page Title**: {title}
   **Space**: {space_key}
   **Page ID**: {created_page_id}
   **URL**: {page_url}
   {if parent_id:}
   **Parent Page**: {parent_page_title} (ID: {parent_id})

   You can now:
   - View the page: {page_url}
   - Edit with `/confluence:update-page {page_id}`
   - Add child pages with parent_id={page_id}
   ```

6. **If creation fails**:
   - Check if user has permission to create pages in that space
   - Verify space key is correct
   - Check if page with same title already exists
   - Provide error message and suggested fixes

## Example Usage

```bash
# Simple page creation (will prompt for details)
/confluence:create-page

# With all details inline
/confluence:create-page "My New Page" in DEV

# After command, provide content when prompted
```

## Content Examples

**Markdown content**:
```markdown
# Welcome to My Page

This is a test page with:
- Bullet points
- **Bold text**
- `Code snippets`

## Section 2
More content here...
```

**Wiki markup**:
```
h1. Welcome to My Page

This is a test page with:
* Bullet points
* *Bold text*
* {{Code snippets}}
```

## Parent Page Support

To create a child page:
1. Get parent page ID using `/confluence:search` or `/confluence:get-page`
2. Include `parent_id` when creating
3. New page will appear in parent's page tree

## Best Practices

- Use descriptive titles
- Add labels after creation for better organization
- Use markdown for easier authoring
- Consider page hierarchy (parent/child structure)
