"""Expose named GraphQL operations as MCP tools.

Tools come from ``operations.graphql`` or from an introspection document.
Mutations stay hidden unless the allowlist sets ``write: true``. The same
rule applies to ``orderIdCard`` and ``saveConsent``, which the schemas declare
as queries. Subscriptions are never exposed.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
from fastmcp import FastMCP
from pydantic import BaseModel
from fastmcp.exceptions import ToolError
from fastmcp.tools.function_tool import FunctionTool
from graphql import OperationType, print_ast
from graphql.language.ast import (
    ListTypeNode,
    NamedTypeNode,
    NonNullTypeNode,
    OperationDefinitionNode,
)
from graphql.language.parser import parse
from mcp_types import ToolAnnotations

from pbm_mcp.allowlist import AllowEntry, load_allowlist
from pbm_mcp.auth import build_auth
from pbm_mcp.catalog import Domain
from pbm_mcp.config import Settings
from pbm_mcp.http import UpstreamGuard, make_client
from pbm_mcp.redact import safe_excerpt

logger = logging.getLogger("pbm_mcp")

# Declared on Query, but each one changes member state.
WRITE_QUERY_FIELDS = frozenset({"orderIdCard", "saveConsent"})

_SCALARS: dict[str, Any] = {
    "String": str,
    "ID": str,
    "Int": int,
    "Float": float,
    "Boolean": bool,
}


@dataclass(frozen=True)
class GraphQLOperation:
    name: str
    kind: str
    document: str
    variables: tuple[tuple[str, Any, bool], ...]
    is_write: bool = False

    def __post_init__(self) -> None:
        if self.kind != "query" and not self.is_write:
            object.__setattr__(self, "is_write", True)


def find_operations(domain_dir: Path) -> Path | None:
    path = domain_dir / "operations.graphql"
    if path.is_file():
        return path
    return None


def parse_operations(source: str) -> list[GraphQLOperation]:
    document = parse(source)
    operations: list[GraphQLOperation] = []
    for definition in document.definitions:
        if not isinstance(definition, OperationDefinitionNode):
            continue
        if definition.name is None:
            raise ValueError("GraphQL operations must be named.")
        variables: list[tuple[str, Any, bool]] = []
        for variable in definition.variable_definitions or []:
            python_type, required = _python_type(variable.type)
            variables.append((variable.variable.name.value, python_type, required))
        operations.append(
            GraphQLOperation(
                name=definition.name.value,
                kind=definition.operation.value,
                document=print_ast(definition),
                variables=tuple(variables),
            )
        )
    return operations


def load_graphql_server(
    domain: Domain,
    settings: Settings,
    operations_path: Path,
    *,
    operations: list[GraphQLOperation] | None = None,
    transport=None,
    clients: list[httpx2.AsyncClient] | None = None,
) -> tuple[FastMCP, int]:
    if operations is None:
        operations = parse_operations(operations_path.read_text())
    allowlist = load_allowlist(settings.allowlists_dir / f"{domain.id}.yaml")
    known = {operation.name for operation in operations}
    for operation_id in allowlist:
        if operation_id not in known:
            logger.info(
                "domain=%s operation=%s status=skipped reason=not_in_spec",
                domain.id,
                operation_id,
            )

    base_url = settings.base_url_for(domain.id)
    if base_url is None:
        raise RuntimeError("base URL missing")
    client = make_client(
        base_url=base_url,
        timeout=settings.timeout_seconds,
        auth=build_auth(settings, domain.id),
        domain=domain.id,
        transport=transport,
    )
    if clients is not None:
        clients.append(client)
    server = FastMCP(domain.title, middleware=[UpstreamGuard()])
    exposed = 0
    for operation in operations:
        entry = allowlist.get(operation.name)
        if entry is None:
            continue
        if operation.kind == OperationType.SUBSCRIPTION.value:
            logger.info(
                "domain=%s operation=%s status=skipped reason=subscription",
                domain.id,
                operation.name,
            )
            continue
        if operation.is_write and not entry.write:
            logger.info(
                "domain=%s operation=%s status=skipped reason=write_not_allowlisted",
                domain.id,
                operation.name,
            )
            continue
        server.add_tool(_build_tool(operation, client, base_url, domain, entry))
        exposed += 1
    return server, exposed


def _build_tool(
    operation: GraphQLOperation,
    client: httpx2.AsyncClient,
    endpoint: str,
    domain: Domain,
    entry: AllowEntry,
):
    parameters = [
        inspect.Parameter(
            name,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=python_type,
            default=inspect.Parameter.empty if required else None,
        )
        for name, python_type, required in operation.variables
    ]

    async def handler(**kwargs: Any) -> dict[str, Any]:
        variables = {
            key: _plain(value) for key, value in kwargs.items() if value is not None
        }
        return await _execute(client, endpoint, operation, variables)

    handler.__name__ = operation.name
    handler.__doc__ = (
        f"{operation.kind} {operation.name} on {domain.title}. {domain.summary}"
    )
    handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters,
        return_annotation=dict[str, Any],
    )
    handler.__annotations__ = {
        name: python_type for name, python_type, _required in operation.variables
    }
    handler.__annotations__["return"] = dict[str, Any]
    read_only = not operation.is_write
    return FunctionTool.from_function(
        handler,
        name=operation.name,
        description=handler.__doc__,
        annotations=ToolAnnotations(
            read_only_hint=read_only,
            destructive_hint=bool(entry.write and operation.is_write),
            open_world_hint=True,
        ),
    )


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


async def _execute(
    client: httpx2.AsyncClient,
    endpoint: str,
    operation: GraphQLOperation,
    variables: dict[str, Any],
) -> dict[str, Any]:
    try:
        response = await client.post(
            endpoint,
            json={
                "query": operation.document,
                "operationName": operation.name,
                "variables": variables,
            },
        )
    except httpx2.TimeoutException as exc:
        raise ToolError("Upstream request timed out, please retry") from exc
    except httpx2.RequestError as exc:
        raise ToolError(f"upstream request failed: {type(exc).__name__}") from exc

    if response.status_code >= 400:
        raise ToolError(
            f"upstream {response.status_code}: {safe_excerpt(response.text)}"
        )
    try:
        body = response.json()
    except json.JSONDecodeError:
        raise ToolError(
            f"upstream {response.status_code}: {safe_excerpt(response.text)}"
        ) from None
    if isinstance(body, dict) and body.get("errors"):
        raise ToolError(
            "graphql errors: " + safe_excerpt(json.dumps(body["errors"]))
        )
    if not isinstance(body, dict):
        raise ToolError("upstream response was not a JSON object")
    return body


def _python_type(type_node: Any) -> tuple[Any, bool]:
    if isinstance(type_node, NonNullTypeNode):
        inner, _required = _python_type(type_node.type)
        return inner, True
    if isinstance(type_node, ListTypeNode):
        item, _required = _python_type(type_node.type)
        return list[item], False  # type: ignore[valid-type]
    if isinstance(type_node, NamedTypeNode):
        return _SCALARS.get(type_node.name.value, Any), False
    return Any, False
