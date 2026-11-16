"""Deny-by-default operation allowlists."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class AllowEntry:
    id: str
    write: bool = False


def load_allowlist(path: Path) -> dict[str, AllowEntry]:
    """Read an allowlist file. A missing or empty file exposes nothing.

    Accepted shapes::

        operations:
          - id: listClaims
          - id: deleteClaim
            write: true
    """
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text()) or {}
    if isinstance(loaded, list):
        raw_ops = loaded
    elif isinstance(loaded, dict):
        raw_ops = loaded.get("operations") or []
    else:
        raise ValueError(f"Allowlist {path} must be a mapping or list.")
    if not isinstance(raw_ops, list):
        raise ValueError(f"Allowlist {path} field 'operations' must be a list.")

    entries: dict[str, AllowEntry] = {}
    for item in raw_ops:
        if isinstance(item, str):
            entries[item] = AllowEntry(id=item, write=False)
            continue
        if not isinstance(item, dict):
            raise ValueError(f"Allowlist {path} has an entry that is not a mapping.")
        operation_id = item.get("id") or item.get("operation_id")
        if not operation_id:
            raise ValueError(f"Allowlist {path} has an entry without an id.")
        entries[str(operation_id)] = AllowEntry(
            id=str(operation_id),
            write=bool(item.get("write", False)),
        )
    return entries


def is_write_method(method: str) -> bool:
    return method.upper() not in READ_METHODS
