# backend/db/migrations.py
#
# 启动时自动执行的 Schema 补丁（全部幂等，可重复运行）。
# 规则：
#   - 只写 ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS 等幂等 DDL
#   - 禁止写 DROP / TRUNCATE 等破坏性变更
#   - 每次 init_db.sql 新增字段，同步在 _MIGRATIONS 里追加一条

from sqlalchemy import text
from backend.dependencies import AsyncSessionLocal
from backend.core.logger import get_logger

logger = get_logger(__name__)

# ── 所有需要补丁的 DDL，按时间顺序追加。SQL 必须幂等（IF NOT EXISTS）──
_MIGRATIONS: list[tuple[str, str]] = [
    (
        "exam_submissions.weak_points",
        "ALTER TABLE exam_submissions ADD COLUMN IF NOT EXISTS weak_points JSONB",
    ),
    (
        "exam_reviews.knowledge_tag",
        "ALTER TABLE exam_reviews ADD COLUMN IF NOT EXISTS knowledge_tag VARCHAR(128)",
    ),
    (
        "exam_submissions.weak_points_summary",
        "ALTER TABLE exam_submissions ADD COLUMN IF NOT EXISTS weak_points_summary TEXT",
    ),
    (
        "idx_exam_submissions_student_created",
        "CREATE INDEX IF NOT EXISTS idx_exam_submissions_student_created "
        "ON exam_submissions (student_id, created_at DESC)",
    ),
    (
        "questions.language",
        "ALTER TABLE questions ADD COLUMN IF NOT EXISTS language VARCHAR(32) NOT NULL DEFAULT 'python'",
    ),
    (
        "questions.code_rubric",
        "ALTER TABLE questions ADD COLUMN IF NOT EXISTS code_rubric JSONB NOT NULL "
        "DEFAULT jsonb_build_object('functional', 60, 'quality', 40)",
    ),
    (
        "question_test_cases",
        """
        CREATE TABLE IF NOT EXISTS question_test_cases (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            name VARCHAR(128) NOT NULL,
            input_data TEXT NOT NULL DEFAULT '',
            expected_output TEXT NOT NULL,
            timeout_seconds INT NOT NULL DEFAULT 3 CHECK (timeout_seconds BETWEEN 1 AND 30),
            weight INT NOT NULL DEFAULT 1 CHECK (weight > 0),
            is_hidden BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "idx_question_test_cases_question_id",
        "CREATE INDEX IF NOT EXISTS idx_question_test_cases_question_id "
        "ON question_test_cases (question_id)",
    ),
    (
        "courses",
        """
        CREATE TABLE IF NOT EXISTS courses (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            name VARCHAR(128) NOT NULL,
            code VARCHAR(32) NOT NULL,
            description TEXT,
            primary_language VARCHAR(32) NOT NULL DEFAULT 'python',
            created_by UUID REFERENCES users(id),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, code)
        )
        """,
    ),
    (
        "course_enrollments",
        """
        CREATE TABLE IF NOT EXISTS course_enrollments (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            student_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            enrolled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (course_id, student_id)
        )
        """,
    ),
    (
        "assignments",
        """
        CREATE TABLE IF NOT EXISTS assignments (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            title VARCHAR(256) NOT NULL,
            description TEXT NOT NULL,
            language VARCHAR(32) NOT NULL DEFAULT 'python',
            entry_file VARCHAR(128) NOT NULL DEFAULT 'main.py',
            rubric JSONB NOT NULL DEFAULT '{}'::jsonb,
            max_score INT NOT NULL DEFAULT 100 CHECK (max_score > 0),
            due_date TIMESTAMPTZ,
            created_by UUID REFERENCES users(id),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "assignment_test_cases",
        """
        CREATE TABLE IF NOT EXISTS assignment_test_cases (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            assignment_id UUID NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            name VARCHAR(128) NOT NULL,
            input_data TEXT NOT NULL DEFAULT '',
            expected_output TEXT NOT NULL,
            timeout_seconds INT NOT NULL DEFAULT 3 CHECK (timeout_seconds BETWEEN 1 AND 30),
            weight INT NOT NULL DEFAULT 1 CHECK (weight > 0),
            is_hidden BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "code_submissions",
        """
        CREATE TABLE IF NOT EXISTS code_submissions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            assignment_id UUID NOT NULL REFERENCES assignments(id),
            student_id UUID NOT NULL REFERENCES users(id),
            original_filename VARCHAR(256) NOT NULL,
            source_path VARCHAR(512) NOT NULL,
            source_sha256 VARCHAR(64) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'submitted'
                CHECK (status IN ('submitted','evaluating','pending_review','published','failed')),
            automatic_score INT,
            teacher_score INT,
            final_score INT,
            weak_points JSONB,
            error_msg TEXT,
            submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "test_run_results",
        """
        CREATE TABLE IF NOT EXISTS test_run_results (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            submission_id UUID NOT NULL REFERENCES code_submissions(id) ON DELETE CASCADE,
            test_case_id UUID REFERENCES assignment_test_cases(id) ON DELETE SET NULL,
            passed BOOLEAN NOT NULL DEFAULT FALSE,
            exit_code INT,
            duration_ms INT,
            stdout TEXT,
            stderr TEXT,
            error_type VARCHAR(32),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "assignment_reviews",
        """
        CREATE TABLE IF NOT EXISTS assignment_reviews (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            submission_id UUID NOT NULL UNIQUE REFERENCES code_submissions(id) ON DELETE CASCADE,
            functional_score INT NOT NULL DEFAULT 0,
            quality_score INT NOT NULL DEFAULT 0,
            automatic_score INT NOT NULL DEFAULT 0,
            dimension_scores JSONB,
            issues JSONB,
            feedback TEXT,
            needs_review BOOLEAN NOT NULL DEFAULT TRUE,
            teacher_comment TEXT,
            reviewed_by UUID REFERENCES users(id),
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "code_reviews",
        """
        CREATE TABLE IF NOT EXISTS code_reviews (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            student_id UUID NOT NULL REFERENCES users(id),
            assignment_id UUID REFERENCES assignments(id) ON DELETE SET NULL,
            submission_id UUID REFERENCES code_submissions(id) ON DELETE SET NULL,
            original_filename VARCHAR(256) NOT NULL,
            source_path VARCHAR(512),
            language VARCHAR(32),
            code_structure JSONB,
            dimension_scores JSONB,
            issues JSONB,
            summary JSONB,
            overall_score INT,
            status VARCHAR(16) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','processing','done','failed')),
            error_msg TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "defense_sessions",
        """
        CREATE TABLE IF NOT EXISTS defense_sessions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            student_id UUID NOT NULL REFERENCES users(id),
            course_id UUID REFERENCES courses(id) ON DELETE SET NULL,
            submission_id UUID REFERENCES code_submissions(id) ON DELETE SET NULL,
            code_review_id UUID REFERENCES code_reviews(id) ON DELETE SET NULL,
            thread_id VARCHAR(128) NOT NULL UNIQUE,
            stage VARCHAR(24) NOT NULL DEFAULT 'overview',
            turn_count INT NOT NULL DEFAULT 0,
            messages JSONB NOT NULL DEFAULT '[]',
            report JSONB,
            overall_score INT,
            status VARCHAR(16) NOT NULL DEFAULT 'in_progress'
                CHECK (status IN ('in_progress','finished')),
            finished_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    ("idx_courses_tenant_id", "CREATE INDEX IF NOT EXISTS idx_courses_tenant_id ON courses (tenant_id)"),
    ("idx_assignments_course_id", "CREATE INDEX IF NOT EXISTS idx_assignments_course_id ON assignments (course_id)"),
    ("idx_assignments_tenant_id", "CREATE INDEX IF NOT EXISTS idx_assignments_tenant_id ON assignments (tenant_id)"),
    ("idx_assignment_test_cases_assignment_id", "CREATE INDEX IF NOT EXISTS idx_assignment_test_cases_assignment_id ON assignment_test_cases (assignment_id)"),
    ("idx_code_submissions_assignment_id", "CREATE INDEX IF NOT EXISTS idx_code_submissions_assignment_id ON code_submissions (assignment_id)"),
    ("idx_code_submissions_student_id", "CREATE INDEX IF NOT EXISTS idx_code_submissions_student_id ON code_submissions (student_id)"),
    ("idx_code_submissions_status", "CREATE INDEX IF NOT EXISTS idx_code_submissions_status ON code_submissions (status)"),
    ("idx_test_run_results_submission_id", "CREATE INDEX IF NOT EXISTS idx_test_run_results_submission_id ON test_run_results (submission_id)"),
    ("idx_code_reviews_student_id", "CREATE INDEX IF NOT EXISTS idx_code_reviews_student_id ON code_reviews (student_id)"),
    ("idx_code_reviews_status", "CREATE INDEX IF NOT EXISTS idx_code_reviews_status ON code_reviews (status)"),
    ("idx_defense_sessions_student_id", "CREATE INDEX IF NOT EXISTS idx_defense_sessions_student_id ON defense_sessions (student_id)"),
    ("idx_defense_sessions_status", "CREATE INDEX IF NOT EXISTS idx_defense_sessions_status ON defense_sessions (status)"),
]


async def run_migrations() -> None:
    """
    在应用启动时执行所有 Schema 补丁。
    单条失败只记录警告，不阻断启动流程。
    """
    async with AsyncSessionLocal() as session:
        for desc, sql in _MIGRATIONS:
            try:
                await session.execute(text(sql))
                await session.commit()
                logger.debug("db.migration_applied", column=desc)
            except Exception as e:
                await session.rollback()
                err = str(e)
                if "already exists" not in err:
                    logger.warning("db.migration_failed", column=desc, error=err)

    logger.info("db.migrations_done", count=len(_MIGRATIONS))
