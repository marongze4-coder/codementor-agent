from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field


class DefenseStage(str, Enum):
    OVERVIEW = "overview"
    DESIGN = "design"
    DEBUGGING = "debugging"
    IMPROVEMENT = "improvement"
    CLOSING = "closing"
    FINISHED = "finished"


class DefenseTurnResult(BaseModel):
    score: int = Field(ge=0, le=100)
    feedback: str
    next_question: str
    evidence: str = ""


class DefenseReport(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    architecture_score: int = Field(ge=0, le=100)
    coding_score: int = Field(ge=0, le=100)
    debugging_score: int = Field(ge=0, le=100)
    communication_score: int = Field(ge=0, le=100)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class DefenseState(TypedDict, total=False):
    messages: list[BaseMessage]
    session_id: str
    thread_id: str
    tenant_id: str
    student_id: str
    user_message: str
    stage: str
    turn_count: int
    history: list[dict[str, Any]]
    assignment_context: dict[str, Any]
    code_review_context: dict[str, Any]
    turn_result: dict[str, Any]
    report: dict[str, Any]
    overall_score: int | None
    structured_output: dict[str, Any]
    fallback_used: bool
