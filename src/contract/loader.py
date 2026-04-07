"""OpenAPI contract loader.

Parses ``open_api.json`` (OpenAPI 3.x or Swagger 2.0) and exposes
per-operation metadata needed by Gate B.

Only the fields Gate B actually checks are extracted:
- method and path
- path parameter names
- query parameter names
- request body field names (top-level properties)
- response field names per status code (top-level properties)

``$ref`` resolution is limited to ``#/components/schemas/`` references
(OpenAPI 3) and ``#/definitions/`` references (Swagger 2).  Deeply nested
``$ref`` chains inside already-resolved schemas are followed recursively up
to a fixed depth to avoid infinite loops.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Set


_HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
)
_MAX_REF_DEPTH = 10


class Operation:
    """Parsed representation of a single OpenAPI operation."""

    def __init__(
        self,
        operation_id: str,
        method: str,
        path: str,
        path_param_names: Set[str],
        query_param_names: Set[str],
        request_body_fields: Optional[Set[str]],
        responses: Dict[int, Set[str]],
    ) -> None:
        self.operation_id = operation_id
        self.method = method                          # uppercase, e.g. "POST"
        self.path = path                              # e.g. "/users"
        self.path_param_names = path_param_names      # {"userId"}
        self.query_param_names = query_param_names    # {"limit", "offset"}
        # None  → operation has no request body
        # set() → body exists but schema has no documented properties
        self.request_body_fields = request_body_fields
        # dict of int status_code -> top-level response field names
        self.responses = responses


class ContractLoader:
    """Load and index an OpenAPI spec by operationId."""

    def __init__(self, spec: dict) -> None:
        self._spec = spec
        # Support both OpenAPI 3 (#/components/schemas/) and Swagger 2 (#/definitions/)
        self._schemas: dict = (
            spec.get("components", {}).get("schemas", {})
            or spec.get("definitions", {})
        )
        self._operations: Dict[str, Operation] = {}
        self._parse()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_operation(self, operation_id: str) -> Optional[Operation]:
        return self._operations.get(operation_id)

    def operation_ids(self) -> Set[str]:
        return set(self._operations.keys())

    @staticmethod
    def from_file(path: str | Path) -> ContractLoader:
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)
        return ContractLoader(spec)

    # ------------------------------------------------------------------
    # Internal parsing
    # ------------------------------------------------------------------

    def _resolve_ref(self, ref: str, depth: int = 0) -> dict:
        if depth > _MAX_REF_DEPTH:
            return {}
        # Only local JSON pointer refs are supported: #/a/b/c
        if not ref.startswith("#/"):
            return {}
        parts = ref.lstrip("#/").split("/")
        obj = self._spec
        try:
            for part in parts:
                obj = obj[part]
        except (KeyError, TypeError):
            return {}
        return obj  # type: ignore[return-value]

    def _resolve_schema(self, schema: dict, depth: int = 0) -> dict:
        if "$ref" in schema:
            return self._resolve_ref(schema["$ref"], depth + 1)
        return schema

    def _extract_top_level_fields(self, schema: dict, depth: int = 0) -> Set[str]:
        schema = self._resolve_schema(schema, depth)
        props = schema.get("properties", {})
        return set(props.keys())

    def _parse(self) -> None:
        paths = self._spec.get("paths", {})
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method not in _HTTP_METHODS:
                    continue
                if not isinstance(operation, dict):
                    continue
                op_id = operation.get("operationId")
                if not op_id:
                    continue

                path_params, query_params = self._parse_parameters(operation)
                request_body_fields = self._parse_request_body(operation)
                responses = self._parse_responses(operation)

                self._operations[op_id] = Operation(
                    operation_id=op_id,
                    method=method.upper(),
                    path=path,
                    path_param_names=path_params,
                    query_param_names=query_params,
                    request_body_fields=request_body_fields,
                    responses=responses,
                )

    def _parse_parameters(self, operation: dict):
        params = operation.get("parameters", [])
        path_params: Set[str] = set()
        query_params: Set[str] = set()
        for param in params:
            if not isinstance(param, dict):
                continue
            location = param.get("in", "")
            name = param.get("name", "")
            if not name:
                continue
            if location == "path":
                path_params.add(name)
            elif location == "query":
                query_params.add(name)
        return path_params, query_params

    def _parse_request_body(self, operation: dict) -> Optional[Set[str]]:
        rb = operation.get("requestBody")
        if rb is None:
            return None
        content = rb.get("content", {})
        json_content = content.get("application/json", {})
        schema = json_content.get("schema")
        if not schema:
            return set()
        return self._extract_top_level_fields(schema)

    def _parse_responses(self, operation: dict) -> Dict[int, Set[str]]:
        responses: Dict[int, Set[str]] = {}
        for status_str, resp_obj in operation.get("responses", {}).items():
            try:
                status_code = int(status_str)
            except (ValueError, TypeError):
                continue
            if not isinstance(resp_obj, dict):
                responses[status_code] = set()
                continue
            content = resp_obj.get("content", {})
            json_content = content.get("application/json", {})
            schema = json_content.get("schema")
            if schema:
                responses[status_code] = self._extract_top_level_fields(schema)
            else:
                responses[status_code] = set()
        return responses
