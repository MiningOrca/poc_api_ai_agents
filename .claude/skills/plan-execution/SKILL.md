# plan-execution

## Purpose

Convert abstract test cases from `output/test_cases.json` into fully-specified executable scenarios in `output/execution_plan.json`. Each scenario includes concrete method, path, parameters, request body, per-step assertions, and bindings that carry state between steps.

This is the strictest reasoning stage in the pipeline. Gate failures here are the most consequential because the executor runs the plan without further interpretation.

## When to use

Invoke this skill at Stage 3, after `output/test_cases.json` has passed Gate A, Gate B, and Gate E. Re-invoke whenever `test_cases.json` or `open_api.json` changes.

## Required inputs

| File | Role |
|---|---|
| `output/test_cases_{endpointId}.json` | Abstract test cases for **one specific endpoint** — passed by the caller |
| `agent/input/open_api.json` | Authoritative contract — read only the operation(s) referenced by the test cases file |
| `agent/json_examples/execution_plan.json` | Canonical shape reference for the output artifact |

This skill is invoked **once per endpoint**. The caller passes a single `test_cases_{endpointId}.json` file. Do not glob or read other test case files.

## Produced output

| File | Role |
|---|---|
| `output/execution_plan_{endpointId}.json` | Executable scenarios for the single endpoint passed as input |

## Schema

```json
{
  "scenarioId": "SC-<ENDPOINT_ABBREV>-001",
  "isSetupFixture": true,
  "setupRef": "SC-<ENDPOINT_ABBREV>-SETUP",
  "endpointId": "<operationId>",
  "title": "<test case title>",
  "category": "positive | negative | boundary | setup",
  "sourceRefs": ["<ruleId>"],
  "expectedStatusCode": 200,
  "steps": [...]
}
```

All plans are written as a JSON array of scenario objects.

### Setup fixture pattern (use when ≥ 3 scenarios share identical setup steps)

When multiple scenarios begin with the same sequence of setup steps, define those steps **once** in a fixture scenario and reference it from the other scenarios. This keeps the plan compact without losing correctness — the executor automatically expands the reference at runtime.

**Fixture scenario** — define it once, placed first in the array:
```json
{
  "scenarioId": "SC-<ABBREV>-SETUP",
  "isSetupFixture": true,
  "endpointId": "<primary endpointId>",
  "title": "Shared setup: <what it establishes>",
  "category": "setup",
  "sourceRefs": [],
  "expectedStatusCode": 200,
  "steps": [
    { "index": 0, "stepRole": "setup", ... },
    { "index": 1, "stepRole": "setup", ... }
  ]
}
```

**Referencing scenario** — omit the repeated setup steps and add `setupRef`:
```json
{
  "scenarioId": "SC-<ABBREV>-001",
  "setupRef": "SC-<ABBREV>-SETUP",
  "endpointId": "<operationId>",
  "title": "...",
  "category": "positive | negative | boundary",
  "sourceRefs": ["<ruleId>"],
  "expectedStatusCode": 200,
  "steps": [
    { "index": 0, "stepRole": "target", ... }
  ]
}
```

Rules for `setupRef` scenarios:
- `steps` contains **only** the scenario's own steps (usually just the target step); start indices at 0.
- The executor prepends the fixture's steps and renumbers indices automatically.
- `setupRef` must match the `scenarioId` of an `isSetupFixture` scenario in the same plan.
- Scenarios that do **not** share the common setup (e.g. single-step negative cases that need no state) must **not** use `setupRef` — inline their steps directly.
- If a scenario needs a different setup sequence, inline its steps directly instead of using `setupRef`.

### Full inline scenario (no fixture)

```json
{
  "scenarioId": "SC-<ENDPOINT_ABBREV>-001",
  "endpointId": "<operationId>",
  "title": "<test case title>",
  "category": "positive | negative | boundary",
  "sourceRefs": ["<ruleId>"],
  "expectedStatusCode": 200,
  "steps": [
    {
      "index": 0,
      "stepRole": "setup | target",
      "title": "<step title>",
      "endpointId": "<operationId>",
      "method": "POST",
      "path": "/resource",
      "pathParams": {},
      "queryParams": {},
      "body": {},
      "assertions": [
        {
          "path": "$.field",
          "operator": "equals | not_equals | exists | not_exists | contains | in | gte | lte",
          "expected": "<value>"
        }
      ],
      "produceBindings": [
        {
          "contextKey": "<key>",
          "sourcePath": "$.responseField"
        }
      ]
    }
  ]
}
```

## Instructions

1. Read the single `output/test_cases_{endpointId}.json` file passed by the caller, `agent/json_examples/execution_plan.json`, and only the operations in `agent/input/open_api.json` referenced by that file. Do not read other test case files.
2. For each test case in the file, produce one scenario object. Write all scenarios to `output/execution_plan_{endpointId}.json` as a JSON array.
3. Assign `scenarioId` using `SC-<ENDPOINT_ABBREV>-` prefix, zero-padded to three digits.
4. Resolve `method` and `path` for each step from `open_api.json` using the step's `endpointId`.
5. Construct `body`, `pathParams`, and `queryParams` from the request schema in `open_api.json`. Use minimal, semantically valid values sufficient to trigger the intended outcome. Do not fabricate fields absent from the schema.
   - For fields that must be unique per run (email, username, slug, or any field the API enforces uniqueness on), use `{{runId}}` as a suffix or prefix — e.g. `"email": "user-{{runId}}@example.com"`. The executor pre-seeds `runId` in the context before execution begins. Do not use fixed literal values for such fields.
6. Assign `stepRole`:
   - Last step in a chained case: `"target"`.
   - All preceding steps: `"setup"`.
   - Single-step cases: the single step is `"target"`.
7. Write assertions for each step:
   - Assertions must reference response fields documented in `open_api.json` for the step's expected status code.
   - Use only the eight supported operators: `equals`, `not_equals`, `exists`, `not_exists`, `contains`, `in`, `gte`, `lte`.
   - Do not assert on fields not present in the documented response schema.
8. Write bindings for chained scenarios:
   - `produceBindings`: extract a response field into a named context key using a JSONPath `sourcePath`.
   - Steps that consume a binding must reference a `contextKey` produced by an earlier step. Use `{{contextKey}}` notation in the consuming step's params or body.
   - Every consumed key must be produced before it is consumed. No dangling references.
9. Single-step scenarios: `produceBindings` is `[]`.
10. Write results to per-endpoint files: `output/execution_plan_{endpointId}.json`. Do not merge multiple endpoints into one file.

## Constraints

- Do not invent endpoints, methods, paths, path parameters, query parameters, request fields, response fields, or status codes not present in `open_api.json`.
- Do not use assertion operators other than the eight listed above.
- Do not reference a context key that has not been produced by an earlier step in the same scenario.
- Do not omit `pathParams`, `queryParams`, `body`, `assertions`, or `produceBindings` — use empty objects/arrays when not applicable.
- Do not mix request schema fields into response assertions or vice versa.

## Deterministic validation

After writing all per-endpoint files, run deterministic validation for each file exactly as shown below.

Do not search for alternative runners.
Do not reimplement gate logic.
Do not use a different contract loader.

```python
import glob, json
from src.gates import run_stage3_gates
from src.contract.loader import ContractLoader

contract = ContractLoader.from_file("agent/input/open_api.json")
for path in sorted(glob.glob("output/execution_plan_*.json")):
    data = json.loads(open(path).read())
    normalized = run_stage3_gates(data, contract)
    open(path, "w").write(json.dumps(normalized, indent=2))
```
## Expected file locations

```
output/test_cases_{endpointId}.json              ← read (single file, passed by caller)
agent/input/open_api.json                        ← read (relevant operations only)
agent/json_examples/execution_plan.json          ← read (shape reference)
output/execution_plan_{endpointId}.json          ← write
```

## Example invocation

```
Run the plan-execution skill.
Input: output/test_cases_createUser.json, agent/input/open_api.json, agent/json_examples/execution_plan.json
Output: output/execution_plan_createUser.json
```
