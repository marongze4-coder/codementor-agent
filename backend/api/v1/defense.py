from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.agents.defense.graph import build_defense_graph
from backend.agents.defense.prompts import FALLBACK_QUESTIONS
from backend.dependencies import get_current_user, get_db


router = APIRouter()
_graph = None


class DefenseSessionCreate(BaseModel):
    course_id: str | None = None
    submission_id: str | None = None
    code_review_id: str | None = None


class DefenseMessage(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_defense_graph()
    return _graph


def _jsonable(row) -> dict[str, Any]:
    return {
        key: str(value) if value is not None and (key == "id" or key.endswith("_id")) else value
        for key, value in row.items()
    }


async def _load_owned_session(session_id: str, db: AsyncSession, user: dict) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT id, student_id, course_id, submission_id, code_review_id, thread_id,
                   stage, turn_count, messages, report, overall_score, status,
                   finished_at, created_at, updated_at
            FROM defense_sessions
            WHERE id = :id AND tenant_id = :tenant_id
            """
        ),
        {"id": session_id, "tenant_id": user["tenant_id"]},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="答辩会话不存在")
    if user["role"] == "student" and str(row["student_id"]) != user["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问该答辩会话")
    return _jsonable(row)


@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    owner_filter = "AND ds.student_id = :student_id" if current_user["role"] == "student" else ""
    result = await db.execute(
        text(
            f"""
            SELECT ds.id, ds.student_id, ds.stage, ds.turn_count, ds.overall_score,
                   ds.status, ds.created_at, ds.updated_at,
                   a.title AS assignment_title, cr.original_filename
            FROM defense_sessions ds
            LEFT JOIN code_submissions cs ON cs.id = ds.submission_id
            LEFT JOIN assignments a ON a.id = cs.assignment_id
            LEFT JOIN code_reviews cr ON cr.id = ds.code_review_id
            WHERE ds.tenant_id = :tenant_id {owner_filter}
            ORDER BY ds.created_at DESC
            """
        ),
        {"tenant_id": current_user["tenant_id"], "student_id": current_user["user_id"]},
    )
    return [_jsonable(row) for row in result.mappings().all()]


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: DefenseSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if not body.submission_id and not body.code_review_id:
        raise HTTPException(status_code=400, detail="请选择一次作业提交或代码审查记录作为答辩依据")

    if body.submission_id:
        result = await db.execute(
            text(
                """
                SELECT assignment_id, student_id, a.course_id
                FROM code_submissions cs
                JOIN assignments a ON a.id = cs.assignment_id
                WHERE cs.id = :id AND cs.tenant_id = :tenant_id
                """
            ),
            {"id": body.submission_id, "tenant_id": current_user["tenant_id"]},
        )
        submission = result.mappings().first()
        if not submission:
            raise HTTPException(status_code=404, detail="作业提交不存在")
        if current_user["role"] == "student" and str(submission["student_id"]) != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="不能基于他人的作业创建答辩")
        course_id = str(submission["course_id"])
    else:
        course_id = body.course_id

    if body.code_review_id:
        result = await db.execute(
            text(
                """
                SELECT student_id FROM code_reviews
                WHERE id = :id AND tenant_id = :tenant_id AND status = 'done'
                """
            ),
            {"id": body.code_review_id, "tenant_id": current_user["tenant_id"]},
        )
        review_owner = result.scalar_one_or_none()
        if review_owner is None:
            raise HTTPException(status_code=404, detail="已完成的代码审查记录不存在")
        if current_user["role"] == "student" and str(review_owner) != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="不能基于他人的代码创建答辩")

    session_id = str(uuid.uuid4())
    thread_id = f"student_{current_user['user_id']}_defense_{session_id}"
    first_question = FALLBACK_QUESTIONS["overview"]
    initial_messages = [{"role": "assistant", "content": first_question}]
    await db.execute(
        text(
            """
            INSERT INTO defense_sessions
                (id, tenant_id, student_id, course_id, submission_id, code_review_id,
                 thread_id, messages)
            VALUES
                (:id, :tenant_id, :student_id, :course_id, :submission_id, :code_review_id,
                 :thread_id, CAST(:messages AS JSONB))
            """
        ),
        {
            "id": session_id,
            "tenant_id": current_user["tenant_id"],
            "student_id": current_user["user_id"],
            "course_id": course_id,
            "submission_id": body.submission_id,
            "code_review_id": body.code_review_id,
            "thread_id": thread_id,
            "messages": json.dumps(initial_messages, ensure_ascii=False),
        },
    )
    return {
        "session_id": session_id,
        "thread_id": thread_id,
        "stage": "overview",
        "status": "in_progress",
        "message": first_question,
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _load_owned_session(session_id, db, current_user)


async def _run_turn(session_id: str, message: str, user: dict) -> dict[str, Any]:
    result = await _get_graph().ainvoke(
        {
            "messages": [HumanMessage(content=message)],
            "session_id": session_id,
            "tenant_id": user["tenant_id"],
            "student_id": user["user_id"],
            "user_message": message,
            "fallback_used": False,
        }
    )
    assistant_message = result["messages"][-1]
    content = assistant_message.text if hasattr(assistant_message, "text") else str(assistant_message.content)
    return {
        "session_id": session_id,
        "stage": result.get("stage"),
        "turn_count": result.get("turn_count"),
        "status": "finished" if result.get("stage") == "finished" else "in_progress",
        "message": content,
        "evaluation": result.get("turn_result"),
        "report": result.get("report"),
        "fallback_used": result.get("fallback_used", False),
    }


@router.post("/sessions/{session_id}/chat")
async def chat(
    session_id: str,
    body: DefenseMessage,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    session = await _load_owned_session(session_id, db, current_user)
    if session["status"] == "finished":
        raise HTTPException(status_code=409, detail="答辩已经结束")
    return await _run_turn(session_id, body.message, current_user)


@router.post("/sessions/{session_id}/chat/stream")
async def chat_stream(
    session_id: str,
    body: DefenseMessage,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    session = await _load_owned_session(session_id, db, current_user)
    if session["status"] == "finished":
        raise HTTPException(status_code=409, detail="答辩已经结束")

    async def event_generator():
        yield {"data": json.dumps({"type": "progress", "message": "正在分析回答并准备下一问..."}, ensure_ascii=False)}
        try:
            result = await _run_turn(session_id, body.message, current_user)
            yield {"data": json.dumps({"type": "message", **result}, ensure_ascii=False)}
            yield {"data": json.dumps({"type": "done", "status": result["status"]}, ensure_ascii=False)}
        except Exception as exc:
            yield {"data": json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.get("/sessions/{session_id}/report")
async def get_report(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    session = await _load_owned_session(session_id, db, current_user)
    if session["status"] != "finished":
        raise HTTPException(status_code=409, detail="答辩尚未结束")
    return {
        "session_id": session_id,
        "overall_score": session["overall_score"],
        "report": session["report"],
        "finished_at": session["finished_at"],
    }
