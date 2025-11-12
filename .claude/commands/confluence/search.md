---
description: Search Confluence pages by keyword or CQL query
---

You are helping the user search for Confluence pages.

The user has provided a search query: {{args}}

**IMPORTANT**: Before proceeding, check if the search query is empty or missing:
- If `{{args}}` is empty, blank, or literally "{{args}}", show usage help (see "If no query provided" section below)
- Otherwise, proceed with the search

Follow these steps:

1. **Parse the search query**:
   - If the query looks like CQL (contains keywords like `type=`, `space=`, `label=`), use it as-is
   - Otherwise, treat it as a simple keyword search

2. **Execute the search** using the Confluence MCP tool:
   ```
   mcp__mcp-atlassian__confluence_search
   ```

   Parameters:
   - `query`: The search query from {{args}}
   - `limit`: Default to 10 results (can be adjusted if user specifies)

3. **Present the results** in a clear format:
   ```markdown
   # Confluence Search Results

   **Query**: {query}
   **Results**: {count} pages found

   ## Pages

   {for each result:}
   ### {page_title}
   - **Space**: {space_key}
   - **Last Updated**: {last_modified}
   - **URL**: {page_url}
   - **Excerpt**: {brief_excerpt_if_available}

   ---
   ```

4. **If no results found**:
   - Suggest alternative search terms
   - Recommend using CQL for more precise searches
   - Provide example CQL queries

5. **If user wants to see a specific page**:
   - Ask which page they'd like to view
   - Use `/confluence:get-page` command or fetch directly with page ID

## Example CQL Queries

Provide these examples if user needs help:
- `type=page AND space=DEV` - All pages in DEV space
- `title ~ "release notes"` - Pages with "release notes" in title
- `label=documentation AND lastModified >= "2024-01-01"` - Recent docs

## Tips

- Default search uses `siteSearch` which mimics the Confluence web UI
- For more control, use CQL queries
- Can filter by space using `spaces_filter` parameter

## If no query provided

If the search query is empty or missing, display this help message:

```markdown
# Confluence Search

You need to provide a search query to search Confluence pages.

## Usage

```
/confluence:search <query>
```

## Examples

**Simple keyword search:**
```
/confluence:search release notes
/confluence:search mcp server
/confluence:search deployment guide
```

**CQL (Confluence Query Language) search:**
```
/confluence:search type=page AND space=OCPERT
/confluence:search title ~ "release" AND lastModified >= "2024-01-01"
/confluence:search label=documentation
/confluence:search space="~username"
```

## Common CQL Patterns

- `type=page AND space=DEV` - All pages in DEV space
- `title ~ "keyword"` - Pages with keyword in title
- `text ~ "phrase"` - Full-text search
- `label=tag` - Pages with specific label
- `lastModified >= "YYYY-MM-DD"` - Recently modified pages
- `space="~username"` - Personal space (note quotes for ~ prefix)

## Need help?

Tell me what you're looking for and I can help construct the right search query!
```
