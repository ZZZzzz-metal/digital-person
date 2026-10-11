"""Four B2 session routes; identity and store ownership belong to the app."""

from fastapi import APIRouter, Request

from b2_core.contracts import ErrorResponse, Identifier, Message, OkResponse, SessionCreate, SessionDTO


router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"],
    responses={
        400: {"model": ErrorResponse, "description": "参数不符合合同"},
        404: {"model": ErrorResponse, "description": "资源不存在或不属当前用户"},
        409: {"model": ErrorResponse, "description": "存储繁忙或会话正在处理"},
    },
)


@router.post("", response_model=SessionDTO)
def create_session(body: SessionCreate, request: Request) -> SessionDTO:
    return request.app.state.store.create_session(request.state.user_id, body.title)


@router.get("", response_model=list[SessionDTO])
def list_sessions(request: Request) -> list[SessionDTO]:
    return request.app.state.store.list_sessions(request.state.user_id)


@router.get("/{session_id}/messages", response_model=list[Message])
def get_messages(session_id: Identifier, request: Request) -> list[Message]:
    return request.app.state.store.get_messages(request.state.user_id, session_id)


@router.delete("/{session_id}", response_model=OkResponse)
def delete_session(session_id: Identifier, request: Request) -> OkResponse:
    request.app.state.store.delete_session(request.state.user_id, session_id)
    return OkResponse()
