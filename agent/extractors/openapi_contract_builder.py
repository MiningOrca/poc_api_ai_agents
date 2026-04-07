from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


class OpenApiContractBuilder:
    """
    Deterministically builds a minimal contract.json from an OpenAPI 3.x JSON spec.

    Keeps only:
    - method/path
    - path/query params
    - request schema
    - response schemas
    - supported status codes
    - required fields

    Notes:
    - Only local refs '#/...' are supported.
    - Output is intentionally minimal and stable for downstream pipeline use.
    """

    HTTP_METHOD_ORDER = {
        "get": 0,
        "post": 1,
        "put": 2,
        "patch": 3,
        "delete": 4,
        "options": 5,
        "head": 6,
        "trace": 7,
    }

    SIMPLE_SCHEMA_KEYS = (
        "type",
        "format",
        "enum",
        "const",
        "nullable",
        "default",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    )

    def __init__(self, input_path: str | Path, output_path: str | Path):
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.spec: dict[str, Any] = {}

    def build(self) -> dict[str, Any]:
        self.spec = self._load_json(self.input_path)

        if not isinstance(self.spec, dict):
            raise ValueError("OpenAPI root must be a JSON object.")
        if "paths" not in self.spec or not isinstance(self.spec["paths"], dict):
            raise ValueError("OpenAPI spec must contain a 'paths' object.")

        endpoints: list[dict[str, Any]] = []

        for path in sorted(self.spec["paths"].keys()):
            path_item = self.spec["paths"][path]
            if not isinstance(path_item, dict):
                continue

            common_parameters = path_item.get("parameters", [])

            for method in self._sorted_http_methods(path_item.keys()):
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue

                endpoints.append(
                    self._build_endpoint(
                        path=path,
                        method=method,
                        common_parameters=common_parameters,
                        operation=operation,
                    )
                )

        return {
            "meta": {
                "source_file": str(self.input_path),
                "openapi_version": self.spec.get("openapi"),
                "title": self.spec.get("info", {}).get("title"),
                "version": self.spec.get("info", {}).get("version"),
                "builder": "OpenApiContractBuilder",
                "format": "contract.json",
            },
            "endpoints": endpoints,
        }

    def save(self, contract: dict[str, Any] | None = None) -> Path:
        if contract is None:
            contract = self.build()

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=False),
            encoding="utf-8",
        )
        return self.output_path

    def build_and_save(self) -> Path:
        contract = self.build()
        return self.save(contract)

    def _build_endpoint(
        self,
        path: str,
        method: str,
        common_parameters: list[Any],
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        merged_parameters = self._merge_parameters(
            common_parameters,
            operation.get("parameters", []),
        )

        path_params: list[dict[str, Any]] = []
        query_params: list[dict[str, Any]] = []

        for parameter in merged_parameters:
            normalized = self._normalize_parameter(parameter)

            location = parameter.get("in")
            if location == "path":
                path_params.append(normalized)
            elif location == "query":
                query_params.append(normalized)

        responses = self._extract_responses(operation.get("responses", {}))

        return {
            "method": method.upper(),
            "path": path,
            "pathParams": path_params,
            "queryParams": query_params,
            "requestBody": self._extract_request_body(operation.get("requestBody")),
            "responses": responses,
            "supportedStatusCodes": self._sort_status_codes(responses.keys()),
        }

    def _merge_parameters(
        self,
        path_level_parameters: list[Any],
        operation_level_parameters: list[Any],
    ) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str], dict[str, Any]] = {}

        for raw_param in list(path_level_parameters or []) + list(operation_level_parameters or []):
            param = self._expand_ref_object(raw_param)
            if not isinstance(param, dict):
                continue

            name = param.get("name")
            location = param.get("in")
            if not name or not location:
                continue

            merged[(str(name), str(location))] = param

        return [
            merged[key]
            for key in sorted(merged.keys(), key=lambda item: (item[1], item[0]))
        ]

    def _normalize_parameter(self, parameter: dict[str, Any]) -> dict[str, Any]:
        schema = self._extract_parameter_schema(parameter)
        return {
            "name": parameter["name"],
            "required": bool(parameter.get("required", False) or parameter.get("in") == "path"),
            "schema": schema,
            "requiredFields": self._collect_required_paths(schema),
        }

    def _extract_parameter_schema(self, parameter: dict[str, Any]) -> dict[str, Any]:
        if "schema" in parameter:
            return self._normalize_schema(parameter["schema"])

        content = parameter.get("content")
        if isinstance(content, dict) and content:
            first_media_type = sorted(content.keys())[0]
            media_entry = content[first_media_type] or {}
            return self._normalize_schema(media_entry.get("schema", {}))

        return {}

    def _extract_request_body(self, request_body: Any) -> dict[str, Any] | None:
        if not request_body:
            return None

        body = self._expand_ref_object(request_body)
        if not isinstance(body, dict):
            return None

        content = body.get("content", {})
        normalized_content: dict[str, Any] = {}

        if isinstance(content, dict):
            for media_type in sorted(content.keys()):
                media_entry = content[media_type] or {}
                schema = self._normalize_schema(media_entry.get("schema", {}))
                normalized_content[media_type] = {
                    "schema": schema,
                    "requiredFields": self._collect_required_paths(schema),
                }

        return {
            "required": bool(body.get("required", False)),
            "content": normalized_content,
        }

    def _extract_responses(self, responses: Any) -> dict[str, Any]:
        if not isinstance(responses, dict):
            return {}

        result: dict[str, Any] = {}

        for status_code in self._sort_status_codes(responses.keys()):
            raw_response = responses[status_code]
            response = self._expand_ref_object(raw_response)

            if not isinstance(response, dict):
                result[str(status_code)] = {"content": {}}
                continue

            content = response.get("content", {})
            normalized_content: dict[str, Any] = {}

            if isinstance(content, dict):
                for media_type in sorted(content.keys()):
                    media_entry = content[media_type] or {}
                    schema = self._normalize_schema(media_entry.get("schema", {}))
                    normalized_content[media_type] = {
                        "schema": schema,
                        "requiredFields": self._collect_required_paths(schema),
                    }

            result[str(status_code)] = {
                "content": normalized_content,
            }

        return result

    def _normalize_schema(self, schema: Any) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return {}

        schema = self._expand_ref_object(schema)

        result: dict[str, Any] = {}

        for key in self.SIMPLE_SCHEMA_KEYS:
            if key in schema:
                result[key] = copy.deepcopy(schema[key])

        if "required" in schema and isinstance(schema["required"], list):
            result["required"] = sorted({str(x) for x in schema["required"]})

        if "properties" in schema and isinstance(schema["properties"], dict):
            result["type"] = result.get("type", "object")
            result["properties"] = {
                prop_name: self._normalize_schema(prop_schema)
                for prop_name, prop_schema in sorted(schema["properties"].items(), key=lambda item: item[0])
            }

        if "items" in schema:
            result["items"] = self._normalize_schema(schema["items"])

        if "additionalProperties" in schema:
            additional = schema["additionalProperties"]
            if isinstance(additional, dict):
                result["additionalProperties"] = self._normalize_schema(additional)
            else:
                result["additionalProperties"] = bool(additional)

        for combiner in ("allOf", "oneOf", "anyOf"):
            if combiner in schema and isinstance(schema[combiner], list):
                result[combiner] = [self._normalize_schema(item) for item in schema[combiner]]

        if "not" in schema and isinstance(schema["not"], dict):
            result["not"] = self._normalize_schema(schema["not"])

        return result

    def _collect_required_paths(self, schema: dict[str, Any], prefix: str = "") -> list[str]:
        paths: set[str] = set()

        if not isinstance(schema, dict):
            return []

        properties = schema.get("properties", {})
        required_fields = schema.get("required", [])

        if isinstance(properties, dict) and isinstance(required_fields, list):
            for field_name in required_fields:
                field_name = str(field_name)
                current = f"{prefix}.{field_name}" if prefix else field_name
                paths.add(current)

                child_schema = properties.get(field_name)
                if isinstance(child_schema, dict):
                    paths.update(self._collect_required_paths(child_schema, current))

        if isinstance(schema.get("allOf"), list):
            for part in schema["allOf"]:
                if isinstance(part, dict):
                    paths.update(self._collect_required_paths(part, prefix))

        if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
            item_prefix = f"{prefix}[]" if prefix else "[]"
            paths.update(self._collect_required_paths(schema["items"], item_prefix))

        return sorted(paths)

    def _expand_ref_object(self, obj: Any, ref_stack: tuple[str, ...] = ()) -> Any:
        if not isinstance(obj, dict):
            return obj

        if "$ref" not in obj:
            return copy.deepcopy(obj)

        ref = obj["$ref"]
        if not isinstance(ref, str):
            raise ValueError(f"Invalid $ref value: {ref!r}")

        if ref in ref_stack:
            return {
                "$ref": ref,
                "circular": True,
            }

        target = self._resolve_ref(ref)
        expanded_target = self._expand_ref_object(target, ref_stack + (ref,))
        siblings = {k: v for k, v in obj.items() if k != "$ref"}

        if siblings:
            return self._deep_merge(expanded_target, siblings)

        return expanded_target

    def _resolve_ref(self, ref: str) -> Any:
        if not ref.startswith("#/"):
            raise ValueError(f"Only local refs are supported, got: {ref}")

        node: Any = self.spec
        for token in ref[2:].split("/"):
            if not isinstance(node, dict) or token not in node:
                raise KeyError(f"Cannot resolve ref: {ref}")
            node = node[token]

        return copy.deepcopy(node)

    def _deep_merge(self, base: Any, override: Any) -> Any:
        if isinstance(base, dict) and isinstance(override, dict):
            result = copy.deepcopy(base)
            for key, value in override.items():
                if key in result:
                    result[key] = self._deep_merge(result[key], value)
                else:
                    result[key] = copy.deepcopy(value)
            return result

        return copy.deepcopy(override)

    def _sorted_http_methods(self, keys: Any) -> list[str]:
        methods = [str(key).lower() for key in keys if str(key).lower() in self.HTTP_METHOD_ORDER]
        return sorted(methods, key=lambda method: self.HTTP_METHOD_ORDER[method])

    def _sort_status_codes(self, codes: Any) -> list[str]:
        def sort_key(code: Any) -> tuple[int, int | str]:
            s = str(code)
            if s.isdigit():
                return (0, int(s))
            return (1, s)

        return [str(code) for code in sorted(codes, key=sort_key)]

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
