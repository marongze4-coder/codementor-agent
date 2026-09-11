from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from sqlalchemy import text

from backend.agents.assignment.state import AssignmentState
from backend.agents.code_review.nodes import analyze_code_locally
from backend.agents.code_review.prompts import DIMENSIONS
from backend.config import get_settings
from backend.core.code_sandbox import SandboxTestCase, run_python_test, sandbox_status
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal


logger = get_logger(__name__)
settings = get_settings()


async def load_assignment_node(state: AssignmentState) -> dict[str, Any]:
    path = Path(state["source_path"])
    if not path.is_file():
        raise FileNotFoundError(f"提交文件不存在: {path}")
    source = path.read_text(encoding="utf-8", errors="replace")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT a.id, a.title, a.description, a.language, a.entry_file,
                       a.rubric, a.max_score, c.name AS course_name
                FROM assignments a
                JOIN courses c ON c.id = a.course_id
                WHERE a.id = :assignment_id AND a.tenant_id = :tenant_id AND a.is_active = TRUE
                """
            ),
            {"assignment_id": state["assignment_id"], "tenant_id": state["tenant_id"]},
        )
        assignment = result.mappings().first()
        if not assignment:
            raise ValueError("作业不存在或已停用")
        cases = await session.execute(
            text(
                """
                SELECT id, name, input_data, expected_output, timeout_seconds, weight, is_hidden
                FROM assignment_test_cases
                WHERE assignment_id = :assignment_id
                ORDER BY created_at, id
                """
            ),
            {"assignment_id": state["assignment_id"]},
        )
    return {
        "source_code": source,
        "assignment": dict(assignment),
        "test_cases": [
            {key: (str(value) if key == "id" else value) for key, value in row.items()}
            for row in cases.mappings().all()
        ],
    }


async def run_functional_tests_node(state: AssignmentState) -> dict[str, Any]:
    ready, reason = await sandbox_status()
    cases = [SandboxTestCase.model_validate(item) for item in state.get("test_cases", [])]
    if not cases:
        return {
            "sandbox_ready": ready,
            "sandbox_reason": "no_test_cases",
            "test_results": [],
            "functional_score": 0,
            "needs_review": True,
        }
    if state["assignment"].get("language") != "python":
        return {
            "sandbox_ready": False,
            "sandbox_reason": "language_not_supported",
            "test_results": [],
            "functional_score": 0,
            "needs_review": True,
        }

    results = await asyncio.gather(*(run_python_test(state["source_path"], case) for case in cases))
    total_weight = sum(case.weight for case in cases)
    passed_weight = sum(case.weight for case, result in zip(cases, results) if result.passed)
    score = round(100 * passed_weight / total_weight) if total_weight else 0
    return {
        "sandbox_ready": ready,
        "sandbox_reason": reason,
        "test_results": [item.model_dump() for item in results],
        "functional_score": score,
        "needs_review": not ready,
    }


async def run_quality_review_node(state: AssignmentState) -> dict[str, Any]:
    structure, scores = analyze_code_locally(state["source_code"], state["file_name"])
    quality_dimensions = [
        result for key, result in scores.items() if key != "correctness"
    ]
    quality_score = round(sum(item.score for item in quality_dimensions) / len(quality_dimensions))
    issues = [issue.model_dump() for result in scores.values() for issue in result.issues]
    return {
        "dimension_scores": [item.model_dump() for item in scores.values()],
        "quality_score": quality_score,
        "issues": issues,
    }


async def aggregate_assignment_node(state: AssignmentState) -> dict[str, Any]:
    rubric = state["assignment"].get("rubric") or {"functional": 60, "quality": 40}
    if isinstance(rubric, str):
        rubric = json.loads(rubric)
    functional_weight = int(rubric.get("functional", 60))
    quality_weight = int(rubric.get("quality", 40))
    denominator = max(1, functional_weight + quality_weight)
    automatic = round(
        (state.get("functional_score", 0) * functional_weight + state.get("quality_score", 0) * quality_weight)
        / denominator
    )
    if not state.get("sandbox_ready"):
        automatic = round(state.get("quality_score", 0) * quality_weight / denominator)

    failed = [item for item in state.get("test_results", []) if not item.get("passed")]
    weak_points = []
    if failed:
        weak_points.append("测试用例与边界条件")
    for issue in state.get("issues", []):
        dimension = issue.get("dimension")
        if dimension and dimension not in weak_points:
            weak_points.append(dimension)
    weak_points = weak_points[:8]
    needs_review = state.get("needs_review", False) or bool(failed) or automatic < 70
    feedback_parts = [
        f"自动评测得分 {automatic}/100。",
        f"功能测试得分 {state.get('functional_score', 0)}，代码质量得分 {state.get('quality_score', 0)}。",
    ]
    if not state.get("sandbox_ready"):
        feedback_parts.append("代码沙箱未就绪，功能分未计入，必须由教师复核。")
    elif failed:
        feedback_parts.append(f"有 {len(failed)} 个测试用例未通过。")
    else:
        feedback_parts.append("全部自动测试用例通过。")
    feedback = "".join(feedback_parts)
    structured = {
        "submission_id": state["submission_id"],
        "assignment_id": state["assignment_id"],
        "automatic_score": automatic,
        "functional_score": state.get("functional_score", 0),
        "quality_score": state.get("quality_score", 0),
        "sandbox_ready": state.get("sandbox_ready", False),
        "sandbox_reason": state.get("sandbox_reason", "unknown"),
        "test_results": state.get("test_results", []),
        "dimension_scores": state.get("dimension_scores", []),
        "issues": state.get("issues", []),
        "weak_points": weak_points,
        "feedback": feedback,
        "needs_review": needs_review,
    }
    return {
        "automatic_score": automatic,
        "weak_points": weak_points,
        "feedback": feedback,
        "needs_review": needs_review,
        "structured_output": structured,
        "messages": [AIMessage(content=feedback)],
    }


async def save_assignment_review_node(state: AssignmentState) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM test_run_results WHERE submission_id = :submission_id"),
            {"submission_id": state["submission_id"]},
        )
        for item in state.get("test_results", []):
            await session.execute(
                text(
                    """
                    INSERT INTO test_run_results
                        (submission_id, test_case_id, passed, exit_code, duration_ms,
                         stdout, stderr, error_type)
                    VALUES
                        (:submission_id, :test_case_id, :passed, :exit_code, :duration_ms,
                         :stdout, :stderr, :error_type)
                    """
                ),
                {"submission_id": state["submission_id"], **item},
            )
        await session.execute(
            text(
                """
                INSERT INTO assignment_reviews
                    (submission_id, functional_score, quality_score, automatic_score,
                     dimension_scores, issues, feedback, needs_review)
                VALUES
                    (:submission_id, :functional_score, :quality_score, :automatic_score,
                     CAST(:scores AS JSONB), CAST(:issues AS JSONB), :feedback, :needs_review)
                ON CONFLICT (submission_id) DO UPDATE SET
                    functional_score = EXCLUDED.functional_score,
                    quality_score = EXCLUDED.quality_score,
                    automatic_score = EXCLUDED.automatic_score,
                    dimension_scores = EXCLUDED.dimension_scores,
                    issues = EXCLUDED.issues,
                    feedback = EXCLUDED.feedback,
                    needs_review = EXCLUDED.needs_review,
                    updated_at = NOW()
                """
            ),
            {
                "submission_id": state["submission_id"],
                "functional_score": state.get("functional_score", 0),
                "quality_score": state.get("quality_score", 0),
                "automatic_score": state["automatic_score"],
                "scores": json.dumps(state.get("dimension_scores", []), ensure_ascii=False),
                "issues": json.dumps(state.get("issues", []), ensure_ascii=False),
                "feedback": state["feedback"],
                "needs_review": state["needs_review"],
            },
        )
        await session.execute(
            text(
                """
                UPDATE code_submissions
                SET status = 'pending_review', automatic_score = :score,
                    weak_points = CAST(:weak_points AS JSONB), error_msg = NULL,
                    updated_at = NOW()
                WHERE id = :submission_id AND tenant_id = :tenant_id
                """
            ),
            {
                "score": state["automatic_score"],
                "weak_points": json.dumps(state["weak_points"], ensure_ascii=False),
                "submission_id": state["submission_id"],
                "tenant_id": state["tenant_id"],
            },
        )
        await session.commit()
    return {}
