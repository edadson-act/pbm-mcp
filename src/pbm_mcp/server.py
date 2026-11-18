"""Compose the twelve PBM APIs into one streamable HTTP MCP server."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx2
from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider

from pbm_mcp.catalog import CATALOG, Domain
from pbm_mcp.config import ConfigError, Settings, get_settings
from pbm_mcp.graphql_loader import find_operations, load_graphql_server
from pbm_mcp.http import quiet_client_logs
from pbm_mcp.introspection import find_introspection, operations_from_introspection
from pbm_mcp.mcp_auth import (
    build_mcp_auth,
    ensure_reachable_bind,
    inbound_authorization_is_forwarded,
)
from pbm_mcp.openapi_loader import find_openapi_spec, load_openapi_server

logger = logging.getLogger("pbm_mcp")


def build_server(
    settings: Settings | None = None,
    *,
    mcp_auth: AuthProvider | None = None,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> FastMCP:
    """Create the parent server.

    A domain with no spec is skipped. A spec with an empty allowlist is mounted
    and exposes zero tools. When ``mcp_auth`` is omitted, a non-empty
    ``PBM_MCP_BEARER_TOKEN`` requires that bearer token on ``/mcp``.
    """
    settings = settings or get_settings()
    if mcp_auth is None:
        mcp_auth = build_mcp_auth(settings)
    ensure_reachable_bind(settings, mcp_auth)
    quiet_client_logs()
    clients: list[httpx2.AsyncClient] = []

    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        try:
            yield None
        finally:
            for client in clients:
                await client.aclose()

    parent = FastMCP(
        "pbm-mcp",
        instructions=(
            "Pharmacy Benefit Management tools. Each tool name starts with the "
            "API namespace. Only allowlisted operations are available."
        ),
        auth=mcp_auth,
        lifespan=lifespan,
    )
    for domain in CATALOG:
        loaded = _load_domain(domain, settings, transport=transport, clients=clients)
        if loaded is None:
            continue
        child, tool_count = loaded
        parent.mount(child, namespace=domain.namespace)
        logger.info(
            "domain=%s status=mounted namespace=%s tools=%d",
            domain.id,
            domain.namespace,
            tool_count,
        )
    return parent


def _load_domain(
    domain: Domain,
    settings: Settings,
    *,
    transport: httpx2.AsyncBaseTransport | None,
    clients: list[httpx2.AsyncClient],
) -> tuple[FastMCP, int] | None:
    domain_dir = settings.specs_dir / domain.id
    openapi_path = find_openapi_spec(domain_dir)
    graphql_path = find_operations(domain_dir)
    introspection_path = None if graphql_path or openapi_path else find_introspection(domain_dir)
    schema_path = domain_dir / "schema.graphql"

    if openapi_path and (graphql_path or introspection_path):
        logger.error(
            "domain=%s status=skipped reason=both_openapi_and_graphql",
            domain.id,
        )
        return None
    if openapi_path is None and graphql_path is None and introspection_path is None:
        if schema_path.is_file():
            logger.info(
                "domain=%s status=skipped reason=graphql_schema_without_operations",
                domain.id,
            )
        else:
            logger.info("domain=%s status=skipped reason=no_spec", domain.id)
        return None
    if settings.base_url_for(domain.id) is None:
        logger.info("domain=%s status=skipped reason=no_base_url", domain.id)
        return None

    try:
        if openapi_path is not None:
            server, count = load_openapi_server(
                domain,
                settings,
                openapi_path,
                transport=transport,
                clients=clients,
            )
        elif graphql_path is not None:
            server, count = load_graphql_server(
                domain,
                settings,
                graphql_path,
                transport=transport,
                clients=clients,
            )
        else:
            assert introspection_path is not None
            server, count = load_graphql_server(
                domain,
                settings,
                introspection_path,
                operations=operations_from_introspection(introspection_path.read_text()),
                transport=transport,
                clients=clients,
            )
    except NotImplementedError:
        logger.error(
            "domain=%s status=skipped reason=auth_not_implemented",
            domain.id,
        )
        return None
    except ConfigError:
        logger.error(
            "domain=%s status=skipped reason=auth_not_configured",
            domain.id,
        )
        return None
    except Exception as exc:
        logger.error(
            "domain=%s status=skipped reason=invalid_spec error_type=%s",
            domain.id,
            type(exc).__name__,
        )
        return None

    return server, count


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    settings = get_settings()
    server = build_server(settings)
    if settings.mcp_bearer_token.strip():
        logger.info("mcp endpoint auth=bearer")
        if inbound_authorization_is_forwarded(settings):
            logger.warning(
                "upstream auth mode forward copies the caller's Authorization "
                "header onto PBM requests, so the MCP bearer token would be sent "
                "upstream. Set PBM_AUTH_MODE to bearer-env or api-key for "
                "upstream credentials."
            )
    else:
        logger.warning(
            "mcp endpoint auth=off host=%s port=%s. Set PBM_MCP_BEARER_TOKEN "
            "before running tailscale funnel; Funnel publishes this port on "
            "the public internet.",
            settings.host,
            settings.port,
        )
    server.run(transport="http", host=settings.host, port=settings.port)
