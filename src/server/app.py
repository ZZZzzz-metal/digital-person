"""Anonymous session API. Real startup failures never select a stub."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from b2_core.contracts import Engine, ErrorDetail, ErrorResponse, Health
from b2_core.store import ResourceNotFound, SQLiteStore, Store, StoreBusy, StoreError, TurnInProgress
from .sessions import router as sessions_router
from .stub import StubEngine


logger = logging.getLogger(__name__)
COOKIE_NAME = "b2_anon"


def _error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(error=ErrorDetail(code=code, message=message)).model_dump(),
    )


def _store_error_response(exc: StoreError) -> JSONResponse:
    if isinstance(exc, ResourceNotFound):
        # Missing resources and another user's resources are indistinguishable.
        return _error_response(404, "NOT_FOUND", "资源不存在")
    if isinstance(exc, (StoreBusy, TurnInProgress)):
        return _error_response(409, exc.code, exc.message)
    return _error_response(500, "STORE_ERROR", "存储操作未完成")


def _ready_health(engine: Engine, mode: str) -> Health:
    """Validate explicit metadata before claiming an engine is ready."""
    is_mock = getattr(engine, "is_mock", None)
    if type(is_mock) is not bool:
        raise ValueError("engine.is_mock must explicitly be a bool")
    if mode == "real" and is_mock is not False:
        raise ValueError("real mode requires engine.is_mock=False")
    model_version = getattr(engine, "model_version", None)
    if not isinstance(model_version, str) or not model_version.strip():
        raise ValueError("engine.model_version must be a nonempty string")
    if not callable(getattr(engine, "generate", None)):
        raise ValueError("engine.generate must be callable")
    return Health(
        status="ok",
        model_ready=True,
        is_mock=is_mock,
        model_version=model_version,
    )


def create_app(
    *,
    mode: str | None = None,
    config_path: str | None = None,
    engine: Engine | None = None,
    engine_factory: Callable[[], Engine] | None = None,
    store: Store | None = None,
    db_path: str | Path | None = None,
) -> FastAPI:
    """Create the API without opening a database or loading a model.

    ``engine`` and a no-argument ``engine_factory`` are mutually exclusive
    injection points for integration and protocol tests. Neither bypasses
    metadata validation, including real mode's explicit non-mock declaration.
    An injected store stays owned by its caller; the default SQLite store is
    opened and closed by each application lifespan. The engine is initialized
    only once even when an application lifespan is reused.
    """
    selected_mode = os.getenv("B2_MODE", "stub") if mode is None else mode
    if selected_mode not in ("stub", "real"):
        raise ValueError("B2_MODE must be 'stub' or 'real'")
    if engine is not None and engine_factory is not None:
        raise ValueError("provide either engine or engine_factory, not both")
    if store is not None and db_path is not None:
        raise ValueError("provide either store or db_path, not both")
    selected_config = (
        os.getenv("B2_MODEL_CONFIG", "weights/inference_config.json")
        if config_path is None
        else config_path
    )
    owns_store = store is None
    selected_db_path = (
        os.getenv("B2_DB_PATH", ".runtime/b2.sqlite3")
        if db_path is None
        else db_path
    )
    if owns_store and isinstance(selected_db_path, str) and not selected_db_path.strip():
        raise ValueError("B2_DB_PATH must be a nonempty file path")
    secure_setting = os.getenv("B2_COOKIE_SECURE", "0")
    if secure_setting not in ("0", "1"):
        raise ValueError("B2_COOKIE_SECURE must be '0' or '1'")
    cookie_secure = secure_setting == "1"

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if owns_store and application.state.store is None:
            application.state.store = SQLiteStore(selected_db_path)
        if not application.state.initialized:
            # A failed real initialization also counts as attempted: health
            # requests cannot cause retries, model reloads, or a mock fallback.
            application.state.initialized = True
            try:
                if engine is not None:
                    candidate = engine
                elif engine_factory is not None:
                    candidate = engine_factory()
                elif selected_mode == "stub":
                    candidate = StubEngine()
                else:
                    from b2_core.model import ModelEngine

                    candidate = ModelEngine(selected_config)
                ready_health = _ready_health(candidate, selected_mode)
            except Exception as exc:
                application.state.initialization_error = (
                    f"{type(exc).__name__}: {exc}"
                )
                logger.exception(
                    "Engine initialization failed in %s mode; health remains degraded",
                    selected_mode,
                )
            else:
                application.state.engine = candidate
                application.state.health = ready_health
        try:
            yield
        finally:
            if owns_store and application.state.store is not None:
                application.state.store.close()
                application.state.store = None

    application = FastAPI(
        title="伴学匿名会话 API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.initialized = False
    application.state.engine = None
    application.state.initialization_error = None
    application.state.store = store
    application.state.health = Health(
        status="degraded",
        model_ready=False,
        is_mock=selected_mode == "stub",
        model_version="unavailable",
    )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError):
        return _error_response(400, "INVALID_REQUEST", "参数不符合合同，请检查输入字段")

    @application.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        if exc.status_code == 404:
            return _error_response(404, "NOT_FOUND", "资源不存在")
        return _error_response(exc.status_code, "HTTP_ERROR", "请求未完成")

    @application.exception_handler(StoreError)
    async def store_error(_: Request, exc: StoreError):
        return _store_error_response(exc)

    @application.middleware("http")
    async def anonymous_identity(request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        active_store = application.state.store
        if active_store is None:
            return _error_response(503, "STORE_UNAVAILABLE", "存储暂不可用")
        try:
            identity = await run_in_threadpool(
                active_store.resolve_user, request.cookies.get(COOKIE_NAME)
            )
        except StoreError as exc:
            return _store_error_response(exc)
        request.state.user_id = identity.user_id
        if "user_id" in request.query_params:
            response = _error_response(400, "INVALID_REQUEST", "用户身份由服务端确定")
        else:
            response = await call_next(request)
        # Validation errors and missing resources retain the newly generated
        # identity too, so the first failed request does not lose its cookie.
        if identity.cookie_token is not None:
            response.set_cookie(
                COOKIE_NAME,
                identity.cookie_token,
                httponly=True,
                samesite="lax",
                path="/",
                secure=cookie_secure,
            )
        return response

    @application.get("/health", response_model=Health)
    async def health() -> Health:
        return application.state.health

    application.include_router(sessions_router)

    def openapi():
        if application.openapi_schema is None:
            schema = get_openapi(
                title=application.title,
                version=application.version,
                routes=application.routes,
            )
            # Request validation is deliberately 400 here, not FastAPI's
            # default 422. Keep the generated API contract truthful for C.
            for operations in schema["paths"].values():
                for operation in operations.values():
                    responses = operation.get("responses", {})
                    if "400" in responses:
                        responses.pop("422", None)
            application.openapi_schema = schema
        return application.openapi_schema

    application.openapi = openapi
    return application


# Importing this ASGI object creates routes only. Lifespan owns model loading.
app = create_app()
