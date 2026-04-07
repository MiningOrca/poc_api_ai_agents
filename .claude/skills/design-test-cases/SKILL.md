# design-test-cases

## Purpose

Read `output/rules.json` and `agent/input/open_api.json` and produce `output/test_cases.json`. This stage decides what to test and why — it does not produce HTTP payloads, request bodies, or transport-level assertions.

## When to use

Invoke this skill at Stage 2, after `output/rules.json` has passed Gate A and Gate E. Re-invoke whenever `rules.json` or `open_api.json` changes.

## Required inputs

| File | Role |
|---|---|
| `output/rules.json` | Extracted rules from Stage 1 |
| `agent/input/open_api.json` | Authoritative contract for all endpoints |

## Produced output

| File | Role |
|---|---|
| `output/test_cases_{endpointId}.json` | Abstract test cases for one endpoint (one file per endpoint) |

## Schema

```json
{
  "endpointId": "<operationId from open_api.json>",
  "cases": [
    {
      "title": "<concise description of intent>",
      "summary": "<one-sentence explanation>",
      "category": "positive | negative | boundary",
      "expectedStatusCode": 200,
      "expectedOutcome": "<human-readable outcome>",
      "sourceRefs": ["<ruleId>"],
      "steps": [
        {
          "endpointId": "<operationId>",
          "summary": "<what this step does>"
        }
      ]
    }
  ]
}
```

## Instructions

1. Read `output/rules.json` and `agent/input/open_api.json`.
2. For each `endpointId` that appears in `rulesByEndpoint`, design test cases that exercise the rules for that endpoint.
3. Also apply `generalRules` to every endpoint where they are relevant.
4. For each test case:
   a. Set `category` to `positive`, `negative`, or `boundary` based on what the case tests.
   b. Set `expectedStatusCode` to the status code documented in `open_api.json` for the expected outcome.
   c. Set `sourceRefs` to the rule IDs from `rules.json` that justify the case. Every case must cite at least one rule.
   d. Set `steps` to the minimal ordered list of endpoint calls needed to execute the case. Single-step cases have one entry. Chained cases list setup steps first, then the target step last.
   e. Step `endpointId` values must be operation IDs present in `open_api.json`.
5. Do not produce request bodies, query parameters, path parameters, headers, or assertion expressions in this artifact.
6. For each endpoint, write one file `output/test_cases_{endpointId}.json` containing a single top-level object `{endpointId, cases: [...]}`. Do not merge multiple endpoints into one file.

## Constraints

- Do not invent endpoints, HTTP methods, paths, or status codes not present in `open_api.json`.
- Do not invent rules not present in `rules.json`.
- Do not produce transport-level details (payloads, headers, assertions). Those belong in Stage 3.
- Do not omit `sourceRefs`. A test case without a rule citation is invalid.
- Do not merge unrelated rules into a single test case.

## Deterministic validation

After writing all per-endpoint files, run deterministic validation for each file exactly as shown below.

Do not search for alternative runners.
Do not reimplement gate logic.
Do not use a different contract loader.

```python
import glob, json
from src.gates import run_stage2_gates
from src.contract.loader import ContractLoader

contract = ContractLoader.from_file("agent/input/open_api.json")
for path in sorted(glob.glob("output/test_cases_*.json")):
    data = json.loads(open(path).read())
    normalized = run_stage2_gates(data, contract)
    open(path, "w").write(json.dumps(normalized, indent=2))
```

## Expected file locations

```
output/rules.json                          ← read
agent/input/open_api.json                  ← read
output/test_cases_{endpointId}.json        ← write (one file per endpoint)
```

## Example invocation

```
Run the design-test-cases skill.
Inputs: output/rules.json, agent/input/open_api.json
Output: output/test_cases_{endpointId}.json per endpoint
```
