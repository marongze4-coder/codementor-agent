# backend/agents/qa/nodes.py

import asyncio
import uuid

from sqlalchemy import text
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from backend.agents.qa.state import QAState
from backend.agents.qa.prompts import (
    HYDE_PROMPT,
    MULTI_QUERY_REWRITE_PROMPT,
    RAG_ANSWER_PROMPT,
    DIRECT_ANSWER_PROMPT,
    GENERAL_ANSWER_PROMPT,
    RAG_STRATEGY_PROMPT,
    SYSTEM_PROMPT,
)
from backend.core.llm_factory import get_llm
from backend.core.memory import (
    trim_messages_to_window,
    should_trigger_summary,
    compress_to_summary,
    build_thread_id,
)
from backend.config import get_settings
from backend.core.logger import get_logger
from backend.core.query_classifier import get_query_classifier

logger = get_logger(__name__)

# ── 检索相关常量 ───────────────────────────────────────────────
MAX_BROAD_QUERIES        = 3   # BROAD 分支最多并行的子 Query 数
RECALL_TOP_K_PRECISE     = 8   # PRECISE：直接检索召回数
RECALL_TOP_K_VAGUE       = 10  # VAGUE：HyDE 语义扩充后多召回些
RECALL_TOP_K_BROAD_PER   = 4   # BROAD：每个子 Query 的召回数
RERANK_TOP_K             = 3   # 精排后保留的最终 chunk 数

def _get_message_content(msg) -> str:
    """统一获取消息文本（兼容 .text 属性和 .content 属性）"""
    if hasattr(msg, "text") and not callable(getattr(msg, "text", None)):
        return msg.text
    if isinstance(msg.content, str):
        return msg.content
    return str(msg.content)


def _format_history_for_prompt(messages: list) -> str:
    """把最近几轮对话格式化为 Prompt 可用的文本"""
    lines = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            lines.append(f"学员：{_get_message_content(msg)}")
        elif isinstance(msg, AIMessage):
            # AI 回答截断，避免 Prompt 过长
            lines.append(f"AI：{_get_message_content(msg)[:200]}...")
    # print(f'lines: {lines}')
    return "\n".join(lines) if lines else "（无历史对话）"


_WEEKDAYS_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

def _current_datetime_str() -> str:
    """返回格式化的当前时间字符串，供注入 Prompt 使用"""
    from datetime import datetime
    now = datetime.now()
    # print(f'now: {now}')
    # print(f'now.weekday()-->{now.weekday()}')
    weekday = _WEEKDAYS_CN[now.weekday()]
    return now.strftime(f"%Y年%m月%d日 {weekday} %H:%M")

def _build_system_content(summary: str | None = None) -> str:
    """
    构建注入了当前时间的 SystemMessage 内容，所有生成节点共用。
    summary 非空时追加历史学习摘要，帮助 LLM 保持多轮上下文连贯。
    """
    content = SYSTEM_PROMPT + f"\n\n【当前时间】{_current_datetime_str()}"
    # print(f'content: {content}')
    if summary:
        content += f"\n\n【学员历史学习摘要】\n{summary}"
    return content

# ──────────────────────────────────────────────────────────────
# 联网请求自动识别
# ──────────────────────────────────────────────────────────────

_WEB_SEARCH_HINTS = (
    "联网", "联网查询", "联网搜索", "上网查", "上网搜", "网上搜",
    "搜索一下", "可以搜索", "帮我搜", "百度一下", "谷歌一下",
)

def _extract_query_and_web_flag(raw: str) -> tuple[str, bool]:
    """
    检测用户消息是否含联网请求指令。
    返回 (清洗后的问题, 是否自动启用联网)。

    联网指令部分被去除，防止被 LLM 当作问题内容处理。
    例："AI是什么，如果不知道可以联网搜索"
      → ("AI 是什么", True)
    """
    import re
    needs_web = any(h in raw for h in _WEB_SEARCH_HINTS)
    # print(f'needs_web: {needs_web}')
    if not needs_web:
        return raw, False
    # clean = re.sub(
    #     r'[，,。.？?！!\s]*(?:如果不知道|不知道的话|不清楚)?(?:你可以|可以)?'
    #     r'(?:联网|上网|网上)?(?:查询|搜索|搜一下|查一查|百度|谷歌).*$',
    #     '',
    #     raw
    # ).strip()
    clean = re.sub(
        r'[，,。.？?！!\s]*(?:如果不知道|不知道的话|不清楚|你可以)'
        r'?\s*(?:可以)?(?:联网|上网|网上)'
        r'?(?:查询|搜索|搜一下|查一查|百度|谷歌).*$',
        '',
        raw,
    ).strip()
    return (clean or raw), True

# ──────────────────────────────────────────────────────────────
# 规则集
# ──────────────────────────────────────────────────────────────

_GENERAL_EXACT = {
    "你好", "hi", "hello", "嗨", "hey",
    "谢谢", "谢谢你", "感谢", "thanks", "thank you",
    "你是谁", "你叫什么", "你叫什么名字", "你是什么",
    "你能做什么", "你有什么功能", "你能帮我做什么",
    "再见", "拜拜", "bye",
}

_GENERAL_KEYWORDS = (
    "你是谁", "你叫什么", "你能做什么", "你有什么功能",
    "介绍一下你自己", "自我介绍",
    "今天天气", "天气怎么样",
    "讲个笑话", "说个故事",
    "今天是", "今天几号", "今天是几号", "今天是星期",
    "现在是", "现在几点", "现在时间", "当前时间", "当前日期",
    "几月几号", "星期几", "是几月", "几号了", "日期是", "今天日期",
)

# 命中即确认为专业问题，跳过 MiniLM，直接进 Layer 2
_SPECIALIZED_KEYWORDS = (
    "课程", "实战", "项目", "案例", "老师", "章节",
    "作业", "课堂", "培训", "我们学的", "课程项目",
    "第几章", "第几节", "训练营",
)

_VAGUE_QUERY_HINTS = (
    "没懂", "不懂", "不太懂", "讲讲", "解释一下",
    "啥意思", "什么意思", "看不懂",
)
_BROAD_QUERY_HINTS = (
    "全面", "系统", "总结", "梳理", "路线",
    "对比", "区别", "全景", "有哪些",
)


def _rule_classify_general(query: str) -> bool:
    """规则层：是否为闲聊/时间/打招呼类（→ GENERAL）"""
    q = query.strip().lower()
    if q in _GENERAL_EXACT:
        return True
    return any(kw in q for kw in _GENERAL_KEYWORDS)



def _rule_classify_specialized(query: str) -> bool:
    """规则层：是否含课程/项目信号词（→ 专业，跳过 MiniLM）"""
    q = query.lower()
    return any(kw in q for kw in _SPECIALIZED_KEYWORDS)

def _fast_rag_strategy(query: str) -> str:
    """规则快判 RAG 策略（< 1ms）"""
    q = query.strip().lower()
    if len(q) <= 6 and any(kw in q for kw in _VAGUE_QUERY_HINTS):
        return "VAGUE"
    if any(kw in q for kw in _BROAD_QUERY_HINTS):
        return "BROAD"
    return "PRECISE"


async def _determine_rag_strategy(query: str) -> str:
    """LLM 精判 RAG 策略（仅在规则判为 VAGUE/BROAD 且问题较长时调用）"""
    try:
        llm = get_llm("qa", temperature=0)
        resp = await llm.ainvoke([
            HumanMessage(content=RAG_STRATEGY_PROMPT.format(query=query))
        ])
        label = _get_message_content(resp).strip().upper()
        if label in ("PRECISE", "VAGUE", "BROAD"):
            return label
    except Exception as e:
        logger.warning("classify_query.rag_strategy_failed", error=str(e))
    return "PRECISE"   # 兜底：最保守策略


async def _determine_rag_strategy_fast(query: str) -> str:
    """
    两阶段策略判定：
    ① 规则快判 → 若为 PRECISE，直接返回（不调 LLM）
    ② 规则判为 VAGUE/BROAD 且问题较长（≥18字）→ LLM 校正（避免误判）
    ③ 规则判为 VAGUE/BROAD 且问题极短 → 直接相信规则
    """
    strategy = _fast_rag_strategy(query)
    if strategy == "PRECISE":
        return strategy
    if len(query.strip()) >= 18:
        return await _determine_rag_strategy(query)
    return strategy


# ──────────────────────────────────────────────────────────────
# 节点：classify_query — Query 类型判断（含历史摘要加载）
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
# 节点：classify_query — Query 类型判断（含历史摘要加载）
# ──────────────────────────────────────────────────────────────

async def classify_query_node(state: QAState) -> dict:
    """
    Query 分类节点，决定走哪条处理路径。

    同时负责从 DB 加载当前会话的历史摘要（合并了源码中的 load_memory 节点）。

    返回的 query_type：
      GENERAL  → 跳过 RAG，直接 LLM 回答
      PRECISE  → 直接向量检索
      VAGUE    → 先 HyDE 再检索
      BROAD    → 先 Multi-Query 改写再并行检索
    """
    # ── 取最后一条 HumanMessage 作为原始输入 ─────────────────
    messages = state.get("messages", [])
    raw_query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            raw_query = _get_message_content(msg)
            break

    # ── 联网指令识别 ──────────────────────────────────────────
    original_query, auto_web = _extract_query_and_web_flag(raw_query)
    # print(f'original_query: {original_query}')
    # print(f'auto_web: {auto_web}')
    # ── 从 DB 加载历史摘要（取代 load_memory_and_embed_node）──
    existing_summary: str | None = None
    try:
        from backend.dependencies import AsyncSessionLocal
        thread_id = build_thread_id(state["student_id"], state["session_id"])
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                text("SELECT summary FROM qa_sessions WHERE thread_id = :tid"),
                {"tid": thread_id},
            )).fetchone()
            existing_summary = row[0] if row else None
    except Exception as e:
        logger.warning("classify_query.load_memory_failed", error=str(e))

    _base: dict = {
        "original_query":    original_query,
        "existing_summary":  existing_summary,
        "rewritten_queries": [],
        "hyde_document":     None,
    }
    if auto_web and not state.get("enable_web_search", False):
        _base["enable_web_search"] = True
        logger.info("classify_query.auto_web_enabled", query=original_query[:50])
    # print(f'_base: {_base}')
    # ── Layer 0a：规则 → GENERAL（闲聊/时间/打招呼）───────────
    if _rule_classify_general(original_query):
        logger.info("classify_query.general_by_rule", query=original_query[:50])
        return {**_base, "query_type": "GENERAL"}

        # ── Layer 0b：关键词快速通道 → 专业（课程/项目词）──────────
    if _rule_classify_specialized(original_query):
        logger.info("classify_query.specialized_by_keyword", query=original_query[:50])
        strategy = await _determine_rag_strategy_fast(original_query)
        logger.info("classify_query.rag_strategy", strategy=strategy)
        return {**_base, "query_type": strategy}
    # ── Layer 1：MiniLM 二分类（CPU 推理，线程池避免阻塞）──────
    loop = asyncio.get_running_loop()
    label, confidence = await loop.run_in_executor(
        None, get_query_classifier().classify, original_query
    )

    if label == "general":
        logger.info(
            "classify_query.general_by_minilm",
            query=original_query[:50],
            confidence=round(confidence, 4),
        )
        return {**_base, "query_type": "GENERAL"}
    # ── Layer 2：MiniLM → 专业，LLM 判检索策略 ──────────────
    logger.info(
        "classify_query.specialized_by_minilm",
        query=original_query[:50],
        confidence=round(confidence, 4),
    )
    strategy = await _determine_rag_strategy_fast(original_query)
    logger.info("classify_query.rag_strategy", strategy=strategy)
    return {**_base, "query_type": strategy}


# ──────────────────────────────────────────────────────────────
# 节点：hyde_generate — HyDE 假设文档生成（VAGUE 分支）
# ──────────────────────────────────────────────────────────────

async def hyde_generate_node(state: QAState) -> dict:
    """
    针对模糊 Query，让 LLM 先生成一段假设性回答文档，
    用该文档的向量代替原始 Query 向量去检索。

    temperature=0.3：生成结果要有一定多样性（覆盖更多语义），
    但不能太随机（避免偏离主题）。
    """
    query    = state["original_query"]
    messages = state.get("messages", [])

    history_text = _format_history_for_prompt(messages[-6:])  # 最近 3 轮

    prompt = HYDE_PROMPT.format(history=history_text, query=query)

    llm = get_llm("qa", temperature=0.3)
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    hyde_doc = _get_message_content(response).strip()

    logger.info(
        "hyde_generate.done",
        query=query[:50],
        hyde_doc_length=len(hyde_doc),
    )

    return {"hyde_document": hyde_doc}

# ──────────────────────────────────────────────────────────────
# 节点：multi_query_rewrite — Multi-Query 改写（BROAD 分支）
# ──────────────────────────────────────────────────────────────

async def multi_query_rewrite_node(state: QAState) -> dict:
    """
    针对宽泛/极短 Query，改写为 3-5 个具体子 Query，
    下一节 retrieve_node 会对这些子 Query 并行检索后合并去重。
    """
    query    = state["original_query"]
    messages = state.get("messages", [])

    # 取上一轮 AI 回答（推断"没懂"指的是什么）
    last_ai_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_ai_text = _get_message_content(msg)
            break

    prompt = MULTI_QUERY_REWRITE_PROMPT.format(
        last_answer=last_ai_text[:500] if last_ai_text else "（无上一轮回答）",
        query=query,
    )

    llm = get_llm("qa", temperature=0.3)
    response = await llm.ainvoke([HumanMessage(content=prompt)])

    # 解析：每行一个子 Query，去掉序号前缀（"1. " "①" "- " 等）
    raw = _get_message_content(response).strip()
    print(f'raw: {raw}')
    rewritten = [line.lstrip("0123456789.-）)、 ").strip()
                 for line in raw.split("\n") if line.strip() and len(line.strip()) > 3][:MAX_BROAD_QUERIES]

    if not rewritten:
        rewritten = [query]   # 改写失败时回退到原始 Query

    logger.info(
        "multi_query_rewrite.done",
        original=query,
        count=len(rewritten),
        queries=rewritten,
    )

    return {"rewritten_queries": rewritten}


# ──────────────────────────────────────────────────────────────
# 节点：retrieve — 混合召回 + 精排
# ──────────────────────────────────────────────────────────────

async def retrieve_node(state: QAState) -> dict:
    """
    调用 retrieve() Pipeline 完成检索与精排，直接输出 ranked_chunks。

    三条路径：
      PRECISE → 用 original_query 直接检索
      VAGUE   → 用 hyde_document 替代 original_query（语义扩充）
      BROAD   → 对所有 rewritten_queries 并行检索，结果合并去重

    retrieve() 是同步函数（BGE-M3 CPU 推理 + Milvus 阻塞 IO），
    必须用 run_in_executor 包装，避免阻塞 asyncio 事件循环。
    """
    from backend.core.reranker import retrieve, RankedDocument

    query_type     = state.get("query_type", "PRECISE").upper()
    tenant_id      = state["tenant_id"]
    course_id      = state.get("course_id")
    original_query = state["original_query"]

    loop = asyncio.get_running_loop()

    # ── BROAD：并行多 Query 检索，合并去重 ───────────────────────
    if query_type == "BROAD" and state.get("rewritten_queries"):
        broad_queries = state["rewritten_queries"][:MAX_BROAD_QUERIES]

        async def retrieve_one(sub_query: str) -> tuple[list, float]:
            return await loop.run_in_executor(
                None,
                lambda: retrieve(
                    sub_query,
                    tenant_id,
                    course_id,
                    recall_top_k=RECALL_TOP_K_BROAD_PER,
                    rerank_top_k=RERANK_TOP_K,
                ),
            )

        results = await asyncio.gather(*[retrieve_one(q) for q in broad_queries])
        # print(f'retrieve_one.results', results)
        # 合并去重：content 前 100 字符为 key，同一内容保留最高分
        seen: dict[str, RankedDocument] = {}
        for ranked_docs, _ in results:
            for doc in ranked_docs:
                key = doc.content[:100]
                if key not in seen or doc.score > seen[key].score:
                    seen[key] = doc

        merged = sorted(seen.values(), key=lambda x: x.score, reverse=True)[:RERANK_TOP_K]
        # ── PRECISE / VAGUE：单路检索 ─────────────────────────────────
    else:
        if query_type == "VAGUE" and state.get("hyde_document"):
            query_text = state["hyde_document"]
            recall_top_k = RECALL_TOP_K_VAGUE
        else:
            query_text = original_query
            recall_top_k = RECALL_TOP_K_PRECISE

        merged, _ = await loop.run_in_executor(
            None,
            lambda: retrieve(
                query_text,
                tenant_id,
                course_id,
                recall_top_k=recall_top_k,
                rerank_top_k=RERANK_TOP_K,
            ),
        )

        # ── 转换 RankedDocument → dict，写入 State ─────────────────────

    # print(f'merged: {merged}')
    # print("*"*80)
    ranked_chunks = [
        {
            "content": doc.content,
            "score": doc.score,
            "metadata": doc.metadata,
        }
        for doc in merged
    ]

    confidence = ranked_chunks[0]["score"] if ranked_chunks else 0.0
    is_high_confidence = confidence >= 0.75

    logger.info(
        "retrieve.done",
        query_type=query_type,
        ranked=len(ranked_chunks),
        confidence=round(confidence, 4),
        is_high_confidence=is_high_confidence,
    )

    return {
        "ranked_chunks": ranked_chunks,
        "confidence": confidence,
        "is_high_confidence": is_high_confidence,
    }

# ──────────────────────────────────────────────────────────────
# 节点：generate_rag — 高置信度 RAG 生成
# ──────────────────────────────────────────────────────────────

async def generate_rag_node(state: QAState) -> dict:
    """
    高置信度 RAG 生成节点。

    将精排后的 Top-3 文档拼成 context，让 LLM 严格基于知识库内容回答。
    回答末尾附加 📚 参考来源，支持历史摘要注入保持多轮连贯性。
    """
    ranked_chunks = state.get("ranked_chunks", [])
    query         = state["original_query"]
    messages      = state.get("messages", [])
    summary       = state.get("existing_summary")

    # 构建知识库上下文与来源列表
    context_parts = []
    sources = []
    for i, chunk in enumerate(ranked_chunks, 1):
        context_parts.append(f"【参考{i}】\n{chunk['content']}")
        source_name = chunk.get("metadata", {}).get("source_name", "课程文档")
        if source_name not in sources:
            sources.append(source_name)

    context_text = "\n\n".join(context_parts)

    # 消息列表：SystemMessage（含当前时间 + 历史摘要）
    llm_messages = [SystemMessage(content=_build_system_content(summary))]

    # 注入历史对话窗口（排除最后一条 HumanMessage）
    # 最后一条 HumanMessage 已拼入 RAG_ANSWER_PROMPT 的 {query}，
    # 再传一次会让问题在上下文里出现两次，影响生成质量。
    windowed = trim_messages_to_window(messages[:-1], window_size=10)
    for msg in windowed:
        if not isinstance(msg, SystemMessage):
            llm_messages.append(msg)

    rag_prompt = RAG_ANSWER_PROMPT.format(context=context_text, query=query)
    llm_messages.append(HumanMessage(content=rag_prompt))

    llm = get_llm("qa", streaming=True)
    response = await llm.ainvoke(llm_messages)
    answer_text = _get_message_content(response).strip()

    sources_text = "\n".join([f"  • {s}" for s in sources])
    final_answer = f"{answer_text}\n\n📚 **参考来源**\n{sources_text}"

    logger.info(
        "generate_rag.done",
        answer_length=len(final_answer),
        sources=sources,
        confidence=round(state.get("confidence", 0), 4),
    )

    return {
        "answer":      final_answer,
        "sources":     sources,
        "answer_mode": "rag",
        "messages":    [AIMessage(content=final_answer)],
        "should_summarize": should_trigger_summary(messages),
        "structured_output": {
            "answer":      final_answer,
            "sources":     sources,
            "confidence":  state.get("confidence", 0),
            "answer_mode": "rag",
        },
    }


# ──────────────────────────────────────────────────────────────
# 节点：web_search — Web 搜索补充（低置信度分支）
# ──────────────────────────────────────────────────────────────

async def web_search_node(state: QAState) -> dict:
    """
    低置信度分支的 Web 搜索节点。

    知识库置信度不足时，调用 Web Search MCP Server 补充互联网信息。
    MCP Server 不可用时静默降级，返回空列表，不阻断后续生成节点。
    """
    from backend.mcp.client import call_mcp_tool

    settings = get_settings()

    if not settings.web_search_mcp_url:
        return {"web_search_results": []}

    try:
        results = await call_mcp_tool(
            server_url=settings.web_search_mcp_url,
            tool_name="web_search",
            arguments={
                "query":       state["original_query"],
                "max_results": 3,
            },
            timeout=10.0,
        )
        count = len(results or [])
        logger.info("web_search.done", count=count)
        return {"web_search_results": results or []}
    except Exception as e:
        logger.warning("web_search.failed", error=str(e))
        return {"web_search_results": []}


# ──────────────────────────────────────────────────────────────
# 节点：generate_direct — 低置信度 LLM 直答（含 Web 搜索补充）
# ──────────────────────────────────────────────────────────────

async def generate_direct_node(state: QAState) -> dict:
    """
    低置信度 LLM 直答节点。

    知识库无足够相关内容时，直接用 LLM 参数知识回答。
    有 Web 搜索结果时注入为上下文（web_augmented 模式）；
    无搜索结果时在回答末尾追加 ⚠️ 提示（llm_direct 模式）。
    """
    query    = state["original_query"]
    messages = state.get("messages", [])
    summary  = state.get("existing_summary")

    llm_messages = [SystemMessage(content=_build_system_content(summary))]

    windowed = trim_messages_to_window(messages[:-1], window_size=10)
    for msg in windowed:
        if not isinstance(msg, SystemMessage):
            llm_messages.append(msg)

    # ── Web 搜索结果注入 ──────────────────────────────────────
    web_results = state.get("web_search_results") or []
    # print(f'web_results-->{web_results}')
    web_context = ""
    web_sources: list[str] = []
    if web_results:
        snippets = "\n".join(
            f"  [{i + 1}] {r.get('title', '')}（{r.get('url', '')}）\n {r.get('snippet', '')[:300]}"
            for i, r in enumerate(web_results)
        )
        web_context = f"\n\n【Web 搜索补充参考】\n{snippets}"
        web_sources = [r.get("url", "") for r in web_results if r.get("url")]
    # print(f'web_context-->{web_context}')
    # print(f'web_sources-->{web_sources}')
    #
    direct_prompt = DIRECT_ANSWER_PROMPT.format(query=query) + web_context
    llm_messages.append(HumanMessage(content=direct_prompt))

    llm = get_llm("qa", streaming=True)
    response = await llm.ainvoke(llm_messages)
    answer_text = _get_message_content(response).strip()
    # print(f'answer_text-->{answer_text}')

    if web_sources:
        # URL 通过 sources 字段传给前端，由 UI 折叠面板展示，不拼进正文
        final_answer = answer_text
        answer_mode  = "web_augmented"
    else:
        final_answer = (
            f"{answer_text}\n\n"
            f"⚠️ **说明**：以上为 AI 基于通用知识的回答，课程知识库中暂无相关内容。"
            f"建议以教师讲解为准，或联系教师补充相关资料。"
        )
        answer_mode = "llm_direct"

    logger.info(
        "generate_direct.done",
        answer_length=len(final_answer),
        confidence=round(state.get("confidence", 0), 4),
        web_sources=len(web_sources),
    )

    return {
        "answer":      final_answer,
        "sources":     web_sources,
        "answer_mode": answer_mode,
        "messages":    [AIMessage(content=final_answer)],
        "should_summarize": should_trigger_summary(messages),
        "structured_output": {
            "answer":      final_answer,
            "sources":     web_sources,
            "confidence":  state.get("confidence", 0),
            "answer_mode": answer_mode,
        },
    }


# ──────────────────────────────────────────────────────────────
# 节点：generate_general — 通用问题直答（跳过 RAG）
# ──────────────────────────────────────────────────────────────

async def generate_general_node(state: QAState) -> dict:
    """
    通用问题直答节点（query_type=GENERAL）。

    适用于：打招呼、问时间、闲聊等与课程无关的问题。
    联网模式下若 web_search_results 非空，注入搜索结果提供时效性信息。
    """
    query       = state["original_query"]
    messages    = state.get("messages", [])
    web_results = state.get("web_search_results") or []

    web_context = ""
    web_sources: list[str] = []
    if web_results:
        snippets = "\n".join(
            f"  [{i + 1}] {r.get('title', '')}（{r.get('url', '')}）\n"
            f"      {r.get('snippet', '')[:300]}"
            for i, r in enumerate(web_results)
        )
        web_context = f"【Web 搜索结果】\n{snippets}\n\n"
        web_sources = [r.get("url", "") for r in web_results if r.get("url")]

    history_text = _format_history_for_prompt(messages[-6:])
    prompt = GENERAL_ANSWER_PROMPT.format(
        query=query,
        history=history_text,
        current_time=_current_datetime_str(),
        web_context=web_context,
    )
    # print(f'prompt: {prompt}')
    # print("*"*80)
    llm = get_llm("qa", streaming=True)
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    answer_text = _get_message_content(response).strip()

    answer_mode = "web_augmented" if web_sources else "general"
    # print(f'answer_text: {answer_text}')
    # print("*" * 80)
    logger.info(
        "generate_general.done",
        answer_length=len(answer_text),
        web_sources=len(web_sources),
    )

    return {
        "answer":      answer_text,
        "sources":     web_sources,
        "answer_mode": answer_mode,
        "messages":    [AIMessage(content=answer_text)],
        "should_summarize": should_trigger_summary(messages),
        "structured_output": {
            "answer":      answer_text,
            "sources":     web_sources,
            "confidence":  1.0,
            "answer_mode": answer_mode,
        },
    }
# ──────────────────────────────────────────────────────────────
# 节点：enqueue_pending — 低置信度问题入队（纯副作用）
# ──────────────────────────────────────────────────────────────

async def enqueue_pending_node(state: QAState) -> dict:
    """
    将低置信度问题写入 knowledge_pending_queue，供教师审查补充知识库。

    ON CONFLICT DO NOTHING：幂等写入，同一问题重复触发不会产生重复记录。
    失败静默，不影响已生成的回答。返回 {} 不修改 State。
    """
    from backend.dependencies import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        INSERT INTO knowledge_pending_queue
                            (id, tenant_id, question, student_id, confidence, status)
                        VALUES (:id, :tenant_id, :question, :student_id, :confidence, 'pending')
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "id":         str(uuid.uuid4()),
                        "tenant_id":  state["tenant_id"],
                        "question":   state["original_query"],
                        "student_id": state["student_id"],
                        "confidence": state.get("confidence", 0.0),
                    },
                )
        logger.info(
            "enqueue_pending.done",
            question=state["original_query"][:50],
            confidence=state.get("confidence", 0),
        )
    except Exception as e:
        logger.warning("enqueue_pending.failed", error=str(e))

    return {}

# ──────────────────────────────────────────────────────────────
# 节点：save_memory — 记忆保存（纯副作用）
# ──────────────────────────────────────────────────────────────

async def save_memory_node(state: QAState) -> dict:
    """
    记忆保存节点：条件触发摘要压缩 + 写回 qa_sessions 表。

    should_summarize=True（对话超过 10 轮）时先压缩历史再写库。
    两步均失败静默，不中断流程。返回 {} 不修改 State。
    """
    from backend.dependencies import AsyncSessionLocal

    messages   = state.get("messages", [])
    student_id = state["student_id"]
    session_id = state["session_id"]
    tenant_id  = state["tenant_id"]
    thread_id  = build_thread_id(student_id, session_id)
    summary    = state.get("existing_summary")

    # ── 条件触发摘要压缩 ─────────────────────────────────────────
    if state.get("should_summarize", False):
        msgs_to_compress = trim_messages_to_window(messages, window_size=10)

        try:
            summary = await compress_to_summary(
                messages=msgs_to_compress,
                existing_summary=summary,
            )
            logger.info("save_memory.summary_compressed", thread_id=thread_id)
        except Exception as e:
            logger.warning("save_memory.compress_failed", error=str(e))

    # ── UPSERT 到 qa_sessions 表 ──────────────────────────────────
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            INSERT INTO qa_sessions
                                (id, tenant_id, student_id, thread_id, summary, summary_version)
                            VALUES (:id, :tenant_id, :student_id, :thread_id, :summary, 1)
                            ON CONFLICT (thread_id) DO UPDATE
                                SET summary         = EXCLUDED.summary,
                                    summary_version = qa_sessions.summary_version + 1,
                                    updated_at      = NOW()
                        """),
                        {
                            "id":         str(uuid.uuid4()),
                            "tenant_id":  tenant_id,
                            "student_id": student_id,
                            "thread_id":  thread_id,
                            "summary":    summary,
                        },
                    )
        except Exception as e:
            logger.warning("save_memory.db_write_failed", error=str(e))

    return {}


if __name__ == '__main__':
    # messages = [SystemMessage(content="你是一个专家"),
    #             HumanMessage(content="你是谁"),
    #             AIMessage(content="我叫张三")]
    #
    # print(_format_history_for_prompt(messages))
    # print(_current_datetime_str())
    # _build_system_content()
    # print(_extract_query_and_web_flag(raw="什么是AI, 如果不知道可以联网搜索"))
    # print(_rule_classify_general(query="你好"))
    # print(_rule_classify_specialized(query="AI课程怎么样"))
    # print(_fast_rag_strategy(query="全面的帮我概括下"))
    import asyncio
    # print(asyncio.run(_determine_rag_strategy(query="Transformer模型的架构组成部分是什么")))
    # 测试下规则下：判断问题为GENERAL
    # state = {"messages": [HumanMessage(content="模型训练的时候是怎么计算梯度的"),
    #                       AIMessage(content="反向传播的算法")],
    #          "original_query":"给我概括下",
    #          "student_id":"stu_001",
    #          "session_id":"sess_001"}
    # result = asyncio.run(classify_query_node(state))
    # result = asyncio.run(hyde_generate_node(state))
    # result = asyncio.run(multi_query_rewrite_node(state))
    # print(f'result: {result}')
    # results = asyncio.run(retrieve_node(state))
    # state.update(results)
    # results2 = asyncio.run(generate_rag_node(state))
    # print(results2)
    # 一定开启mcp server服务（new_main.py运行）
    # results3 = asyncio.run(web_search_node(state))
    # # print(f'results3={results3}')
    # state = {"query_type":"PRECISE",
    #          "original_query":"什么是AI",
    #          "tenant_id":"tenant_default",}
    # #
    # web_search_results = {'web_search_results': [{'title': '人工智能',
    #                                              'url': 'https:www.123.com',
    #                                              'snippet': '人工智能',
    #                                              'content': '人工智能（AI）让机器像人一样智能，代替人类工作'}]}
    # state.update(web_search_results)
    # # results4 = asyncio.run(generate_direct_node(state))
    # # print(results4)
    # results5 = asyncio.run(generate_general_node(state))
    # print(results5)
    # state = {"query_type": "PRECISE",
    #          "original_query": "什么是AI",
    #          "tenant_id": "tenant_default", }
    # # state.update(web_search_results)
    # state = {"query_type": "PRECISE",
    #          "original_query": "AI和JAVA有什么区别和联系",
    #          "tenant_id": "tenant_default",
    #          "student_id":"1efe1246-e355-4714-8b1b-bd4e7c8bce51", #必须在users库中出现
    #          "confidence": 0.74}
    #
    # asyncio.run(enqueue_pending_node(state))
    state = {"messages": [HumanMessage(content="模型训练的时候是怎么计算梯度的"),
                          AIMessage(content="反向传播的算法")],
             "original_query": "给我概括下",
             "student_id":"1efe1246-e355-4714-8b1b-bd4e7c8bce51",
             "tenant_id": "tenant_default",
             "session_id": "sess_001",
             "existing_summary":"这是我们给大家演示的最最新的摘要"}
    result5 = asyncio.run(save_memory_node(state))
    print("*"*80)
    print(result5)


