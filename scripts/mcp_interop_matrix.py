r"""FE-2 MCP 生态互通能力矩阵生成器（W5-D，零网络）。

我方面=live 注册面（asyncio list_tools/list_resources，test_mcp_server 同法）；
彼方面=peer_snapshots/*.json 离线快照（URL+分支+快照日期留档；commit 锚缺失时
在快照内如实注明）。**本脚本零网络 IO**——只读本地快照，不拉远端；快照由
带网络窗的会话经用户代理通道（web_reader/zread）预先取回落盘。

能力域 10 列（rfauto docs 域分类同源）：建模/求解/后处理/优化/校准/测量/版图/
知识/远程/基准；格值=有（工具名列表）/无/未知（快照缺失，离线降级）。
我方工具名→域映射为脚本内人工维护常量（前缀规则+显式覆盖），未命中进
"未映射"清单如实披露（不硬塞）。

用法::

    .venv/Scripts/python.exe scripts/mcp_interop_matrix.py \
        [--snapshots-dir runs/w5_phase5/w5d/peer_snapshots] \
        [--outdir runs/w5_phase5/w5d]

产物：interop_matrix.md + interop_matrix.json（发现空白不等于立项——gap 清单
登记 TODO 待裁决，B4 巡检纪律同款）。
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

DEFAULT_SNAPSHOT_DIR = REPO_ROOT / "runs" / "w5_phase5" / "w5d" / "peer_snapshots"
DEFAULT_OUTDIR = REPO_ROOT / "runs" / "w5_phase5" / "w5d"

#: 预期对拍对象（MCP server 三席+快照缺失降级口径见 spec §2.5 风险①）
EXPECTED_SERVER_PEERS = ("pyaedt-mcp", "ansys-aedt-mcp", "kicad-mcp")

DOMAINS = ("建模", "求解", "后处理", "优化", "校准", "测量", "版图", "知识", "远程", "基准")

# ── 我方工具名→域（人工维护：前缀规则优先级从上到下；显式覆盖最后生效） ──────
_OUR_PREFIX_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("知识", ("search_knowledge", "get_guidelines_for", "error_hints_lookup",
             "explain_run", "diagnose", "rag_", "anchors_", "rationale_")),
    ("远程", ("doctor", "remote_")),
    ("版图", ("kicad_", "farfield_", "port_gate")),
    ("校准", ("correlate_measurement", "certify_design", "goldset_regression",
             "netlist_goldset_replay")),
    ("优化", ("rf_run_sampler", "rf_propose_params", "rf_critique_point",
             "rf_spec_cost", "warm_start_optimize", "autotune_self_verify",
             "self_heal_run", "robustness_report", "uq_", "recommend_templates",
             "mcts_search", "inverse_prefilter", "topology_propose",
             "start_tune")),
    ("测量", ("vna_", "nfmeas_", "bands_", "sar_analytic_plane_wave")),
    ("求解", ("create_run", "poll_job", "wait_job", "cancel_job", "run_campaign",
             "mmt_solve", "electrothermal_chain", "preflight_run", "run_sweep")),
    ("后处理", ("get_metrics", "get_run_artifacts", "compare_runs", "run_monitor",
               "export_report_pdf", "report_narrative", "build_datasheet",
               "fault_tree_report", "log_digest", "even_odd_report",
               "dispersion_report", "get_model_3d")),
    ("基准", ("agentbench_regression", "dataset_", "db_", "discover_workdir_runs",
             "import_workdir_runs", "import_solid_payload", "lake_", "query_dataset",
             "list_datasets")),
    ("建模", ("synthesize", "budget_analysis", "cascade_budget", "spur_search",
             "if_plan_sweep", "slotline_synthesis", "msl_", "nfc_coil_",
             "compose_netlist", "validate_recipe", "list_models", "list_template_specs",
             "list_calculators", "run_calculator", "draft_recipe_from_spec",
             "list_composable_templates", "render_constraint_check",
             "metasurface_", "weave_", "cryo_surface_estimate", "parasitic_extract_rlc",
             "plan_campaign", "get_campaign_status", "save_campaign_plan",
             "multi_agent_run", "si_", "pdn_", "emc_", "adc_interleave_spurs",
             "jitter_budget_snr", "com_pam4_run", "aging_", "humidity_uptake",
             "afs_plan", "cm_")),
)
_OUR_OVERRIDES: dict[str, str] = {
    # 显式覆盖：与前缀规则域判定不同的个案（人工判读）
    "slotline_analysis": "建模",      # 槽线族分析=设计域（合成对拍面）
    "marchand_balun_design": "建模",  # balun 综合=设计域
    "marchand_two_section_synthesis": "建模",
    "read_hfss_touchstone_comments": "校准",  # HFSS 仲裁读回=校准对拍面
    "diagnose": "知识",               # run 诊断→知识/诊断域（explain 家族）
    "compare_runs": "后处理",
}

_UNMAPPED = "未映射"


def our_tool_domain(name: str) -> str:
    """我方工具名→域（前缀规则+显式覆盖；未命中返回未映射标记）。"""
    if name in _OUR_OVERRIDES:
        return _OUR_OVERRIDES[name]
    for domain, patterns in _OUR_PREFIX_RULES:
        for pat in patterns:
            if fnmatch.fnmatchcase(name, pat) or name.startswith(pat):
                return domain
    return _UNMAPPED


def our_side() -> dict[str, Any]:
    """我方注册面事实（asyncio list_tools/list_resources，零副作用只读）。"""
    from rfauto.mcp_server import get_mcp_server

    mcp = get_mcp_server()
    tools = asyncio.run(mcp.list_tools())
    resources = asyncio.run(mcp.list_resources())
    return {
        "peer": "rfauto（本仓）",
        "kind": "mcp-server",
        "protocol": {
            "sdk": "FastMCP（jlowin/fastmcp）",
            "transports": ["stdio（python -m rfauto.mcp_server / rfauto-mcp）"],
            "resource_schemes": sorted({str(r.uri) for r in resources}),
            "envelope": "ok/errors/skipped 三态业务信封（service/envelope.py 契约 1.0；"
                        "工具返回体统一 ok 布尔+errors 列表，可复现契约面）",
            "tool_naming": "<tool>（自有注册表；入 dsh 后映射为 mcp__rfauto__<tool>）",
        },
        "tool_count": len(tools),
        "resource_count": len(resources),
        "tools": sorted(t.name for t in tools),
        "source_anchor": "asyncio.run(get_mcp_server().list_tools())（可复现；"
                         "test_mcp_server.py 同法）",
    }


def load_snapshots(snapshot_dir: str | Path) -> dict[str, dict[str, Any]]:
    """读彼方快照（缺失/坏 JSON 如实跳过并返回错误注记）。"""
    snapshot_dir = Path(snapshot_dir)
    snapshots: dict[str, dict[str, Any]] = {}
    if not snapshot_dir.is_dir():
        return snapshots
    for path in sorted(snapshot_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("peer"):
            snapshots[str(data["peer"])] = data
    return snapshots


def _peer_domain_tools(snapshot: dict[str, Any], domain: str) -> list[str]:
    """彼方快照按域取工具名（tool_domains 逐工具或 tool_domains_grouped 分组）。"""
    per_tool = snapshot.get("tool_domains") or {}
    grouped = snapshot.get("tool_domains_grouped") or {}
    names = [n for n, d in per_tool.items() if d == domain]
    names.extend(grouped.get(domain) or [])
    return sorted(names)


def build_matrix(ours: dict[str, Any], snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """构建 10 域×对拍对象矩阵（格值=有/无/未知（快照缺失）+工具名列表）。"""
    server_peers = [p for p in EXPECTED_SERVER_PEERS]
    columns: list[dict[str, Any]] = [
        {
            "peer": ours["peer"],
            "kind": ours["kind"],
            "tool_count": ours["tool_count"],
            "snapshot": {"live": True, "note": "本仓 live 注册面，无快照窗依赖"},
        }
    ]
    for peer in server_peers:
        snap = snapshots.get(peer)
        if snap is None:
            columns.append(
                {
                    "peer": peer,
                    "kind": "mcp-server",
                    "tool_count": None,
                    "snapshot": {"live": False, "missing": True,
                                 "note": "快照缺失（离线降级）：格值一律未知，gap 登记 TODO"},
                }
            )
            continue
        columns.append(
            {
                "peer": peer,
                "kind": snap.get("kind", "mcp-server"),
                "tool_count": snap.get("tool_count_note", ""),
                "snapshot": {
                    "live": False,
                    "source_urls": snap.get("snapshot", {}).get("source_urls", []),
                    "branch": snap.get("snapshot", {}).get("branch"),
                    "commit": snap.get("snapshot", {}).get("commit"),
                    "captured_at": snap.get("snapshot", {}).get("captured_at"),
                },
            }
        )

    rows: list[dict[str, Any]] = []
    unmapped_ours: list[str] = []
    by_domain: dict[str, list[str]] = {d: [] for d in DOMAINS}
    for name in ours["tools"]:
        d = our_tool_domain(name)
        if d == _UNMAPPED:
            unmapped_ours.append(name)
        else:
            by_domain[d].append(name)

    for domain in DOMAINS:
        row: dict[str, Any] = {"domain": domain}
        for col in columns:
            if col["snapshot"].get("live"):
                names = sorted(by_domain[domain])
                row[col["peer"]] = {
                    "status": "有" if names else "无",
                    "tools": names,
                }
            elif col["snapshot"].get("missing"):
                row[col["peer"]] = {
                    "status": "未知（快照缺失，离线降级）",
                    "tools": [],
                }
            else:
                names = _peer_domain_tools(snapshots[col["peer"]], domain)
                row[col["peer"]] = {
                    "status": ("有" if names else "无"),
                    "tools": names,
                }
        rows.append(row)

    return {
        "schema": "rfauto-mcp-interop-matrix-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "domains": list(DOMAINS),
        "columns": columns,
        "rows": rows,
        "clients": [snapshots[k] for k in sorted(snapshots) if snapshots[k].get("kind", "").startswith("client-harness")],
        "unmapped_ours": sorted(unmapped_ours),
        "gaps": _collect_gaps(rows, columns),
    }


def _collect_gaps(rows: list[dict[str, Any]], columns: list[dict[str, Any]]) -> list[str]:
    """gap 清单（发现空白不等于立项——登记 TODO 待裁决）。"""
    gaps: list[str] = []
    ours_col = columns[0]["peer"]
    for row in rows:
        ours_has = row[ours_col]["status"] == "有"
        for col in columns[1:]:
            cell = row[col["peer"]]
            if cell["status"].startswith("未知"):
                continue
            if ours_has and cell["status"] == "无":
                gaps.append(f"{row['domain']}：rfauto 有而 {col['peer']} 无（rfauto 独有能力，非补齐项）")
            if (not ours_has) and cell["status"] == "有":
                gaps.append(f"{row['domain']}：{col['peer']} 有而 rfauto 无（待裁决是否补齐）")
    missing = [c["peer"] for c in columns[1:] if c["snapshot"].get("missing")]
    if missing:
        gaps.append(f"快照缺失对象（离线降级，commit/工具面锚待网络窗补齐）: {', '.join(missing)}")
    return gaps


def render_markdown(matrix: dict[str, Any]) -> str:
    """矩阵渲染 md 表（表头带快照口径：live/URL+分支+快照日期，citation-rot 防御）。"""
    lines: list[str] = []
    lines.append("# rfauto MCP 生态互通能力矩阵（FE-2，W5-D）")
    lines.append("")
    lines.append(f"- 生成时间：{matrix['generated_at']}（零网络；彼方=离线快照）")
    lines.append("- 我方口径：live 注册面 list_tools/list_resources（每格工具名可复现）")
    lines.append("- 彼方口径：peer_snapshots/*.json 离线快照（URL+分支+快照日期；"
                 "commit 锚缺失在快照内注明——工具数一律标快照日期，不裸引 README 数字）")
    lines.append("- 格值：有（工具名列表）/无/未知（快照缺失，离线降级）")
    lines.append("- gap 清单=发现空白登记 TODO 待裁决，**发现空白不等于立项**")
    lines.append("")
    header = "| 能力域 | " + " | ".join(c["peer"] for c in matrix["columns"]) + " |"
    sep = "|---" * (len(matrix["columns"]) + 1) + "|"
    lines.append(header)
    lines.append(sep)
    for row in matrix["rows"]:
        cells = [row["domain"]]
        for col in matrix["columns"]:
            cell = row[col["peer"]]
            if cell["tools"]:
                shown = "、".join(cell["tools"][:6])
                extra = len(cell["tools"]) - 6
                if extra > 0:
                    shown += f" 等 {len(cell['tools'])} 个"
                cells.append(f"{cell['status']}：{shown}")
            else:
                cells.append(cell["status"])
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    unmapped = matrix.get("unmapped_ours") or []
    lines.append(f"我方未映射工具（{len(unmapped)} 个，人工映射表外如实披露）: "
                 + ("、".join(unmapped) if unmapped else "无"))
    lines.append("")
    lines.append("## gap 清单（待裁决）")
    lines.append("")
    for gap in matrix["gaps"]:
        lines.append(f"- {gap}")
    lines.append("")
    clients = matrix.get("clients") or []
    if clients:
        lines.append("## 客户端载体对拍对象（互通面，非能力矩阵列）")
        lines.append("")
        for snap in clients:
            lines.append(f"### {snap['peer']}（{snap.get('upstream', '')}）")
            cfg = snap.get("mcp_client_config", {})
            for key, value in cfg.items():
                lines.append(f"- {key}: {value}")
            inter = snap.get("interop_reading", {})
            for key, value in inter.items():
                lines.append(f"- {key}: {value}")
            lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FE-2 MCP 生态互通能力矩阵生成器（零网络）")
    parser.add_argument("--snapshots-dir", default=str(DEFAULT_SNAPSHOT_DIR),
                        help="彼方快照目录（缺省 runs/w5_phase5/w5d/peer_snapshots）")
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR),
                        help="产物目录（缺省 runs/w5_phase5/w5d）")
    args = parser.parse_args(argv)

    ours = our_side()
    snapshots = load_snapshots(args.snapshots_dir)
    matrix = build_matrix(ours, snapshots)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "interop_matrix.json"
    md_path = outdir / "interop_matrix.md"
    json_path.write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(render_markdown(matrix), encoding="utf-8")

    print(f"tools(rfauto)={ours['tool_count']} resources={ours['resource_count']}")
    print(f"peers loaded={sorted(snapshots)}")
    print(f"unmapped(ours)={len(matrix['unmapped_ours'])} gaps={len(matrix['gaps'])}")
    print(f"written: {json_path}")
    print(f"written: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
