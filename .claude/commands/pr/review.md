---
description: Intelligent code review for a pull request
---

You are helping the user perform an intelligent code review of a pull request.

## Usage

```bash
# Review a specific PR
/pr:review 123

# Review current branch's PR (if no number provided, will ask)
/pr:review
```

## Input

PR number from args: {{args}}

If no PR number is provided, ask the user which PR to review.

## Review Process

Follow these steps to perform a comprehensive code review:

### 1. Fetch PR Information

Use the GitHub MCP tool to get PR details:
- Basic info: title, description, author, status
- Changed files list
- PR diff/patches

```bash
# Get PR details
gh pr view <PR_NUMBER>

# Get list of changed files
gh pr diff <PR_NUMBER> --name-only

# Get full diff
gh pr diff <PR_NUMBER>
```

### 2. Analyze PR Context

**Understand the purpose:**
- Read PR title and description
- Identify the type of change:
  - Bug fix
  - New feature
  - Refactoring
  - Documentation
  - Test improvement
  - Performance optimization
  - Security fix

**Assess scope:**
- How many files changed?
- Which components/modules affected?
- Is this a focused change or broad refactoring?

### 3. Code Quality Analysis

For each changed file, analyze:

**A. Security Issues:**
- SQL injection vulnerabilities (if database queries modified)
- Command injection (subprocess calls, shell commands)
- Path traversal vulnerabilities (file operations)
- Hardcoded credentials or secrets
- Unsafe deserialization
- Authentication/authorization bypasses
- XSS vulnerabilities (if web-facing code)
- Insecure cryptography usage

**B. Bug Patterns:**
- Null/None pointer dereferences
- Resource leaks (files, connections not closed)
- Race conditions in concurrent code
- Off-by-one errors in loops
- Incorrect error handling (swallowing exceptions)
- Logic errors in conditionals
- Unhandled edge cases

**C. Code Quality:**
- Code duplication
- Complex functions (too long, too many branches)
- Poor variable/function naming
- Missing error handling
- Inconsistent code style
- Dead/unreachable code
- TODO/FIXME comments that need addressing

**D. Python-Specific Issues (for this project):**
- Missing type hints (Python 3.11+ project)
- Improper exception handling
- Inefficient list comprehensions
- Mutable default arguments
- Missing docstrings for public functions
- Not following PEP 8 conventions
- Dangerous use of eval/exec

### 4. Test Coverage Analysis

**Check for tests:**
- Are there new test files in `tests/` directory?
- Do tests cover the new/modified functionality?
- Are edge cases tested?
- Are error paths tested?

**Test quality:**
- Are tests meaningful (not just smoke tests)?
- Do they use proper assertions?
- Are test names descriptive?
- Mock external dependencies appropriately?

**For this project specifically:**
- If `oar/core/` modules changed, are there corresponding tests in `tests/`?
- If CLI commands added/modified in `oar/cli/`, are they tested?
- If operators changed in `oar/core/operators.py`, are integration points tested?

### 5. Documentation Review

**Check if documentation is updated:**
- If new CLI command added, is it documented in AGENTS.md?
- If new configuration added, is it in CLAUDE.md or README.md?
- Are docstrings added/updated for new/modified functions?
- If new environment variable required, is it documented?
- If API/interface changed, is it reflected in docs?

**For this project specifically:**
- New OAR commands should be in AGENTS.md
- New MCP tools should update mcp_server/README.md
- Configuration changes should update CLAUDE.md

### 6. Project-Specific Checks

**For Release Tests project:**

**A. ConfigStore Integration:**
- Do new modules properly integrate with ConfigStore?
- Are config keys documented?
- Is encryption handled correctly?

**B. Error Handling:**
- Are custom exceptions from `oar/core/exceptions.py` used?
- Is error handling consistent with existing patterns?

**C. Logging:**
- Is logging added for important operations?
- Are log levels appropriate (DEBUG, INFO, WARNING, ERROR)?

**D. Google Sheets Integration:**
- If worksheet operations added, are they using `oar/core/worksheet.py`?
- Is task status properly updated?

**E. External Service Integration:**
- Kerberos required operations (Errata Tool, LDAP)?
- API tokens properly retrieved from environment?
- Retry logic for network operations?

**F. CLI Command Structure:**
- Click decorators properly used?
- Help text clear and descriptive?
- Error messages user-friendly?

**G. Background Processes:**
- File-based locking implemented?
- Timeout handling present?
- Cleanup on exit?

### 7. Breaking Changes Assessment

**Check for breaking changes:**
- API signature changes
- Configuration format changes
- CLI command syntax changes
- Database schema changes
- Removed functionality

**If breaking changes found:**
- Are they necessary?
- Is there a migration path?
- Is it documented?
- Are deprecation warnings added?

### 8. Performance Considerations

**Check for performance issues:**
- Inefficient algorithms (O(n²) where O(n) possible)
- Unnecessary database/API calls in loops
- Large file operations without streaming
- Missing pagination for large datasets
- Synchronous operations that could be async
- Memory leaks (large objects not freed)

### 9. Generate Review Report

**Provide a structured review in this format:**

```markdown
# Code Review: PR #<NUMBER> - <TITLE>

## Summary
- **Type**: [Bug Fix/Feature/Refactoring/etc.]
- **Scope**: [Small/Medium/Large]
- **Files Changed**: <count>
- **Lines Added/Removed**: +<add> / -<remove>

## Overall Assessment
[High-level assessment of the PR quality and readiness]

**Recommendation**: ✅ Approve / ⚠️ Approve with Comments / ❌ Request Changes

---

## Detailed Findings

### 🔒 Security Issues
[List any security vulnerabilities found, or "None found"]

**Priority**: [Critical/High/Medium/Low]

1. **[Issue Title]** - `file.py:123`
   - **Problem**: [Description]
   - **Impact**: [Security impact]
   - **Suggestion**: [How to fix]

### 🐛 Potential Bugs
[List potential bugs, or "None found"]

1. **[Issue Title]** - `file.py:456`
   - **Problem**: [Description]
   - **Impact**: [When/how it could fail]
   - **Suggestion**: [How to fix]

### 📊 Code Quality
[List code quality issues, or "Looks good"]

**Positives:**
- [Things done well]

**Improvements Needed:**
1. **[Issue Title]** - `file.py:789`
   - **Problem**: [Description]
   - **Suggestion**: [How to improve]

### 🧪 Test Coverage
[Assessment of test coverage]

**Status**: ✅ Well Tested / ⚠️ Partially Tested / ❌ Missing Tests

- **Tests Added**: [Yes/No - list files if yes]
- **Coverage**: [What's tested]
- **Missing**: [What should be tested but isn't]

**Recommendations:**
- [Specific test suggestions]

### 📚 Documentation
[Assessment of documentation]

**Status**: ✅ Well Documented / ⚠️ Partially Documented / ❌ Missing Documentation

- **Updated Files**: [List updated doc files]
- **Missing**: [What documentation is missing]

### ⚡ Performance
[Performance considerations, or "No concerns"]

### 💥 Breaking Changes
[List breaking changes, or "None"]

---

## Recommendations

### Must Fix (Required before merge):
1. [Critical issues that must be addressed]

### Should Fix (Strongly recommended):
1. [Important issues that should be addressed]

### Nice to Have (Optional improvements):
1. [Suggestions for improvement]

---

## Questions for Author
1. [Any clarifying questions about design decisions]

---

## Additional Comments
[Any other relevant observations or context]
```

### 10. Post Review (Optional)

Ask the user if they want to:
1. **Post review as PR comment** - Add the review as a comment
2. **Submit formal review** - Use GitHub review API (approve/request changes/comment)
3. **Just show me the analysis** - No action on GitHub

**Important Notes:**
- Focus on providing constructive, actionable feedback
- Explain WHY something is an issue, not just WHAT
- Suggest specific fixes when possible
- Acknowledge good patterns and clean code
- Be thorough but prioritize critical issues
- Consider the project context (this is an enterprise automation tool)
- Balance perfectionism with pragmatism
