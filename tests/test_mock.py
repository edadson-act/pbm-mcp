"""The local GraphQL mock, exercised in-process. No live PBM hosts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from graphql import parse
from graphql.language.ast import FieldNode, OperationDefinitionNode
from httpx2 import ASGITransport, AsyncClient

from pbm_mcp.allowlist import load_allowlist
from pbm_mcp.catalog import CATALOG
from pbm_mcp.introspection import find_introspection, operations_from_introspection
from pbm_mcp.mock.app import create_app
from pbm_mcp.mock.generate import index_schema

_REPO = Path(__file__).resolve().parents[1]
_BUNDLES: dict[str, tuple] = {}


def _targets() -> list:
    rows = []
    for domain in CATALOG:
        allow = load_allowlist(_REPO / "allowlists" / f"{domain.id}.yaml")
        for name in allow:
            rows.append(pytest.param(domain.id, name, id=f"{domain.id}-{name}"))
    return rows


def _bundle(domain_id: str):
    cached = _BUNDLES.get(domain_id)
    if cached is not None:
        return cached
    spec = find_introspection(_REPO / "specs" / domain_id)
    assert spec is not None
    text = spec.read_text()
    types, roots = index_schema(text)
    fields = {field["name"]: field for _kind, field in roots}
    documents = {
        operation.name: operation.document
        for operation in operations_from_introspection(text)
    }
    cached = (types, fields, documents)
    _BUNDLES[domain_id] = cached
    return cached


def _root_field(document: str, operation_name: str) -> FieldNode:
    parsed = parse(document)
    for definition in parsed.definitions:
        if not isinstance(definition, OperationDefinitionNode):
            continue
        if definition.name is None or definition.name.value != operation_name:
            continue
        for selection in definition.selection_set.selections:
            if isinstance(selection, FieldNode) and selection.name.value == operation_name:
                return selection
    raise AssertionError(operation_name)


@pytest.fixture(scope="module")
def mock_app(tmp_path_factory):
    empty = tmp_path_factory.mktemp("generated-mock")
    return create_app(
        specs_dir=_REPO / "specs",
        allowlists_dir=_REPO / "allowlists",
        fixtures_dir=empty / "fixtures",
        world_dir=empty / "world",
    )


async def _post(app, domain_id: str, payload: dict, headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(
            f"/v1/{domain_id}/graphql",
            json=payload,
            headers=headers,
        )


@pytest.mark.parametrize("domain_id,operation_name", _targets())
async def test_allowlisted_operation_returns_selected_fields(
    mock_app,
    domain_id,
    operation_name,
):
    types, fields, documents = _bundle(domain_id)
    document = documents[operation_name]
    response = await _post(
        mock_app,
        domain_id,
        {
            "query": document,
            "operationName": operation_name,
            "variables": {},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "errors" not in body
    assert operation_name in body["data"]
    root = _root_field(document, operation_name)
    _assert_value(
        body["data"][operation_name],
        fields[operation_name].get("type") or {},
        types,
        root.selection_set,
        operation_name,
    )


async def test_mock_status_500(mock_app):
    response = await _post(
        mock_app,
        "drug-pricing",
        {"query": "query drugPricing { drugPricing }", "operationName": "drugPricing"},
        headers={"X-Mock-Status": "500"},
    )
    assert response.status_code == 500
    assert "500" in response.text


async def test_mock_status_graphql_error(mock_app):
    response = await _post(
        mock_app,
        "drug-pricing",
        {"query": "query drugPricing { drugPricing }", "operationName": "drugPricing"},
        headers={"X-Mock-Status": "graphql-error"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["errors"], list) and body["errors"]
    assert body.get("data") is None


async def test_unknown_operation(mock_app):
    response = await _post(
        mock_app,
        "drug-pricing",
        {"query": "query nope { nope }", "operationName": "nope"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["errors"], list) and body["errors"]
    assert body.get("data") is None


@pytest.mark.parametrize(
    "domain_id,operation_name",
    [
        ("id-card", "orderIdCard"),
        ("member-consent", "saveConsent"),
        ("prior-auth", "submit"),
    ],
)
async def test_writes_return_graphql_errors(mock_app, domain_id, operation_name):
    response = await _post(
        mock_app,
        domain_id,
        {"query": "query x { x }", "operationName": operation_name, "variables": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["errors"], list) and body["errors"]
    assert body.get("data") is None


async def test_string_variable_overwrites_same_named_field(mock_app):
    _types, _fields, documents = _bundle("drug-search")
    response = await _post(
        mock_app,
        "drug-search",
        {
            "query": documents["drugSearch"],
            "operationName": "drugSearch",
            "variables": {"productName": "atorvastatin"},
        },
    )
    assert response.status_code == 200
    drug = response.json()["data"]["drugSearch"]["drugs"][0]
    assert drug["productName"] == "atorvastatin"
    assert drug["gpi10"] == "example-gpi10"


async def test_nested_variable_does_not_overwrite_fields(mock_app):
    _types, _fields, documents = _bundle("drug-search")
    response = await _post(
        mock_app,
        "drug-search",
        {
            "query": documents["drugSearch"],
            "operationName": "drugSearch",
            "variables": {"drugSearchRequest": {"productName": "atorvastatin"}},
        },
    )
    assert response.status_code == 200
    drug = response.json()["data"]["drugSearch"]["drugs"][0]
    assert drug["productName"] == "example-productName"


async def test_fixture_replaces_generated_value(tmp_path):
    domain_id = "drug-pricing"
    operation_name = "drugPricing"
    folder = tmp_path / domain_id
    folder.mkdir()
    (folder / f"{operation_name}.json").write_text(json.dumps({"source": "fixture"}))
    app = create_app(
        specs_dir=_REPO / "specs",
        allowlists_dir=_REPO / "allowlists",
        fixtures_dir=tmp_path,
        world_dir=tmp_path / "world",
    )
    _types, _fields, documents = _bundle(domain_id)
    response = await _post(
        app,
        domain_id,
        {
            "query": documents[operation_name],
            "operationName": operation_name,
            "variables": {},
        },
    )
    assert response.status_code == 200
    assert response.json()["data"][operation_name] == {"source": "fixture"}


_WRITE_SPEC = {
    "data": {
        "__schema": {
            "queryType": {"name": "Query"},
            "mutationType": {"name": "Mutation"},
            "subscriptionType": None,
            "types": [
                {
                    "kind": "OBJECT",
                    "name": "Query",
                    "fields": [
                        {
                            "name": "fetchIdCard",
                            "isDeprecated": False,
                            "args": [],
                            "type": {"kind": "OBJECT", "name": "Card"},
                        },
                        {
                            "name": "orderIdCard",
                            "isDeprecated": False,
                            "args": [],
                            "type": {"kind": "OBJECT", "name": "Card"},
                        },
                    ],
                },
                {
                    "kind": "OBJECT",
                    "name": "Mutation",
                    "fields": [
                        {
                            "name": "submit",
                            "isDeprecated": False,
                            "args": [],
                            "type": {"kind": "OBJECT", "name": "Card"},
                        }
                    ],
                },
                {
                    "kind": "OBJECT",
                    "name": "Card",
                    "fields": [
                        {
                            "name": "ok",
                            "args": [],
                            "isDeprecated": False,
                            "type": {"kind": "SCALAR", "name": "Boolean"},
                        }
                    ],
                },
                {"kind": "SCALAR", "name": "Boolean"},
            ],
        }
    }
}


async def test_allowlisted_writes_still_error(tmp_path):
    specs = tmp_path / "specs" / "id-card"
    specs.mkdir(parents=True)
    (specs / "id-card.json").write_text(json.dumps(_WRITE_SPEC))
    allowlists = tmp_path / "allowlists"
    allowlists.mkdir()
    (allowlists / "id-card.yaml").write_text(
        yaml.safe_dump(
            {
                "operations": [
                    {"id": "fetchIdCard"},
                    {"id": "orderIdCard"},
                    {"id": "submit"},
                ]
            }
        )
    )
    app = create_app(
        specs_dir=tmp_path / "specs",
        allowlists_dir=allowlists,
        fixtures_dir=tmp_path / "fixtures",
        world_dir=tmp_path / "world",
    )
    read = await _post(
        app,
        "id-card",
        {
            "query": "query fetchIdCard { fetchIdCard { ok } }",
            "operationName": "fetchIdCard",
            "variables": {},
        },
    )
    assert read.status_code == 200
    assert read.json()["data"]["fetchIdCard"] == {"ok": False}
    for name in ("orderIdCard", "submit"):
        response = await _post(
            app,
            "id-card",
            {"query": "query x { x }", "operationName": name, "variables": {}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["errors"]
        assert body.get("data") is None


def _assert_value(value, type_ref, types, selection_set, field_name: str) -> None:
    node = type_ref or {}
    while node.get("kind") == "NON_NULL":
        node = node.get("ofType") or {}
    if node.get("kind") == "LIST":
        assert isinstance(value, list) and len(value) == 1, field_name
        _assert_value(
            value[0],
            node.get("ofType") or {},
            types,
            selection_set,
            field_name,
        )
        return
    named = node.get("name")
    typedef = types.get(named) if named else None
    kind = typedef.get("kind") if typedef else None
    if selection_set is None:
        if kind in {"OBJECT", "INTERFACE", "UNION"}:
            assert isinstance(value, dict), field_name
            assert set(value) == {"__typename"}, field_name
            assert isinstance(value["__typename"], str) and value["__typename"]
            return
        _assert_leaf(field_name, value)
        return
    if kind not in {"OBJECT", "INTERFACE"}:
        _assert_leaf(field_name, value)
        return
    assert isinstance(value, dict), field_name
    selected: list[FieldNode] = []
    for selection in selection_set.selections:
        assert isinstance(selection, FieldNode), field_name
        selected.append(selection)
    got = set(value)
    expected = {selection.name.value for selection in selected}
    assert got == expected, f"{field_name}: {sorted(got ^ expected)}"
    fields = {
        field["name"]: field
        for field in typedef.get("fields") or []
        if field.get("name")
    }
    for selection in selected:
        name = selection.name.value
        if name == "__typename":
            _assert_leaf(name, value[name])
            continue
        _assert_value(
            value[name],
            fields[name].get("type") or {},
            types,
            selection.selection_set,
            name,
        )


def _assert_leaf(name: str, value) -> None:
    if isinstance(value, list):
        assert len(value) == 1, name
        _assert_leaf(name, value[0])
        return
    if name == "__typename":
        assert isinstance(value, str) and value
        return
    if isinstance(value, bool):
        assert value is False
        return
    if isinstance(value, float):
        assert value == 1.0
        return
    if isinstance(value, int):
        assert value == 1
        return
    if isinstance(value, str):
        assert value == f"example-{name}", (name, value)
        return
    raise AssertionError(f"{name} has unexpected value {value!r}")
