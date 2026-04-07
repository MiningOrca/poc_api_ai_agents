# Gate Usage Instructions

How to use the deterministic gate layer in `src/`.

---

## Overview

The gate layer sits between every skill-driven stage and the next stage of the pipeline. It does three things:

1. **Validate** the candidate artifact produced by the skill.
2. **Reject** it with structured errors if any check fails.
3. **Normalize** it into canonical form before it is persisted or passed downstream.

The gate layer is pure Python, has no LLM calls, and is deterministic.

---

## Quick start — use `src/gates.py`

The simplest way to run gates is through the per-stage functions in `src/gates.py`. Each function runs all gates required for that stage boundary and returns the normalized artifact.

```python
import json
from src.gates import run_stage1_gates, run_stage2_gates, run_stage3_gates, run_stage5_gates
from src.contract.loader import ContractLoader
from src.validators.errors import GateFailure

# Load the contract once and reuse it across stages
contract = ContractLoader.from_file("agent/input/open_api.json")

# Stage 1 — after extract-rules skill writes output/rules.json
with open("output/rules.json") as f:
    rules_data = json.load(f)

try:
    normalized_rules = run_stage1_gates(rules_data)
    # normalized_rules is a plain dict — write it back or pass it downstream
    with open("output/rules.json", "w") as f:
        json.dump(normalized_rules, f, indent=2)
except GateFailure as e:
    print(e.to_dict())  # structured error — halt the pipeline
```

The same pattern applies to all other stages:

| Stage boundary | Function | Contract required |
|---|---|---|
| After Stage 1 (rules.json) | `run_stage1_gates(data)` | No |
| After Stage 2 (test_cases.json) | `run_stage2_gates(data, contract)` | Yes |
| After Stage 3 (execution_plan.json) | `run_stage3_gates(data, contract)` | Yes |
| After Stage 5 (review_report.json) | `run_stage5_gates(data)` | No |

---

## Handling `GateFailure`

All gate functions raise `GateFailure` when the artifact is rejected. The exception carries a list of `ValidationError` objects and can be serialized.

```python
from src.validators.errors import GateFailure, ValidationError

try:
    normalized = run_stage3_gates(plan_data, contract)
except GateFailure as e:
    # Print all errors
    for error in e.errors:
        print(f"[{error.gate}] {error.artifact} / {error.field}: {error.reason}")

    # Or serialize to dict for logging / reporting
    result = e.to_dict()
    # {
    #   "gate_failure": true,
    #   "errors": [
    #     {"gate": "Gate B — Contract conformance",
    #      "artifact": "execution_plan.json",
    #      "field": "[0].steps[0].body.unknownField",
    #      "reason": "'unknownField' is not a documented request body field of 'create_user_users_post'"}
    #   ]
    # }
```

Each `ValidationError` always tells you:
- **gate** — which gate rejected it (A, B, C, D, or E)
- **artifact** — which file is being validated
- **field** — JSON path inside the artifact that caused the failure
- **reason** — human-readable explanation

---

## Contract loader

`ContractLoader` parses `open_api.json` and indexes all operations by `operationId`. It is required for Gate B.

```python
from src.contract.loader import ContractLoader

contract = ContractLoader.from_file("agent/input/open_api.json")

# List all known operation IDs
print(contract.operation_ids())
# {'create_user_users_post', 'deposit_wallets_deposit_post', ...}

# Look up a single operation
op = contract.get_operation("create_user_users_post")
print(op.method)            # 'POST'
print(op.path)              # '/users'
print(op.path_param_names)  # set()
print(op.query_param_names) # set()
print(op.request_body_fields)  # {'name', 'email'}
print(op.responses)         # {201: {'userId', 'name', 'email'}, 400: {'error', 'details'}, ...}
```

`ContractLoader` can also be constructed directly from a parsed dict if you already have the spec in memory:

```python
import json
with open("agent/input/open_api.json") as f:
    spec = json.load(f)
contract = ContractLoader(spec)
```

---

## Using individual gates

If you need to run gates individually — for example to validate only shape without a contract — import each gate module directly.

### Gate A — Artifact shape

```python
from src.validators import gate_a
from src.validators.errors import GateFailure

# Validates rules.json
gate_a.validate_rules(data)

# Validates test_cases.json
gate_a.validate_test_cases(data)

# Validates execution_plan.json
gate_a.validate_execution_plan(data)

# Validates review_report.json
gate_a.validate_review_report(data)
```

Gate A rejects any artifact that is missing required fields, has a wrong type, or contains malformed nested objects. It does not need the contract.

### Gate B — Contract conformance

```python
from src.validators import gate_b
from src.contract.loader import ContractLoader

contract = ContractLoader.from_file("agent/input/open_api.json")

# test_cases.json: checks all endpointId values in cases and steps
gate_b.validate_test_cases(data, contract)

# execution_plan.json: checks method, path, params, body fields,
# expected status codes, and assertion target fields
gate_b.validate_execution_plan(data, contract)
```

Gate B is the only gate that requires the contract. For `execution_plan.json` it also checks that assertion `path` fields (JSONPath root segment) exist in the response schema for the relevant status code.

### Gate C — Assertion operators

```python
from src.validators import gate_c

gate_c.validate_execution_plan(data)
```

Allowed operators: `equals`, `not_equals`, `exists`, `not_exists`, `contains`, `in`, `gte`, `lte`. Any other value causes rejection.

### Gate D — Binding validity

```python
from src.validators import gate_d

gate_d.validate_execution_plan(data)
```

Gate D checks two things per scenario:

1. Every `produceBindings[*].sourcePath` is a valid JSONPath (e.g. `$.userId`).
2. Every `{{contextKey}}` template reference in `pathParams`, `queryParams`, or `body` of a step was produced by a `produceBindings` entry in an **earlier** step of the same scenario.

### Gate E — Normalization

```python
from src.normalizers.gate_e import (
    normalize_rules,
    normalize_test_cases,
    normalize_execution_plan,
    normalize_review_report,
)

normalized = normalize_rules(data)
normalized = normalize_test_cases(data)
normalized = normalize_execution_plan(data)
normalized = normalize_review_report(data)
```

Each normalizer returns a **new dict or list** — the input is not mutated. Normalization is idempotent: applying it twice produces the same result as applying it once.

What normalization does per artifact:

| Artifact | Defaults added | Field order enforced |
|---|---|---|
| `rules.json` | `generalRules: []`, `rulesByEndpoint: {}`, `sourceRefs: []` per rule | `id → text → sourceRefs` per rule |
| `test_cases.json` | `cases: []`, `mode: "single"`, `summary: ""`, `expectedOutcome: ""`, `steps: []`, `sourceRefs: []` | `title → summary → category → mode → ...` per case |
| `execution_plan.json` | `sourceRefs: []`, `steps: []`, `title: ""`, `pathParams: {}`, `queryParams: {}`, `body: {}`, `assertions: []`, `produceBindings: []` per step | `scenarioId → endpointId → title → ...` per scenario |
| `review_report.json` | `rootCauseHypotheses: []`, `testDesignIssues: []`, `recommendedActions: []`, `evidence: []`, `missingChecks: []` | `scenarioId → verdict → summary → ...` per verdict |

---

## Typed models

`src/models/` contains strict dataclass models for each artifact. These are optional — gates operate directly on raw dicts — but useful if downstream code benefits from typed access.

```python
import json
from src.models.rules import RulesArtifact
from src.models.test_cases import EndpointTestCases
from src.models.execution_plan import Scenario
from src.models.review_report import ReviewVerdict

with open("output/rules.json") as f:
    data = json.load(f)

artifact = RulesArtifact.from_dict(data)
for rule in artifact.generalRules:
    print(rule.id, rule.text)

for endpoint_id, rules in artifact.rulesByEndpoint.items():
    print(endpoint_id, [r.id for r in rules])
```

The `from_dict` methods on all model classes assume the artifact has already passed Gate A. Passing an invalid artifact to `from_dict` may raise a `KeyError` rather than a structured `GateFailure`.

---

## Gate responsibilities by stage

| Stage | Gates run | Artifact |
|---|---|---|
| 1 — Rules extraction | A, E | `output/rules.json` |
| 2 — Test case design | A, B, E | `output/test_cases.json` |
| 3 — Execution planning | A, B, C, D, E | `output/execution_plan.json` |
| 4 — Execution | None (executor output is deterministic code) | `output/execution_report.json` |
| 5 — Result review | A, E | `output/review_report.json` |

Stage 3 runs all five gates and is the strictest boundary because the executor runs the plan without further interpretation.

---

## Error identification reference

| Gate | Triggered by |
|---|---|
| Gate A | Missing required field, wrong type, malformed nested object |
| Gate B | Unknown `operationId`, wrong HTTP method or path, undocumented param or body field, undocumented status code, implausible assertion target field |
| Gate C | Assertion `operator` not in the eight allowed values |
| Gate D | `sourcePath` not a valid JSONPath; `{{key}}` consumed before it was produced |
| Gate E | Not a rejection gate — normalization always succeeds on a Gate A-valid artifact |
