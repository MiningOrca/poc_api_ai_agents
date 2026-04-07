## Purpose
This repo generates specification-driven QA artifacts for API testing from:
- `agent/input/context.md`
- `agent/input/open_api.json` or `swagger.json`

Outputs:
- `output/rules.json`
- `output/test_cases_{endpointId}.json` (one per endpoint)
- `output/execution_plan_{endpointId}.json` (one per endpoint)
- `output/execution_report_{endpointId}.json` (one per endpoint)
- `output/review_report.json`

Execution, CI, environment setup, and runtime recovery are out of scope unless explicitly requested.

## Non-negotiables
- Prefer deterministic parsing, normalization, validation, and projection.
- Use the LLM only for test design: what to test, not API fact invention.
- Never invent endpoints, fields, status codes, business rules, or hidden dependencies.
- If sources conflict, surface the conflict.
- Keep artifacts schema-strict, compact, and diff-friendly.
- If a contract changes, update downstream consumers in the same change.

## Pipeline
1. `context.md` -> `output/rules.json`
2. `output/rules.json` + `open_api.json` -> `output/test_cases_{endpointId}.json` (one per endpoint)
3. `output/test_cases_{endpointId}.json` + `open_api.json` -> `output/execution_plan_{endpointId}.json` (one per endpoint)
4. `output/execution_plan_{endpointId}.json` -> `output/execution_report_{endpointId}.json` (executor, one per endpoint)
5. `output/execution_report_{endpointId}.json` + `output/execution_plan_{endpointId}.json` + `output/rules.json` -> `output/review_report.json`

Stages 1, 3–4 are deterministic. Stage 2 is LLM-assisted. Stage 5 is LLM-driven review.

## Artifact rules
- Test cases are abstract: title, category, mode, expected status, source refs, minimal dependency hints.
- Scenarios are concrete: resolved contract fragments, per-step expectations, stable context bindings.
- Resolve response expectations by the exact step status code.
- Do not mix request schema and response schema views.

## Working style
- Read existing code before structural changes.
- Prefer small reviewable edits over rewrites.
- Keep Python readable and prompts strict.
- Keep chat concise; keep repo artifacts normal professional technical English.

## Immediate focus
Get one endpoint flow clean end-to-end before scaling breadth.

## Runtime
- Use `python3` (not `python`) for all Python commands.

## Top-level orchestration
To run the full pipeline end-to-end, use `.claude/skills/run_pipeline/SKILL.md`.
That skill coordinates all five stages in order, invokes the correct driver for each stage (skill or deterministic code), and runs the required gates after each skill-driven stage.
Use it instead of running individual stage skills manually when you want a full pipeline pass.