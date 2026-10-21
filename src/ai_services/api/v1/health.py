"""Liveness (open, status only) and readiness (detail only with the service credential)."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ai_services.auth import extract_bearer, token_is_valid
from ai_services.readiness import check_dependencies, overall_status
from ai_services.schemas import Liveness, Readiness

router = APIRouter(prefix="/v1/health")


@router.get("/live", operation_id="healthLive", openapi_extra={"security": []})
async def live() -> Liveness:
    return Liveness(status="ok")


@router.get(
    "/ready",
    operation_id="healthReady",
    response_model=Readiness,
    openapi_extra={"security": [{}, {"serviceToken": []}]},  # credential optional
    responses={503: {"model": Readiness, "description": "Not ready (or shutting down)."}},
)
async def ready(request: Request) -> JSONResponse:
    state = request.app.state
    credentialed = token_is_valid(
        extract_bearer(request.headers.get("authorization")), state.settings.service_tokens
    )
    results = await check_dependencies(state.settings.readiness_dependencies)
    status = "not_ready" if state.shutting_down else overall_status(results)
    body: dict[str, Any] = {"status": status}
    if credentialed:
        body["dependencies"] = [{"name": r.name, "status": r.status} for r in results]
    return JSONResponse(body, status_code=200 if status == "ready" else 503)
