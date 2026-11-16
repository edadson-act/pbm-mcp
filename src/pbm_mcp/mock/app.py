"""GraphQL stand-in for the twelve PBM domains.

One POST route per catalog id, ``/v1/{domain}/graphql``. Allowlisted reads
return synthetic data. Unknown operations, mutations, and the write queries
``orderIdCard`` and ``saveConsent`` return a GraphQL ``errors`` entry.
``X-Mock-Status: 500`` and ``X-Mock-Status: graphql-error`` force those faults.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from pbm_mcp.allowlist import load_allowlist
from pbm_mcp.catalog import CATALOG
from pbm_mcp.config import get_settings
from pbm_mcp.graphql_loader import WRITE_QUERY_FIELDS
from pbm_mcp.introspection import find_introspection
from pbm_mcp.mock.generate import (
    DEFAULT_FIXTURES_DIR,
    generate_return_value,
    index_schema,
    load_operation_fixture,
)
from pbm_mcp.mock.world import (
    DEFAULT_WORLD_DIR,
    WorldError,
    compose_operation,
    load_world,
)

logger = logging.getLogger("pbm_mcp.mock")

HOST = "127.0.0.1"
PORT = 8001


@dataclass(frozen=True)
class _Operation:
    name: str
    kind: str
    type_ref: dict[str, Any]
    allowlisted: bool


@dataclass(frozen=True)
class _Domain:
    domain_id: str
    types: dict[str, Any]
    operations: dict[str, _Operation]
    fixtures_dir: Path
    world_dir: Path


def create_app(
    *,
    specs_dir: Path | None = None,
    allowlists_dir: Path | None = None,
    fixtures_dir: Path | None = None,
    world_dir: Path | None = None,
) -> Starlette:
    """Build the mock. Paths default to the repo layout used by ``pbm-mcp``."""
    specs_dir = specs_dir or Path("specs")
    allowlists_dir = allowlists_dir or Path("allowlists")
    fixtures_dir = fixtures_dir or DEFAULT_FIXTURES_DIR
    if world_dir is None:
        world_dir = DEFAULT_WORLD_DIR
    routes: list[Route] = []
    for domain in CATALOG:
        state = _load_domain(
            domain.id,
            specs_dir / domain.id,
            allowlists_dir / f"{domain.id}.yaml",
            fixtures_dir,
            world_dir,
        )
        endpoint = _endpoint(state)
        endpoint.__name__ = f"graphql_{domain.namespace}"
        routes.append(
            Route(
                f"/v1/{domain.id}/graphql",
                endpoint=endpoint,
                methods=["POST"],
                name=f"{domain.id}-graphql",
            )
        )
    return Starlette(routes=routes)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    settings = get_settings()
    root = settings.specs_dir.parent
    app = create_app(
        specs_dir=settings.specs_dir,
        allowlists_dir=settings.allowlists_dir,
        fixtures_dir=root / "mocks" / "fixtures",
        world_dir=root / "mocks" / "world",
    )
    logger.info("pbm-mock listening on http://%s:%s", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


def _load_domain(
    domain_id: str,
    domain_dir: Path,
    allowlist_path: Path,
    fixtures_dir: Path,
    world_dir: Path,
) -> _Domain:
    allowlist = load_allowlist(allowlist_path)
    spec = find_introspection(domain_dir)
    operations: dict[str, _Operation] = {}
    types: dict[str, Any] = {}
    if spec is not None:
        types, roots = index_schema(spec.read_text())
        for kind, field in roots:
            name = field.get("name")
            if not name:
                continue
            operations[name] = _Operation(
                name=name,
                kind=kind,
                type_ref=field.get("type") or {},
                allowlisted=name in allowlist,
            )
    for operation_id in allowlist:
        if operation_id not in operations:
            logger.warning(
                "domain=%s operation=%s status=unmapped reason=not_in_schema",
                domain_id,
                operation_id,
            )
    served = sum(1 for operation in operations.values() if _is_served(operation))
    logger.info("domain=%s status=ready operations=%d", domain_id, served)
    return _Domain(
        domain_id=domain_id,
        types=types,
        operations=operations,
        fixtures_dir=fixtures_dir,
        world_dir=world_dir,
    )


def _endpoint(domain: _Domain):
    async def graphql(request: Request) -> Response:
        return await _handle(request, domain)

    return graphql


async def _handle(request: Request, domain: _Domain) -> Response:
    fault = (request.headers.get("x-mock-status") or "").strip()
    if fault == "500":
        return Response("mock status 500", status_code=500, media_type="text/plain")
    if fault == "graphql-error":
        return _error("mock graphql error")

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return _error("Request body must be JSON.")
    if not isinstance(payload, dict):
        return _error("Request body must be a JSON object.")
    operation_name = payload.get("operationName")
    if not isinstance(operation_name, str) or not operation_name:
        return _error("operationName is required.")
    variables = payload.get("variables") or {}
    if not isinstance(variables, dict):
        return _error("variables must be an object.")

    operation = domain.operations.get(operation_name)
    if operation is None or not operation.allowlisted:
        return _error(f"Unknown operation {operation_name}.")
    if not _is_served(operation):
        return _error(f"Operation {operation_name} is not available.")

    try:
        found, fixture = load_operation_fixture(
            domain.fixtures_dir,
            domain.domain_id,
            operation_name,
        )
    except json.JSONDecodeError:
        return _error(f"Fixture for {operation_name} is not valid JSON.")
    if found:
        value = fixture
    else:
        try:
            world = load_world(domain.world_dir)
            composed = (
                compose_operation(operation_name, variables, world)
                if world is not None
                else None
            )
        except json.JSONDecodeError:
            return _error("Demo world is not valid JSON.")
        except WorldError as exc:
            return _error(str(exc))
        if composed is not None and composed.handled:
            if composed.error:
                return _error(composed.error)
            value = composed.value
        else:
            value = generate_return_value(operation.type_ref, domain.types, variables)
    return JSONResponse({"data": {operation_name: value}})


def _is_served(operation: _Operation) -> bool:
    return (
        operation.allowlisted
        and operation.kind == "query"
        and operation.name not in WRITE_QUERY_FIELDS
    )


def _error(message: str) -> JSONResponse:
    return JSONResponse(
        {"data": None, "errors": [{"message": message}]},
        status_code=200,
    )
