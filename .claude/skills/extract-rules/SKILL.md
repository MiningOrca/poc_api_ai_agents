# extract-rules

## Purpose

Read `agent/input/context.md` and extract all business and product rules into `output/rules.json`. Rules are the authoritative input for all downstream test design stages.

## When to use

Invoke this skill at Stage 1 of the pipeline, before test case design. Re-invoke whenever `context.md` changes.

## Required inputs

| File | Role |
|---|---|
| `agent/input/context.md` | Source of truth for business rules |

## Produced output

| File | Role |
|---|---|
| `output/rules.json` | Extracted rules, validated and normalized |

## Schema

```json
{
  "generalRules": [
    {
      "id": "GR-001",
      "text": "<atomic rule statement>",
      "sourceRefs": ["context:<section>"]
    }
  ],
  "rulesByEndpoint": {
    "<endpointId>": [
      {
        "id": "ER-<ENDPOINT>-001",
        "text": "<atomic rule statement>",
        "sourceRefs": ["context:<section>"]
      }
    ]
  }
}
```

`endpointId` values must match operation identifiers in `agent/input/open_api.json`.

## Instructions

1. Read `agent/input/context.md` in full.
2. Identify the section boundaries (headings, numbered items, or named blocks).
3. Extract rules that apply to all endpoints into `generalRules`.
4. Extract rules scoped to a specific endpoint or operation into `rulesByEndpoint`, keyed by the endpoint's operation ID.
5. Each rule must be atomic: one condition, constraint, or behavior per rule object.
6. Set `id` using the prefix `GR-` for general rules and `ER-<ENDPOINT_ABBREV>-` for endpoint rules, zero-padded to three digits.
7. Set `sourceRefs` to `["context:<section-name>"]` where `<section-name>` is the heading or label in `context.md` that contains the rule.
8. If `context.md` contains conflicting statements about the same rule, do not silently resolve the conflict. Surface both variants as separate rules and append `[CONFLICT]` to each `text` value.
9. Write the result to `output/rules.json`.

## Constraints

- Do not invent rules not present in `context.md`.
- Do not infer undocumented business logic.
- Do not reference `open_api.json` as a rule source — it is a contract, not a rule document.
- Do not merge multiple distinct constraints into one rule object.
- Do not omit `sourceRefs`.

## Deterministic validation

After writing `output/rules.json`, run deterministic validation exactly as shown below.

Do not search for alternative runners.
Do not reimplement gate logic.
Do not validate by manual reasoning when deterministic validation is available.

```python
import json
from src.gates import run_stage1_gates

data = json.loads(open("output/rules.json").read())
normalized = run_stage1_gates(data)
open("output/rules.json", "w").write(json.dumps(normalized, indent=2))
```

## Expected file locations

```
agent/input/context.md       ← read
output/rules.json             ← write
```

## Example invocation

```
Run the extract-rules skill.
Input: agent/input/context.md
Output: output/rules.json
```
