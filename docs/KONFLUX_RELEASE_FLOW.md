# Konflux Release Flow Specification

> **This document has been moved.**
>
> The authoritative workflow specification now lives in the `release-workflow` skill:
>
> **`.claude/skills/release-workflow/SKILL.md`**
>
> That file is the single source of truth for:
> - Task graph and execution order
> - Build promotion checkpoint logic
> - Test result evaluation (candidate vs promoted builds)
> - Gate check criteria
> - Async task orchestration
> - Error handling and retry strategies
> - All MCP tool usage patterns
> - Troubleshooting guide
>
> The skill is automatically loaded by Claude Code when `/release:drive` is invoked.
