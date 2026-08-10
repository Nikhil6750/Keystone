"""Exception -> HTTP error-envelope mapping for the API layer."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.engine.compensation_exceptions import (
    CompensationAlreadyCompletedError,
    CompensationExecutionError,
    CompensationHandlerNotRegisteredError,
    InvalidCompensationStateError,
)
from app.engine.exceptions import InvalidWorkflowStateError, WorkflowNotFoundError
from app.engine.orchestration.errors import OrchestrationExecutionNotFoundError
from app.engine.registry import ExecutorNotRegisteredError
from app.resilience.circuit_breaker import CircuitBreakerOpenError
from app.schemas.errors import APIError, APIErrorCode, APIErrorEnvelope
from app.services.agent_connection import UnknownAgentTypeError, VerificationInProgressError

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

    @app.exception_handler(CircuitBreakerOpenError)
    async def _circuit_breaker_open(_: Request, exc: CircuitBreakerOpenError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_envelope(APIErrorCode.CIRCUIT_BREAKER_OPEN, str(exc)),
        )

    @app.exception_handler(CompensationAlreadyCompletedError)
    async def _compensation_already_completed(
        _: Request, exc: CompensationAlreadyCompletedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_envelope(APIErrorCode.COMPENSATION_ALREADY_COMPLETED, str(exc)),
        )

    @app.exception_handler(InvalidCompensationStateError)
    async def _invalid_compensation_state(
        _: Request, exc: InvalidCompensationStateError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_envelope(APIErrorCode.INVALID_COMPENSATION_STATE, str(exc)),
        )

    @app.exception_handler(CompensationHandlerNotRegisteredError)
    async def _compensation_handler_not_registered(
        _: Request, exc: CompensationHandlerNotRegisteredError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_envelope(APIErrorCode.COMPENSATION_HANDLER_NOT_REGISTERED, str(exc)),
        )

    @app.exception_handler(CompensationExecutionError)
    async def _compensation_execution_failed(
        _: Request, exc: CompensationExecutionError
    ) -> JSONResponse:
        # Normal handler-execution failures are handled inside CompensationService
        # and returned as a 200 with the persisted failed workflow; reaching this
        # handler means one leaked unexpectedly, so it is treated as a server error.
        logger.exception("unexpected_compensation_execution_error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(APIErrorCode.COMPENSATION_EXECUTION_FAILED, str(exc)),
        )

    @app.exception_handler(UnknownAgentTypeError)
    async def _unknown_agent_type(_: Request, exc: UnknownAgentTypeError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_envelope(APIErrorCode.AGENT_TYPE_UNKNOWN, str(exc)),
        )

    @app.exception_handler(VerificationInProgressError)
    async def _verification_in_progress(
        _: Request, exc: VerificationInProgressError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_envelope(APIErrorCode.AGENT_VERIFICATION_IN_PROGRESS, str(exc)),
        )

    @app.exception_handler(OrchestrationExecutionNotFoundError)
    async def _orchestration_execution_not_found(
        _: Request, exc: OrchestrationExecutionNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_envelope(APIErrorCode.ORCHESTRATION_EXECUTION_NOT_FOUND, str(exc)),
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
