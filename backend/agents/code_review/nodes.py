from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import text

from backend.agents.code_review.prompts import (
    CODE_REVIEW_SYSTEM_PROMPT,
    DIMENSION_REVIEW_PROMPT,
    DIMENSIONS,
)
from backend.agents.code_review.state import (
    CodeIssue,
    CodeReviewState,
    CodeReviewSummary,
    CodeStructure,
    DimensionScore,
)
from backend.config import get_settings
from backend.core.llm_factory import get_structured_llm
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal


logger = get_logger(__name__)
settings = get_settings()

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".ts": "typescript",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".go": "go",
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def detect_language(file_name: str) -> str:
    return LANGUAGE_BY_SUFFIX.get(Path(file_name).suffix.lower(), "text")


def _issue(
    dimension: str,
    severity: str,
    title: str,
    suggestion: str,
    *,
    line: int | None = None,
    evidence: str = "",
) -> CodeIssue:
    return CodeIssue(
        dimension=dimension,
        severity=severity,
        title=title,
        evidence=evidence,
        line=line,
        suggestion=suggestion,
    )


def analyze_code_locally(source: str, file_name: str) -> tuple[CodeStructure, dict[str, DimensionScore]]:
    """Deterministic baseline used both as a guardrail and as an offline fallback."""
    language = detect_language(file_name)
    lines = source.splitlines()
    structure = CodeStructure(language=language, file_name=file_name, line_count=len(lines))
    scores = {
        key: DimensionScore(dimension=label, score=82, summary="未发现明显问题", issues=[])
        for key, label, _focus, _weight in DIMENSIONS
    }

    if not source.strip():
        issue = _issue("功能正确性", "critical", "代码为空", "提交可运行的源代码。")
        scores["correctness"] = DimensionScore(
            dimension="功能正确性", score=0, summary="没有可评审代码", issues=[issue]
        )
        structure.syntax_valid = False
        structure.syntax_error = "empty source"
        return structure, scores

    long_lines = [i for i, value in enumerate(lines, 1) if len(value) > 120]
    if long_lines:
        scores["readability"].score -= min(20, len(long_lines) * 2)
        scores["readability"].issues.append(
            _issue(
                "可读性与规范",
                "low",
                "存在过长代码行",
                "拆分表达式或提取局部变量，使单行不超过 120 个字符。",
                line=long_lines[0],
                evidence=f"共 {len(long_lines)} 行超过 120 个字符",
            )
        )

    duplicate_literals = len(re.findall(r"(['\"])(.{8,}?)\1", source))
    if duplicate_literals > 8:
        scores["maintainability"].score -= 8
        scores["maintainability"].issues.append(
            _issue(
                "模块化与可维护性",
                "low",
                "代码中包含较多较长字面量",
                "把重复使用的文本或配置提取为常量。",
                evidence=f"检测到 {duplicate_literals} 个较长字符串字面量",
            )
        )

    dangerous_patterns = (
        (r"\beval\s*\(", "eval 会执行任意表达式"),
        (r"\bexec\s*\(", "exec 会执行任意代码"),
        (r"os\.system\s*\(", "os.system 可能造成命令注入"),
        (r"subprocess\..*shell\s*=\s*True", "shell=True 可能造成命令注入"),
    )
    for pattern, reason in dangerous_patterns:
        match = re.search(pattern, source)
        if match:
            line = source[: match.start()].count("\n") + 1
            scores["security"].score -= 30
            scores["security"].issues.append(
                _issue(
                    "安全性",
                    "high",
                    "检测到危险代码执行方式",
                    "避免执行未经验证的字符串；改用类型化参数和白名单逻辑。",
                    line=line,
                    evidence=reason,
                )
            )

    if language != "python":
        structure.functions = re.findall(
            r"(?:function\s+|(?:public|private|protected|static|async|void|int|string)\s+)([A-Za-z_]\w*)\s*\(",
            source,
        )[:100]
        scores["correctness"].summary = "非 Python 代码仅完成通用静态检查，正确性需要测试用例或 LLM 进一步判断"
        return structure, scores

    try:
        tree = ast.parse(source, filename=file_name)
    except SyntaxError as exc:
        structure.syntax_valid = False
        structure.syntax_error = exc.msg
        issue = _issue(
            "功能正确性",
            "critical",
            "Python 语法错误",
            "根据错误行修正语法后重新提交。",
            line=exc.lineno,
            evidence=exc.msg,
        )
        scores["correctness"] = DimensionScore(
            dimension="功能正确性", score=15, summary="代码无法通过 Python 语法解析", issues=[issue]
        )
        return structure, scores

    structure.classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)][:100]
    function_nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    structure.functions = [node.name for node in function_nodes][:200]
    structure.imports = sorted(
        {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
    )
    if any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and "__name__" in ast.unparse(node.test)
        for node in ast.walk(tree)
    ):
        structure.entry_points.append("__main__")

    no_docstrings = [node for node in function_nodes if not ast.get_docstring(node)]
    if function_nodes and len(no_docstrings) / len(function_nodes) >= 0.6:
        scores["readability"].score -= 10
        node = no_docstrings[0]
        scores["readability"].issues.append(
            _issue(
                "可读性与规范",
                "low",
                "多数函数缺少用途说明",
                "为承担业务职责的函数补充简短 docstring。",
                line=getattr(node, "lineno", None),
                evidence=f"{len(no_docstrings)}/{len(function_nodes)} 个函数无 docstring",
            )
        )

    long_functions = [
        node
        for node in function_nodes
        if (getattr(node, "end_lineno", node.lineno) - node.lineno + 1) > 50
    ]
    if long_functions:
        scores["maintainability"].score -= min(24, 8 * len(long_functions))
        node = long_functions[0]
        scores["maintainability"].issues.append(
            _issue(
                "模块化与可维护性",
                "medium",
                "函数职责过多",
                "按输入处理、核心计算和输出组织拆分函数。",
                line=node.lineno,
                evidence=f"函数 {node.name} 超过 50 行",
            )
        )

    nested_depth = 0

    def visit_depth(node: ast.AST, depth: int = 0) -> None:
        nonlocal nested_depth
        control = isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.If, ast.Try, ast.With))
        current = depth + 1 if control else depth
        nested_depth = max(nested_depth, current)
        for child in ast.iter_child_nodes(node):
            visit_depth(child, current)

    visit_depth(tree)
    if nested_depth >= 5:
        scores["algorithm"].score -= min(25, (nested_depth - 4) * 7)
        scores["algorithm"].issues.append(
            _issue(
                "算法与复杂度",
                "medium",
                "控制流嵌套较深",
                "使用提前返回、拆分函数或更合适的数据结构降低嵌套。",
                evidence=f"最大控制流嵌套深度为 {nested_depth}",
            )
        )

    bare_except = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and node.type is None
    ]
    if bare_except:
        scores["robustness"].score -= min(30, 15 * len(bare_except))
        scores["robustness"].issues.append(
            _issue(
                "异常处理与健壮性",
                "medium",
                "使用了裸 except",
                "捕获具体异常并记录上下文，避免吞掉编程错误。",
                line=bare_except[0].lineno,
                evidence="except: 会捕获包括退出信号在内的全部异常",
            )
        )

    mutable_defaults = [
        node
        for node in function_nodes
        for default in node.args.defaults
        if isinstance(default, (ast.List, ast.Dict, ast.Set))
    ]
    if mutable_defaults:
        scores["robustness"].score -= 18
        scores["robustness"].issues.append(
            _issue(
                "异常处理与健壮性",
                "high",
                "函数使用可变默认参数",
                "默认值改为 None，并在函数内部创建新的容器。",
                line=mutable_defaults[0].lineno,
                evidence="可变默认值会在多次调用之间共享",
            )
        )

    for value in scores.values():
        value.score = max(0, min(100, value.score))
        if value.issues:
            value.summary = f"发现 {len(value.issues)} 个需要改进的问题"
    return structure, scores


async def load_source_node(state: CodeReviewState) -> dict[str, Any]:
    path = Path(state["source_path"])
    if not path.is_file():
        raise FileNotFoundError(f"代码文件不存在: {path}")
    if path.stat().st_size > settings.max_code_upload_bytes:
        raise ValueError("代码文件超过允许大小")
    source = path.read_text(encoding="utf-8", errors="replace")
    file_name = state.get("file_name") or path.name
    return {
        "file_name": file_name,
        "language": detect_language(file_name),
        "source_code": source,
    }


async def analyze_structure_node(state: CodeReviewState) -> dict[str, Any]:
    structure, local_scores = analyze_code_locally(state["source_code"], state["file_name"])
    return {
        "structure": structure.model_dump(),
        "dimension_scores": [value.model_dump() for value in local_scores.values()],
    }


async def run_dimension_reviews_node(state: CodeReviewState) -> dict[str, Any]:
    local_by_name = {item["dimension"]: DimensionScore.model_validate(item) for item in state["dimension_scores"]}
    if not settings.deepseek_api_key.strip():
        logger.info("code_review.local_fallback", reason="api_key_missing")
        return {"fallback_used": True}

    source = state["source_code"][:18000]
    structure_json = json.dumps(state["structure"], ensure_ascii=False)

    async def review_one(key: str, label: str, focus: str, _weight: float) -> DimensionScore:
        try:
            runnable = get_structured_llm("code_review", DimensionScore)
            result = await runnable.ainvoke(
                [
                    SystemMessage(content=CODE_REVIEW_SYSTEM_PROMPT),
                    HumanMessage(
                        content=DIMENSION_REVIEW_PROMPT.format(
                            dimension=label,
                            focus=focus,
                            structure=structure_json,
                            language=state["language"],
                            source_code=source,
                        )
                    ),
                ]
            )
            result.dimension = label
            for issue in result.issues:
                issue.dimension = label
            baseline = local_by_name[label]
            result.score = round(result.score * 0.75 + baseline.score * 0.25)
            known = {(item.title, item.line) for item in result.issues}
            result.issues.extend(
                item for item in baseline.issues if (item.title, item.line) not in known
            )
            return result
        except Exception as exc:
            logger.warning("code_review.dimension_failed", dimension=key, error=str(exc))
            return local_by_name[label]

    results = await asyncio.gather(*(review_one(*item) for item in DIMENSIONS))
    return {"dimension_scores": [item.model_dump() for item in results]}


async def aggregate_review_node(state: CodeReviewState) -> dict[str, Any]:
    score_by_name = {
        item["dimension"]: DimensionScore.model_validate(item)
        for item in state["dimension_scores"]
    }
    overall = round(
        sum(score_by_name[label].score * weight for _key, label, _focus, weight in DIMENSIONS)
    )
    all_issues = [issue for result in score_by_name.values() for issue in result.issues]
    deduped: dict[tuple[str, int | None], CodeIssue] = {}
    for issue in all_issues:
        key = (issue.title, issue.line)
        previous = deduped.get(key)
        if previous is None or SEVERITY_ORDER.get(issue.severity, 9) < SEVERITY_ORDER.get(previous.severity, 9):
            deduped[key] = issue
    issues = sorted(
        deduped.values(),
        key=lambda value: (SEVERITY_ORDER.get(value.severity, 9), value.line or 10**9),
    )
    grade = "A" if overall >= 90 else "B" if overall >= 80 else "C" if overall >= 70 else "D" if overall >= 60 else "E"
    strengths = [f"{label}表现较好" for _key, label, _focus, _weight in DIMENSIONS if score_by_name[label].score >= 85]
    priorities = [issue.title for issue in issues if issue.severity in {"critical", "high", "medium"}][:5]
    next_steps = [issue.suggestion for issue in issues[:5]] or ["补充测试用例并保持当前代码规范。"]
    summary = CodeReviewSummary(
        overall_score=overall,
        grade=grade,
        strengths=strengths or ["代码能够通过基础结构分析"],
        priorities=priorities,
        next_steps=next_steps,
    )
    structured = {
        "review_id": state["review_id"],
        "file_name": state["file_name"],
        "language": state["language"],
        "structure": state["structure"],
        "dimension_scores": [item.model_dump() for item in score_by_name.values()],
        "issues": [item.model_dump() for item in issues],
        "summary": summary.model_dump(),
        "overall_score": overall,
    }
    message = (
        f"代码审查完成：综合得分 {overall}，等级 {grade}。"
        f"共发现 {len(issues)} 个改进项，其中 {len(priorities)} 个建议优先处理。"
    )
    return {
        "issues": structured["issues"],
        "summary": structured["summary"],
        "overall_score": overall,
        "structured_output": structured,
        "messages": [AIMessage(content=message)],
    }


async def save_review_node(state: CodeReviewState) -> dict[str, Any]:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    """
                    UPDATE code_reviews
                    SET language = :language,
                        code_structure = CAST(:structure AS JSONB),
                        dimension_scores = CAST(:scores AS JSONB),
                        issues = CAST(:issues AS JSONB),
                        summary = CAST(:summary AS JSONB),
                        overall_score = :overall_score,
                        status = 'done',
                        error_msg = NULL,
                        updated_at = NOW()
                    WHERE id = :review_id AND tenant_id = :tenant_id
                    """
                ),
                {
                    "language": state["language"],
                    "structure": json.dumps(state["structure"], ensure_ascii=False),
                    "scores": json.dumps(state["dimension_scores"], ensure_ascii=False),
                    "issues": json.dumps(state["issues"], ensure_ascii=False),
                    "summary": json.dumps(state["summary"], ensure_ascii=False),
                    "overall_score": state["overall_score"],
                    "review_id": state["review_id"],
                    "tenant_id": state["tenant_id"],
                },
            )
            await session.commit()
    except Exception as exc:
        logger.error("code_review.save_failed", review_id=state.get("review_id"), error=str(exc))
        raise
    return {}
