from typing import List, Optional

from pydantic import BaseModel, Field


class HistoryTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str = ""
    doc_ids: Optional[List[str]] = None  # None / empty => search every uploaded paper
    history: List[HistoryTurn] = Field(default_factory=list)


class Source(BaseModel):
    id: int
    document: str
    doc_id: str
    page: Optional[int] = None
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    found: bool
    sources: List[Source]
    passages_read: int
    documents_searched: int
