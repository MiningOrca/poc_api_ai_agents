from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class SpecSectionsBuilder:

    def build(self, input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
        input_path = Path(input_path)
        output_path = Path(output_path)

        text = input_path.read_text(encoding="utf-8")
        text = self._normalize_text(text)
        lines = text.splitlines()

        context_lines = self._extract_context_lines(lines)

        general_rules_lines = self._extract_block_between(
            context_lines,
            start_pred=self._is_general_rules_heading,
            end_pred=self._is_api_endpoints_heading,
        )

        api_endpoints_lines = self._extract_block_between(
            context_lines,
            start_pred=self._is_api_endpoints_heading,
            end_pred=self._is_sample_data_heading_or_next_major_section,
        )

        sample_data_lines = self._extract_block_between(
            context_lines,
            start_pred=self._is_sample_data_heading,
            end_pred=self._is_next_major_section_after_context,
        )

        endpoints = self._parse_endpoints(api_endpoints_lines)

        result = {
            "meta": {
                "source_file": str(input_path),
                "parser_version": "1.0.0",
                "format": "spec_sections",
            },
            "general_rules_block": self._join_lines(general_rules_lines),
            "general_rules": self._parse_bullets(general_rules_lines),
            "sample_data_block": self._join_lines(sample_data_lines),
            "sample_data": self._parse_sample_data(sample_data_lines),
            "endpoints": endpoints,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return result

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\ufeff", "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.strip() + "\n"

    def _join_lines(self, lines: list[str]) -> str:
        return "\n".join(lines).strip()

    def _strip_outer_bold(self, line: str) -> str:
        s = line.strip()
        if s.startswith("**") and s.endswith("**") and len(s) >= 4:
            s = s[2:-2].strip()
        return s

    def _extract_context_lines(self, lines: list[str]) -> list[str]:

        start_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip().lower()
            # todo
            if (
                "3. context:" in stripped
                or "# 3. context:" in stripped
                or "## 3. context:" in stripped
                or "**3. context:" in stripped
            ):
                start_idx = i
                break

        if start_idx is None:
            return lines

        end_idx = len(lines)
        for i in range(start_idx + 1, len(lines)):
            stripped = lines[i].strip().lower()
            if stripped.startswith("**4. ") or stripped.startswith("# 4. ") or stripped.startswith("## 4. ") or stripped.startswith("### 4. "):
                end_idx = i
                break

        return lines[start_idx:end_idx]

    def _extract_block_between(
        self,
        lines: list[str],
        start_pred,
        end_pred,
    ) -> list[str]:
        start_idx = None
        for i, line in enumerate(lines):
            if start_pred(line):
                start_idx = i + 1
                break

        if start_idx is None:
            return []

        end_idx = len(lines)
        for i in range(start_idx, len(lines)):
            if end_pred(lines[i]):
                end_idx = i
                break

        return lines[start_idx:end_idx]

    def _is_general_rules_heading(self, line: str) -> bool:
        s = line.strip().lower()
        return s == "## 3.1. general rules" or s == "### 3.1. general rules"

    def _is_api_endpoints_heading(self, line: str) -> bool:
        s = line.strip().lower()
        return s == "## 3.2. api endpoints" or s == "### 3.2. api endpoints"

    def _is_sample_data_heading(self, line: str) -> bool:
        s = line.strip().lower()
        return s == "## 3.3. sample initial data" or s == "### 3.3. sample initial data"

    def _is_sample_data_heading_or_next_major_section(self, line: str) -> bool:
        s = line.strip().lower()
        return self._is_sample_data_heading(line) or s.startswith("**4. ") or s.startswith("# 4. ") or s.startswith("## 4. ") or s.startswith("### 4. ")

    def _is_next_major_section_after_context(self, line: str) -> bool:
        s = line.strip().lower()
        return s.startswith("**4. ") or s.startswith("# 4. ") or s.startswith("## 4. ") or s.startswith("### 4. ")


    def _is_endpoint_heading(self, line: str) -> bool:
        s = line.strip()
        return s.startswith("### 3.2.") or s.startswith("#### 3.2.")

    def _parse_endpoint_heading(self, line: str) -> tuple[str, str]:

        s = line.strip()
        s = s.lstrip("#").strip()

        parts = s.split(".", 3)
        if len(parts) >= 4:
            section_number = f"{parts[0]}.{parts[1]}.{parts[2]}"
            title = parts[3].strip()
            if title.startswith("."):
                title = title[1:].strip()
            return section_number, title

        return "", s

    def _parse_endpoints(self, lines: list[str]) -> list[dict[str, Any]]:
        chunks: list[list[str]] = []
        current: list[str] = []

        for line in lines:
            if self._is_endpoint_heading(line):
                if current:
                    chunks.append(current)
                current = [line]
            else:
                if current:
                    current.append(line)

        if current:
            chunks.append(current)

        return [self._parse_endpoint_chunk(chunk) for chunk in chunks]

    def _route_lines_into_sections(
        self, lines: list[str]
    ) -> tuple[dict[str, list[str]], int | None]:
        section_buffers: dict[str, list[str]] = {
            "request_example": [],
            "rules": [],
            "parameters": [],
            "response_example": [],
            "error_responses": [],
        }

        current_section: str | None = None
        success_status_code: int | None = None

        for line in lines:
            stripped = line.strip()

            if self._is_request_example_label(stripped):
                current_section = "request_example"
                continue

            if self._is_rules_label(stripped):
                current_section = "rules"
                continue

            if self._is_parameters_label(stripped):
                current_section = "parameters"
                continue

            if self._is_success_response_label(stripped):
                current_section = "response_example"
                success_status_code = self._extract_status_code(stripped)
                continue

            if self._is_error_responses_label(stripped):
                current_section = "error_responses"
                continue

            possible_method, possible_path = self._try_parse_method_and_path_from_line(stripped)
            if possible_method and possible_path:
                continue

            if current_section is not None:
                section_buffers[current_section].append(line)

        return section_buffers, success_status_code

    def _parse_endpoint_chunk(self, lines: list[str]) -> dict[str, Any]:
        raw_block = self._join_lines(lines)
        section_number, title = self._parse_endpoint_heading(lines[0])
        method, path = self._extract_method_and_path(lines)
        section_buffers, success_status_code = self._route_lines_into_sections(lines[1:])
        request_example_block = self._join_lines(section_buffers["request_example"])
        rules_block = self._join_lines(section_buffers["rules"])
        parameters_block = self._join_lines(section_buffers["parameters"])
        response_example_block = self._join_lines(section_buffers["response_example"])
        error_responses_block = self._join_lines(section_buffers["error_responses"])
        endpoint = {
            "endpoint_id": self._slugify(title),
            "section_number": section_number,
            "title": title,
            "method": method,
            "path": path,
            "raw_block": raw_block,
            "rules_block": rules_block,
            "rules": self._parse_bullets(section_buffers["rules"]),
            "parameters_block": parameters_block,
            "parameters": self._parse_named_bullets(section_buffers["parameters"]),
            "error_responses_block": error_responses_block,
            "error_responses": self._parse_error_responses(section_buffers["error_responses"]),
            "request_example_block": request_example_block,
            "request_example": self._parse_json_from_block(request_example_block),
            "response_example_block": response_example_block,
            "response_example": self._parse_json_from_block(response_example_block),
            "success_status_code": success_status_code,
        }
        endpoint["views"] = {
            "rules_only_view": self._build_rules_only_view(endpoint),
            "contract_view": self._build_contract_view(endpoint),
            "example_view": self._build_example_view(endpoint),
        }
        return endpoint

    def _extract_method_and_path(self, lines: list[str]) -> tuple[str | None, str | None]:
        for line in lines:
            method, path = self._try_parse_method_and_path_from_line(line.strip())
            if method and path:
                return method, path
        return None, None

    def _try_parse_method_and_path_from_line(self, line: str) -> tuple[str | None, str | None]:
        s = line.strip()

        m = re.match(r"^\*\*(GET|POST|PUT|PATCH|DELETE)\*\*\s*`([^`]+)`\s*$", s)
        if m:
            return m.group(1), m.group(2)

        m = re.match(r"^\*\*(GET|POST|PUT|PATCH|DELETE)\s+(.+?)\*\*$", s)
        if m:
            return m.group(1), m.group(2).strip().strip("`")

        return None, None

    def _is_request_example_label(self, line: str) -> bool:
        s = self._strip_outer_bold(line).lower()
        return s == "request example:" or s == "request (example):"

    def _is_rules_label(self, line: str) -> bool:
        s = self._strip_outer_bold(line).lower()
        return s == "rules:"

    def _is_parameters_label(self, line: str) -> bool:
        s = self._strip_outer_bold(line).lower()
        return s == "parameters:"

    def _is_success_response_label(self, line: str) -> bool:
        s = self._strip_outer_bold(line).lower()
        return s.startswith("successful response (")

    def _is_error_responses_label(self, line: str) -> bool:
        s = self._strip_outer_bold(line).lower()
        return s == "error responses:" or s == "error responses (examples):"

    def _extract_status_code(self, line: str) -> int | None:
        m = re.search(r"\((\d{3})\)", line)
        if not m:
            return None
        return int(m.group(1))

    def _parse_bullets(self, lines: list[str]) -> list[str]:
        items: list[str] = []
        current: list[str] = []

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("- "):
                if current:
                    items.append(" ".join(current).strip())
                current = [stripped[2:].strip()]
            elif stripped:
                if current:
                    current.append(stripped)

        if current:
            items.append(" ".join(current).strip())

        return items

    def _parse_named_bullets(self, lines: list[str]) -> list[dict[str, str]]:
        bullets = self._parse_bullets(lines)
        result = []

        for bullet in bullets:
            m = re.match(r"^`?([^`]+?)`?\s*[—-]\s*(.+)$", bullet)
            if m:
                result.append(
                    {
                        "name": m.group(1).strip(),
                        "description": m.group(2).strip(),
                    }
                )
            else:
                result.append(
                    {
                        "name": "",
                        "description": bullet,
                    }
                )

        return result

    def _parse_error_responses(self, lines: list[str]) -> list[dict[str, Any]]:
        bullets = self._parse_bullets(lines)
        result = []

        for bullet in bullets:
            m = re.match(r"^`?(\d{3})`?\s*[—-]\s*(.+)$", bullet)
            if m:
                result.append(
                    {
                        "status_code": int(m.group(1)),
                        "description": m.group(2).strip(),
                    }
                )
            else:
                result.append(
                    {
                        "status_code": None,
                        "description": bullet,
                    }
                )

        return result

    def _parse_json_from_block(self, block: str) -> Any:
        if not block.strip():
            return None

        if "```" in block:
            inside = []
            in_fence = False

            for line in block.splitlines():
                stripped = line.strip()
                if stripped.startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    inside.append(line)

            candidate = "\n".join(inside).strip()
            if candidate:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass

        candidate = block.strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None


    def _parse_sample_data(self, lines: list[str]) -> list[dict[str, Any]]:
        bullets = self._parse_bullets(lines)
        result = []

        for bullet in bullets:
            m = re.match(
                r"^`([^`]+)`:\s*([^,]+),\s*balance\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Z]+)$",
                bullet
            )
            if m:
                result.append(
                    {
                        "userId": m.group(1),
                        "name": m.group(2).strip(),
                        "balance": float(m.group(3)),
                        "currency": m.group(4),
                    }
                )
            else:
                result.append({"raw": bullet})

        return result

    def _build_endpoint_header_lines(self, endpoint: dict[str, Any]) -> list[str]:
        method = endpoint.get("method") or ""
        path = endpoint.get("path") or ""
        title = endpoint.get("title") or ""
        parts: list[str] = []
        parts.append(f"Endpoint: {method} {path}".strip())
        parts.append(f"Title: {title}")
        if endpoint.get("parameters"):
            parts.append("")
            parts.append("Parameters:")
            for p in endpoint["parameters"]:
                if p["name"]:
                    parts.append(f"- {p['name']}: {p['description']}")
                else:
                    parts.append(f"- {p['description']}")
        return parts

    def _build_error_response_lines(self, endpoint: dict[str, Any]) -> list[str]:
        parts: list[str] = []
        if endpoint.get("error_responses"):
            parts.append("")
            parts.append("Error responses:")
            for err in endpoint["error_responses"]:
                code = err.get("status_code")
                desc = err.get("description", "")
                if code is not None:
                    parts.append(f"- {code}: {desc}")
                else:
                    parts.append(f"- {desc}")
        return parts

    def _build_rules_only_view(self, endpoint: dict[str, Any]) -> str:
        parts = self._build_endpoint_header_lines(endpoint)

        if endpoint.get("rules"):
            parts.append("")
            parts.append("Rules:")
            for rule in endpoint["rules"]:
                parts.append(f"- {rule}")

        parts.extend(self._build_error_response_lines(endpoint))
        return "\n".join(parts).strip()

    def _build_contract_view(self, endpoint: dict[str, Any]) -> str:
        parts = self._build_endpoint_header_lines(endpoint)

        if endpoint.get("success_status_code") is not None:
            parts.insert(2, f"Success status code: {endpoint['success_status_code']}")

        if endpoint.get("request_example") is not None:
            parts.append("")
            parts.append("Request example JSON:")
            parts.append(json.dumps(endpoint["request_example"], ensure_ascii=False, indent=2))

        if endpoint.get("response_example") is not None:
            parts.append("")
            parts.append("Response example JSON:")
            parts.append(json.dumps(endpoint["response_example"], ensure_ascii=False, indent=2))

        parts.extend(self._build_error_response_lines(endpoint))
        return "\n".join(parts).strip()

    def _build_example_view(self, endpoint: dict[str, Any]) -> str:
        parts = self._build_endpoint_header_lines(endpoint)

        if endpoint.get("request_example_block"):
            parts.append("")
            parts.append("Request example:")
            parts.append(endpoint["request_example_block"])

        if endpoint.get("response_example_block"):
            parts.append("")
            parts.append("Successful response example:")
            parts.append(endpoint["response_example_block"])

        return "\n".join(parts).strip()

    def _slugify(self, text: str) -> str:
        text = text.lower()
        text = text.replace("&", "and")
        text = re.sub(r"[^a-z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text)
        return text.strip("_")


def main() -> None:
    builder = SpecSectionsBuilder()

    input_path = "../input/context.md"
    output_path = "../input/spec_sections.json"

    result = builder.build(input_path=input_path, output_path=output_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
