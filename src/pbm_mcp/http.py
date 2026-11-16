"""HTTP client, request log, and upstream error sanitizing."""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar

import httpx2
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import ToolResult

from pbm_mcp.redact import safe_excerpt

logger = logging.getLogger("pbm_mcp")

current_operation: ContextVar[str] = ContextVar("pbm_operation", default="unknown")


def quiet_client_logs() -> None:
    """Stop HTTP libraries from logging request URLs, which can carry member ids."""
    for name in ("httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(name).setLevel(logging.WARNING)


class LoggingTransport(httpx2.AsyncBaseTransport):
    """Log domain, operation, status, and latency. Never log the URL or body."""

    def __init__(self, domain: str, inner: httpx2.AsyncBaseTransport) -> None:
        self._domain = domain
        self._inner = inner

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        operation = current_operation.get()
        started = time.perf_counter()
        try:
            response = await self._inner.handle_async_request(request)
        except Exception:
            self._log(operation, "error", started)
            raise
        self._log(operation, str(response.status_code), started)
        return response

    async def aclose(self) -> None:
        closer = getattr(self._inner, "aclose", None)
        if closer is not None:
            await closer()

    def _log(self, operation: str, status: str, started: float) -> None:
        latency_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "domain=%s operation=%s status=%s latency_ms=%.0f",
            self._domain,
            operation,
            status,
            latency_ms,
        )


class UpstreamGuard(Middleware):
    """Name the in-flight operation and strip secrets from tool errors."""

    async def on_call_tool(self, context, call_next) -> ToolResult:  # type: ignore[no-untyped-def]
        token = current_operation.set(context.message.name)
        try:
            return await call_next(context)
        except Exception as exc:
            raise ToolError(safe_excerpt(str(exc))) from None
        finally:
            current_operation.reset(token)


def make_client(
    *,
    base_url: str,
    timeout: float,
    auth: httpx2.Auth | None,
    domain: str,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> httpx2.AsyncClient:
    inner = transport if transport is not None else httpx2.AsyncHTTPTransport()
    return httpx2.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        auth=auth,
        transport=LoggingTransport(domain, inner),
    )
