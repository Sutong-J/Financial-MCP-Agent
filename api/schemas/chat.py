from pydantic import BaseModel, Field


class SessionOut(BaseModel):
    id: str
    title: str
    company_name: str | None = None
    stock_code: str | None = None
    created_at: str
    updated_at: str


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    message_type: str
    created_at: str


class SessionDetailOut(SessionOut):
    messages: list[ChatMessageOut] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class SessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1)
