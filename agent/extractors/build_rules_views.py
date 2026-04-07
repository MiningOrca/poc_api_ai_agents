from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


class RulesViewsBuilder:
    """
    Deterministically builds rules_views.json from spec_sections.json.

    Output structure:
    - meta
    - general_rules_view
    - endpoint_rules_views

    Notes:
    - general rules are stored once at top level
    - endpoint views contain only endpoint-specific data
    - prompt rendering is intentionally NOT part of this class
    """

    def __init__(self, input_path: str | Path, output_path: str | Path):
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)

    def build(self) -> dict[str, Any]:
        spec = self._load_json(self.input_path)
        endpoints = spec.get("endpoints", [])

        if not isinstance(endpoints, list):
            raise ValueError("'endpoints' must be a list in spec_sections.json")

        return {
            "meta": {
                "source_file": str(self.input_path),
                "generator": "RulesViewsBuilder",
                "version": "1.0.0",
                "format": "rules_views",
            },
            "general_rules_view": self._build_general_rules_view(spec),
            "endpoint_rules_views": [
                self._build_endpoint_rules_view(endpoint)
                for endpoint in endpoints
                if isinstance(endpoint, dict)
            ],
        }

    def save(self, data: dict[str, Any] | None = None) -> Path:
        if data is None:
            data = self.build()

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.output_path

    def build_and_save(self) -> Path:
        data = self.build()
        return self.save(data)

    def _build_general_rules_view(self, spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "section": "3.1",
            "title": "General rules",
            "items": self._parse_general_rules(spec),
        }

    def _build_endpoint_rules_view(self, endpoint: dict[str, Any]) -> dict[str, Any]:
        return {
            "endpoint_id": self._normalize_inline_text(str(endpoint.get("endpoint_id", ""))),
            "section_number": self._normalize_inline_text(str(endpoint.get("section_number", ""))),
            "title": self._normalize_inline_text(str(endpoint.get("title", ""))),
            "method": self._normalize_inline_text(str(endpoint.get("method", ""))).upper(),
            "path": self._normalize_inline_text(str(endpoint.get("path", ""))),
            "parameters": self._parse_parameters(endpoint),
            "endpoint_rules": self._parse_endpoint_rules(endpoint),
            "error_responses": self._parse_error_responses(endpoint),
            "success_status_code": endpoint.get("success_status_code"),
        }

    def _parse_general_rules(self, spec: dict[str, Any]) -> list[str]:
        rules = spec.get("general_rules")
        if isinstance(rules, list) and rules:
            return [
                self._normalize_inline_text(str(item))
                for item in rules
                if str(item).strip()
            ]

        return self._clean_block_lines(spec.get("general_rules_block"))

    def _parse_parameters(self, endpoint: dict[str, Any]) -> list[dict[str, str]]:
        parameters = endpoint.get("parameters")
        if isinstance(parameters, list) and parameters:
            return self._parse_parameters_from_list(parameters)
        return self._parse_parameters_from_block(endpoint.get("parameters_block"))

    def _parse_parameters_from_list(self, parameters: list) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for item in parameters:
            if isinstance(item, dict):
                name = self._normalize_inline_text(str(item.get("name", "")))
                description = self._normalize_inline_text(str(item.get("description", "")))
                if name:
                    result.append({
                        "name": name,
                        "description": description,
                    })
            else:
                text = self._normalize_inline_text(str(item))
                if text:
                    result.append({
                        "name": text,
                        "description": "",
                    })
        return result

    def _parse_parameters_from_block(self, block: str | None) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for line in self._clean_block_lines(block):
            if "—" in line:
                name, description = line.split("—", 1)
            elif ":" in line:
                name, description = line.split(":", 1)
            else:
                name, description = line, ""

            result.append({
                "name": self._normalize_inline_text(name),
                "description": self._normalize_inline_text(description),
            })
        return result

    def _parse_endpoint_rules(self, endpoint: dict[str, Any]) -> list[str]:
        rules = endpoint.get("rules")
        if isinstance(rules, list) and rules:
            return [
                self._normalize_inline_text(str(item))
                for item in rules
                if str(item).strip()
            ]

        return self._clean_block_lines(endpoint.get("rules_block"))

    def _parse_error_responses(self, endpoint: dict[str, Any]) -> list[dict[str, Any]]:
        error_responses = endpoint.get("error_responses")
        if isinstance(error_responses, list) and error_responses:
            return self._parse_error_responses_from_list(error_responses)
        return self._parse_error_responses_from_block(endpoint.get("error_responses_block"))

    def _parse_error_responses_from_list(self, error_responses: list) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in error_responses:
            if isinstance(item, dict):
                status_code = item.get("status_code")
                description = self._normalize_inline_text(str(item.get("description", "")))
                if status_code is not None:
                    result.append({
                        "status_code": int(status_code),
                        "description": description,
                    })
            else:
                parsed = self._parse_error_line(str(item))
                if parsed:
                    result.append(parsed)
        return result

    def _parse_error_responses_from_block(self, block: str | None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for line in self._clean_block_lines(block):
            parsed = self._parse_error_line(line)
            if parsed:
                result.append(parsed)
        return result

    def _parse_error_line(self, line: str) -> dict[str, Any] | None:
        line = self._normalize_inline_text(line)

        match = re.match(r"^`?(\d{3})`?\s*[—\-:]\s*(.+)$", line)
        if match:
            return {
                "status_code": int(match.group(1)),
                "description": self._normalize_inline_text(match.group(2)),
            }

        match = re.match(r"^(\d{3})\s+(.+)$", line)
        if match:
            return {
                "status_code": int(match.group(1)),
                "description": self._normalize_inline_text(match.group(2)),
            }

        return None

    def _clean_block_lines(self, block: Any) -> list[str]:
        if not block:
            return []

        text = str(block).replace("\r\n", "\n").replace("\r", "\n")
        result: list[str] = []

        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
            line = re.sub(r"^[-*]\s+", "", line).strip()
            line = self._normalize_inline_text(line)

            if line:
                result.append(line)

        return result

    def _normalize_inline_text(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("Root JSON must be an object.")

        return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build rules_views.json from spec_sections.json"
    )
    parser.add_argument(
        "--input",
        default="../input/spec_sections.json",
        help="Path to spec_sections.json",
    )
    parser.add_argument(
        "--output",
        default="../input/rules_views.json",
        help="Path to output rules_views.json",
    )

    args = parser.parse_args()

    builder = RulesViewsBuilder(
        input_path=args.input,
        output_path=args.output,
    )

    output_path = builder.build_and_save()
    print(f"rules_views written to: {output_path}")
