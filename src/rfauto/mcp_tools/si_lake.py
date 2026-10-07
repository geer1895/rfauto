"""si_channel_report/lake_query_runs/lake_pack_campaign（SI 通道 + runs 湖薄壳）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 33. df7 T2 SI 通道报告（si_channel_service 薄壳） ────────────────────────

@mcp.tool
def si_channel_report(
    source: str,
    passivity_tol: float = 0.01,
    causality_threshold: float = 0.02,
    pre_cursor_guard_ns: float = 1.0,
    tdr_window_ns: float = 2.0,
    fext_paths: list[str] | None = None,
    next_paths: list[str] | None = None,
    markdown: bool = False,
) -> dict[str, Any]:
    """SI 通道报告（si_lake 域）：Touchstone/run → 无源性/因果性/TDR/COM。

    df7 T2 四段纯后处理只读面（零求解器）；不用于通道修复建议生成。
    无源性=全频段 σmax(S)≤1+tol（numpy SVD）；因果性=IEEE P370 风格
    （带限 IFFT 负时间能量占比 + 低频视在群延迟符号，自实现口径如实标注）；
    TDR=S11 阶跃响应阻抗剖面（前 2ns 均值/全程 min/max/平坦度+降采样剖面）；
    COM=IEEE 93A 冻结口径（PyChOpMarg，4 端口文件可用，2 端口如实
    not_applicable，pychopmarg 缺装/失败 degraded 不阻塞，#105）。
    源文件缺失/解析失败 → ok=False error 信封。只读无时序约束。

    Args:
        source: Touchstone 文件路径（.sNp）或 run 目录（sparams.csv 掩码
            口径优先，或 Touchstone 产物）
        passivity_tol: 无源性容差（max σmax ≤ 1+tol）
        causality_threshold: 负时间能量占比阈值
        pre_cursor_guard_ns: 因果性循环尾窗宽度 ns
        tdr_window_ns: TDR 统计窗 ns
        fext_paths: COM 远端串扰 4 端口文件列表（可选）
        next_paths: COM 近端串扰 4 端口文件列表（可选）
        markdown: True 时附带 markdown 渲染文本

    Returns:
        dict: {ok, source, passivity, causality, tdr, com, provenance,
        warnings, markdown?}
    """
    from rfauto.service.si_channel_service import si_channel_report
    try:
        return si_channel_report(
            source,
            passivity_tol=passivity_tol,
            causality_threshold=causality_threshold,
            pre_cursor_guard_ns=pre_cursor_guard_ns,
            tdr_window_ns=tdr_window_ns,
            fext_paths=fext_paths,
            next_paths=next_paths,
            markdown=markdown,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 34. df7 F3 runs 湖（lake_service 薄壳；MCP 面最小化注记） ────────────────
# MCP 面只暴露只读查询（lake_query_runs）与本地归档产出（lake_pack_campaign）。
# index/verify/restore 属本地运维面（index 写索引库、verify/restore 处理本地
# 归档落盘/恢复），不进 MCP——最小面原则；本地运维走 CLI `rfauto lake ...`。

@mcp.tool
def lake_query_runs(
    db_path: str | None = None,
    template: str | None = None,
    adapter: str | None = None,
    study: str | None = None,
    campaign: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """runs/ 湖索引只读查询（df7 F3）：等值过滤+日期段，参数化 ? 绑定。

    查询前需先建索引库（CLI `rfauto lake index` 或 service build_runs_index，
    属本地运维面不进 MCP）；库不存在/过滤值非法 → ok=False 如实不抛出。

    Args:
        db_path: 湖索引 DuckDB 路径（None=缺省 runs/.lake_index.duckdb）
        template: 模板过滤（meta.model 等值；None/空串不过滤）
        adapter: 适配器过滤（meta.adapter 等值；None/空串不过滤）
        study: study 过滤（meta.study_name 等值；None/空串不过滤）
        campaign: 战役目录名过滤（None/空串不过滤）
        date_from: 起始日期 YYYY-MM-DD（created_date 闭区间；None 不过滤）
        date_to: 截止日期 YYYY-MM-DD（created_date 闭区间；None 不过滤）
        limit: 返回行数上限（最小 1）

    Returns:
        dict: {ok, rows: [dict], n_rows, db_path, table}
    """
    from rfauto.service.lake_service import query_runs_index
    try:
        return query_runs_index(
            db_path, template=template, adapter=adapter, study=study,
            campaign=campaign, date_from=date_from, date_to=date_to,
            limit=limit)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def lake_pack_campaign(campaign_dir: str, out_path: str) -> dict[str, Any]:
    """战役冷层打包（si_lake 域）：战役目录 → tar.zst+偏移清单（只读源）。

    df7 F3。确定性排序+归一化 tar 头（同内容重打包 pack_sha256 逐位
    一致）；偏移清单落 ``<out_path>.manifest.json``（每文件 path/offset/
    size/sha256 + 整包 pack_sha256 内容寻址锚）。原目录零改动（只读），
    不用于热层数据删除。校验（verify）与恢复（restore）属本地运维面不进
    MCP，走 CLI ``rfauto lake verify/restore``。战役目录不存在/无文件 →
    ok=False 如实；写盘失败 → ok=False。时序：打包后校验走 CLI verify。

    Args:
        campaign_dir: 战役目录（只读，原目录零改动；不存在/无文件 ok=False）
        out_path: 归档落点（.tar.zst）

    Returns:
        dict: {ok, pack_path, manifest_path, n_files, total_bytes,
        pack_sha256, pack_size_bytes}
    """
    from rfauto.service.lake_service import pack_campaign
    try:
        return pack_campaign(campaign_dir, out_path)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 35. W7 台账①态接线：COM PAM4 单点运行（si_channel_service 薄壳，X3 批） ──

@mcp.tool
def com_pam4_run(
    thru_s4p: str,
    preset: str = "8023dj",
    fb_gbaud: float | None = None,
    fext_s4p: list[str] | None = None,
    next_s4p: list[str] | None = None,
    g_dc_stride: int = 8,
    g_dc2_stride: int = 11,
    pinned_taps: list[float] | None = None,
    opt_mode: str = "przf",
) -> dict[str, Any]:
    """单点 COM 运行（si_lake 域）：.s4p 通道 → COM/FOM（pychopmarg 权威）。

    IEEE 802.3。按随包 preset 重建参数后跑 COM：com_db（final-COM）与
    fom_db（优化 FOM，PRZF 时=93A-36）两列并报不自证一致（C2-1 口径）；
    verification=unverified_vs_802com_vectors 如实透传；不用于眼图仿真。
    契约错误（文件缺失/非 s4p/preset 未知）→ ok=False + errors；缺装 →
    ok=True+status="unavailable" 如实。粗档缺省（g_dc 8/g_dc2 11）
    秒级—十秒级。只读计算面，无时序约束。

    Args:
        thru_s4p: 直通 4 端口 Touchstone 路径（只受理 .s4p）
        preset: 随包 preset（"8023by" | "8023dj"；802.3ck 未随包发布）
        fb_gbaud: 覆盖波特率 Gbaud（None=preset 原值）
        fext_s4p: 远端串扰 4 端口文件列表（可选）
        next_s4p: 近端串扰 4 端口文件列表（可选）
        g_dc_stride: CTLE 一档等距抽稀（≥1；1=全档，缺省 8 粗档）
        g_dc2_stride: CTLE 二档等距抽稀（≥1，缺省 11 粗档）
        pinned_taps: 钉死 Tx FFE 全部抽头（长度=preset 抽头数，|v|.sum()≤1；
            钉抽头路线单组合秒级）
        opt_mode: 均衡选择目标（"przf"=93A 规格路线 | "mmse"）

    Returns:
        {ok, schema_version, result: {status, com_db, fom_db, fom_db_recalc,
        as_v, sigma_v, eq, params, source, verification, ...}, provenance}；
        契约错误（文件缺失/非 s4p/preset 未知）→ ok=False + errors；
        pychopmarg 缺装 → ok=True + result.status="unavailable"。
    """
    from rfauto.service.si_channel_service import com_pam4_run
    return com_pam4_run(
        thru_s4p,
        fext_s4p=fext_s4p,
        next_s4p=next_s4p,
        preset=preset,
        fb_gbaud=fb_gbaud,
        g_dc_stride=g_dc_stride,
        g_dc2_stride=g_dc2_stride,
        pinned_taps=pinned_taps,
        opt_mode=opt_mode,
    )
