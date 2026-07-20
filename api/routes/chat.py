from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.db.database import get_db
from api.db.models import User
from api.deps import get_current_user
from api.schemas.chat import ChatRequest
from api.services.analysis_service import stream_chat_turn

router = APIRouter(tags=["chat"])


@router.post("/sessions/{session_id}/chat")
async def chat_with_session(
    session_id: str,
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow_app = request.app.state.workflow
    if workflow_app is None:
        raise HTTPException(status_code=503, detail="工作流未初始化")

    async def event_stream():
        async for chunk in stream_chat_turn(
            db,
            workflow_app,
            session_id,
            current_user.id,
            body.message.strip(),
        ):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
