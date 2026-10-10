"""Demo chat orchestration; only a completed HTTP turn writes messages.

The worker has no store access. A timed-out Python thread cannot be stopped;
its late result is discarded and the shared engine gate stays locked until the
actual calculation finishes, including across reused application lifespans.
"""

from __future__ import annotations

import asyncio
import logging
from _thread import LockType
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from time import perf_counter

from fastapi import APIRouter, Request

from b2_core.contracts import ChatRequest, ChatResponse, CoreReply, CoreRequest, Engine, ErrorResponse
from b2_core.memory import build_memory_context
from b2_core.turn import build_core_request, run_turn


logger = logging.getLogger(__name__)


class ChatError(RuntimeError):
    """A public, generic model error that carries no prompt or exception text."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class ModelBusy(RuntimeError):
    pass


class InferenceWorker:
    """One generation at a time, with an application-owned reusable gate.

    shutdown(wait=False) returns without killing a running model call. A new
    worker for the same app must receive the same gate, so closing/reopening a
    lifespan cannot run the same engine concurrently with that old call.
    """

    def __init__(self, gate: LockType) -> None:
        self._gate = gate
        self._state_lock = Lock()
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="b2-inference")

    @property
    def closed(self) -> bool:
        with self._state_lock:
            return self._closed

    def submit(self, request: CoreRequest, engine: Engine) -> Future[CoreReply]:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("inference worker is closed")
            if not self._gate.acquire(blocking=False):
                raise ModelBusy()
            try:
                future = self._executor.submit(run_turn, request, engine)
            except BaseException:
                self._gate.release()
                raise
            # A cancelled/expired HTTP await must not release this gate early.
            future.add_done_callback(lambda _: self._gate.release())
            return future

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


def _observe_future(future: asyncio.Future) -> None:
    # Retrieve late exceptions too, preventing asyncio from logging raw model
    # exceptions (which may contain sensitive inputs) after an HTTP timeout.
    if not future.cancelled():
        future.exception()


router = APIRouter(
    prefix="/api",
    tags=["chat"],
    responses={
        400: {"model": ErrorResponse, "description": "参数不符合合同"},
        404: {"model": ErrorResponse, "description": "资源不存在或不属当前用户"},
        409: {"model": ErrorResponse, "description": "会话正在处理请求或存储繁忙"},
        503: {"model": ErrorResponse, "description": "模型不可用、繁忙或超时"},
    },
)


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    store = request.app.state.store
    # These are short storage transactions. No cancellation await intervenes
    # between obtaining a reservation and recording its cleanup obligation, or
    # between atomic completion and marking the request completed.
    reservation = store.reserve_turn(request.state.user_id, body.session_id, body.client_turn_id)
    if isinstance(reservation, ChatResponse):
        return reservation
    completed = False
    try:
        engine = request.app.state.engine
        health = request.app.state.health
        worker = request.app.state.inference_worker
        if engine is None or not health.model_ready or worker is None:
            raise ChatError("MODEL_UNAVAILABLE", "模型暂不可用")
        started = perf_counter()
        # Only actual storage exceptions use the shared StoreError handler.
        # A model that raises an identically named exception remains a model
        # failure and must not turn into an ownership/storage response.
        history = store.get_messages(request.state.user_id, body.session_id)
        memories = store.list_memories(request.state.user_id)
        try:
            context = build_memory_context(body.text, memories.items if memories.enabled else [])
            core_request = build_core_request(body.text, history, context.prompt_text)
            concurrent_future = worker.submit(core_request, engine)
        except ModelBusy:
            raise ChatError("MODEL_BUSY", "模型正在处理其他请求，请稍后重试") from None
        except Exception:
            raise ChatError("MODEL_UNAVAILABLE", "模型暂不可用") from None
        try:
            wrapped = asyncio.wrap_future(concurrent_future)
            wrapped.add_done_callback(_observe_future)
            done, _ = await asyncio.wait(
                {wrapped}, timeout=request.app.state.chat_timeout_seconds
            )
        except Exception:
            raise ChatError("MODEL_UNAVAILABLE", "模型暂不可用") from None
        # wait never cancels the underlying future on timeout/cancellation
        # and works on the declared Python 3.10 runtime too. Only our own wait
        # deadline produces MODEL_TIMEOUT; all exceptions from generate,
        # including ChatError and TimeoutError, take the generic result path.
        if not done:
            raise ChatError("MODEL_TIMEOUT", "模型响应超时，请稍后重试") from None
        try:
            reply = wrapped.result()
            # Retain the startup metadata boundary even if an injected engine
            # mutates its metadata later; real health cannot emit mock success.
            if reply.is_mock != health.is_mock or reply.model_version != health.model_version:
                raise ValueError("reply metadata differs from startup metadata")
            response = ChatResponse(
                session_id=body.session_id,
                client_turn_id=body.client_turn_id,
                reply=reply.reply,
                emotion=reply.emotion,
                expression=reply.expression,
                retrieved_memories=context.retrieved_memories,
                model_version=reply.model_version,
                elapsed_ms=max(0, int((perf_counter() - started) * 1000)),
                is_mock=reply.is_mock,
            )
        except Exception:
            # No input, stack trace, or underlying model exception is logged.
            raise ChatError("MODEL_UNAVAILABLE", "模型暂不可用") from None
        store.complete_turn(reservation, body.text, response)
        completed = True
        return response
    finally:
        # CancelledError is a BaseException, so cancellation also reaches this
        # cleanup. Only this reservation's token can release its pending turn.
        if not completed:
            try:
                store.abort_turn(reservation)
            except Exception as exc:
                # A failed storage cleanup leaves lease expiry as recovery;
                # preserve the original error and never expose its contents.
                logger.warning("Turn cleanup did not complete (%s)", type(exc).__name__)
