"""Synthetic JSON for allowlisted GraphQL reads.

The walk matches ``introspection._selection``: depth 2, skip deprecated
fields, skip fields that require arguments. Object and interface fields
become nested objects. Scalars and enums are leaves. Lists contain one item.
A type with no selectable fields is ``{"__typename": "<type>"}``.

Values are synthetic. A top-level string variable replaces a same-named
string or enum field on every object. Nested objects inside variables are
not consulted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pbm_mcp.introspection import (
    _SCALARS,
    _SELECTION_DEPTH,
    _load_schema,
    _named_type,
    _requires_args,
    _root_fields,
)

# Integer-like custom scalars in the shipped documents. Everything else
# that is not Boolean, Int, or Float is filled as a string.
_INTEGER_SCALARS = frozenset({"Int", "BigInteger"})
_NUMERIC_SCALARS = _INTEGER_SCALARS | {"Float"}

DEFAULT_FIXTURES_DIR = Path("mocks/fixtures")


def index_schema(
    text: str,
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    """Return ``(types, root fields)`` from an introspection document."""
    schema = _load_schema(text)
    types = {
        item["name"]: item for item in schema.get("types") or [] if item.get("name")
    }
    return types, _root_fields(schema, types)


def generate_return_value(
    type_ref: dict[str, Any],
    types: dict[str, Any],
    variables: dict[str, Any] | None = None,
) -> Any:
    """JSON value for one root field's return type."""
    strings = _string_variables(variables)
    named = _named_type(type_ref)
    typedef = types.get(named) if named else None
    kind = typedef.get("kind") if typedef else None
    if kind in {"OBJECT", "INTERFACE"}:
        value = _object_value(named, types, _SELECTION_DEPTH, frozenset(), strings)
        if value is None and named:
            value = {"__typename": named}
        return _wrap_lists(type_ref, value)
    if kind in {"SCALAR", "ENUM"} or named in _SCALARS:
        return _leaf(named, typedef, "", strings, type_ref)
    if named:
        return _wrap_lists(type_ref, {"__typename": named})
    return None


def load_operation_fixture(
    fixtures_dir: Path,
    domain_id: str,
    operation_name: str,
) -> tuple[bool, Any]:
    """Return ``(True, value)`` when ``fixtures/{domain}/{operation}.json`` exists.

    The file replaces the generated data value for that operation. ``False``
    means there is no override.
    """
    path = fixtures_dir / domain_id / f"{operation_name}.json"
    if not path.is_file():
        return False, None
    return True, json.loads(path.read_text())


def _object_value(
    type_name: str | None,
    types: dict[str, Any],
    depth: int,
    seen: frozenset[str],
    strings: dict[str, str],
) -> dict[str, Any] | None:
    if not type_name or type_name not in types or depth < 0 or type_name in seen:
        return None
    typedef = types[type_name]
    if typedef.get("kind") not in {"OBJECT", "INTERFACE"}:
        return None
    result: dict[str, Any] = {}
    for field in typedef.get("fields") or []:
        if field.get("isDeprecated") or _requires_args(field):
            continue
        field_name = field.get("name")
        if not field_name:
            continue
        type_ref = field.get("type") or {}
        inner = _named_type(type_ref)
        inner_def = types.get(inner) if inner else None
        kind = inner_def.get("kind") if inner_def else None
        if kind in {"SCALAR", "ENUM"} or inner in _SCALARS:
            result[field_name] = _leaf(inner, inner_def, field_name, strings, type_ref)
            continue
        if kind in {"OBJECT", "INTERFACE"} and depth > 0:
            nested = _object_value(
                inner,
                types,
                depth - 1,
                seen | {type_name},
                strings,
            )
            if nested is not None:
                result[field_name] = _wrap_lists(type_ref, nested)
    if not result:
        result["__typename"] = type_name
    return result


def _leaf(
    named: str | None,
    typedef: dict[str, Any] | None,
    field_name: str,
    strings: dict[str, str],
    type_ref: dict[str, Any],
) -> Any:
    if field_name in strings and _accepts_string_override(named, typedef):
        value: Any = strings[field_name]
    elif typedef is not None and typedef.get("kind") == "ENUM":
        value = _enum_value(typedef, field_name)
    else:
        value = _scalar_value(named, field_name)
    return _wrap_lists(type_ref, value)


def _accepts_string_override(
    named: str | None,
    typedef: dict[str, Any] | None,
) -> bool:
    if named in {"Boolean"} or named in _NUMERIC_SCALARS:
        return False
    if typedef is not None and typedef.get("kind") == "ENUM":
        return True
    if named in {"String", "ID"}:
        return True
    return typedef is not None and typedef.get("kind") == "SCALAR"


def _scalar_value(named: str | None, field_name: str) -> Any:
    if named == "Boolean":
        return False
    if named in _INTEGER_SCALARS:
        return 1
    if named == "Float":
        return 1.0
    return f"example-{field_name}"


def _enum_value(typedef: dict[str, Any], field_name: str) -> str:
    for item in typedef.get("enumValues") or []:
        name = item.get("name")
        if name and not item.get("isDeprecated"):
            return str(name)
    return f"example-{field_name}"


def _wrap_lists(type_ref: dict[str, Any], value: Any) -> Any:
    count = 0
    node = type_ref
    while node.get("kind") in {"NON_NULL", "LIST"}:
        if node.get("kind") == "LIST":
            count += 1
        node = node.get("ofType") or {}
    for _ in range(count):
        value = [value]
    return value


def _string_variables(variables: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(variables, dict):
        return {}
    return {key: value for key, value in variables.items() if isinstance(value, str)}
