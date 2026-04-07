---
name: run-pipeline
description: Run the full API QA pipeline from input context and contract to final review report using existing stage skills and deterministic gates.
---

# Skill: run_pipeline

## Purpose

Run the full end-to-end API QA pipeline in five stages.
Delegate LLM-driven stages to subagents that invoke stage skills by name.
Use deterministic code inline for Stage 4.
Stop immediately on the first failure.

This skill is an orchestrator only.
Do not implement, patch, repair, or replace repository code.

## Required inputs

Before starting, verify these files exist (use Glob or Bash):
- `agent/input/context.md`
- `agent/input/open_api.json`
- `agent/input/runtime.json`
- `agent/json_examples/execution_plan.json`

If any required file is missing, stop and report the missing path.

## Invocation model

- LLM-driven stages (1, 2, 3, 5): spawn a subagent via the **Agent tool** with a minimal prompt (see below).
- The subagent invokes the stage skill by name using the **Skill tool** — do NOT pass SKILL.md content.
- Stage 4 (executor): run inline via Bash.
- After each stage: verify expected output files exist using **Glob** only — do NOT read file content.

## Runtime rules

- Run stages strictly in order.
- Do not continue after a failed stage or failed gate.
- Do not manually repair or re-create artifacts.
- Use only existing repository skills and existing deterministic code.

## Stages

### Stage 1 — Rules Extraction

Spawn subagent with this prompt (verbatim):
```
Invoke the extract-rules skill.
Input: agent/input/context.md
Output: output/rules.json
```

After subagent completes: verify `output/rules.json` exists via Glob.

---

### Stage 2 — Test Case Design

Spawn subagent with this prompt (verbatim):
```
Invoke the design-test-cases skill.
Inputs: output/rules.json, agent/input/open_api.json
Output: output/test_cases_{endpointId}.json per endpoint
```

After subagent completes: verify at least one `output/test_cases_*.json` exists via Glob.

---

### Stage 3 — Execution Planning

For each `output/test_cases_{endpointId}.json` file found via Glob, spawn one subagent.
Process endpoints sequentially — verify each output before spawning the next.

Subagent prompt template (fill in the actual endpointId):
```
Invoke the plan-execution skill.
Input test cases file: output/test_cases_{endpointId}.json
Input contract: agent/input/open_api.json
Input example: agent/json_examples/execution_plan.json
Output: output/execution_plan_{endpointId}.json
```

After each subagent completes: verify `output/execution_plan_{endpointId}.json` exists via Glob.

---

### Stage 4 — Execution

Run inline for each endpoint plan file found via Glob (sequential):

```bash
python3 -m src.executor.runner \
  --plan output/execution_plan_{endpointId}.json \
  --report output/execution_report_{endpointId}.json \
  --base-url http://localhost:8000
```

No gate after this stage.

---

### Stage 5 — Review Execution

Spawn subagent with this prompt (verbatim, listing all actual report files found):
```
Invoke the review-execution skill.
Inputs:
  - output/execution_report_*.json (all per-endpoint files)
  - output/rules.json
  - agent/input/open_api.json (relevant slice only)
Output: output/review_report.json
```

After subagent completes: verify `output/review_report.json` exists via Glob.

---

## Failure handling

On any failure:
- stop immediately
- report stage number and stage name
- report failed artifact path
- report failed gate or runtime failure
- report the last valid artifact produced

## Success output

When all stages complete successfully, report exactly:

Pipeline complete.

Artifacts produced:
- `output/rules.json`
- `output/test_cases_{endpointId}.json` (one per endpoint)
- `output/execution_plan_{endpointId}.json` (one per endpoint)
- `output/execution_report_{endpointId}.json` (one per endpoint)
- `output/review_report.json`

Review summary: `<summary from review_report.json>`
