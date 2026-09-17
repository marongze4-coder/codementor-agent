-- ============================================================
-- EduAgent PostgreSQL 数据库初始化脚本
-- Docker 启动时自动执行（挂载到 /docker-entrypoint-initdb.d/）
-- ============================================================

-- 启用 UUID 自动生成扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 用户与权限表
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    username        VARCHAR(64) NOT NULL,
    email           VARCHAR(128) NOT NULL,
    password_hash   VARCHAR(256) NOT NULL,
    role            VARCHAR(16) NOT NULL CHECK (role IN ('student', 'teacher', 'admin')),
    class_id        UUID,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, email)
);
CREATE INDEX idx_users_tenant_id ON users (tenant_id);
CREATE INDEX idx_users_role ON users (role);
CREATE INDEX idx_users_class_id ON users (class_id);

-- ============================================================
-- 知识库待补充队列
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_pending_queue (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    question        TEXT NOT NULL,
    student_id      UUID REFERENCES users(id),
    confidence      FLOAT NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'resolved', 'dismissed')),
    resolved_by     UUID REFERENCES users(id),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_knowledge_pending_queue_tenant_id ON knowledge_pending_queue (tenant_id);
CREATE INDEX idx_knowledge_pending_queue_status ON knowledge_pending_queue (status);

-- ============================================================
-- 试卷批改相关表
-- ============================================================
CREATE TABLE IF NOT EXISTS exams (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    title           VARCHAR(256) NOT NULL,
    description     TEXT,
    due_date        TIMESTAMPTZ,
    created_by      UUID REFERENCES users(id),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_exams_tenant_id ON exams (tenant_id);

CREATE TABLE IF NOT EXISTS questions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    exam_id         UUID REFERENCES exams(id) ON DELETE CASCADE,
    question_no     INT NOT NULL,
    question_type   VARCHAR(16) NOT NULL
                    CHECK (question_type IN ('single_choice', 'multi_choice', 'judge', 'short_answer', 'code')),
    content         TEXT NOT NULL,
    correct_answer  TEXT,
    score           INT NOT NULL DEFAULT 10,
    knowledge_tag   VARCHAR(128),
    language        VARCHAR(32) NOT NULL DEFAULT 'python',
    code_rubric     JSONB NOT NULL DEFAULT '{"functional":60,"quality":40}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_questions_exam_id ON questions (exam_id);
CREATE INDEX idx_questions_knowledge_tag ON questions (knowledge_tag);

CREATE TABLE IF NOT EXISTS scoring_points (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    question_id     UUID REFERENCES questions(id) ON DELETE CASCADE,
    point_desc      TEXT NOT NULL,
    point_score     INT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    confirmed_by    UUID REFERENCES users(id),
    confirmed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_scoring_points_question_id ON scoring_points (question_id);

CREATE TABLE IF NOT EXISTS question_test_cases (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    question_id     UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    name            VARCHAR(128) NOT NULL,
    input_data      TEXT NOT NULL DEFAULT '',
    expected_output TEXT NOT NULL,
    timeout_seconds INT NOT NULL DEFAULT 3 CHECK (timeout_seconds BETWEEN 1 AND 30),
    weight          INT NOT NULL DEFAULT 1 CHECK (weight > 0),
    is_hidden       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_question_test_cases_question_id ON question_test_cases (question_id);

CREATE TABLE IF NOT EXISTS exam_submissions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    exam_id         UUID REFERENCES exams(id),
    student_id      UUID REFERENCES users(id),
    source          VARCHAR(16) NOT NULL DEFAULT 'word'
                    CHECK (source IN ('word', 'online', 'miniapp')),
    word_minio_path VARCHAR(512),
    status          VARCHAR(16) NOT NULL DEFAULT 'submitted'
                    CHECK (status IN ('submitted', 'ai_processing', 'pending_review', 'reviewed', 'published')),
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ,
    weak_points          JSONB,
    weak_points_summary  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (exam_id, student_id)
);
CREATE INDEX idx_exam_submissions_tenant_id ON exam_submissions (tenant_id);
CREATE INDEX idx_exam_submissions_exam_id ON exam_submissions (exam_id);
CREATE INDEX idx_exam_submissions_student_id ON exam_submissions (student_id);
CREATE INDEX idx_exam_submissions_status ON exam_submissions (status);

CREATE TABLE IF NOT EXISTS exam_reviews (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id   UUID REFERENCES exam_submissions(id) ON DELETE CASCADE,
    question_id     UUID REFERENCES questions(id),
    question_type   VARCHAR(16) NOT NULL,
    knowledge_tag   VARCHAR(128),
    student_answer  TEXT,
    ai_score        INT,
    ai_feedback     TEXT,
    ai_raw_result   JSONB,
    teacher_score   INT,
    teacher_comment TEXT,
    final_score     INT,
    needs_review    BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by     UUID REFERENCES users(id),
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_exam_reviews_submission_id ON exam_reviews (submission_id);
CREATE INDEX idx_exam_reviews_needs_review ON exam_reviews (needs_review);
CREATE INDEX idx_exam_reviews_knowledge_tag ON exam_reviews (knowledge_tag);

-- ============================================================
-- 问答会话表
-- ============================================================
CREATE TABLE IF NOT EXISTS qa_sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    student_id      UUID REFERENCES users(id),
    thread_id       VARCHAR(128) NOT NULL UNIQUE,
    summary         TEXT,
    summary_version INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_qa_sessions_tenant_id ON qa_sessions (tenant_id);
CREATE INDEX idx_qa_sessions_student_id ON qa_sessions (student_id);
CREATE INDEX idx_qa_sessions_thread_id ON qa_sessions (thread_id);

-- ============================================================
-- CodeMentor：课程与编程实训领域表
-- ============================================================
CREATE TABLE IF NOT EXISTS courses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    name            VARCHAR(128) NOT NULL,
    code            VARCHAR(32) NOT NULL,
    description     TEXT,
    primary_language VARCHAR(32) NOT NULL DEFAULT 'python',
    created_by      UUID REFERENCES users(id),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_courses_tenant_id ON courses (tenant_id);

CREATE TABLE IF NOT EXISTS course_enrollments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id       UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    student_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    enrolled_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (course_id, student_id)
);

CREATE TABLE IF NOT EXISTS assignments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    course_id       UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title           VARCHAR(256) NOT NULL,
    description     TEXT NOT NULL,
    language        VARCHAR(32) NOT NULL DEFAULT 'python',
    entry_file      VARCHAR(128) NOT NULL DEFAULT 'main.py',
    rubric          JSONB NOT NULL DEFAULT '{"functional":60,"quality":40}',
    max_score       INT NOT NULL DEFAULT 100 CHECK (max_score > 0),
    due_date        TIMESTAMPTZ,
    created_by      UUID REFERENCES users(id),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_assignments_course_id ON assignments (course_id);
CREATE INDEX idx_assignments_tenant_id ON assignments (tenant_id);

CREATE TABLE IF NOT EXISTS assignment_test_cases (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    assignment_id   UUID NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    name            VARCHAR(128) NOT NULL,
    input_data      TEXT NOT NULL DEFAULT '',
    expected_output TEXT NOT NULL,
    timeout_seconds INT NOT NULL DEFAULT 3 CHECK (timeout_seconds BETWEEN 1 AND 30),
    weight          INT NOT NULL DEFAULT 1 CHECK (weight > 0),
    is_hidden       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_assignment_test_cases_assignment_id ON assignment_test_cases (assignment_id);

CREATE TABLE IF NOT EXISTS code_submissions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    assignment_id   UUID NOT NULL REFERENCES assignments(id),
    student_id      UUID NOT NULL REFERENCES users(id),
    original_filename VARCHAR(256) NOT NULL,
    source_path     VARCHAR(512) NOT NULL,
    source_sha256   VARCHAR(64) NOT NULL,
    status          VARCHAR(24) NOT NULL DEFAULT 'submitted'
                    CHECK (status IN ('submitted','evaluating','pending_review','published','failed')),
    automatic_score INT,
    teacher_score   INT,
    final_score     INT,
    weak_points     JSONB,
    error_msg       TEXT,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_code_submissions_assignment_id ON code_submissions (assignment_id);
CREATE INDEX idx_code_submissions_student_id ON code_submissions (student_id);
CREATE INDEX idx_code_submissions_status ON code_submissions (status);

CREATE TABLE IF NOT EXISTS test_run_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id   UUID NOT NULL REFERENCES code_submissions(id) ON DELETE CASCADE,
    test_case_id    UUID REFERENCES assignment_test_cases(id) ON DELETE SET NULL,
    passed          BOOLEAN NOT NULL DEFAULT FALSE,
    exit_code       INT,
    duration_ms     INT,
    stdout          TEXT,
    stderr          TEXT,
    error_type      VARCHAR(32),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_test_run_results_submission_id ON test_run_results (submission_id);

CREATE TABLE IF NOT EXISTS assignment_reviews (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id   UUID NOT NULL UNIQUE REFERENCES code_submissions(id) ON DELETE CASCADE,
    functional_score INT NOT NULL DEFAULT 0,
    quality_score   INT NOT NULL DEFAULT 0,
    automatic_score INT NOT NULL DEFAULT 0,
    dimension_scores JSONB,
    issues          JSONB,
    feedback        TEXT,
    needs_review    BOOLEAN NOT NULL DEFAULT TRUE,
    teacher_comment TEXT,
    reviewed_by     UUID REFERENCES users(id),
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS code_reviews (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    student_id      UUID NOT NULL REFERENCES users(id),
    assignment_id   UUID REFERENCES assignments(id) ON DELETE SET NULL,
    submission_id   UUID REFERENCES code_submissions(id) ON DELETE SET NULL,
    original_filename VARCHAR(256) NOT NULL,
    source_path     VARCHAR(512),
    language        VARCHAR(32),
    code_structure  JSONB,
    dimension_scores JSONB,
    issues          JSONB,
    summary         JSONB,
    overall_score   INT,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','done','failed')),
    error_msg       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_code_reviews_student_id ON code_reviews (student_id);
CREATE INDEX idx_code_reviews_status ON code_reviews (status);

CREATE TABLE IF NOT EXISTS defense_sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    student_id      UUID NOT NULL REFERENCES users(id),
    course_id       UUID REFERENCES courses(id) ON DELETE SET NULL,
    submission_id   UUID REFERENCES code_submissions(id) ON DELETE SET NULL,
    code_review_id  UUID REFERENCES code_reviews(id) ON DELETE SET NULL,
    thread_id       VARCHAR(128) NOT NULL UNIQUE,
    stage           VARCHAR(24) NOT NULL DEFAULT 'overview',
    turn_count      INT NOT NULL DEFAULT 0,
    messages        JSONB NOT NULL DEFAULT '[]',
    report          JSONB,
    overall_score   INT,
    status          VARCHAR(16) NOT NULL DEFAULT 'in_progress'
                    CHECK (status IN ('in_progress','finished')),
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_defense_sessions_student_id ON defense_sessions (student_id);
CREATE INDEX idx_defense_sessions_status ON defense_sessions (status);

-- ============================================================
-- 自动更新 updated_at 触发器
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users',
        'exams', 'exam_submissions', 'exam_reviews',
        'qa_sessions',
        'courses', 'assignments', 'code_submissions',
        'assignment_reviews', 'code_reviews', 'defense_sessions'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_updated_at ON %s', t, t);
        EXECUTE format('
            CREATE TRIGGER trg_%s_updated_at
            BEFORE UPDATE ON %s
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        ', t, t);
    END LOOP;
END;
$$;
