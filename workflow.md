# Workflow

End-to-end pipeline for API QA automation. Five sequential stages, separated by deterministic validation and normalization gates.

---

## Stage 1 — Rules Extraction

**Driver:** Skill (`agent/skills/extract_rules/SKILL.md`)

| | Artifact |
|---|---|
| **Input** | `agent/input/context.md` |
| **Output** | `output/rules.json` |

**What happens:**

The skill reads `context.md` and extracts business and product rules into a compact, traceable structure. Rules are separated into general rules and endpoint-specific rules. Each rule should be atomic, concise, and reference its source section where possible.

**Gate after this stage:**

| Gate | Check |
|---|---|
| A — Shape | Required fields present (`generalRules`, `rulesByEndpoint`); no wrong types or malformed objects |
| E — Normalization | Stable field ordering; empty collections defaulted; optional structures filled with canonical empty values |

Gate failure halts the pipeline. No downstream stage runs until the candidate artifact passes.

---

## Stage 2 — Test Case Design

**Driver:** Skill (`agent/skills/design_test_cases/SKILL.md`)

| | Artifact |
|---|---|
| **Input** | `output/rules.json` + `agent/input/open_api.json` |
| **Output** | `output/test_cases.json` |

**What happens:**

The skill designs test intent per endpoint. For each case it decides: what to test, whether the case is positive / negative / boundary, whether the flow is single-step or chained, and which source rules justify the case. This stage operates at the design level — it does not produce HTTP payloads or transport-level assertions.

**Gate after this stage:**

| Gate | Check |
|---|---|
| A — Shape | Required fields present (`endpointId`, `title`, `category`, `sourceRefs`, `steps`); no wrong types |
| B — Contract conformance | Every `endpointId` maps to a real operation in `open_api.json`; HTTP methods and paths exist in the contract |
| E — Normalization | Stable field ordering; empty step lists defaulted; `mode` defaulted when absent |

Gate failure halts the pipeline.

---

## Stage 3 — Execution Planning

**Driver:** Skill (`agent/skills/plan_execution/SKILL.md`)

| | Artifact |
|---|---|
| **Input** | `output/test_cases.json` + `agent/input/open_api.json` + `agent/json_examples/execution_plan.json` |
| **Output** | `output/execution_plan.json` |

**What happens:**

The skill converts abstract test cases into executable scenarios. For each scenario it decides: setup step sequence, target step, concrete method / path / params / body, assertions per step, and bindings that carry state between steps. Chained scenarios include one or more setup steps that produce bindings consumed by later steps.

This stage is skill-driven rather than deterministic because test execution often requires non-trivial state transitions, multi-endpoint setup chains, and context propagation that a rigid compiler cannot express reliably.

**Gate after this stage:**

| Gate | Check |
|---|---|
| A — Shape | All required step fields present (`endpointId`, `method`, `path`, `assertions`, `stepRole`); no wrong types |
| B — Contract conformance | All methods, paths, path/query/body fields, and expected status codes validated against `open_api.json`; response assertion targets reference plausible fields |
| C — Assertion operators | Only `equals`, `not_equals`, `exists`, `not_exists`, `contains`, `in`, `gte`, `lte` accepted; any other operator rejects the artifact |
| D — Binding validity | `produceBindings` use legal source paths; every consumed context key is defined earlier in the scenario or in setup context; no step consumes a key that was never produced |
| E — Normalization | Stable field ordering; empty assertion and binding lists defaulted; optional structures filled with canonical empty values |

Gate failure halts the pipeline. This is the strictest gate boundary in the pipeline because execution planning is the most operationally consequential reasoning layer.

---

## Stage 4 — Execution

**Driver:** Deterministic code (`src/executor/`)

| | Artifact |
|---|---|
| **Input** | `output/execution_plan.json` |
| **Output** | `output/execution_report.json` |

**What happens:**

The executor reads the validated and normalized execution plan and performs runtime execution. It:

- sends HTTP requests step by step in scenario order
- resolves binding references from shared context
- records the actual request and response for each step
- evaluates assertions against actual responses
- stores step-level pass/fail results and assertion outcomes
- captures execution errors and timestamps
- aggregates scenario-level pass/fail

The executor is normal application code. It does not use LLM skills. Its output format is fixed by the internal model.

**Validation note:**

Because the executor is deterministic code, artifact shape is guaranteed by the implementation. No separate gate is applied to `execution_report.json`. The report must be self-contained and sufficient for downstream review without raw executor logs.

---

## Stage 5 — Result Review

**Driver:** Skill (`agent/skills/review_execution/SKILL.md`)

| | Artifact |
|---|---|
| **Input** | `output/execution_report.json` + `output/execution_plan.json` + `output/rules.json` + relevant slice of `agent/input/open_api.json` |
| **Output** | `output/review_report.json` |

**What happens:**

The skill reviews execution outcomes and evaluates diagnostic quality. It does not re-execute anything. For each scenario it produces a structured verdict covering:

- **Failure classification:** application bug / test issue / contract mismatch / environment issue / inconclusive
- **Validation sufficiency:** whether the executed assertions were adequate to prove the intended business rule (independent of whether the scenario passed or failed)
- **Root-cause hypotheses:** evidence-backed explanation of what likely caused the outcome
- **Recommended actions:** concrete next steps

**Gate after this stage:**

| Gate | Check |
|---|---|
| A — Shape | Required fields present (`verdict`, `summary`, `failureClassification`, `validationSufficiency`, `evidence`, `recommendedActions`); no wrong types |
| E — Normalization | Stable field ordering; empty recommendation lists defaulted |

Gate failure halts reporting. The raw skill output is not used downstream until it passes.

---

## Gate Summary

| Gate | What it checks | Applied after stages |
|---|---|---|
| A — Artifact shape | Required fields, correct types, no malformed objects | 1, 2, 3, 5 |
| B — Contract conformance | Endpoint IDs, methods, paths, params, status codes valid against `open_api.json` | 2, 3 |
| C — Assertion operators | Only the eight supported operators accepted | 3 |
| D — Binding validity | Produce/consume consistency; no dangling references | 3 |
| E — Normalization | Canonical field order, defaulted empty collections, canonical scalar formatting | 1, 2, 3, 5 |

All gates are implemented in `src/validators/` and `src/normalizers/`. They are deterministic code, not skills. Gate failure halts the pipeline and returns a structured error indicating which gate failed and which field or check caused the rejection.

---

## Artifact Flow

```
agent/input/context.md
        │
        ▼
  [Skill: extract_rules]
        │
   [Gate A + E]
        │
        ▼
  output/rules.json
        │
        ├─── agent/input/open_api.json
        ▼
  [Skill: design_test_cases]
        │
   [Gate A + B + E]
        │
        ▼
  output/test_cases.json
        │
        ├─── agent/input/open_api.json
        ├─── agent/json_examples/execution_plan.json
        ▼
  [Skill: plan_execution]
        │
   [Gate A + B + C + D + E]
        │
        ▼
  output/execution_plan.json
        │
        ▼
  [Code: executor]
        │
        ▼
  output/execution_report.json
        │
        ├─── output/execution_plan.json
        ├─── output/rules.json
        ├─── agent/input/open_api.json (relevant slice)
        ▼
  [Skill: review_execution]
        │
   [Gate A + E]
        │
        ▼
  output/review_report.json
```

---

## Traceability

The pipeline preserves end-to-end traceability:

- Each rule in `rules.json` references its source section in `context.md`.
- Each test case in `test_cases.json` references the rule IDs that justify it.
- Each scenario in `execution_plan.json` is linked to its originating test case.
- Each step result in `execution_report.json` records actual request/response data and assertion outcomes.
- Each verdict in `review_report.json` cites specific steps and assertions as evidence.

This chain allows the system to answer, for any review finding: which business rule was being tested, which step failed, and why the failure is classified the way it is.
