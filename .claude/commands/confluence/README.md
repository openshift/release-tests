# Confluence Slash Commands

This directory contains slash commands for interacting with Confluence through the MCP integration.

## Available Commands

### `/confluence:search <query>`
Search for Confluence pages using keywords or CQL queries.

**Examples**:
- `/confluence:search release notes`
- `/confluence:search type=page AND space=DEV`
- `/confluence:search label=documentation`

### `/confluence:get-page <page_id|url|title>`
Retrieve and display a specific Confluence page.

**Examples**:
- `/confluence:get-page 123456789`
- `/confluence:get-page https://company.atlassian.net/wiki/spaces/DEV/pages/123456789/Page`
- `/confluence:get-page "Release Notes" in DEV`

### `/confluence:create-page`
Create a new Confluence page (interactive - will prompt for details).

**Example**:
- `/confluence:create-page` (then provide space, title, content when prompted)
- `/confluence:create-page "My New Page" in DEV`

### `/confluence:update-page <page_id|url|title>`
Update an existing Confluence page.

**Examples**:
- `/confluence:update-page 123456789`
- `/confluence:update-page "Release Notes" in DEV`

## Creating Your Own Confluence Commands

Want to add more Confluence commands? Here's how:

### 1. Create a new `.md` file in this directory

```bash
touch .claude/commands/confluence/my-command.md
```

### 2. Add frontmatter with description

```markdown
---
description: Brief description of what the command does
---
```

### 3. Write instructions for Claude

The instructions should:
- Parse user input from `{{args}}`
- Call the appropriate MCP tool (see available tools below)
- Format and present results to the user
- Handle errors gracefully

### 4. Test your command

Use it like: `/confluence:my-command <args>`

## Available Confluence MCP Tools

You can use these tools in your slash commands:

**Read Operations**:
- `mcp__mcp-atlassian__confluence_search` - Search pages
- `mcp__mcp-atlassian__confluence_get_page` - Get page content
- `mcp__mcp-atlassian__confluence_get_page_children` - Get child pages
- `mcp__mcp-atlassian__confluence_get_comments` - Get page comments
- `mcp__mcp-atlassian__confluence_get_labels` - Get page labels
- `mcp__mcp-atlassian__confluence_search_user` - Search Confluence users

**Write Operations**:
- `mcp__mcp-atlassian__confluence_create_page` - Create new page
- `mcp__mcp-atlassian__confluence_update_page` - Update existing page
- `mcp__mcp-atlassian__confluence_delete_page` - Delete page
- `mcp__mcp-atlassian__confluence_add_comment` - Add comment to page
- `mcp__mcp-atlassian__confluence_add_label` - Add label to page

## Command Template

Here's a basic template for creating new commands:

```markdown
---
description: Your command description here
---

You are helping the user <do something> in Confluence.

The user has provided: {{args}}

Follow these steps:

1. **Parse the input**:
   - Extract relevant parameters from {{args}}
   - Validate input format
   - Ask for missing required information

2. **Call the MCP tool**:
   - Use appropriate mcp__mcp-atlassian__confluence_* tool
   - Pass required parameters
   - Handle optional parameters

3. **Present results**:
   - Format output in clear markdown
   - Include relevant links and metadata
   - Provide next steps or related actions

4. **Handle errors**:
   - Catch common error scenarios
   - Provide helpful error messages
   - Suggest resolution steps

## Example Usage

See existing commands in this directory for complete examples:
- `search.md` - Shows how to search and present results
- `get-page.md` - Shows how to fetch and display content
- `create-page.md` - Shows how to handle write operations
- `update-page.md` - Shows how to handle updates safely
```

## Tips

- **Use clear descriptions**: The description appears in `/help` output
- **Handle missing args**: Not all users will provide complete arguments
- **Provide examples**: Show users how to use the command
- **Format output nicely**: Use markdown headers, lists, code blocks
- **Be helpful on errors**: Guide users to fix issues
- **Reference related commands**: Help users discover other commands

## More Ideas for Commands

Here are some ideas for additional Confluence commands you could create:

- `/confluence:list-children <page_id>` - List child pages
- `/confluence:add-comment <page_id> <comment>` - Add comment to page
- `/confluence:add-label <page_id> <label>` - Add label to page
- `/confluence:get-space-pages <space_key>` - List all pages in a space
- `/confluence:recent-changes` - Show recently updated pages
- `/confluence:my-pages` - Show pages you created/updated
- `/confluence:copy-page <page_id> <new_title>` - Duplicate a page

Feel free to create any of these or come up with your own!
