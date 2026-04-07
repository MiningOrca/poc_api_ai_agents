# Executor Usage Instructions

How to use the deterministic execution layer in `src/executor/`.

---

## Overview

The executor is Stage 4 of the pipeline. It reads a validated and normalized `execution_plan.json` and produces `execution_report.json`.

It does four things:

1. **Resolve** `{{contextKey}}` binding templates in each step's transport fields before the request is sent.
2. **Send** HTTP requests step by step in scenario order.
3. **Evaluate** assertions against each actual response.
4. **Record** all evidence — actual request, actual response, assertion outcomes, timestamps — in a self-contained report.

The executor is pure Python, has no LLM calls, and is deterministic. It assumes the plan has already passed all gates (A, B, C, D, E) before execution starts.

---

## Quick start — CLI

Run the executor from the repository root:

```bash
python -m src.executor.runner \
    --plan output/execution_plan.json \
    --report output/execution_report.json \
    --base-url http://localhost:8080
```

The base URL can also be supplied via the environment variable `API_BASE_URL`:

```bash
export API_BASE_URL=http://localhost:8080
python -m src.executor.runner
```

Default paths are `output/execution_plan.json` and `output/execution_report.json`, so those flags can be omitted when using the standard layout.

On completion the runner prints a one-line summary and exits with code `0`. A non-zero exit code means the runner itself failed (missing file, invalid JSON), not that scenarios failed — scenario failures are captured in the report.

---

## Quick start — Python API

```python
import json
from src.executor.runner import run

run(
    plan_path="output/execution_plan.json",
    report_path="output/execution_report.json",
    base_url="http://localhost:8080",
)

with open("output/execution_report.json") as f:
    report = json.load(f)

# report is a list when the plan was a list, a single object when the plan was
# a single scenario — cardinality matches the input plan exactly
```

`run()` raises `FileNotFoundError` if the plan path does not exist and `json.JSONDecodeError` if the file is not valid JSON. All other failures (transport errors, assertion failures, binding errors) are captured in the report rather than raised.

---

## Report structure

The execution report mirrors the plan's cardinality. Each scenario entry contains:

```json
{
  "scenarioId": "SC-CU-001",
  "title": "Reject creation when email is already taken",
  "endpointId": "create_user",
  "passed": false,
  "startedAtUtc": "2026-04-06T12:00:00Z",
  "finishedAtUtc": "2026-04-06T12:00:03Z",
  "failedStepIndex": 1,
  "steps": [
    {
      "index": 0,
      "title": "Create initial user",
      "stepRole": "setup",
      "passed": true,
      "method": "POST",
      "path": "/users",
      "requestBody": { "name": "John", "email": "john@example.com" },
      "expectedStatusCode": null,
      "actualStatusCode": 201,
      "assertionResults": [
        { "path": "$.userId", "operator": "exists", "expected": true, "actual": true, "passed": true, "error": null }
      ],
      "responseBody": { "userId": "u-1001", "email": "john@example.com" },
      "error": null,
      "startedAtUtc": "2026-04-06T12:00:00Z",
      "finishedAtUtc": "2026-04-06T12:00:01Z"
    }
  ]
}
```

Key fields:

| Field | Meaning |
|---|---|
| `passed` | `true` only when every step passed |
| `failedStepIndex` | Index of the first failing step, or `null` if all passed |
| `step.passed` | `false` if status code mismatched or any assertion failed or transport error |
| `step.expectedStatusCode` | `null` for setup steps with no explicit override |
| `step.error` | Status code mismatch message or transport error; `null` on success |
| `assertionResults[*].passed` | Per-assertion outcome |
| `assertionResults[*].error` | Human-readable reason for failure; `null` on success |

---

## Components

### `runner.py` — entry point

Loads the plan, iterates scenarios in order, assembles the report, and writes the output file. This is the only file that touches the filesystem.

```python
from src.executor.runner import run

run("output/execution_plan.json", "output/execution_report.json", "http://localhost:8080")
```

### `scenario_executor.py` — scenario loop

Executes a single scenario dict. Iterates steps in index order and threads a shared context dict between them. Stops at the first failing step and preserves all collected evidence.

```python
from src.executor.scenario_executor import execute_scenario

result = execute_scenario(scenario_dict, base_url="http://localhost:8080")
print(result["passed"])         # bool
print(result["failedStepIndex"])  # int or None
print(result["steps"])          # list of step result dicts
```

### `step_executor.py` — single step

Executes one step: resolves bindings, sends the request, checks the status code, evaluates assertions, and extracts produced bindings.

```python
from src.executor.step_executor import execute_step

step_result, updated_context = execute_step(
    step=step_dict,
    scenario_expected_status=409,
    context={"user_id": "u-1001"},
    base_url="http://localhost:8080",
)
print(step_result["passed"])
print(updated_context)  # context extended with any produced bindings
```

Returns a `(step_result_dict, updated_context)` tuple. If the step fails, the returned context is unchanged — bindings from failed steps are not propagated.

### `binding_resolver.py` — binding resolution

Two independent operations:

**Value extraction** from a response body using a `$.field.nested` path:

```python
from src.executor.binding_resolver import extract_value, value_exists

body = {"userId": "u-1001", "address": {"city": "Berlin"}}

extract_value(body, "$.userId")            # "u-1001"
extract_value(body, "$.address.city")      # "Berlin"
value_exists(body, "$.address.city")       # True
value_exists(body, "$.address.zip")        # False
```

`extract_value` raises `BindingError` if the path cannot be traversed. `value_exists` returns `False` instead.

**Template substitution** in step transport fields:

```python
from src.executor.binding_resolver import resolve_step_fields, apply_path_params, update_context

path_params, query_params, body = resolve_step_fields(
    path_params={"id": "{{user_id}}"},
    query_params={},
    body={"ref": "{{user_id}}"},
    context={"user_id": "u-1001"},
)
# path_params → {"id": "u-1001"}
# body        → {"ref": "u-1001"}

# Substitute {param} placeholders in a URL path template
path = apply_path_params("/users/{id}", {"id": "u-1001"})
# "/users/u-1001"

# Extract produced bindings from a response body and extend context
new_context = update_context(
    context={},
    produce_bindings=[{"contextKey": "user_id", "sourcePath": "$.userId"}],
    response_body={"userId": "u-1001"},
)
# {"user_id": "u-1001"}
```

`resolve_step_fields` and `update_context` raise `BindingError` when a referenced key or path cannot be resolved. No fallback values are invented.

**Template syntax:**
- `"{{key}}"` — whole-string reference: preserves the native type of the context value (int, bool, …)
- `"prefix-{{key}}-suffix"` — partial substitution: stringifies the context value

### `assertion_engine.py` — assertion evaluation

```python
from src.executor.assertion_engine import evaluate_assertion, evaluate_all

body = {"userId": "u-1001", "email": "john@example.com", "score": 42}

# Single assertion
result = evaluate_assertion(
    assertion={"path": "$.email", "operator": "equals", "expected": "john@example.com"},
    response_body=body,
)
# {"path": "$.email", "operator": "equals", "expected": "...", "actual": "...", "passed": True, "error": None}

# All assertions for a step
results, all_passed = evaluate_all(step["assertions"], response_body=body)
```

Supported operators:

| Operator | Passes when |
|---|---|
| `equals` | `actual == expected` |
| `not_equals` | `actual != expected` |
| `exists` | path is present in the response body |
| `not_exists` | path is absent from the response body |
| `contains` | string/list/dict `actual` contains `expected` |
| `in` | `actual` is a member of the `expected` list |
| `gte` | `actual >= expected` |
| `lte` | `actual <= expected` |

`exists` and `not_exists` never raise — absence of a path is a valid outcome, not an error.

### `http_client.py` — HTTP transport

```python
from src.executor.http_client import send_request

response = send_request(
    method="POST",
    url="http://localhost:8080/users",
    query_params={},
    body={"name": "John", "email": "john@example.com"},
)

print(response.status_code)  # int or None on network error
print(response.body)         # parsed JSON, raw string, or None
print(response.error)        # None on success; error message on network failure
```

- Request body is serialised as JSON and `Content-Type: application/json` is added automatically.
- Non-2xx responses are returned as `HttpResponse` with the real status code — they are **not** raised as exceptions.
- Network-level failures (connection refused, DNS, timeout) are captured in `response.error`; `response.status_code` will be `None`.
- Response bodies are parsed as JSON when possible; raw strings otherwise.

### `report_builder.py` — report assembly

```python
from src.executor.report_builder import build_report

report = build_report(
    scenario_results=[result1, result2],
    plan_was_list=True,   # True → list output; False → single-object output
)
```

Applies canonical field ordering to every nested object for stable diffs. The builder does not make any HTTP calls or assertions — it only transforms data.

---

## Binding resolution rules

1. A `{{contextKey}}` reference in `pathParams`, `queryParams`, or `body` must have been produced by a `produceBindings` entry in an **earlier** step of the same scenario.
2. If the key is absent from the context at the time the step runs, `BindingError` is raised and the step is marked failed — no fallback value is used.
3. Bindings produced by a failed step are **not** added to the context. Subsequent steps that depend on them will also fail with a `BindingError`.

---

## Status code enforcement

| Step role | `expectedStatusCode` source |
|---|---|
| `target` | `scenario.expectedStatusCode` (unless a step-level override is present) |
| `setup` | Step-level `expectedStatusCode` only; no enforcement if absent |
| Any role | Step-level `expectedStatusCode` takes precedence when present |

A status code mismatch sets `step.passed = false` and populates `step.error` with `"Expected X, got Y"`. The assertions are still evaluated after a status mismatch so downstream review has the full response evidence.

---

## Execution flow per scenario

```
For each scenario in plan order:
  context = {}
  For each step in index order:
    1. Resolve {{contextKey}} templates in pathParams, queryParams, body
    2. Substitute {param} placeholders in path
    3. Send HTTP request
    4. Check expected status code (if applicable)
    5. Evaluate all assertions against response body
    6. If step passed: extract produceBindings into context
    7. If step failed: record error, stop iterating steps
  Aggregate step results into scenario result
```

A scenario is marked `passed: true` only when every step passes. Execution aborts at the first failing step; later steps are not run and do not appear in the report.

---

## Error representation

All executor errors are represented as structured data in the report, never as unhandled exceptions.

| Failure type | Where it appears |
|---|---|
| Transport error (network, DNS) | `step.error`, `step.actualStatusCode: null` |
| Status code mismatch | `step.error` ("Expected X, got Y"), `step.passed: false` |
| Assertion failure | `assertionResults[*].passed: false`, `assertionResults[*].error` |
| Binding resolution failure | `step.error`, `step.passed: false` |
| Assertion path not found | `assertionResults[*].passed: false`, `assertionResults[*].error` |
