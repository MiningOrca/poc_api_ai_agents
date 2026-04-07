---
name: fix-maint-file
description: Fix all maintainability issues from .claude/reports/maintainability_review.json for exactly one file, using minimal necessary context
disable-model-invocation: true
context: fork
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
  - Edit
  - Write
---

Fix maintainability issues for exactly one file from `.claude/reports/maintainability_review.json`.

The target file path is: `$ARGUMENTS`

You must only fix issues that are explicitly listed in the review report for this file.

Workflow:

1. Extract only the requested file entry from the review report by running:
   `mkdir -p .claude/tmp && python3 .claude/skills/fix-maint-file/extract_file_issues.py "$ARGUMENTS" > ".claude/tmp/fix-maint-file.json"`

2. Read only `.claude/tmp/fix-maint-file.json` first.
   Do not read the full review report unless extraction failed.

3. From the extracted file entry, get:
   - target file path
   - file summary
   - all issues
   - line ranges
   - symbols
   - fix_instructions
   - acceptance_criteria

4. Build a plan for this file only:
   - group overlapping or clearly related issues
   - keep unrelated issues conceptually separate even if fixed in one edit pass
   - do not add new issues not present in the report

5. Minimize context usage:
   - If the file is small enough, you may read the full file.
   - Treat files of about 450 lines or less as small enough to read fully.
   - If the file is larger, first read only local windows around issue ranges.
   - Default window:
     - start at `max(1, issue_start - 40)`
     - read through `issue_end + 40`
   - Merge overlapping windows before reading.
   - Use `Read` with `offset` and `limit`.
   - Expand only if necessary to safely implement the fixes.

6. Only read other files if:
   - a listed issue clearly depends on another local symbol or helper
   - the dependency is necessary to avoid breaking behavior
   - the other file is directly relevant to one of the listed issues

7. Apply the smallest safe set of changes that:
   - resolves the listed issues for this file
   - satisfies the listed fix instructions
   - satisfies the listed acceptance criteria
   - does not intentionally change business behavior

8. Prefer:
   - one coherent refactor pass for related issues in the same region
   - small extractions over rewrites
   - preserving public interfaces unless a listed issue requires otherwise
   - limited, file-scoped edits

9. Avoid:
   - rewriting the whole file unless the listed issues make that clearly necessary
   - style-only cleanup outside the listed issues
   - fixing issues from other files
   - broad project cleanup
   - speculative refactors not required by the report

10. After editing:
   - reread the changed regions
   - reread any extracted helpers or changed signatures
   - verify every listed issue for this file against the code
   - verify the listed acceptance criteria
   - if straightforward and local, run lightweight validation for the changed file only:
     - `python -m py_compile <file>` or
     - `ruff check <file>`
   - do not run broad project-wide checks

11. Git commit rules:
   - If the file-level fix is complete, validation passed, and there are actual code changes, create one commit for this file.
   - Stage only the files intentionally changed for this file fix.
   - Never use `git add -A`.
   - Use explicit paths with `git add`.
   - Review staged changes with `git diff --cached`.
   - Do not commit unrelated changes.

12. Commit message format:
   `fix(maint): $ARGUMENTS`

13. Never commit if:
   - no file changed
   - validation clearly failed
   - listed issues for this file are still unresolved
   - unrelated files were modified and are not intentionally required

14. In the final response, provide only:
   - file path
   - issue ids addressed
   - files changed
   - commit hash
   - concise summary of the fix
   - anything still uncertain