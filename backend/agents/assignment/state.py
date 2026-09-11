from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import BaseMessage


class AssignmentState(TypedDict, total=False):
    messages: list[BaseMessage]
    submission_id: str
    assignment_id: str
    student_id: str
    tenant_id: str
    source_path: str
    file_name: str
    source_code: str
    assignment: dict[str, Any]
    test_cases: list[dict[str, Any]]
    sandbox_ready: bool
    sandbox_reason: str
    test_results: list[dict[str, Any]]
    functional_score: int
    quality_score: int
    automatic_score: int
    dimension_scores: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    weak_points: list[str]
    feedback: str
    needs_review: bool
    structured_output: dict[str, Any]
    fallback_used: bool
    error_msg: str | None
