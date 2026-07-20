from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.db.database import get_db
from api.db.models import User
from api.deps import get_current_user
from api.schemas.chat import SessionDetailOut, SessionOut, SessionUpdateRequest
from api.services.session_store import SessionStore

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _store(db: Session, user: User) -> SessionStore:
    return SessionStore(db, user.id)


@router.get("", response_model=list[SessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _store(db, current_user).list_sessions()


@router.post("", response_model=SessionOut, status_code=201)
def create_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _store(db, current_user).create_session()


@router.get("/{session_id}", response_model=SessionDetailOut)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    detail = _store(db, current_user).get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="会话不存在")
    return detail


@router.patch("/{session_id}", response_model=SessionOut)
def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updated = _store(db, current_user).update_session_title(session_id, body.title)
    if not updated:
        raise HTTPException(status_code=404, detail="会话不存在")
    return updated


@router.delete("/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _store(db, current_user).delete_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")


@router.get("/{session_id}/report")
def get_session_report(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = _store(db, current_user).get_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="暂无报告")
    return {"content": report}
