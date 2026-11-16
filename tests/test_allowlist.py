import logging

import httpx2
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from pbm_mcp.catalog import CATALOG
from pbm_mcp.redact import safe_excerpt
from pbm_mcp.server import build_server
from tests.helpers import (
    capture_transport,
    make_settings,
    tool_names,
    write_allowlist,
    write_graphql,
    write_openapi,
)


async def test_missing_spec_boots_with_no_tools(tmp_path):
    assert len(CATALOG) == 12
    server = build_server(make_settings(tmp_path))
    assert await tool_names(server) == []


async def test_empty_allowlist_mounts_no_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("PBM_CLAIM_HISTORY_BASE_URL", "https://claims.test")
    settings = make_settings(tmp_path)
    write_openapi(settings, "claim-history")
    write_allowlist(settings, "claim-history", [])
    assert await tool_names(build_server(settings)) == []


async def test_writes_stay_hidden_unless_allowlisted(tmp_path, monkeypatch):
    monkeypatch.setenv("PBM_CLAIM_HISTORY_BASE_URL", "https://claims.test")
    settings = make_settings(tmp_path)
    write_openapi(settings, "claim-history")
    write_allowlist(
        settings,
        "claim-history",
        [
            {"id": "listClaims"},
            {"id": "submitClaim"},
            {"id": "deleteClaim", "write": True},
            {"id": "missingOperation"},
        ],
    )
    assert await tool_names(build_server(settings)) == [
        "claim_history_deleteClaim",
        "claim_history_listClaims",
    ]


async def test_missing_base_url_skips_domain(tmp_path):
    settings = make_settings(tmp_path)
    write_openapi(settings, "claim-history")
    write_allowlist(settings, "claim-history", [{"id": "listClaims"}])
    assert await tool_names(build_server(settings)) == []


async def test_both_spec_styles_skip_domain(tmp_path, monkeypatch):
    monkeypatch.setenv("PBM_ID_CARD_BASE_URL", "https://id-card.test/graphql")
    settings = make_settings(tmp_path)
    write_graphql(settings, "id-card")
    write_openapi(settings, "id-card")
    write_allowlist(settings, "id-card", [{"id": "MemberCard"}])
    assert await tool_names(build_server(settings)) == []


async def test_schema_without_operations_skips_domain(tmp_path, monkeypatch):
    monkeypatch.setenv("PBM_ID_CARD_BASE_URL", "https://id-card.test/graphql")
    settings = make_settings(tmp_path)
    domain_dir = settings.specs_dir / "id-card"
    domain_dir.mkdir()
    (domain_dir / "schema.graphql").write_text("type Query { idCard: ID }\n")
    assert await tool_names(build_server(settings)) == []


async def test_upstream_error_redacts_bearer_token(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("PBM_CLAIM_HISTORY_BASE_URL", "https://claims.test")
    settings = make_settings(tmp_path, auth_mode="api-key", api_key="secret-key")
    write_openapi(settings, "claim-history")
    write_allowlist(settings, "claim-history", [{"id": "listClaims"}])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            500,
            json={"detail": "Bearer super-secret-token", "memberId": "m-100"},
        )

    server = build_server(settings, transport=httpx2.MockTransport(handler))
    with caplog.at_level(logging.INFO, logger="pbm_mcp"), pytest.raises(ToolError) as raised:
        async with Client(server) as client:
            await client.call_tool("claim_history_listClaims", {"memberId": "m-100"})

    message = str(raised.value)
    assert "super-secret-token" not in message
    assert "Bearer [redacted]" in message
    assert "m-100" not in caplog.text
    assert "domain=claim-history" in caplog.text
    assert "operation=listClaims" in caplog.text
    assert "status=500" in caplog.text


def test_safe_excerpt_redacts_assigned_secrets():
    text = 'token: abc.def password="hunter2" ' + ("x" * 600)
    excerpt = safe_excerpt(text, limit=80)
    assert "abc.def" not in excerpt
    assert "hunter2" not in excerpt
    assert excerpt.endswith("…")
    assert len(excerpt) == 81
