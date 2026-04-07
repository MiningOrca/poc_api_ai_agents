# Execution Guide

API QA pipeline: specification-driven test artifact generation and execution.

---

## 1. Purpose

The pipeline transforms business context and an OpenAPI contract into executable test scenarios, runs them against a live API, and produces a structured review report.

**Required inputs:**
- `agent/input/context.md` — business and product rules
- `agent/input/open_api.json` — OpenAPI 3.x or Swagger 2.0 contract

**Expected outputs (in `output/`):**
- `output/rules.json` — extracted business rules
- `output/test_cases.json` — abstract test case designs per endpoint
- `output/execution_plan.json` — concrete executable scenarios with HTTP details
- `output/execution_report.json` — step-level execution results
- `output/review_report.json` — verdict, failure classification, root-cause hypotheses

---

## 2. Prerequisites

**Python version:** Python 3.12 (`.venv` with Python 3.12 is present at `.venv/`).

There is no `pyproject.toml`, `requirements.txt`, or `setup.py` in this repository. The core code (`src/`) uses only the Python standard library (`json`, `urllib`, `pathlib`, `dataclasses`, `argparse`). No dependency installation is required for the gate validators, normalizers, contract loader, or executor.

**Activate the existing virtual environment before running code:**
```sh
source .venv/bin/activate
```

**Environment variable (Stage 4 only):**
- `API_BASE_URL` — base URL of the API under test (e.g. `http://localhost:8080`)
- Can be passed as `--base-url` flag instead

**Required input files (must exist before starting):**
- `agent/input/context.md` — present in the repository
- `agent/input/open_api.json` — present in the repository
- `agent/json_examples/execution_plan.json` — present; used as a format reference for Stage 3

---

## 3. Repository Structure

```
APIAgent/
├── workflow.md                      # Architectural source of truth (5 stages, gates A–E)
├── CLAUDE.md                        # Project purpose and non-negotiables
├── instruction_gate.md              # Gate API usage reference
├── instruction_executioner.md       # Executor usage reference
│
├── agent/
│   ├── architecture.md              # Detailed architecture document
│   ├── input/
│   │   ├── context.md               # Stage 1 input: business rules
│   │   └── open_api.json            # Stages 2, 3, 5 input: API contract
│   ├── json_examples/               # Reference examples for all artifact types
│   │   ├── rules.json
│   │   ├── test_cases.json
│   │   ├── execution_plan.json
│   │   ├── execution_report.json
│   │   └── review_report.json
│   └── skills/
│       └── run_pipeline/SKILL.md    # Orchestration skill specification
│
├── src/
│   ├── gates.py                     # Stage-level gate orchestrators (run_stage1_gates etc.)
│   ├── contract/
│   │   └── loader.py                # OpenAPI/Swagger parser (ContractLoader)
│   ├── models/                      # Typed dataclasses for all artifacts
│   │   ├── rules.py
│   │   ├── test_cases.py
│   │   ├── execution_plan.py
│   │   └── review_report.py
│   ├── validators/                  # Deterministic gate implementations
│   │   ├── errors.py                # ValidationError, GateFailure
│   │   ├── gate_a.py                # Shape validation
│   │   ├── gate_b.py                # Contract conformance
│   │   ├── gate_c.py                # Assertion operator whitelist
│   │   └── gate_d.py                # Binding produce/consume validity
│   ├── normalizers/
│   │   └── gate_e.py                # Canonical field ordering and defaults
│   └── executor/                    # Stage 4: deterministic HTTP execution
│       ├── runner.py                # Entry point (CLI + Python API)
│       ├── scenario_executor.py
│       ├── step_executor.py
│       ├── binding_resolver.py
│       ├── assertion_engine.py
│       ├── http_client.py
│       └── report_builder.py
│
└── output/                          # Pipeline outputs written here
    └── rules.json                   # Stage 1 output (already generated)
```

---

## 4. Pipeline Stages

### Stage 1 — Rules Extraction
| | |
|---|---|
| **Driver** | Skill (`agent/skills/extract_rules/SKILL.md`) |
| **Input** | `agent/input/context.md` |
| **Output** | `output/rules.json` |
| **Gates** | A (shape) + E (normalization) via `src/gates.py::run_stage1_gates` |
| **Type** | Skill-driven (LLM) |

The skill reads `context.md` and extracts business rules into general rules and endpoint-specific rules, each with a source reference. After the skill writes the artifact, gates A and E must pass before Stage 2 can proceed.

**Note:** `output/rules.json` is already present from a prior run.

---

### Stage 2 — Test Case Design
| | |
|---|---|
| **Driver** | Skill (`agent/skills/design_test_cases/SKILL.md`) |
| **Input** | `output/rules.json` + `agent/input/open_api.json` |
| **Output** | `output/test_cases.json` |
| **Gates** | A + B (contract conformance) + E via `src/gates.py::run_stage2_gates` |
| **Type** | Skill-driven (LLM) |

The skill designs abstract test intent per endpoint — positive, negative, and boundary cases — without producing HTTP payloads. Gate B verifies every `endpointId` resolves to a real operation in the contract.

---

### Stage 3 — Execution Planning
| | |
|---|---|
| **Driver** | Skill (`agent/skills/plan_execution/SKILL.md`) |
| **Input** | `output/test_cases.json` + `agent/input/open_api.json` + `agent/json_examples/execution_plan.json` |
| **Output** | `output/execution_plan.json` |
| **Gates** | A + B + C + D + E via `src/gates.py::run_stage3_gates` — strictest boundary |
| **Type** | Skill-driven (LLM) |

The skill converts abstract test cases into concrete executable scenarios: HTTP method, path, params, body, assertions per step, and inter-step bindings. The format example (`json_examples/execution_plan.json`) is provided as a structural reference. This stage has the most gates because it is the most operationally consequential reasoning layer.

---

### Stage 4 — Execution
| | |
|---|---|
| **Driver** | Deterministic code (`src/executor/runner.py`) |
| **Input** | `output/execution_plan.json` |
| **Output** | `output/execution_report.json` |
| **Gates** | None (shape guaranteed by implementation) |
| **Type** | Deterministic code only |

**This is the only stage with a direct CLI entry point:**

```sh
python -m src.executor.runner \
    --plan output/execution_plan.json \
    --report output/execution_report.json \
    --base-url http://localhost:8080
```

Or with the environment variable:
```sh
export API_BASE_URL=http://localhost:8080
python -m src.executor.runner
```

The executor sends HTTP requests step by step, resolves `{{binding}}` references between steps, evaluates assertions, and records full evidence (actual request/response bodies, timestamps, assertion outcomes). Scenarios abort at the first failing step. Exit code 0 is returned even when scenarios fail; non-zero exit means the runner itself could not complete (I/O error, bad plan path, missing base URL).

---

### Stage 5 — Result Review
| | |
|---|---|
| **Driver** | Skill (`agent/skills/review_execution/SKILL.md`) |
| **Input** | `output/execution_report.json` + `output/execution_plan.json` + `output/rules.json` + relevant slice of `agent/input/open_api.json` |
| **Output** | `output/review_report.json` |
| **Gates** | A + E via `src/gates.py::run_stage5_gates` |
| **Type** | Skill-driven (LLM) |

The skill reviews execution outcomes without re-executing anything. It produces: failure classification, validation sufficiency assessment, root-cause hypotheses, and recommended actions.

---

## 5. Run Instructions

### Full pipeline

The pipeline is orchestrated by the `run_pipeline` skill defined in `agent/skills/run_pipeline/SKILL.md`. This skill is a Claude Code skill — it is invoked by telling Claude Code to run it, not by a shell command. There is no single shell command for the full pipeline.

**To run the full pipeline via Claude Code:**
```
Run the full pipeline. Inputs are in agent/input/. Write outputs to output/.
```

Claude Code will invoke each stage skill in order, run the deterministic gates after each skill-driven stage, and halt on the first gate failure.

### Stage-by-stage (if running manually or debugging)

**Stage 1 — Rules Extraction**

Invoke the `extract-rules` skill in Claude Code, then validate:
```python
import json
from src.gates import run_stage1_gates

data = json.loads(open("output/rules.json").read())
normalized = run_stage1_gates(data)
open("output/rules.json", "w").write(json.dumps(normalized, indent=2))
```

**Stage 2 — Test Case Design**

Invoke the `design-test-cases` skill, then validate:
```python
import json
from src.gates import run_stage2_gates
from src.contract.loader import ContractLoader

contract = ContractLoader.from_file("agent/input/open_api.json")
data = json.loads(open("output/test_cases.json").read())
normalized = run_stage2_gates(data, contract)
open("output/test_cases.json", "w").write(json.dumps(normalized, indent=2))
```

**Stage 3 — Execution Planning**

Invoke the `plan-execution` skill, then validate:
```python
import json
from src.gates import run_stage3_gates
from src.contract.loader import ContractLoader

contract = ContractLoader.from_file("agent/input/open_api.json")
data = json.loads(open("output/execution_plan.json").read())
normalized = run_stage3_gates(data, contract)
open("output/execution_plan.json", "w").write(json.dumps(normalized, indent=2))
```

**Stage 4 — Execution** (the only stage with a direct shell command)

```sh
python -m src.executor.runner \
    --plan output/execution_plan.json \
    --report output/execution_report.json \
    --base-url http://localhost:8080
```

**Stage 5 — Result Review**

Invoke the `review-execution` skill, then validate:
```python
import json
from src.gates import run_stage5_gates

data = json.loads(open("output/review_report.json").read())
normalized = run_stage5_gates(data)
open("output/review_report.json", "w").write(json.dumps(normalized, indent=2))
```

---

## 6. Gate Behavior

Gates are deterministic Python code. They raise `GateFailure` (from `src/validators/errors.py`) on rejection.

```python
from src.validators.errors import GateFailure

try:
    normalized = run_stage3_gates(data, contract)
except GateFailure as exc:
    for error in exc.errors:
        print(error.gate, error.artifact, error.field, error.reason)
```

Each `ValidationError` contains:
- `gate` — which gate failed (e.g. `"gate_b"`)
- `artifact` — the artifact type (e.g. `"execution_plan"`)
- `field` — the specific field or path that failed
- `reason` — human-readable explanation

**Gate failure halts the pipeline.** No downstream stage runs until the artifact is corrected and passes all required gates. Gates do not attempt repairs; they surface failures only.

**Where to look:**
- Gate A failures: missing or wrong-typed required fields
- Gate B failures: endpoint ID, method, path, param, or status code not present in `open_api.json`
- Gate C failures: unsupported assertion operator (only `equals`, `not_equals`, `exists`, `not_exists`, `contains`, `in`, `gte`, `lte` are accepted)
- Gate D failures: `{{key}}` reference consumed before it was produced, or invalid `$.` JSONPath in `produceBindings`
- Gate E: normalizer modifies the artifact in place; does not raise unless the artifact is structurally incompatible

---

## 7. Output Artifacts

| Artifact | Path | Produced by | Gates applied |
|---|---|---|---|
| Rules | `output/rules.json` | Stage 1 skill | A + E |
| Test cases | `output/test_cases.json` | Stage 2 skill | A + B + E |
| Execution plan | `output/execution_plan.json` | Stage 3 skill | A + B + C + D + E |
| Execution report | `output/execution_report.json` | Stage 4 executor | None (shape guaranteed) |
| Review report | `output/review_report.json` | Stage 5 skill | A + E |

All artifacts are UTF-8 JSON, pretty-printed with 2-space indent. The `output/` directory is created by the executor if absent; for skill-driven stages, it must exist before the skill writes to it.

---

## 8. Current Implementation Status

| Component | Status |
|---|---|
| Gate A — shape validation | Implemented (`src/validators/gate_a.py`) |
| Gate B — contract conformance | Implemented (`src/validators/gate_b.py`) |
| Gate C — assertion operators | Implemented (`src/validators/gate_c.py`) |
| Gate D — binding validity | Implemented (`src/validators/gate_d.py`) |
| Gate E — normalization | Implemented (`src/normalizers/gate_e.py`) |
| Stage-level gate orchestration | Implemented (`src/gates.py`) |
| Contract loader (OpenAPI 3.x + Swagger 2.0) | Implemented (`src/contract/loader.py`) |
| Typed artifact models | Implemented (`src/models/`) |
| Stage 4 executor (full) | Implemented (`src/executor/`) |
| Orchestration skill spec | Implemented (`agent/skills/run_pipeline/SKILL.md`) |
| Stage 1 skill spec (`extract_rules`) | **Missing** — `agent/skills/extract_rules/SKILL.md` does not exist |
| Stage 2 skill spec (`design_test_cases`) | **Missing** — `agent/skills/design_test_cases/SKILL.md` does not exist |
| Stage 3 skill spec (`plan_execution`) | **Missing** — `agent/skills/plan_execution/SKILL.md` does not exist |
| Stage 5 skill spec (`review_execution`) | **Missing** — `agent/skills/review_execution/SKILL.md` does not exist |
| `output/rules.json` | Present (generated from prior Stage 1 run) |
| `output/test_cases.json` | Not yet generated |
| `output/execution_plan.json` | Not yet generated |
| `output/execution_report.json` | Not yet generated |
| `output/review_report.json` | Not yet generated |

---

## 9. Known Gaps and Caveats

**Missing individual stage skill files.**
`workflow.md` and `agent/skills/run_pipeline/SKILL.md` both reference four skill files that do not exist in the repository:
- `agent/skills/extract_rules/SKILL.md`
- `agent/skills/design_test_cases/SKILL.md`
- `agent/skills/plan_execution/SKILL.md`
- `agent/skills/review_execution/SKILL.md`

The orchestration skill (`run_pipeline/SKILL.md`) describes invoking these skills by name. The instruction content for each stage must be embedded directly in the skill invocation prompt or supplied by the Claude Code operator until these files are created.

**CLAUDE.md pipeline description is inconsistent with workflow.md.**
`CLAUDE.md` describes artifact names (`spec_sections.json`, `rules_views.json`, `contract.json`, `test_cases_<endpoint>.json`, `scenarios_<endpoint>.json`) that do not match the artifact names used in `workflow.md` or produced by the current code (`rules.json`, `test_cases.json`, `execution_plan.json`). `workflow.md` is the architectural source of truth; `CLAUDE.md`'s pipeline section appears to be outdated.

**No dependency manifest.**
There is no `pyproject.toml`, `requirements.txt`, or `setup.py`. The code uses stdlib only, so this is not currently a blocker, but the Python version requirement (3.12) is only discoverable via the `.venv/` directory.

**No single shell command for the full pipeline.**
Stages 1, 2, 3, and 5 are skill-driven. There is no CLI wrapper or Makefile target that runs the complete pipeline from the shell. The only direct shell entry point is Stage 4 (`python -m src.executor.runner`).

**Gate invocation is a manual step after each skill stage.**
The `run_pipeline` skill spec describes when to call each gate function, but gate invocation itself is not automated unless the orchestration skill (or the caller) runs the Python gate code explicitly after each skill output is written.

---

## 10. Minimal Successful Path

To run the pipeline in its current state with the existing `output/rules.json`:

1. **Verify prerequisites:**
   ```sh
   source .venv/bin/activate
   # Confirm these files exist:
   # agent/input/context.md
   # agent/input/open_api.json
   # agent/json_examples/execution_plan.json
   # output/rules.json
   ```

2. **Run Stage 2 (design-test-cases) via Claude Code,** then validate the output:
   ```python
   import json
   from src.gates import run_stage2_gates
   from src.contract.loader import ContractLoader
   contract = ContractLoader.from_file("agent/input/open_api.json")
   data = json.loads(open("output/test_cases.json").read())
   normalized = run_stage2_gates(data, contract)
   open("output/test_cases.json", "w").write(json.dumps(normalized, indent=2))
   ```

3. **Run Stage 3 (plan-execution) via Claude Code,** then validate:
   ```python
   import json
   from src.gates import run_stage3_gates
   from src.contract.loader import ContractLoader
   contract = ContractLoader.from_file("agent/input/open_api.json")
   data = json.loads(open("output/execution_plan.json").read())
   normalized = run_stage3_gates(data, contract)
   open("output/execution_plan.json", "w").write(json.dumps(normalized, indent=2))
   ```

4. **Run Stage 4 (executor) against a live API:**
   ```sh
   python -m src.executor.runner \
       --plan output/execution_plan.json \
       --report output/execution_report.json \
       --base-url http://localhost:8080
   ```

5. **Run Stage 5 (review-execution) via Claude Code,** then validate:
   ```python
   import json
   from src.gates import run_stage5_gates
   data = json.loads(open("output/review_report.json").read())
   normalized = run_stage5_gates(data)
   open("output/review_report.json", "w").write(json.dumps(normalized, indent=2))
   ```

The shortest path if you only need to verify the executor works against an existing plan: steps 4 only, using `agent/json_examples/execution_plan.json` as a reference plan (after adapting it to your API base URL).