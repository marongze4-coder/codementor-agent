from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field


class CodeIssue(BaseModel):
    dimension: str = Field(description="所属评审维度")
    severity: str = Field(description="critical/high/medium/low")
    title: str = Field(description="问题标题")
    evidence: str = Field(default="", description="代码证据或定位说明")
    line: int | None = Field(default=None, ge=1, description="代码行号")
    suggestion: str = Field(description="可执行的修改建议")


class CodeStructure(BaseModel):
    language: str
    file_name: str
    line_count: int = 0
    classes: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    syntax_valid: bool = True
    syntax_error: str | None = None


class DimensionScore(BaseModel):
    dimension: str
    score: int = Field(ge=0, le=100)
    summary: str
    issues: list[CodeIssue] = Field(default_factory=list)


class CodeReviewSummary(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    grade: str
    strengths: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class CodeReviewState(TypedDict, total=False):
    messages: list[BaseMessage]
    review_id: str
    tenant_id: str
    student_id: str
    source_path: str
    file_name: str
    language: str
    source_code: str
    structure: dict[str, Any]
    dimension_scores: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    summary: dict[str, Any]
    overall_score: int
    structured_output: dict[str, Any]
    fallback_used: bool
    error_msg: str | None
