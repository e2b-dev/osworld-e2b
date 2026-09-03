"""Shared immutable identity policy for OSWorld E2B sandboxes."""

from __future__ import annotations

import re

_IMMUTABLE_TEMPLATE_RE = re.compile(
    r"^[a-z0-9][a-z0-9_-]*:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def require_immutable_template_ref(reference: str | None, variable: str) -> str:
    """Return a validated E2B ``name:build_id`` reference or fail closed."""
    if not reference:
        raise ValueError(f"{variable} is required and must be an immutable name:build_id reference")
    if not _IMMUTABLE_TEMPLATE_RE.fullmatch(reference):
        raise ValueError(
            f"{variable} must be an immutable name:build_id reference; got {reference!r}"
        )
    return reference
