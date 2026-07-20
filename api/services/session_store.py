from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.db.models import AnalysisSnapshot, ChatMessage, ChatSession
from src.utils.session_context import SessionContext
from src.utils.state_definition import AgentState


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_to_dict(session: ChatSession) -> dict:
    return {
        "id": session.id,
        "title": session.title,
        "company_name": session.company_name,
        "stock_code": session.stock_code,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _message_to_dict(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "message_type": message.message_type,
        "created_at": message.created_at,
    }


class SessionStore:
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id

    def list_sessions(self) -> list[dict]:
        rows = (
            self.db.query(ChatSession)
            .filter(ChatSession.user_id == self.user_id)
            .order_by(ChatSession.updated_at.desc())
            .all()
        )
        return [_session_to_dict(row) for row in rows]

    def create_session(self, title: str = "新对话") -> dict:
        now = _now_iso()
        row = ChatSession(
            id=str(uuid.uuid4()),
            user_id=self.user_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return _session_to_dict(row)

    def get_session(self, session_id: str) -> ChatSession | None:
        return (
            self.db.query(ChatSession)
            .filter(
                ChatSession.id == session_id,
                ChatSession.user_id == self.user_id,
            )
            .first()
        )

    def get_session_detail(self, session_id: str) -> dict | None:
        row = self.get_session(session_id)
        if not row:
            return None
        detail = _session_to_dict(row)
        detail["messages"] = [_message_to_dict(m) for m in row.messages]
        return detail

    def update_session_title(self, session_id: str, title: str) -> dict | None:
        row = self.get_session(session_id)
        if not row:
            return None
        row.title = title
        row.updated_at = _now_iso()
        self.db.commit()
        self.db.refresh(row)
        return _session_to_dict(row)

    def delete_session(self, session_id: str) -> bool:
        row = self.get_session(session_id)
        if not row:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def add_user_message(self, session_id: str, content: str) -> dict | None:
        row = self.get_session(session_id)
        if not row:
            return None
        message = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="user",
            content=content,
            message_type="text",
            created_at=_now_iso(),
        )
        row.updated_at = message.created_at
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return _message_to_dict(message)

    def add_assistant_message(
        self,
        session_id: str,
        content: str,
        *,
        message_type: str = "text",
    ) -> dict | None:
        row = self.get_session(session_id)
        if not row:
            return None
        message = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content=content,
            message_type=message_type,
            created_at=_now_iso(),
        )
        row.updated_at = message.created_at
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return _message_to_dict(message)

    def save_snapshot(
        self,
        session_id: str,
        state: AgentState,
        *,
        report_path: str | None = None,
    ) -> None:
        row = self.get_session(session_id)
        if not row:
            return

        data = dict(state.get("data", {}))
        snapshot = self.db.query(AnalysisSnapshot).filter(
            AnalysisSnapshot.session_id == session_id
        ).first()
        payload = json.dumps(data, ensure_ascii=False)
        now = _now_iso()
        if snapshot:
            snapshot.state_json = payload
            snapshot.report_path = report_path
            snapshot.updated_at = now
        else:
            snapshot = AnalysisSnapshot(
                session_id=session_id,
                state_json=payload,
                report_path=report_path,
                updated_at=now,
            )
            self.db.add(snapshot)

        row.company_name = data.get("company_name")
        row.stock_code = data.get("stock_code")
        if data.get("company_name") and row.title == "新对话":
            row.title = str(data["company_name"])
        row.updated_at = now
        self.db.commit()

        if data.get("final_report"):
            try:
                from src.rag import get_report_rag

                get_report_rag().index_analysis(self.user_id, session_id, data)
            except Exception:
                pass

    def load_session_context(self, session_id: str) -> SessionContext | None:
        row = self.get_session(session_id)
        if not row:
            return None

        ctx = SessionContext()
        for message in row.messages:
            if message.role == "user":
                ctx.append_user(message.content)
            elif message.role == "assistant":
                ctx.append_assistant(message.content)

        snapshot = row.snapshot
        if snapshot:
            data = json.loads(snapshot.state_json)
            ctx.last_state = AgentState(
                messages=[],
                data=data,
                metadata={},
            )
            ctx.turn_count = sum(1 for m in row.messages if m.role == "user")
        return ctx

    def get_report(self, session_id: str) -> str | None:
        row = self.get_session(session_id)
        if not row or not row.snapshot:
            return None
        data = json.loads(row.snapshot.state_json)
        return data.get("final_report")
