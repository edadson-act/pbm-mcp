import json
from pathlib import Path

from fastmcp import Client
from graphql import parse
from pydantic import BaseModel

from pbm_mcp.catalog import CATALOG
from pbm_mcp.config import Settings
from pbm_mcp.introspection import find_introspection, operations_from_introspection
from pbm_mcp.server import build_server
from tests.helpers import (
    capture_transport,
    make_settings,
    tool_names,
    write_allowlist,
    write_graphql,
)


def _id_card_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("PBM_ID_CARD_BASE_URL", "https://id-card.test/graphql")
    settings = make_settings(tmp_path)
    write_graphql(settings, "id-card")
    return settings


async def test_mutations_and_subscriptions_are_excluded(tmp_path, monkeypatch):
    settings = _id_card_settings(tmp_path, monkeypatch)
    write_allowlist(
        settings,
        "id-card",
        [
            {"id": "MemberCard"},
            {"id": "UpdateConsent"},
            {"id": "WatchConsent", "write": True},
        ],
    )
    assert await tool_names(build_server(settings)) == ["id_card_MemberCard"]


async def test_graphql_post_shape(tmp_path, monkeypatch):
    settings = _id_card_settings(tmp_path, monkeypatch)
    write_allowlist(
        settings,
        "id-card",
        [
            {"id": "MemberCard"},
            {"id": "UpdateConsent", "write": True},
        ],
    )
    seen: dict = {}
    server = build_server(settings, transport=capture_transport(seen))
    async with Client(server) as client:
        result = await client.call_tool("id_card_MemberCard", {"memberId": "m-100"})
    assert result.data == {"ok": True}
    body = json.loads(seen["content"])
    assert seen["method"] == "POST"
    assert seen["url"] == "https://id-card.test/graphql"
    assert body["operationName"] == "MemberCard"
    assert body["variables"] == {"memberId": "m-100"}
    assert "query MemberCard" in body["query"]
    assert "mutation" not in body["query"]


async def test_allowlisted_mutation_is_posted(tmp_path, monkeypatch):
    settings = _id_card_settings(tmp_path, monkeypatch)
    write_allowlist(settings, "id-card", [{"id": "UpdateConsent", "write": True}])
    seen: dict = {}
    server = build_server(settings, transport=capture_transport(seen))
    async with Client(server) as client:
        names = sorted(tool.name for tool in await client.list_tools())
        await client.call_tool(
            "id_card_UpdateConsent",
            {"memberId": "m-100", "granted": True},
        )
    assert names == ["id_card_UpdateConsent"]
    body = json.loads(seen["content"])
    assert body["operationName"] == "UpdateConsent"
    assert body["variables"] == {"memberId": "m-100", "granted": True}
    assert body["query"].startswith("mutation UpdateConsent")


_REPO = Path(__file__).resolve().parents[1]

_MINI_INTROSPECTION = json.dumps(
    {
        "data": {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": None,
                "subscriptionType": None,
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "drugSearch",
                                "isDeprecated": False,
                                "args": [
                                    {
                                        "name": "drugSearchRequest",
                                        "type": {
                                            "kind": "NON_NULL",
                                            "ofType": {
                                                "kind": "INPUT_OBJECT",
                                                "name": "DrugSearchRequest",
                                            },
                                        },
                                    }
                                ],
                                "type": {"kind": "OBJECT", "name": "DrugSearchResponse"},
                            },
                            {
                                "name": "orderIdCard",
                                "isDeprecated": False,
                                "args": [
                                    {
                                        "name": "request",
                                        "type": {
                                            "kind": "INPUT_OBJECT",
                                            "name": "OrderIDCardInput",
                                        },
                                    }
                                ],
                                "type": {"kind": "OBJECT", "name": "OrderResult"},
                            },
                        ],
                    },
                    {
                        "kind": "INPUT_OBJECT",
                        "name": "DrugSearchRequest",
                        "inputFields": [
                            {
                                "name": "queryTerm",
                                "type": {
                                    "kind": "NON_NULL",
                                    "ofType": {"kind": "SCALAR", "name": "String"},
                                },
                            }
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "DrugSearchResponse",
                        "fields": [
                            {
                                "name": "total",
                                "args": [],
                                "isDeprecated": False,
                                "type": {"kind": "SCALAR", "name": "Int"},
                            }
                        ],
                    },
                    {
                        "kind": "INPUT_OBJECT",
                        "name": "OrderIDCardInput",
                        "inputFields": [
                            {
                                "name": "memberId",
                                "type": {"kind": "SCALAR", "name": "String"},
                            }
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "OrderResult",
                        "fields": [
                            {
                                "name": "ok",
                                "args": [],
                                "isDeprecated": False,
                                "type": {"kind": "SCALAR", "name": "Boolean"},
                            }
                        ],
                    },
                    {"kind": "SCALAR", "name": "String"},
                    {"kind": "SCALAR", "name": "Int"},
                    {"kind": "SCALAR", "name": "Boolean"},
                ],
            }
        }
    }
)


def _write_introspection(settings: Settings, domain_id: str, body: str) -> None:
    domain_dir = settings.specs_dir / domain_id
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / f"{domain_id}-mp-api.yaml").write_text(body)


async def test_introspection_hides_write_queries(tmp_path, monkeypatch):
    monkeypatch.setenv("PBM_ID_CARD_BASE_URL", "https://id-card.test/graphql")
    settings = make_settings(tmp_path)
    _write_introspection(settings, "id-card", _MINI_INTROSPECTION)
    write_allowlist(
        settings,
        "id-card",
        [{"id": "drugSearch"}, {"id": "orderIdCard"}],
    )
    assert await tool_names(build_server(settings)) == ["id_card_drugSearch"]


async def test_introspection_posts_nested_input(tmp_path, monkeypatch):
    monkeypatch.setenv("PBM_DRUG_SEARCH_BASE_URL", "https://drug-search.test/graphql")
    settings = make_settings(tmp_path)
    _write_introspection(settings, "drug-search", _MINI_INTROSPECTION)
    write_allowlist(settings, "drug-search", [{"id": "drugSearch"}])
    seen: dict = {}
    server = build_server(settings, transport=capture_transport(seen))
    async with Client(server) as client:
        result = await client.call_tool(
            "drug_search_drugSearch",
            {"drugSearchRequest": {"queryTerm": "lipitor"}},
        )
    assert result.data == {"ok": True}
    body = json.loads(seen["content"])
    parse(body["query"])
    assert body["operationName"] == "drugSearch"
    assert body["variables"] == {"drugSearchRequest": {"queryTerm": "lipitor"}}
    assert "total" in body["query"]


async def test_shipped_specs_expose_read_operations_only(monkeypatch):
    for domain in CATALOG:
        env_name = "PBM_" + domain.id.upper().replace("-", "_") + "_BASE_URL"
        monkeypatch.setenv(env_name, f"https://{domain.id}.test/graphql")
    settings = Settings(
        specs_dir=_REPO / "specs",
        allowlists_dir=_REPO / "allowlists",
        auth_mode="none",
    )
    names = await tool_names(build_server(settings))
    expected: list[str] = []
    hidden_writes: list[str] = []
    for domain in CATALOG:
        spec = find_introspection(_REPO / "specs" / domain.id)
        assert spec is not None
        for operation in operations_from_introspection(spec.read_text()):
            tool = f"{domain.namespace}_{operation.name}"
            if operation.is_write:
                hidden_writes.append(tool)
            else:
                expected.append(tool)
    assert names == sorted(expected)
    assert hidden_writes
    assert set(hidden_writes).isdisjoint(names)
    operations = operations_from_introspection(
        (_REPO / "specs/drug-search/drug-search-mp-api.yaml").read_text()
    )
    drug_forms = next(operation for operation in operations if operation.name == "drugForms")
    parse(drug_forms.document)
    assert "gpi10" in drug_forms.document
    assert "forms {" in drug_forms.document
    request_type = drug_forms.variables[0][1]
    assert issubclass(request_type, BaseModel)
