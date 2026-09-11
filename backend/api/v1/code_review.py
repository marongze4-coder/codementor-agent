from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.code_review.graph import build_code_review_graph
from backend.agents.code_review.nodes import LANGUAGE_BY_SUFFIX
from backend.config import get_settings
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user, get_db


router = APIRouter()
logger = get_logger(__name__)
settings = get_settings()
_graph = None


class ReviewCreated(BaseModel):
    review_id: str
    status: str
    file_name: str


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_code_review_graph()
    return _graph


async def _mark_failed(review_id: str, tenant_id: str, error: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE code_reviews
                SET status = 'failed', error_msg = :error, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tenant_id
                """
            ),
            {"id": review_id, "tenant_id": tenant_id, "error": error[:2000]},
        )
        await session.commit()


async def _run_review(
    review_id: str,
    tenant_id: str,
    student_id: str,
    source_path: str,
    file_name: str,
) -> None:
    try:
        await _get_graph().ainvoke(
            {
                "review_id": review_id,
                "tenant_id": tenant_id,
                "student_id": student_id,
                "source_path": source_path,
                "file_name": file_name,
                "messages": [],
                "fallback_used": False,
            }
        )
    except Exception as exc:
        logger.error("code_review.background_failed", review_id=review_id, error=str(exc), exc_info=True)
        await _mark_failed(review_id, tenant_id, str(exc))
    finally:
        try:
            os.unlink(source_path)
        except FileNotFoundError:
            pass


@router.post("/submit", response_model=ReviewCreated, status_code=status.HTTP_202_ACCEPTED)
async def submit_code_review(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    original_name = Path(file.filename or "submission.py").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in LANGUAGE_BY_SUFFIX:
        supported = ", ".join(sorted(LANGUAGE_BY_SUFFIX))
        raise HTTPException(status_code=400, detail=f"不支持该文件类型，可上传：{supported}")

    content = await file.read(settings.max_code_upload_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="上传的代码文件为空")
    if len(content) > settings.max_code_upload_bytes:
        raise HTTPException(status_code=413, detail="代码文件超过大小限制")

    upload_dir = Path(tempfile.gettempdir()) / "codementor" / "code_reviews"
    upload_dir.mkdir(parents=True, exist_ok=True)
    review_id = str(uuid.uuid4())
    source_path = upload_dir / f"{review_id}{suffix}"
    source_path.write_bytes(content)

    await db.execute(
        text(
            """
            INSERT INTO code_reviews
                (id, tenant_id, student_id, original_filename, source_path, status)
            VALUES
                (:id, :tenant_id, :student_id, :file_name, :source_path, 'processing')
            """
        ),
        {
            "id": review_id,
            "tenant_id": current_user["tenant_id"],
            "student_id": current_user["user_id"],
            "file_name": original_name,
            "source_path": str(source_path),
        },
    )
    await db.commit()
    background_tasks.add_task(
        _run_review,
        review_id,
        current_user["tenant_id"],
        current_user["user_id"],
        str(source_path),
        original_name,
    )
    return ReviewCreated(review_id=review_id, status="processing", file_name=original_name)


@router.get("/reviews/{review_id}")
async def get_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT id, student_id, original_filename, language, code_structure,
                   dimension_scores, issues, summary, overall_score, status,
                   error_msg, created_at, updated_at
            FROM code_reviews
            WHERE id = :id AND tenant_id = :tenant_id
            """
        ),
        {"id": review_id, "tenant_id": current_user["tenant_id"]},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="代码审查记录不存在")
    if current_user["role"] == "student" and str(row["student_id"]) != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权查看该审查记录")
    return {key: (str(value) if key in {"id", "student_id"} and value is not None else value) for key, value in row.items()}


@router.get("/reviews")
async def list_reviews(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    filters = "tenant_id = :tenant_id"
    params: dict[str, Any] = {"tenant_id": current_user["tenant_id"], "limit": limit}
    if current_user["role"] == "student":
        filters += " AND student_id = :student_id"
        params["student_id"] = current_user["user_id"]
    result = await db.execute(
        text(
            f"""
            SELECT id, student_id, original_filename, language, overall_score,
                   status, created_at, updated_at
            FROM code_reviews
            WHERE {filters}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        {key: (str(value) if key in {"id", "student_id"} and value is not None else value) for key, value in row.items()}
        for row in result.mappings().all()
    ]


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    filters = "id = :id AND tenant_id = :tenant_id"
    params = {"id": review_id, "tenant_id": current_user["tenant_id"]}
    if current_user["role"] == "student":
        filters += " AND student_id = :student_id"
        params["student_id"] = current_user["user_id"]
    result = await db.execute(text(f"DELETE FROM code_reviews WHERE {filters}"), params)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="代码审查记录不存在")
    return None
