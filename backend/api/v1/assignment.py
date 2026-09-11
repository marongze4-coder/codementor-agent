from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.assignment.graph import build_assignment_graph
from backend.config import get_settings
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user, get_db


router = APIRouter()
logger = get_logger(__name__)
settings = get_settings()
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SUBMISSION_ROOT = PROJECT_ROOT / "storage" / "submissions"
_graph = None


class CourseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    code: str = Field(min_length=2, max_length=32)
    description: str = ""
    primary_language: str = "python"


class AssignmentCreate(BaseModel):
    course_id: str
    title: str = Field(min_length=2, max_length=256)
    description: str = Field(min_length=2)
    language: str = "python"
    entry_file: str = "main.py"
    rubric: dict[str, int] = Field(default_factory=lambda: {"functional": 60, "quality": 40})
    max_score: int = Field(default=100, gt=0, le=1000)
    due_date: datetime | None = None


class TestCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    input_data: str = ""
    expected_output: str
    timeout_seconds: int = Field(default=3, ge=1, le=30)
    weight: int = Field(default=1, gt=0, le=100)
    is_hidden: bool = True


class SubmissionCreated(BaseModel):
    submission_id: str
    status: str


class ReviewDecision(BaseModel):
    score: int = Field(ge=0, le=100)
    comment: str = Field(default="", max_length=2000)


def _require_teacher(user: dict) -> None:
    if user["role"] not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="仅教师或管理员可以执行此操作")


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_assignment_graph()
    return _graph


def _jsonable_row(row) -> dict[str, Any]:
    return {
        key: (str(value) if value is not None and (key.endswith("_id") or key == "id") else value)
        for key, value in row.items()
    }


async def _mark_submission_failed(submission_id: str, tenant_id: str, error: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE code_submissions
                SET status = 'failed', error_msg = :error, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tenant_id
                """
            ),
            {"id": submission_id, "tenant_id": tenant_id, "error": error[:2000]},
        )
        await session.commit()


async def _run_evaluation(
    submission_id: str,
    assignment_id: str,
    student_id: str,
    tenant_id: str,
    source_path: str,
    file_name: str,
) -> None:
    try:
        await _get_graph().ainvoke(
            {
                "messages": [],
                "submission_id": submission_id,
                "assignment_id": assignment_id,
                "student_id": student_id,
                "tenant_id": tenant_id,
                "source_path": source_path,
                "file_name": file_name,
                "fallback_used": False,
            }
        )
    except Exception as exc:
        logger.error("assignment.evaluation_failed", submission_id=submission_id, error=str(exc), exc_info=True)
        await _mark_submission_failed(submission_id, tenant_id, str(exc))


@router.get("/courses")
async def list_courses(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        text(
            """
            SELECT id, name, code, description, primary_language, is_active, created_at
            FROM courses
            WHERE tenant_id = :tenant_id AND is_active = TRUE
            ORDER BY created_at DESC
            """
        ),
        {"tenant_id": current_user["tenant_id"]},
    )
    return [_jsonable_row(row) for row in result.mappings().all()]


@router.post("/courses", status_code=status.HTTP_201_CREATED)
async def create_course(
    body: CourseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_teacher(current_user)
    course_id = str(uuid.uuid4())
    try:
        await db.execute(
            text(
                """
                INSERT INTO courses
                    (id, tenant_id, name, code, description, primary_language, created_by)
                VALUES
                    (:id, :tenant_id, :name, :code, :description, :language, :created_by)
                """
            ),
            {
                "id": course_id,
                "tenant_id": current_user["tenant_id"],
                "name": body.name,
                "code": body.code.upper(),
                "description": body.description,
                "language": body.primary_language,
                "created_by": current_user["user_id"],
            },
        )
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="课程编号已存在") from exc
        raise
    return {"course_id": course_id, "status": "created"}


@router.get("")
async def list_assignments(
    course_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    where = "a.tenant_id = :tenant_id AND a.is_active = TRUE"
    params: dict[str, Any] = {"tenant_id": current_user["tenant_id"]}
    if course_id:
        where += " AND a.course_id = :course_id"
        params["course_id"] = course_id
    result = await db.execute(
        text(
            f"""
            SELECT a.id, a.course_id, c.name AS course_name, a.title, a.description,
                   a.language, a.entry_file, a.rubric, a.max_score, a.due_date, a.created_at
            FROM assignments a
            JOIN courses c ON c.id = a.course_id
            WHERE {where}
            ORDER BY a.created_at DESC
            """
        ),
        params,
    )
    return [_jsonable_row(row) for row in result.mappings().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_assignment(
    body: AssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_teacher(current_user)
    if body.language != "python":
        raise HTTPException(status_code=400, detail="当前代码沙箱只支持 Python 作业")
    assignment_id = str(uuid.uuid4())
    result = await db.execute(
        text(
            """
            INSERT INTO assignments
                (id, tenant_id, course_id, title, description, language, entry_file,
                 rubric, max_score, due_date, created_by)
            SELECT :id, :tenant_id, id, :title, :description, :language, :entry_file,
                   CAST(:rubric AS JSONB), :max_score, :due_date, :created_by
            FROM courses
            WHERE id = :course_id AND tenant_id = :tenant_id AND is_active = TRUE
            RETURNING id
            """
        ),
        {
            "id": assignment_id,
            "tenant_id": current_user["tenant_id"],
            "course_id": body.course_id,
            "title": body.title,
            "description": body.description,
            "language": body.language,
            "entry_file": Path(body.entry_file).name,
            "rubric": json.dumps(body.rubric),
            "max_score": body.max_score,
            "due_date": body.due_date,
            "created_by": current_user["user_id"],
        },
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="课程不存在或已停用")
    return {"assignment_id": assignment_id, "status": "created"}


@router.post("/{assignment_id}/test-cases", status_code=status.HTTP_201_CREATED)
async def create_test_case(
    assignment_id: str,
    body: TestCaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_teacher(current_user)
    test_id = str(uuid.uuid4())
    result = await db.execute(
        text(
            """
            INSERT INTO assignment_test_cases
                (id, assignment_id, name, input_data, expected_output,
                 timeout_seconds, weight, is_hidden)
            SELECT :id, a.id, :name, :input_data, :expected_output,
                   :timeout_seconds, :weight, :is_hidden
            FROM assignments a
            WHERE a.id = :assignment_id AND a.tenant_id = :tenant_id
            RETURNING id
            """
        ),
        {
            "id": test_id,
            "assignment_id": assignment_id,
            "tenant_id": current_user["tenant_id"],
            **body.model_dump(),
        },
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="作业不存在")
    return {"test_case_id": test_id, "status": "created"}


@router.post("/{assignment_id}/submit", response_model=SubmissionCreated, status_code=202)
async def submit_assignment(
    assignment_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    file_name = Path(file.filename or "main.py").name
    suffix = Path(file_name).suffix.lower()
    if suffix != ".py":
        raise HTTPException(status_code=400, detail="当前实训作业只接受 .py 文件")
    content = await file.read(settings.max_code_upload_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="提交文件为空")
    if len(content) > settings.max_code_upload_bytes:
        raise HTTPException(status_code=413, detail="代码文件超过大小限制")

    assignment_exists = await db.execute(
        text(
            """
            SELECT 1 FROM assignments
            WHERE id = :id AND tenant_id = :tenant_id AND is_active = TRUE
            """
        ),
        {"id": assignment_id, "tenant_id": current_user["tenant_id"]},
    )
    if not assignment_exists.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="作业不存在或已停用")

    submission_id = str(uuid.uuid4())
    destination = SUBMISSION_ROOT / current_user["tenant_id"] / assignment_id / submission_id
    destination.mkdir(parents=True, exist_ok=True)
    source_path = destination / file_name
    source_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    await db.execute(
        text(
            """
            INSERT INTO code_submissions
                (id, tenant_id, assignment_id, student_id, original_filename,
                 source_path, source_sha256, status)
            VALUES
                (:id, :tenant_id, :assignment_id, :student_id, :file_name,
                 :source_path, :digest, 'evaluating')
            """
        ),
        {
            "id": submission_id,
            "tenant_id": current_user["tenant_id"],
            "assignment_id": assignment_id,
            "student_id": current_user["user_id"],
            "file_name": file_name,
            "source_path": str(source_path),
            "digest": digest,
        },
    )
    await db.commit()
    background_tasks.add_task(
        _run_evaluation,
        submission_id,
        assignment_id,
        current_user["user_id"],
        current_user["tenant_id"],
        str(source_path),
        file_name,
    )
    return SubmissionCreated(submission_id=submission_id, status="evaluating")


@router.get("/submissions")
async def list_submissions(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    owner_filter = "AND s.student_id = :student_id" if current_user["role"] == "student" else ""
    result = await db.execute(
        text(
            f"""
            SELECT s.id, s.student_id, s.original_filename, s.status, s.automatic_score,
                   s.final_score, s.submitted_at, a.title AS assignment_title,
                   c.name AS course_name
            FROM code_submissions s
            JOIN assignments a ON a.id = s.assignment_id
            JOIN courses c ON c.id = a.course_id
            WHERE s.tenant_id = :tenant_id {owner_filter}
            ORDER BY s.submitted_at DESC
            LIMIT 100
            """
        ),
        {"tenant_id": current_user["tenant_id"], "student_id": current_user["user_id"]},
    )
    return [_jsonable_row(row) for row in result.mappings().all()]


@router.get("/submissions/{submission_id}")
async def get_submission(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        text(
            """
            SELECT s.id, s.assignment_id, s.student_id, s.original_filename, s.status,
                   s.automatic_score, s.teacher_score, s.final_score, s.weak_points,
                   s.error_msg, s.submitted_at, s.published_at,
                   a.title AS assignment_title, c.name AS course_name,
                   r.functional_score, r.quality_score, r.dimension_scores,
                   r.issues, r.feedback, r.needs_review, r.teacher_comment
            FROM code_submissions s
            JOIN assignments a ON a.id = s.assignment_id
            JOIN courses c ON c.id = a.course_id
            LEFT JOIN assignment_reviews r ON r.submission_id = s.id
            WHERE s.id = :id AND s.tenant_id = :tenant_id
            """
        ),
        {"id": submission_id, "tenant_id": current_user["tenant_id"]},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="提交记录不存在")
    if current_user["role"] == "student" and str(row["student_id"]) != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权查看该提交")

    tests = await db.execute(
        text(
            """
            SELECT tr.test_case_id, tc.name, tc.is_hidden, tr.passed, tr.exit_code,
                   tr.duration_ms, tr.stdout, tr.stderr, tr.error_type
            FROM test_run_results tr
            LEFT JOIN assignment_test_cases tc ON tc.id = tr.test_case_id
            WHERE tr.submission_id = :submission_id
            ORDER BY tr.created_at
            """
        ),
        {"submission_id": submission_id},
    )
    test_rows = [_jsonable_row(item) for item in tests.mappings().all()]
    if current_user["role"] == "student":
        for item in test_rows:
            if item.get("is_hidden"):
                item["stdout"] = ""
                item["stderr"] = "" if item.get("passed") else "隐藏测试未通过"
    payload = _jsonable_row(row)
    payload["test_results"] = test_rows
    return payload


@router.get("/pending-reviews")
async def list_pending_reviews(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_teacher(current_user)
    result = await db.execute(
        text(
            """
            SELECT s.id, s.assignment_id, s.student_id, s.original_filename,
                   s.automatic_score, s.submitted_at, a.title AS assignment_title,
                   u.username AS student_name
            FROM code_submissions s
            JOIN assignments a ON a.id = s.assignment_id
            JOIN users u ON u.id = s.student_id
            WHERE s.tenant_id = :tenant_id AND s.status = 'pending_review'
            ORDER BY s.submitted_at
            """
        ),
        {"tenant_id": current_user["tenant_id"]},
    )
    return [_jsonable_row(row) for row in result.mappings().all()]


@router.post("/submissions/{submission_id}/confirm")
async def confirm_submission(
    submission_id: str,
    body: ReviewDecision,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_teacher(current_user)
    result = await db.execute(
        text(
            """
            UPDATE code_submissions
            SET teacher_score = :score, final_score = :score, status = 'published',
                published_at = NOW(), updated_at = NOW()
            WHERE id = :id AND tenant_id = :tenant_id AND status = 'pending_review'
            RETURNING id
            """
        ),
        {
            "id": submission_id,
            "tenant_id": current_user["tenant_id"],
            "score": body.score,
        },
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="提交不存在或当前状态不可发布")
    await db.execute(
        text(
            """
            UPDATE assignment_reviews
            SET needs_review = FALSE, teacher_comment = :comment,
                reviewed_by = :reviewer, reviewed_at = NOW(), updated_at = NOW()
            WHERE submission_id = :submission_id
            """
        ),
        {
            "submission_id": submission_id,
            "comment": body.comment,
            "reviewer": current_user["user_id"],
        },
    )
    return {"submission_id": submission_id, "status": "published", "final_score": body.score}
