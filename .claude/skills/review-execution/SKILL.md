# review-execution

## Purpose

Review the execution outcomes in `output/execution_report.json` and produce structured diagnostic verdicts
in `output/review_report.json`. This skill does not re-execute anything. It evaluates what happened, why, and what
should happen next.

## When to use

Invoke this skill at Stage 5, after the executor has produced `output/execution_report.json`. Re-invoke whenever the
report changes.

## Required inputs

| File | Role |
|---|---|
| `output/execution_report_{endpointId}.json` | Raw execution outcomes (one file per endpoint, read all). Each scenario already includes `category`, `sourceRefs`, and `expectedStatusCode` from the plan. |
| `output/rules.json` | Business rules that the scenarios were designed to verify |
| `agent/input/open_api.json` | Relevant slice — used to check contract fidelity of actual responses |

For `open_api.json`, read only the operations referenced by the scenarios under review. Do not load the full spec if it
is large.

Do **not** read `execution_plan_{endpointId}.json` files — all plan metadata needed for review is already embedded in
the execution reports.

## Produced output

| File | Role |
|---|---|
| `output/review_report.json` | Structured verdict per scenario |

## Schema

```json
{
  "scenarioId": "SC-<ENDPOINT_ABBREV>-001",
  "verdict": "pass | fail | inconclusive",
  "summary": "<one-sentence description of outcome>",
  "failureClassification": {
    "kind": "application_bug | test_issue | contract_mismatch | environment_issue | inconclusive",
    "confidence": "high | medium | low"
  },
  "rootCauseHypotheses": [
    "<evidence-backed explanation>"
  ],
  "validationAssessment": {
    "isSufficient": true,
    "missingChecks": []
  },
  "testDesignIssues": [],
  "recommendedActions": [
    "<concrete next step>"
  ],
  "evidence": [
    "<specific step index, actual vs expected values>"
  ]
}
```

If `output/review_report.json` covers multiple scenarios, write a JSON array of verdict objects.

## Instructions

1. Read all `execution_report_{endpointId}.json` files, `output/rules.json`, and the relevant slice of `agent/input/open_api.json`. Do not read plan files.
2. Filter scenarios: only review scenarios that have at least one failed assertion or execution error. Skip scenarios where all assertions passed — do not include them in `output/review_report.json` at all. For each remaining scenario, use the embedded `sourceRefs`, `category`, and `expectedStatusCode` fields.
3. Determine `verdict`:
    - `"pass"` if all assertions in all steps passed.
    - `"fail"` if any assertion failed or a step produced an execution error.
    - `"inconclusive"` if execution was incomplete or results cannot be interpreted.
4. Classify the failure using `failureClassification.kind`:
    - `application_bug`: the API returned a response that contradicts `open_api.json` or business rules.
    - `test_issue`: the test case or plan is flawed (wrong expected value, bad binding, unreachable setup).
    - `contract_mismatch`: the API response shape differs from what `open_api.json` documents.
    - `environment_issue`: network error, timeout, or infrastructure failure with no application-level response.
    - `inconclusive`: cannot determine cause from available evidence.
5. Set `confidence` based on how directly the evidence points to the classification.
6. Write `rootCauseHypotheses` as specific, evidence-backed statements. Reference step indices, actual vs expected
   values, and rule IDs where relevant.
7. Assess `validationAssessment.isSufficient`: were the assertions in the plan adequate to verify the cited business
   rule? This judgment is independent of whether the scenario passed or failed.
8. List `missingChecks` if the assertions were insufficient to fully verify the rule.
9. List `testDesignIssues` if the plan itself contained structural problems (wrong body, unreachable binding, etc.).
10. Write `recommendedActions` as concrete, actionable steps. Do not write generic advice.
11. Populate `evidence` with specific references: step index, `expectedStatusCode` vs `actualStatusCode`, failing
    assertion path and values.
12. Write all verdicts (all endpoints combined) to `output/review_report.json` as a JSON array.

## Constraints

- Do not re-execute requests or simulate responses.
- Do not invent response fields or status codes not present in `execution_report.json` or `open_api.json`.
- Do not change `verdict` based on opinion — base it on the assertion results in `execution_report.json`.
- Do not omit `evidence`. A verdict without evidence citations is invalid.
- Do not provide generic recommendations (e.g., "check the logs"). Recommendations must be specific to the observed
  failure.

## Deterministic validation

After writing `output/review_report.json`, run deterministic validation exactly as shown below.

Do not search for alternative runners.
Do not reimplement gate logic.

```python
import json
from src.gates import run_stage5_gates

data = json.loads(open("output/review_report.json").read())
normalized = run_stage5_gates(data)
open("output/review_report.json", "w").write(json.dumps(normalized, indent=2))
```

## Expected file locations

```
output/execution_report_{endpointId}.json   ← read (one per endpoint, read all)
output/rules.json                           ← read
agent/input/open_api.json                   ← read (relevant slice only)
output/review_report.json                   ← write (single file, all endpoints)
```

## Example invocation

```
Run the review-execution skill.
Inputs: output/execution_report_*.json, output/rules.json, agent/input/open_api.json (relevant slice)
Output: output/review_report.json
```
