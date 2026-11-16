"""Turn one dropped-in OpenAPI document into an allowlisted MCP server."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx2
import yaml
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap
from fastmcp.utilities.openapi import HTTPRoute

from pbm_mcp.allowlist import AllowEntry, is_write_method, load_allowlist
from pbm_mcp.auth import build_auth
from pbm_mcp.catalog import Domain
from pbm_mcp.config import Settings
from pbm_mcp.http import UpstreamGuard, make_client

logger = logging.getLogger("pbm_mcp")

OPENAPI_NAMES = ("openapi.yaml", "openapi.yml", "openapi.json")


def find_openapi_spec(domain_dir: Path) -> Path | None:
    for name in OPENAPI_NAMES:
        path = domain_dir / name
        if path.is_file():
            return path
    return None


def read_spec(path: Path) -> dict:
    text = path.read_text()
    if path.suffix == ".json":
        loaded = json.loads(text)
    else:
        loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"OpenAPI spec {path} must be a mapping.")
    return loaded


def spec_operation_ids(spec: dict) -> set[str]:
    found: set[str] = set()
    paths = spec.get("paths") or {}
    if not isinstance(paths, dict):
        return found
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() in {"parameters", "summary", "description", "servers"}:
                continue
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if operation_id:
                found.add(str(operation_id))
    return found


def load_openapi_server(
    domain: Domain,
    settings: Settings,
    spec_path: Path,
    *,
    transport=None,
    clients: list[httpx2.AsyncClient] | None = None,
) -> tuple[FastMCP, int]:
    """Mount only allowlisted operations. Writes need ``write: true``."""
    spec = read_spec(spec_path)
    allowlist = load_allowlist(settings.allowlists_dir / f"{domain.id}.yaml")
    _log_unknown(domain.id, allowlist, spec_operation_ids(spec))
    auth = build_auth(settings, domain.id)
    base_url = settings.base_url_for(domain.id)
    if base_url is None:
        raise RuntimeError("base URL missing")
    client = make_client(
        base_url=base_url,
        timeout=settings.timeout_seconds,
        auth=auth,
        domain=domain.id,
        transport=transport,
    )
    if clients is not None:
        clients.append(client)

    def route_map_fn(route: HTTPRoute, mcp_type: MCPType) -> MCPType:
        if not route.operation_id:
            return MCPType.EXCLUDE
        entry = allowlist.get(route.operation_id)
        if entry is None:
            return MCPType.EXCLUDE
        if is_write_method(route.method) and not entry.write:
            return MCPType.EXCLUDE
        return MCPType.TOOL

    server = FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name=domain.title,
        route_maps=[RouteMap(mcp_type=MCPType.EXCLUDE)],
        route_map_fn=route_map_fn,
        validate_output=False,
    )
    server.add_middleware(UpstreamGuard())
    exposed = sum(1 for entry in allowlist.values() if _entry_is_tool(entry, spec))
    return server, exposed


def _entry_is_tool(entry: AllowEntry, spec: dict) -> bool:
    """Best-effort count. The route map is the source of truth at runtime."""
    for path_item in (spec.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            if operation.get("operationId") != entry.id:
                continue
            if is_write_method(method) and not entry.write:
                return False
            return True
    return False


def _log_unknown(domain_id: str, allowlist: dict[str, AllowEntry], known: set[str]) -> None:
    for operation_id in allowlist:
        if operation_id not in known:
            logger.info(
                "domain=%s operation=%s status=skipped reason=not_in_spec",
                domain_id,
                operation_id,
            )
