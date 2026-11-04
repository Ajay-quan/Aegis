"""Route-template resolution that is stable across FastAPI versions.

Since FastAPI 0.14x, routes from ``include_router(prefix=...)`` are matched inside an internal
wrapper and ``scope["route"].path`` is *relative* to the router ("/audit" instead of
"/api/v1/admin/audit"). Authorization, metrics and the audit trail all need the full template,
so it is reconstructed from public data only: fill the route template with the request's path
parameters, and whatever precedes it in the URL path is the router prefix.
"""
from __future__ import annotations

import re

from fastapi import Request

_PARAM = re.compile(r"{([^}:]+)(?::[^}]+)?}")


def route_template(request: Request) -> str | None:
    """Full templated path of the matched route (e.g. ``/api/v1/memories/{memory_id}``)."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if template is None:
        return None
    params = request.path_params
    filled = _PARAM.sub(lambda m: str(params.get(m.group(1), m.group(0))), template)
    path = request.url.path
    if filled != path and path.endswith(filled):
        return path[: len(path) - len(filled)] + template
    return template
