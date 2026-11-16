"""Fixtures shared by the MCP server tests. No live PBM hosts."""

from __future__ import annotations

from pathlib import Path

import httpx2
import yaml
from fastmcp import Client

from pbm_mcp.config import Settings
from pbm_mcp.server import build_server

CLAIM_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Claim History", "version": "1.0.0"},
    "paths": {
        "/claims": {
            "get": {
                "operationId": "listClaims",
                "summary": "List claims",
                "parameters": [
                    {
                        "name": "memberId",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {"schema": {"type": "object"}}
                        },
                    }
                },
            },
            "post": {
                "operationId": "submitClaim",
                "summary": "Submit a claim",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"memberId": {"type": "string"}},
                                "required": ["memberId"],
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {"schema": {"type": "object"}}
                        },
                    }
                },
            },
        },
        "/claims/{claimId}": {
            "delete": {
                "operationId": "deleteClaim",
                "summary": "Delete a claim",
                "parameters": [
                    {
                        "name": "claimId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {"schema": {"type": "object"}}
                        },
                    }
                },
            }
        },
    },
}

ID_CARD_OPERATIONS = """
query MemberCard($memberId: ID!) {
  idCard(memberId: $memberId) {
    bin
  }
}

mutation UpdateConsent($memberId: ID!, $granted: Boolean!) {
  updateConsent(memberId: $memberId, granted: $granted) {
    ok
  }
}

subscription WatchConsent($memberId: ID!) {
  consentChanged(memberId: $memberId) {
    ok
  }
}
"""


def make_settings(tmp_path: Path, **overrides) -> Settings:
    specs = tmp_path / "specs"
    allowlists = tmp_path / "allowlists"
    specs.mkdir()
    allowlists.mkdir()
    return Settings(specs_dir=specs, allowlists_dir=allowlists, **overrides)


def write_allowlist(settings: Settings, domain_id: str, operations: list) -> None:
    path = settings.allowlists_dir / f"{domain_id}.yaml"
    path.write_text(yaml.safe_dump({"operations": operations}))


def write_openapi(settings: Settings, domain_id: str, spec: dict | None = None) -> None:
    domain_dir = settings.specs_dir / domain_id
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "openapi.yaml").write_text(yaml.safe_dump(spec or CLAIM_SPEC))


def write_graphql(
    settings: Settings,
    domain_id: str,
    operations: str = ID_CARD_OPERATIONS,
) -> None:
    domain_dir = settings.specs_dir / domain_id
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "schema.graphql").write_text("type Query { idCard(memberId: ID!): ID }\n")
    (domain_dir / "operations.graphql").write_text(operations)


async def tool_names(server) -> list[str]:
    async with Client(server) as client:
        tools = await client.list_tools()
    return sorted(tool.name for tool in tools)


def capture_transport(bucket: dict) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        bucket["method"] = request.method
        bucket["url"] = str(request.url)
        bucket["headers"] = {key.lower(): value for key, value in request.headers.items()}
        bucket["content"] = request.content.decode()
        return httpx2.Response(200, json={"ok": True})

    return httpx2.MockTransport(handler)


def build(settings: Settings, transport=None):
    return build_server(settings, transport=transport)
