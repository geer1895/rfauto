"""rationale_recall/rationale_checklist/rag_query/rag_explain（F11/F2 经验记忆与 RAG 只读检索）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope


@mcp.tool
def rationale_recall(
    task: str,
    memory_path: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """F11 经验记忆检索：任务描述 → 命中历史坑/核对表/动作（确定性，无 embedding）。

    无副作用，可安全调用。缺省用内置经验（#198/#219/#152 网格伪象核对表）；
    未命中不硬凑（零命中=正常结果）。命中即附离线审计要求时如实在
    require_offline_audit 标注。空任务 → ok=False。只读无时序约束。

    Args:
        task: 任务描述文本（模板名/场景关键词）
        memory_path: 外部经验记忆 JSON（save_entries 产物）；缺省仅内置
        top_k: 返回命中数上限

    Returns:
        dict: {ok, hits, checklists, actions, require_offline_audit}
    """
    from rfauto.service.rationale_memory import recall_with_memory
    return recall_with_memory(task, memory_path=memory_path, top_k=top_k)


@mcp.tool
def rationale_checklist(
    template: str,
    extras: str | None = None,
    memory_path: str | None = None,
) -> dict[str, Any]:
    """F11 冒烟前核对表门禁：模板名 → 核对表 + gate（命中即要求先离线审计）。

    无副作用，可安全调用。返回 markdown 章节供报告/任务书直接嵌入。
    未命中=空核对表非错误；gate 非空时冒烟/真跑前必须先离线审计。
    空模板名 → ok=False。只读无时序约束。

    Args:
        template: 模板名（如 patch、cyl_grid）
        extras: 场景补充关键词（可选）
        memory_path: 外部经验记忆 JSON；缺省仅内置

    Returns:
        dict: {ok, template, checklists, actions, hits, require_offline_audit, gate, markdown}
    """
    from rfauto.service.rationale_memory import checklist_with_memory
    return checklist_with_memory(template, extras=extras, memory_path=memory_path)


# ─── 32. RAG 知识库检索（F2⑥ 薄壳，只读词法 BM25） ──────────────────────────

@mcp.tool
def rag_query(
    text: str,
    top_k: int = 5,
    docs_dir: str | None = "docs",
    runs_dir: str | None = "runs",
    runs_limit: int | None = None,
    mode: str = "lexical",
    alpha: float = 0.5,
) -> dict[str, Any]:
    """RAG 知识库检索（只读；citation 文件+标题+行号可溯）。

    索引仓库文档（docs/**/*.md）与 runs/ 战役元数据（meta.json +
    recipe.snapshot.yaml）；确定性、零网络。mode=lexical（缺省）为词法
    BM25；mode=semantic 为确定性语义档（hashing/TF-IDF 降级路线，非真
    embedding，无语义泛化）；mode=hybrid 为 BM25×语义混合排序（alpha
    融合系数：0=纯词法、1=纯稠密）。
    agent 开工前知识命中核对：与 rationale_checklist（F11 核对表门禁）
    配套使用，命中 citation 可直接打开原文核对。
    不用于数值取证（snippet 仅供上下文）；目录全缺失 → ok=False errors
    信封。只读；大语料首查需建索引（慢），无时序约束。

    Args:
        text: 查询文本（中英文皆可，CJK bigram 分词）
        top_k: 返回命中数上限
        docs_dir: 文档目录（传 null 跳过该来源）
        runs_dir: runs 历史目录（传 null 跳过该来源）
        runs_limit: 最多索引 N 个 run 目录
        mode: 检索模式 lexical|semantic|hybrid（缺省 lexical 词法 BM25）
        alpha: hybrid 模式融合系数（0.0 到 1.0，仅 mode=hybrid 消费）

    Returns:
        dict: {ok, query, query_terms, n_indexed, n_hits, n_matched,
               hits: [{rank, score, chunk_id, source_kind, citation, snippet}]}
    """
    if mode == "semantic":
        from rfauto.service.rag_service import semantic_query_corpus
        return semantic_query_corpus(text, top_k=top_k, docs_dir=docs_dir,
                                     runs_dir=runs_dir, base_dir=".",
                                     runs_limit=runs_limit)
    if mode == "hybrid":
        from rfauto.service.rag_service import hybrid_query_corpus
        return hybrid_query_corpus(text, top_k=top_k, alpha=alpha,
                                   docs_dir=docs_dir, runs_dir=runs_dir,
                                   base_dir=".", runs_limit=runs_limit)
    if mode != "lexical":
        # 与 CLI BadParameter 同口径：非法 mode 显式报错信封，不静默落词法
        return error_envelope(f"mode 必须是 lexical|semantic|hybrid，收到 {mode!r}")
    from rfauto.service.rag_service import query_corpus
    return query_corpus(text, top_k=top_k, docs_dir=docs_dir,
                        runs_dir=runs_dir, base_dir=".", runs_limit=runs_limit)


@mcp.tool
def rag_explain(
    text: str,
    top_k: int = 5,
    docs_dir: str | None = "docs",
    runs_dir: str | None = "runs",
    runs_limit: int | None = None,
) -> dict[str, Any]:
    """RAG 检索 + 逐词 BM25 分数明细（tf/df/idf/contribution，打分可溯）。

    同 rag_query（只读词法检索、citation 可溯），额外给出每个命中的
    逐词打分明细，便于核对"为什么命中/排名"。
    失败形态同 rag_query（目录全缺失 → ok=False errors 信封）；不用于
    数值取证。只读；大语料首查需建索引，无时序约束。

    Args:
        text: 查询文本（中英文皆可）
        top_k: 返回命中数上限
        docs_dir: 文档目录（传 null 跳过该来源）
        runs_dir: runs 历史目录（传 null 跳过该来源）
        runs_limit: 最多索引 N 个 run 目录

    Returns:
        dict: 同 rag_query，hits[].score_breakdown 附逐词明细
    """
    from rfauto.service.rag_service import explain_corpus
    return explain_corpus(text, top_k=top_k, docs_dir=docs_dir,
                          runs_dir=runs_dir, base_dir=".", runs_limit=runs_limit)
