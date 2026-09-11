"""创建程序设计课程、示例作业与测试用例（幂等）。"""

import asyncio
import sys
import uuid
from pathlib import Path

import asyncpg

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure:
        _reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import get_settings


async def main() -> None:
    settings = get_settings()
    connection = await asyncpg.connect(
        f"postgresql://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )
    try:
        teacher_id = await connection.fetchval(
            "SELECT id FROM users WHERE tenant_id=$1 AND role IN ('teacher','admin') ORDER BY role DESC LIMIT 1",
            settings.default_tenant_id,
        )
        student_ids = await connection.fetch(
            "SELECT id FROM users WHERE tenant_id=$1 AND role='student'",
            settings.default_tenant_id,
        )
        if not teacher_id:
            raise RuntimeError("未找到教师账号，请先运行 scripts/seed_data.py")

        course_id = await connection.fetchval(
            "SELECT id FROM courses WHERE tenant_id=$1 AND code='PY101'",
            settings.default_tenant_id,
        )
        if not course_id:
            course_id = uuid.uuid4()
            await connection.execute(
                """
                INSERT INTO courses(id,tenant_id,name,code,description,primary_language,created_by)
                VALUES($1,$2,'Python 程序设计基础','PY101','从基础语法、函数、数据结构到工程化测试的课程实训。','python',$3)
                """,
                course_id, settings.default_tenant_id, teacher_id,
            )

        for row in student_ids:
            await connection.execute(
                "INSERT INTO course_enrollments(course_id,student_id) VALUES($1,$2) ON CONFLICT DO NOTHING",
                course_id, row["id"],
            )

        assignment_id = await connection.fetchval(
            "SELECT id FROM assignments WHERE course_id=$1 AND title='成绩统计器' LIMIT 1", course_id
        )
        if not assignment_id:
            assignment_id = uuid.uuid4()
            await connection.execute(
                """
                INSERT INTO assignments(id,tenant_id,course_id,title,description,language,entry_file,rubric,created_by)
                VALUES($1,$2,$3,'成绩统计器',
                '读取一行以空格分隔的整数成绩，输出平均分（保留两位小数）、最高分和最低分，格式：平均分 最高分 最低分。',
                'python','main.py','{"functional":60,"quality":40}'::jsonb,$4)
                """,
                assignment_id, settings.default_tenant_id, course_id, teacher_id,
            )

        test_cases = [
            ("基础数据", "80 90 70\n", "80.00 90 70\n", False),
            ("单个成绩", "100\n", "100.00 100 100\n", True),
            ("边界成绩", "0 100 60 40\n", "50.00 100 0\n", True),
        ]
        for name, input_data, expected, hidden in test_cases:
            exists = await connection.fetchval(
                "SELECT 1 FROM assignment_test_cases WHERE assignment_id=$1 AND name=$2", assignment_id, name
            )
            if not exists:
                await connection.execute(
                    """
                    INSERT INTO assignment_test_cases(assignment_id,name,input_data,expected_output,is_hidden,weight)
                    VALUES($1,$2,$3,$4,$5,1)
                    """,
                    assignment_id, name, input_data, expected, hidden,
                )
        print(f"示例课程与作业已就绪：course_id={course_id}, assignment_id={assignment_id}")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
