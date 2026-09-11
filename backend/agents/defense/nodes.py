from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import text

from backend.agents.defense.prompts import (
    DEFENSE_SYSTEM_PROMPT,
    FALLBACK_QUESTIONS,
    REPORT_PROMPT,
    TURN_PROMPT,
)
from backend.agents.defense.state import DefenseReport, DefenseStage, DefenseState, DefenseTurnResult
from backend.config import get_settings
from backend.core.llm_factory import get_structured_llm
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal


logger = get_logger(__name__)
settings = get_settings()
STAGES = ["overview", "design", "debugging", "improvement", "closing"]
END_KEYWORDS = {"结束答辩", "结束", "提交报告", "finish", "stop"}


async def load_defense_context_node(state: DefenseState) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT ds.stage, ds.turn_count, ds.messages, ds.submission_id, ds.code_review_id,
                       a.title AS assignment_title, a.description AS assignment_description,
                       cs.automatic_score, cs.weak_points,
                       ar.feedback AS assignment_feedback, ar.issues AS assignment_issues,
                       cr.original_filename, cr.overall_score AS code_review_score,
                       cr.issues AS code_review_issues, cr.summary AS code_review_summary
                FROM defense_sessions ds
                LEFT JOIN code_submissions cs ON cs.id = ds.submission_id
                LEFT JOIN assignments a ON a.id = cs.assignment_id
                LEFT JOIN assignment_reviews ar ON ar.submission_id = cs.id
                LEFT JOIN code_reviews cr ON cr.id = ds.code_review_id
                WHERE ds.id = :session_id AND ds.tenant_id = :tenant_id
                """
            ),
            {"session_id": state["session_id"], "tenant_id": state["tenant_id"]},
        )
        row = result.mappings().first()
    if not row:
        raise ValueError("答辩会话不存在")
    history = row["messages"] or []
    if isinstance(history, str):
        history = json.loads(history)
    assignment_context = {
        "title": row["assignment_title"],
        "description": row["assignment_description"],
        "automatic_score": row["automatic_score"],
        "weak_points": row["weak_points"] or [],
        "feedback": row["assignment_feedback"],
        "issues": (row["assignment_issues"] or [])[:8],
    }
    code_review_context = {
        "file_name": row["original_filename"],
        "overall_score": row["code_review_score"],
        "issues": (row["code_review_issues"] or [])[:8],
        "summary": row["code_review_summary"],
    }
    return {
        "stage": row["stage"],
        "turn_count": row["turn_count"],
        "history": history,
        "assignment_context": assignment_context,
        "code_review_context": code_review_context,
    }


async def advance_stage_node(state: DefenseState) -> dict[str, Any]:
    text_value = state["user_message"].strip().lower()
    turn_count = state.get("turn_count", 0) + 1
    if text_value in END_KEYWORDS or turn_count >= 10:
        return {"stage": DefenseStage.FINISHED.value, "turn_count": turn_count}
    current = state.get("stage", DefenseStage.OVERVIEW.value)
    try:
        index = STAGES.index(current)
    except ValueError:
        index = 0
    if turn_count % 2 == 0 and index < len(STAGES) - 1:
        current = STAGES[index + 1]
    return {"stage": current, "turn_count": turn_count}


def route_after_stage(state: DefenseState) -> str:
    return "report" if state.get("stage") == DefenseStage.FINISHED.value else "respond"


async def generate_defense_response_node(state: DefenseState) -> dict[str, Any]:
    stage = state.get("stage", DefenseStage.OVERVIEW.value)
    if not settings.deepseek_api_key.strip():
        question = FALLBACK_QUESTIONS.get(stage, FALLBACK_QUESTIONS["closing"])
        content = f"已记录你的回答。{question}"
        return {
            "turn_result": {"score": None, "feedback": "等待模型或教师评价", "next_question": question},
            "messages": [AIMessage(content=content)],
            "fallback_used": True,
        }

    runnable = get_structured_llm("defense", DefenseTurnResult)
    result = await runnable.ainvoke(
        [
            SystemMessage(content=DEFENSE_SYSTEM_PROMPT),
            HumanMessage(
                content=TURN_PROMPT.format(
                    stage=stage,
                    turn_count=state["turn_count"],
                    assignment_context=json.dumps(state["assignment_context"], ensure_ascii=False),
                    code_review_context=json.dumps(state["code_review_context"], ensure_ascii=False),
                    history=json.dumps(state.get("history", [])[-8:], ensure_ascii=False),
                    answer=state["user_message"],
                )
            ),
        ]
    )
    content = f"{result.feedback}\n\n{result.next_question}"
    return {"turn_result": result.model_dump(), "messages": [AIMessage(content=content)]}


async def generate_defense_report_node(state: DefenseState) -> dict[str, Any]:
    history = list(state.get("history", []))
    history.append({"role": "student", "content": state["user_message"]})
    if not settings.deepseek_api_key.strip():
        report = {
            "overall_score": None,
            "score_status": "pending_teacher_review",
            "strengths": [],
            "weaknesses": state.get("assignment_context", {}).get("weak_points", []),
            "recommendations": ["配置大模型密钥或由教师完成答辩评分。"],
        }
        return {
            "report": report,
            "overall_score": None,
            "structured_output": report,
            "messages": [AIMessage(content="答辩已结束，记录已保存，等待教师完成最终评价。")],
            "fallback_used": True,
        }

    runnable = get_structured_llm("defense", DefenseReport)
    report = await runnable.ainvoke(
        [
            SystemMessage(content=DEFENSE_SYSTEM_PROMPT),
            HumanMessage(
                content=REPORT_PROMPT.format(
                    assignment_context=json.dumps(state["assignment_context"], ensure_ascii=False),
                    code_review_context=json.dumps(state["code_review_context"], ensure_ascii=False),
                    history=json.dumps(history, ensure_ascii=False),
                )
            ),
        ]
    )
    return {
        "report": report.model_dump(),
        "overall_score": report.overall_score,
        "structured_output": report.model_dump(),
        "messages": [AIMessage(content=f"答辩结束，综合得分 {report.overall_score}/100。")],
    }


async def save_defense_turn_node(state: DefenseState) -> dict[str, Any]:
    history = list(state.get("history", []))
    history.append({"role": "student", "content": state["user_message"]})
    assistant_content = state["messages"][-1].content
    assistant_item: dict[str, Any] = {"role": "assistant", "content": assistant_content}
    if state.get("turn_result"):
        assistant_item["evaluation"] = state["turn_result"]
    history.append(assistant_item)
    finished = state.get("stage") == DefenseStage.FINISHED.value
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE defense_sessions
                SET stage = :stage, turn_count = :turn_count,
                    messages = CAST(:messages AS JSONB),
                    report = CAST(:report AS JSONB), overall_score = :overall_score,
                    status = :status,
                    finished_at = CASE WHEN :finished THEN NOW() ELSE finished_at END,
                    updated_at = NOW()
                WHERE id = :session_id AND tenant_id = :tenant_id
                """
            ),
            {
                "stage": state["stage"],
                "turn_count": state["turn_count"],
                "messages": json.dumps(history, ensure_ascii=False),
                "report": json.dumps(state.get("report"), ensure_ascii=False) if state.get("report") else None,
                "overall_score": state.get("overall_score"),
                "status": "finished" if finished else "in_progress",
                "finished": finished,
                "session_id": state["session_id"],
                "tenant_id": state["tenant_id"],
            },
        )
        await session.commit()
    return {}
