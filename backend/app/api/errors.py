"""Exception -> HTTP error-envelope mapping for the API layer."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.engine.exceptions import InvalidWorkflowStateError, WorkflowNotFoundError
from app.engine.registry import ExecutorNotRegisteredError
from app.schemas.errors import APIError, APIErrorCode, APIErrorEnvelope

logger = logging.getLogger(__name__)


def _envelope(code: APIErrorCode, message: str, details: Any | None = None) -> dict[str, Any]:
    body = APIErrorEnvelope(error=APIError(code=code, message=message, details=details))
    return body.model_dump(mode="json")


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers mapping domain/framework exceptions to the API error envelope.

    Never exposes stack traces, database URLs, or internal configuration in the
    response body; unexpected exceptions are logged server-side and returned
    as a sanitized 500.
    """

    @app.exception_handler(WorkflowNotFoundError)
    async def _workflow_not_found(_: Request, exc: WorkflowNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_envelope(APIErrorCode.WORKFLOW_NOT_FOUND, str(exc)),
        )

    @app.exception_handler(InvalidWorkflowStateError)
    async def _invalid_workflow_state(_: Request, exc: InvalidWorkflowStateError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_envelope(APIErrorCode.INVALID_WORKFLOW_STATE, str(exc)),
        )

    @app.exception_handler(ExecutorNotRegisteredError)
    async def _executor_not_registered(_: Request, exc: ExecutorNotRegisteredError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_envelope(APIErrorCode.AGENT_EXECUTOR_NOT_REGISTERED, str(exc)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_envelope(
                APIErrorCode.INVALID_REQUEST,
                "request validation failed",
                details=jsonable_encoder(exc.errors()),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(APIErrorCode.INVALID_REQUEST, str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(APIErrorCode.INTERNAL_ERROR, "an unexpected error occurred"),
        )
