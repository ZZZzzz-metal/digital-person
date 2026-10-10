"""User-confirmed memory management; no automatic extraction or model call."""

from fastapi import APIRouter, Request

from b2_core.contracts import (
    ErrorResponse,
    Identifier,
    MemoryItem,
    MemoryKey,
    MemoryList,
    MemorySave,
    MemorySettings,
    OkResponse,
)


router = APIRouter(
    prefix="/api/memories",
    tags=["memories"],
    responses={
        400: {"model": ErrorResponse, "description": "参数不符合合同"},
        404: {"model": ErrorResponse, "description": "资源不存在或不属当前用户"},
        409: {"model": ErrorResponse, "description": "记忆已关闭或存储繁忙"},
    },
)


@router.get("", response_model=MemoryList)
def list_memories(request: Request) -> MemoryList:
    return request.app.state.store.list_memories(request.state.user_id)


# This fixed path must precede /{key}; otherwise "settings" would be parsed
# as a memory key and rejected before the settings body could be validated.
@router.put("/settings", response_model=MemoryList)
def set_memory_enabled(body: MemorySettings, request: Request) -> MemoryList:
    return request.app.state.store.set_memory_enabled(
        request.state.user_id, body.enabled
    )


@router.put("/{key}", response_model=MemoryItem)
def save_memory(key: MemoryKey, body: MemorySave, request: Request) -> MemoryItem:
    return request.app.state.store.save_memory(
        request.state.user_id, key, body.value
    )


@router.delete("/{memory_id}", response_model=OkResponse)
def delete_memory(memory_id: Identifier, request: Request) -> OkResponse:
    # Explicit deletion remains available while memory is disabled.
    request.app.state.store.delete_memory(request.state.user_id, memory_id)
    return OkResponse()


@router.delete("", response_model=OkResponse)
def clear_memories(request: Request) -> OkResponse:
    # Clearing neither reenables memory nor changes another user's data.
    request.app.state.store.clear_memories(request.state.user_id)
    return OkResponse()
