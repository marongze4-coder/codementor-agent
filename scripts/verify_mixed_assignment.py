"""验证综合作业三轨中的客观题规则轨和代码 Docker/AST 轨。"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import text


for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure:
        _reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.exam.nodes import _review_one_code, _run_objective_track, _run_subjective_track
from backend.dependencies import AsyncSessionLocal


EXAM_ID = "e0000001-0000-0000-0000-000000000001"


async def main() -> None:
    async with AsyncSessionLocal() as session:
        question_rows = await session.execute(
            text("""
                SELECT id, question_no, question_type, content, correct_answer,
                       score, knowledge_tag, language, code_rubric
                FROM questions
                WHERE exam_id = :exam_id
                ORDER BY question_no
            """),
            {"exam_id": EXAM_ID},
        )
        questions = [dict(row) for row in question_rows.mappings().all()]
        if len(questions) != 5:
            raise RuntimeError("综合作业演示题目未初始化，请先运行 seed_standard_exam.py")

        code_question = next(item for item in questions if item["question_type"] == "code")
        test_rows = await session.execute(
            text("""
                SELECT id, name, input_data, expected_output,
                       timeout_seconds, weight, is_hidden
                FROM question_test_cases
                WHERE question_id = :question_id
                ORDER BY created_at, id
            """),
            {"question_id": code_question["id"]},
        )
        test_cases = [
            {**dict(row), "id": str(row["id"])}
            for row in test_rows.mappings().all()
        ]

    objective = next(item for item in questions if item["question_type"] == "single_choice")
    objective.update({
        "question_id": str(objective.pop("id")),
        "student_answer": "b",
        "full_score": objective.pop("score"),
    })
    objective_result = (await _run_objective_track([objective]))[0]
    if not objective_result["is_correct"] or objective_result["score"] != 5:
        raise RuntimeError("客观题规则轨验证失败")

    subjective = next(item for item in questions if item["question_type"] == "short_answer")
    subjective.update({
        "question_id": str(subjective.pop("id")),
        "student_answer": "可迭代对象能通过 iter 获取迭代器，next 逐个取值。",
        "full_score": subjective.pop("score"),
        "scoring_points": [],
    })
    subjective_result = (await _run_subjective_track([subjective]))[0]
    if not subjective_result["needs_review"]:
        raise RuntimeError("无模型密钥时简答题必须进入教师复核")

    code_question.update({
        "question_id": str(code_question.pop("id")),
        "student_answer": (
            "scores = list(map(int, input().split()))\n"
            "print(f'{sum(scores) / len(scores):.2f} {max(scores)} {min(scores)}')\n"
        ),
        "full_score": code_question.pop("score"),
        "test_cases": test_cases,
    })
    code_result = await _review_one_code(code_question)
    if code_result["functional_score"] != 100:
        raise RuntimeError(f"代码功能轨验证失败：{code_result['functional_score']}")
    if code_result["test_cases_passed"] != len(test_cases):
        raise RuntimeError("代码测试用例未全部通过")
    if len(code_result["dimension_scores"]) != 6:
        raise RuntimeError("AST/规则质量分析未返回六个维度")

    print("综合作业三轨核心验证通过")
    print("客观题：答案标准化与规则判分正常")
    print("简答题：无模型密钥时不伪造评分，已进入教师复核")
    print(
        "代码题："
        f"Docker {code_result['test_cases_passed']}/{code_result['test_cases_total']} 通过；"
        f"功能分 {code_result['functional_score']}；质量分 {code_result['quality_score']}；"
        f"本题得分 {code_result['score']}/{code_result['full_score']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
