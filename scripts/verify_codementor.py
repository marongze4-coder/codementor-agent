"""CodeMentor Agent 本地配置与核心能力自检。"""

import asyncio
import sys
from pathlib import Path

import asyncpg

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure:
        _reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.code_review.nodes import analyze_code_locally
from backend.config import get_settings
from backend.core.code_sandbox import sandbox_status


REQUIRED_TABLES = {
    "courses", "course_enrollments", "assignments", "assignment_test_cases",
    "code_submissions", "test_run_results", "assignment_reviews", "code_reviews",
    "defense_sessions",
}


async def main() -> None:
    settings = get_settings()
    connection = await asyncpg.connect(
        f"postgresql://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )
    try:
        rows = await connection.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        )
        found = {row["table_name"] for row in rows}
        missing = REQUIRED_TABLES - found
        if missing:
            raise RuntimeError(f"数据库缺少表：{sorted(missing)}")
        course_count = await connection.fetchval("SELECT count(*) FROM courses")
        assignment_count = await connection.fetchval("SELECT count(*) FROM assignments")
    finally:
        await connection.close()

    ready, reason = await sandbox_status()
    if not ready:
        raise RuntimeError(f"代码沙箱未就绪：{reason}")

    structure, scores = analyze_code_locally("def add(a, b):\n    return a + b\n", "demo.py")
    if not structure.syntax_valid or len(scores) != 6:
        raise RuntimeError("代码审查器自检失败")

    print("CodeMentor 自检通过")
    print(f"数据库表：{len(REQUIRED_TABLES)} 个；课程：{course_count}；作业：{assignment_count}")
    print(f"代码沙箱：{settings.sandbox_image}（{reason}）")
    print("代码审查：6 个维度")


if __name__ == "__main__":
    asyncio.run(main())
