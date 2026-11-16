"""Build GraphQL operations from an introspection document.

The files under ``specs/`` are introspection results saved as ``.yaml``. They
name every root field and the shape of its input, and they do not name a host
or an HTTP auth scheme. Two fields are queries in the schema and writes in
practice: ``orderIdCard`` and ``saveConsent``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, create_model

from pbm_mcp.graphql_loader import WRITE_QUERY_FIELDS, GraphQLOperation

_SCALARS: dict[str, Any] = {
    "String": str,
    "ID": str,
    "Int": int,
    "Float": float,
    "Boolean": bool,
}

_SELECTION_DEPTH = 2


def find_introspection(domain_dir: Path) -> Path | None:
    """Return the single introspection document in a domain directory."""
    if not domain_dir.is_dir():
        return None
    matches = [
        path
        for path in sorted(domain_dir.iterdir())
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".json"} and _is_introspection(path)
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"{domain_dir} has more than one introspection document.")
    return matches[0]


def operations_from_introspection(text: str) -> list[GraphQLOperation]:
    schema = _load_schema(text)
    types = {item["name"]: item for item in schema.get("types") or [] if item.get("name")}
    models: dict[str, type[BaseModel]] = {}
    operations: list[GraphQLOperation] = []
    for kind, field in _root_fields(schema, types):
        operations.append(_operation(kind, field, types, models))
    return operations


def _is_introspection(path: Path) -> bool:
    try:
        loaded = _load_jsonish(path.read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(loaded, dict):
        return False
    schema = loaded.get("data", {}).get("__schema") if isinstance(loaded.get("data"), dict) else None
    return isinstance(schema, dict) and "queryType" in schema


def _load_schema(text: str) -> dict[str, Any]:
    loaded = _load_jsonish(text)
    if not isinstance(loaded, dict):
        raise ValueError("Introspection document must be a JSON object.")
    data = loaded.get("data")
    schema = data.get("__schema") if isinstance(data, dict) else None
    if not isinstance(schema, dict):
        raise ValueError("Introspection document has no __schema.")
    return schema


def _load_jsonish(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import yaml

        loaded = yaml.safe_load(text)
        if loaded is None:
            raise ValueError("Empty spec file.")
        return loaded


def _root_fields(schema: dict[str, Any], types: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for kind, key in (("query", "queryType"), ("mutation", "mutationType")):
        root = schema.get(key) or {}
        name = root.get("name") if isinstance(root, dict) else None
        if not name or name not in types:
            continue
        for field in types[name].get("fields") or []:
            if field.get("isDeprecated"):
                continue
            found.append((kind, field))
    return found


def _operation(
    kind: str,
    field: dict[str, Any],
    types: dict[str, Any],
    models: dict[str, type[BaseModel]],
) -> GraphQLOperation:
    name = field["name"]
    variables: list[tuple[str, Any, bool]] = []
    var_decls: list[str] = []
    call_args: list[str] = []
    for arg in field.get("args") or []:
        arg_name = arg["name"]
        python_type, required = _python_type(arg.get("type") or {}, types, models, ())
        variables.append((arg_name, python_type, required))
        var_decls.append(f"${arg_name}: {_graphql_type(arg.get('type') or {})}")
        call_args.append(f"{arg_name}: ${arg_name}")
    selection = _selection(_named_type(field.get("type") or {}), types, _SELECTION_DEPTH, frozenset())
    decl = f"({', '.join(var_decls)})" if var_decls else ""
    call = f"({', '.join(call_args)})" if call_args else ""
    document = f"{kind} {name}{decl} {{\n  {name}{call}{selection}\n}}\n"
    return GraphQLOperation(
        name=name,
        kind=kind,
        document=document,
        variables=tuple(variables),
        is_write=kind != "query" or name in WRITE_QUERY_FIELDS,
    )


def _python_type(
    type_ref: dict[str, Any],
    types: dict[str, Any],
    models: dict[str, type[BaseModel]],
    stack: tuple[str, ...],
) -> tuple[Any, bool]:
    required = False
    node = type_ref
    while node.get("kind") == "NON_NULL":
        required = True
        node = node.get("ofType") or {}
    if node.get("kind") == "LIST":
        item, _item_required = _python_type(node.get("ofType") or {}, types, models, stack)
        return list[item], required  # type: ignore[valid-type]
    name = node.get("name")
    if name in _SCALARS:
        return _SCALARS[name], required
    typedef = types.get(name) if name else None
    if not typedef:
        return Any, required
    if typedef.get("kind") == "ENUM":
        values = [
            item["name"]
            for item in typedef.get("enumValues") or []
            if item.get("name") and not item.get("isDeprecated")
        ]
        if values:
            from typing import Literal

            return Literal.__getitem__(tuple(values)), required
        return str, required
    if typedef.get("kind") == "INPUT_OBJECT" and name:
        if name in stack:
            return dict[str, Any], required
        return _input_model(name, types, models, stack + (name,)), required
    return Any, required


def _input_model(
    name: str,
    types: dict[str, Any],
    models: dict[str, type[BaseModel]],
    stack: tuple[str, ...],
) -> type[BaseModel]:
    cached = models.get(name)
    if cached is not None:
        return cached
    fields: dict[str, Any] = {}
    for field in types[name].get("inputFields") or []:
        field_name = field.get("name")
        if not field_name:
            continue
        python_type, required = _python_type(field.get("type") or {}, types, models, stack)
        description = field.get("description") or None
        if required:
            fields[field_name] = (
                python_type,
                Field(..., description=description) if description else ...,
            )
        else:
            fields[field_name] = (
                python_type | None,
                Field(default=None, description=description) if description else None,
            )
    model = create_model(name, **fields)
    models[name] = model
    return model


def _selection(
    type_name: str | None,
    types: dict[str, Any],
    depth: int,
    seen: frozenset[str],
) -> str:
    if not type_name or type_name not in types or depth < 0 or type_name in seen:
        return ""
    typedef = types[type_name]
    if typedef.get("kind") not in {"OBJECT", "INTERFACE"}:
        return ""
    lines: list[str] = []
    for field in typedef.get("fields") or []:
        if field.get("isDeprecated") or _requires_args(field):
            continue
        field_name = field.get("name")
        if not field_name:
            continue
        inner = _named_type(field.get("type") or {})
        inner_def = types.get(inner) if inner else None
        kind = inner_def.get("kind") if inner_def else None
        if kind in {"SCALAR", "ENUM"} or inner in _SCALARS:
            lines.append(field_name)
            continue
        if kind in {"OBJECT", "INTERFACE"} and depth > 0:
            nested = _selection(inner, types, depth - 1, seen | {type_name})
            if nested:
                lines.append(f"{field_name}{nested}")
    if not lines:
        lines.append("__typename")
    body = "\n".join(f"    {line}" for line in lines)
    return " {\n" + body + "\n  }"


def _requires_args(field: dict[str, Any]) -> bool:
    for arg in field.get("args") or []:
        if (arg.get("type") or {}).get("kind") == "NON_NULL":
            return True
    return False


def _named_type(type_ref: dict[str, Any]) -> str | None:
    node = type_ref
    while node.get("kind") in {"NON_NULL", "LIST"}:
        node = node.get("ofType") or {}
    return node.get("name")


def _graphql_type(type_ref: dict[str, Any]) -> str:
    kind = type_ref.get("kind")
    if kind == "NON_NULL":
        return _graphql_type(type_ref.get("ofType") or {}) + "!"
    if kind == "LIST":
        return "[" + _graphql_type(type_ref.get("ofType") or {}) + "]"
    return str(type_ref.get("name") or "String")
