#!/usr/bin/env python3
import json
import sys
from pathlib import Path

REPORT_PATH = Path(".claude/reports/maintainability_review.json")


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: extract_file_issues.py <relative/path.py>")

    target_path = sys.argv[1]

    if not REPORT_PATH.exists():
        fail(f"review report not found: {REPORT_PATH}")

    try:
        data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"failed to parse review report: {exc}")

    matches = [
        file_entry
        for file_entry in data.get("files", [])
        if file_entry.get("path") == target_path
    ]

    if not matches:
        fail(f"file not found in review report: {target_path}", 2)

    if len(matches) > 1:
        fail(f"duplicate file entry in review report: {target_path}", 3)

    result = {
        "review_target": data.get("review_target", "."),
        "file": matches[0],
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()