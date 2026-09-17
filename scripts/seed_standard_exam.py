"""
把「标准试卷」（题目 + 正确答案 + 得分点）灌进数据库 exams / questions / scoring_points。
这是第 6 章批改前的「数据准备」——库里有了这份标准卷，load_questions_meta 才有东西可读。

- 用 SQLAlchemy + text()，复用项目的 AsyncSessionLocal（与课件正文节点代码同一种写法）
- 幂等：先按固定 exam_id 删除（级联清掉 questions/scoring_points），再插入
用法：
    conda activate edu_agent
    python scripts/seed_standard_exam.py
"""
import asyncio
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure:
        _reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text
from backend.dependencies import AsyncSessionLocal

TENANT = "tenant_default"

# ── 固定 ID（幂等 + 方便测试脚本引用）──────────────────────────
EXAM_ID = "e0000001-0000-0000-0000-000000000001"
Q = {  # question_no -> 固定 question_id
    1: "e0000001-0000-0000-0000-0000000000a1",
    2: "e0000001-0000-0000-0000-0000000000a2",
    3: "e0000001-0000-0000-0000-0000000000a3",
    4: "e0000001-0000-0000-0000-0000000000a4",
    5: "e0000001-0000-0000-0000-0000000000a5",
}

# ── 标准作业：Python 程序设计综合作业（5 题，总分 40）────────────
QUESTIONS = [
    # (no, type, content, correct_answer, score, knowledge_tag)
    (1, "single_choice",
     "Python 中用于定义函数的关键字是（ ）\n"
     "A. func\nB. def\nC. function\nD. lambda",
     "B", 5, "Python函数"),
    (2, "multi_choice",
     "下列哪些是 Python 内置可变容器（多选）\n"
     "A. list\nB. tuple\nC. dict\nD. set",
     "ACD", 6, "Python数据结构"),
    (3, "judge", "判断：Python 元组创建后不能直接修改其中的元素。", "正确", 4, "Python数据结构"),
    (4, "short_answer", "请解释 Python 中可迭代对象与迭代器的区别，并说明 iter() 和 next() 的作用。", "", 10, "Python迭代协议"),
    (5, "code",
     "读取一行空格分隔的整数成绩，输出平均分（保留两位小数）、最高分和最低分，格式：平均分 最高分 最低分。",
     "scores = list(map(int, input().split()))\nprint(f'{sum(scores) / len(scores):.2f} {max(scores)} {min(scores)}')",
     15, "Python综合应用"),
]

# ── 第4题（简答）得分点，共 10 分 ─────────────────────────────
SCORING_POINTS = [
    ("说明可迭代对象能够通过 iter() 返回迭代器", 3),
    ("说明迭代器保存遍历状态并实现 next() 协议", 3),
    ("说明 next() 逐个取值，耗尽后抛出 StopIteration", 2),
    ("能够结合 for 循环说明迭代协议的使用", 2),
]

CODE_TEST_CASES = [
    ("基础数据", "80 90 70\n", "80.00 90 70\n", False, 1),
    ("单个成绩", "100\n", "100.00 100 100\n", True, 1),
    ("边界成绩", "0 100 60 40\n", "50.00 100 0\n", True, 1),
]


async def main():
    # AsyncSessionLocal 是项目里统一的异步会话工厂，连接配置已在项目内配好，这里直接用
    async with AsyncSessionLocal() as session:
        # 幂等：先删（questions / scoring_points 靠外键 ON DELETE CASCADE 自动清掉）
        await session.execute(text("DELETE FROM exams WHERE id = :id"), {"id": EXAM_ID})

        await session.execute(
            text("""INSERT INTO exams (id, tenant_id, title, description, is_active)
                    VALUES (:id, :tenant, :title, :desc, TRUE)"""),
            {
                "id": EXAM_ID, "tenant": TENANT,
                "title": "Python 程序设计综合作业（三轨批改演示）",
                "desc": "覆盖单选、多选、判断、简答和代码题；代码题使用 Docker 测试与 AST 质量分析。",
            },
        )

        for no, qtype, content, correct, score, tag in QUESTIONS:
            await session.execute(
                text("""INSERT INTO questions
                            (id, tenant_id, exam_id, question_no, question_type,
                             content, correct_answer, score, knowledge_tag,
                             language, code_rubric)
                        VALUES (:id, :tenant, :exam_id, :no, :qtype,
                                :content, :correct, :score, :tag,
                                'python', jsonb_build_object('functional', 60, 'quality', 40))"""),
                {
                    "id": Q[no], "tenant": TENANT, "exam_id": EXAM_ID, "no": no,
                    "qtype": qtype, "content": content, "correct": correct,
                    "score": score, "tag": tag,
                },
            )

        for desc, pts in SCORING_POINTS:
            await session.execute(
                text("""INSERT INTO scoring_points
                            (question_id, point_desc, point_score, is_active)
                        VALUES (:qid, :desc, :pts, TRUE)"""),
                {"qid": Q[4], "desc": desc, "pts": pts},
            )

        for name, input_data, expected_output, is_hidden, weight in CODE_TEST_CASES:
            await session.execute(
                text("""INSERT INTO question_test_cases
                            (question_id, name, input_data, expected_output,
                             timeout_seconds, weight, is_hidden)
                        VALUES (:qid, :name, :input_data, :expected_output,
                                3, :weight, :is_hidden)"""),
                {
                    "qid": Q[5],
                    "name": name,
                    "input_data": input_data,
                    "expected_output": expected_output,
                    "weight": weight,
                    "is_hidden": is_hidden,
                },
            )

        await session.commit()  # SQLAlchemy 需要显式提交，写入才会落库

        # 自检
        total = (await session.execute(
            text("SELECT SUM(score) FROM questions WHERE exam_id = :id"),
            {"id": EXAM_ID})).scalar()
        n_q = (await session.execute(
            text("SELECT COUNT(*) FROM questions WHERE exam_id = :id"),
            {"id": EXAM_ID})).scalar()
        n_sp = (await session.execute(
            text("SELECT COUNT(*) FROM scoring_points WHERE question_id = :qid"),
            {"qid": Q[4]})).scalar()
        n_tests = (await session.execute(
            text("SELECT COUNT(*) FROM question_test_cases WHERE question_id = :qid"),
            {"qid": Q[5]})).scalar()

    print(f"已写入标准卷：exam_id={EXAM_ID}")
    print(f"   题目 {n_q} 道，总分 {total}；简答题得分点 {n_sp} 个；代码测试 {n_tests} 个")
    print("   把测试脚本里的 EXAM_ID 设成上面这个，即可提交批改")


if __name__ == "__main__":
    asyncio.run(main())
