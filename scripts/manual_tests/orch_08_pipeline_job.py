# scripts/manual_tests/orch_08_pipeline_job.py
# 第8章 真实端到端测试：真实 PDF → 简历审查 Agent → 模拟面试 Agent（多轮对话）
#
# ══════════════════════════════════════════════════════════════════════
#  Phase 1  Pipeline（自动串联）
#           orch.handle(pipeline_mode=True) 依次调用：
#           ① 简历审查 Agent  →  提取结构化字段 + 六维度评分
#           ② 当 weighted_score ≥ 60 时，自动注入 resume_review_id 并启动面试首轮
#           返回：step_1（简历结果）+ step_2（面试首问）
#
#  Phase 2  续跑面试（多轮对话）
#           Pipeline 内部给 Interview 分配的 session_id = f"{pipeline_session_id}_step1"
#           续跑只需用同一个 student_id + "…_step1" session_id，MemorySaver 自动恢复状态
#           连续发送 AUTO_ANSWERS，推动面试从 WARMUP → TECH_BASE → PROJECT 阶段递进
# ══════════════════════════════════════════════════════════════════════
#
# 依赖：DeepSeek API / PostgreSQL:5433
# 运行：conda activate edu_agent && python scripts/manual_tests/orch_08_pipeline_job.py

import sys
import asyncio
import uuid
sys.path.insert(0, ".")

from sqlalchemy import text
from backend.dependencies import AsyncSessionLocal
from backend.core.logger import get_logger,configure_logging
configure_logging()
from backend.core.orchestrator import get_orchestrator, AgentRequest, AgentType

PDF_PATH       = "/Users/ligang/Desktop/LiveEduAgent/samples/简历模版.pdf"
TENANT_ID      = "tenant_default"
PIPELINE_SID   = "e2e-pipeline-test"          # Pipeline 请求的 session_id（固定，方便追踪）
TARGET_POS     = "Java后端开发工程师"


# ─── 自动回答库：面试每一轮由测试脚本代劳作答 ────────────────────────────────
# 真实场景：学员在前端打字；这里用脚本模拟，让测试能无人值守跑完
AUTO_ANSWERS = [
    # 轮次 2（Pipeline 首问之后的回答 —— WARMUP 阶段，面试官通常先让自我介绍）
    "您好，我叫张伟，3年Java后端开发经验。熟悉Spring Boot / MyBatis / Redis，"
    "在上家公司主导过电商秒杀模块的后端设计，QPS 峰值处理超过 5000。",

    # 轮次 3（TECH_BASE 阶段 —— 基础技术题）
    "HashMap底层是数组+链表+红黑树。初始容量16，负载因子0.75，当链表长度超8且数组≥64时"
    "树化成红黑树。JDK8后扩容改为尾插法，解决了死链问题。",

    # 轮次 4（TECH_BASE 阶段 —— 继续技术题）
    "Redis持久化有RDB和AOF两种。RDB是定时快照，恢复快但可能丢最近写入；"
    "AOF记录每条写命令，数据更安全但文件更大。生产通常两者结合使用。",

    # 轮次 5（PROJECT 阶段 —— 面试官会针对简历项目深挖）
    "秒杀场景我们用Redis+Lua脚本实现原子扣减库存，避免超卖。"
    "Lua脚本把'检查库存'和'扣库存'合并成单条命令，Redis单线程保证原子性。"
    "实测在4核8G机器上稳定支持5000 QPS，库存误差率为零。",

    # 轮次 6（PROJECT 阶段 —— 追问或下一个项目）
    "分布式事务这里用的是本地消息表+定时补偿方案。下单时在同一个本地事务写订单+写消息，"
    "消息投递失败由定时任务重试，最终一致性。选它而不是Seata是因为团队规模小，"
    "引入Seata运维成本高，本地消息表更轻量可控。",

    # 轮次 7（CLOSING 阶段 —— 学员提问环节）
    "谢谢面试官。我想请问一下贵公司的后端技术栈目前是否有微服务拆分的计划？"
    "以及团队在技术选型上倾向于自研还是引入开源框架？",
]


def section(title: str):
    print("\n" + "═" * 64 + f"\n  {title}\n" + "═" * 64)


async def setup_review_record() -> str:
    """
    在 resume_reviews 表预建一条 processing 状态的记录。
    Resume Agent 的 save_results_node 会用 review_id 找到它并 UPDATE（写入评分结果）。
    """
    review_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("""
                    INSERT INTO resume_reviews
                        (id, tenant_id, pdf_minio_path, status)
                    VALUES
                        (:id, :tenant_id, :pdf_minio_path, 'processing')
                """),
                {
                    "id":             review_id,
                    "tenant_id":      TENANT_ID,
                    "pdf_minio_path": f"local/{review_id}.pdf",
                },
            )
    print(f"预建 resume_reviews 记录: {review_id}")
    return review_id


async def get_db_score(review_id: str) -> float:
    """确认 save_results_node 已把评分落库。"""
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            text("SELECT scores FROM resume_reviews WHERE id = :id"),
            {"id": review_id},
        )
        r = row.mappings().fetchone()
    if not r:
        return -1.0
    import json
    scores = r["scores"]
    if isinstance(scores, str):
        scores = json.loads(scores)
    return float((scores or {}).get("weighted_score", -1))


async def cleanup(review_id: str):
    """测试结束后删除测试数据（CASCADE 会级联删除 interview_sessions 等引用行）。"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM resume_reviews WHERE id = :id"),
                {"id": review_id},
            )
    print(f"已清理 resume_reviews: {review_id}")


# ─────────────────────────────────────────────────────────────────────
#  Phase 1：用 Pipeline 跑「简历审查 → 面试首轮」
# ─────────────────────────────────────────────────────────────────────
async def phase1_pipeline(orch, review_id: str):
    student_id = f"e2e-stu-{review_id[:8]}"

    req = AgentRequest(
        student_id=student_id,
        tenant_id=TENANT_ID,
        session_id=PIPELINE_SID,                 # 固定，方便 Phase 2 推算 thread_id
        agent_type=AgentType.RESUME,
        user_message="请帮我审查简历并准备模拟面试",
        pipeline_mode=True,
        context={
            "pipeline_key":    "job_preparation",
            "review_id":       review_id,
            "pdf_local_path":  PDF_PATH,
            "pdf_minio_path":  "",
            "target_position": TARGET_POS,
        },
    )

    print(f"Pipeline thread_id (Resume 步骤): {req.thread_id}")
    print("启动 Pipeline，等待响应（简历审查约需 30–60 秒）…\n")

    resp = await orch.handle(req)
    return student_id, req, resp


# ─────────────────────────────────────────────────────────────────────
#  Phase 2：续跑面试（多轮对话）
#  session_id 必须与 Pipeline 内部给 Interview 分配的一致：
#    _run_pipeline 里 idx=1（Interview） → session_id = f"{PIPELINE_SID}_step1"
#  使用相同 thread_id 命中 MemorySaver，面试状态无缝续接
# ─────────────────────────────────────────────────────────────────────
async def phase2_interview(orch, student_id: str):
    # 对齐 _run_pipeline 里 step_request 的 session_id 格式
    interview_session_id = f"{PIPELINE_SID}_step1"

    section(f"Phase 2：续跑面试（共 {len(AUTO_ANSWERS)} 轮）")
    print(f"Interview thread_id: student_{student_id}_session_{interview_session_id}")
    print("── 下面每一轮：脚本自动作答 → 面试官给出下一个问题 ──\n")

    for turn_idx, answer in enumerate(AUTO_ANSWERS):
        turn_num = turn_idx + 2          # Phase 1 已经是第 1 轮，这里从第 2 轮开始

        # 打印本轮学员的回答
        print(f"┌─ 第 {turn_num} 轮 ── 学员回答 ".ljust(62, "─") + "┐")
        print(f"│ {answer[:120]}{'…' if len(answer) > 120 else ''}")
        print("└" + "─" * 62 + "┘")

        turn_req = AgentRequest(
            student_id=student_id,
            tenant_id=TENANT_ID,
            session_id=interview_session_id,     # ← 关键：与 Pipeline 分配给 Interview 的一致
            agent_type=AgentType.INTERVIEW,
            user_message=answer,
            pipeline_mode=False,                 # 直接进 _run_single_agent，不再触发 Pipeline
            context={
                "target_position": TARGET_POS,
            },
        )

        turn_resp = await orch.handle(turn_req)

        # 打印面试官的回应
        ai_content = turn_resp.content or "(无文本响应)"
        print(f"\n► 面试官（第 {turn_num} 轮响应，前 400 字）:")
        print(ai_content[:400] + ("…" if len(ai_content) > 400 else ""))

        # 检查是否已生成面试报告（FINISHED 阶段）
        structured = turn_resp.structured or {}
        if structured.get("report") or structured.get("overall_score"):
            section("面试报告已生成（FINISHED 阶段）")
            print(f"综合评分      : {structured.get('overall_score', '—')}")
            print(f"技术深度      : {structured.get('technical_depth', '—')}")
            print(f"表达逻辑      : {structured.get('expression_logic', '—')}")
            print(f"项目理解      : {structured.get('project_understanding', '—')}")
            print(f"核心优势      : {structured.get('strengths', '—')}")
            print(f"提升建议      : {structured.get('improvements', '—')}")
            print("\n✅ 面试已达到 FINISHED 阶段，报告生成完毕")
            return True

        print()   # 每轮之间空一行

    print(f"\n── {len(AUTO_ANSWERS)} 轮对话完成，面试持续推进中（未到 FINISHED，按预期） ──")
    print("    真实面试通常需要 15–25 轮才到 FINISHED，测试脚本跑 6 轮用于演示流程。")
    return False


# ─────────────────────────────────────────────────────────────────────
#  主流程
# ─────────────────────────────────────────────────────────────────────
async def main():
    section("端到端测试：真实 PDF → 简历审查 → 模拟面试（多轮）")

    review_id = await setup_review_record()

    try:
        orch = get_orchestrator()

        # ── Phase 1：Pipeline ─────────────────────────────────────
        section("Phase 1：Pipeline（简历审查 + 面试首轮）")
        student_id, pipeline_req, resp = await phase1_pipeline(orch, review_id)

        assert resp.success, f"Pipeline 整体失败: {resp.error_msg}"
        print(f"success      : {resp.success}")
        print(f"执行步骤     : {list((resp.structured or {}).keys())}")

        # Step 1：简历审查
        section("Step 1 详情：简历审查结果")
        step1 = (resp.structured or {}).get("step_1", {})
        s1_data = step1.get("structured") or {}
        score   = s1_data.get("weighted_score", -1)
        print(f"success          : {step1.get('success')}")
        print(f"weighted_score   : {score}")
        print(f"dimensions       : {list(s1_data.get('dimensions', {}).keys())}")
        print(f"review_id (returned): {s1_data.get('review_id')}")

        assert step1.get("success"),  "Step 1（简历审查）失败"
        assert score >= 0,             "weighted_score 未写回"

        # # 验证 save_results_node 落库
        # db_score = await get_db_score(review_id)
        # print(f"DB 落库 score    : {db_score}")
        # assert db_score >= 0, "resume_reviews 里未找到 scores，save_results_node 可能未执行"
        #
        # # Step 2：面试首轮
        # section("Step 2 详情：面试首轮（Pipeline 自动启动）")
        # if score >= 60:
        #     step2 = (resp.structured or {}).get("step_2", {})
        #     print(f"success      : {step2.get('success')}")
        #     print(f"\n面试官首问（Pipeline 结果 content 最后 400 字）:")
        #     print(resp.content[-400:])
        #     assert "step_2" in (resp.structured or {}), "score≥60 但未找到 step_2，面试未启动"
        # else:
        #     print(f"简历评分 {score:.1f} < 60，Pipeline 在门槛处终止，面试未启动 ✓")
        #     assert "step_2" not in (resp.structured or {}), "score<60 但 step_2 意外存在"
        #     print("\n⚠  简历评分不足 60 分，跳过 Phase 2 面试续跑")
        #     return
        #
        # # ── Phase 2：续跑面试 ─────────────────────────────────────
        # await phase2_interview(orch, student_id)
        #
        # section("✅ 端到端测试通过")
        # print(f"• 真实 PDF      : {PDF_PATH}")
        # print(f"• 简历综合分    : {score:.1f}")
        # print(f"• DB 落库分     : {db_score:.1f}")
        # print(f"• 面试轮次      : {len(AUTO_ANSWERS) + 1} 轮（含 Pipeline 首轮）")
        # print(f"• 数据流已验证  : resume_review_id → Interview load_context_node")

    finally:
        await cleanup(review_id)


asyncio.run(main())
