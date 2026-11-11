"""T-Q19 批 2 接线席 Q-W9-3（aurora_q 方向 E）——vendor-docs CLI/MCP 接线单测
+ T-Q5 批 3 format_overview MCP 工具接线单测（两提案合席=计数链单笔）。

覆盖面（任务书 ≥22 条）：
- CLI ``rfauto vendor-docs build|search|audit`` 三叶信封正负例（tmp 小语料
  照 Q-W6-4 fixture 先例；零 runs/ 湖写入、零网络——db 全落 tmp_path）；
- --db 必填（缺省拒写——#144 同族；缺 --db/--root 走 usage 信封 exit 2）；
- help 卫生（--help 构建成功 + 零裸 %，#305 家族）；
- MCP vendor_docs_build/search/audit 三工具注册面+直调同源同输出；
- MCP format_overview 工具注册面+fixture .ds 端到端（件 2）；
- 计数链（CLI 304 / MCP 171 + 域映射 版图/知识）。

红线钉：厂商内容零入库（audit within_chunk_limit=True）；单测零网络零
真机语料（本机 ADS 安装树不在测试面——侦察只发生在开发会话，探针档
runs/aurora_q/qw93_stats/ 留证）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app

# ── fixtures（tmp 小语料；零湖写入零网络）────────────────────────────────────

DOC_EN = """<html><head><title>Wave Port Setup</title></head>
<body><p>Assign a wave port on the sheet body. The wave port excites the
mode on the port face. Wave port calibration deembedding removes the
feed length from the S-parameter reference plane.</p></body></html>"""

DOC_EN_2 = """<html><head><title>Lumped Port</title></head>
<body><p>A lumped port is a concentrated excitation between two
conductors. Lumped port impedance can be defined directly.</p></body></html>"""


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    _write(root, "guides/wave_port.html", DOC_EN)
    _write(root, "guides/lumped.html", DOC_EN_2)
    return root


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "idx" / "vendor.sqlite"


def _invoke(args: list[str]):
    return CliRunner().invoke(app, args)


def _invoke_json(args: list[str]) -> tuple[int, dict]:
    result = _invoke(args)
    payload = json.loads(result.output)
    return result.exit_code, payload


# ── CLI 正例（build→search→audit 全链，tmp 语料）────────────────────────────


def test_cli_build_ok_envelope(corpus: Path, db_path: Path) -> None:
    rc, payload = _invoke_json([
        "vendor-docs", "build", "--root", f"ansys_help={corpus}",
        "--db", str(db_path), "--json"])
    assert rc == 0, payload
    assert payload["ok"] is True
    assert payload["indexed_files"] == 2
    assert payload["total_chunks"] == 2
    assert payload["errors"] == []
    assert payload["roots"] == {"ansys_help": str(corpus)}
    assert payload["db_path"] == str(db_path)
    assert db_path.is_file()


def test_cli_build_rebuild_idempotent(corpus: Path, db_path: Path) -> None:
    """增量去重：同语料二跑 dedup_skipped=2；--rebuild 全量重建零去重。"""
    args = ["vendor-docs", "build", "--root", f"ansys_help={corpus}",
            "--db", str(db_path), "--json"]
    _, first = _invoke_json(args)
    assert first["ok"] is True
    _, second = _invoke_json(args)
    assert second["ok"] is True
    assert second["dedup_skipped"] == 2
    assert second["chunks_new"] == 0
    _, third = _invoke_json([*args, "--rebuild"])
    assert third["ok"] is True
    assert third["dedup_skipped"] == 0
    assert third["total_chunks"] == first["total_chunks"]


def test_cli_search_ok_envelope(corpus: Path, db_path: Path) -> None:
    _invoke_json(["vendor-docs", "build", "--root", f"ansys_help={corpus}",
                  "--db", str(db_path), "--json"])
    rc, payload = _invoke_json([
        "vendor-docs", "search", "wave port", "--db", str(db_path), "--json"])
    assert rc == 0, payload
    assert payload["ok"] is True
    assert payload["total"] >= 1
    hit = payload["hits"][0]
    assert hit["source"] == "ansys_help"
    assert hit["title"] == "Wave Port Setup"
    assert hit["path"] == "guides/wave_port.html"  # 相对语料根路径（service 口径）
    assert "[wave]" in hit["snippet"] or "wave" in hit["snippet"].lower()
    assert payload["mode"] in ("fts5", "fts5_phrase", "like")


def test_cli_audit_ok_envelope_zero_ingest(corpus: Path,
                                           db_path: Path) -> None:
    """audit 正例：红线复核面 within_chunk_limit=True（库内仅摘要块）。"""
    _invoke_json(["vendor-docs", "build", "--root", f"ansys_help={corpus}",
                  "--db", str(db_path), "--json"])
    rc, payload = _invoke_json([
        "vendor-docs", "audit", "--db", str(db_path), "--json"])
    assert rc == 0, payload
    assert payload["ok"] is True
    assert payload["n_files"] == 2
    assert payload["n_chunks"] == 2
    assert payload["within_chunk_limit"] is True
    assert payload["declared_chunk_chars"] == 1200
    assert payload["max_chunk_chars"] <= payload["declared_chunk_chars"]
    assert "零入仓" in payload["note"]


def test_cli_human_output_no_json(corpus: Path, db_path: Path) -> None:
    _invoke_json(["vendor-docs", "build", "--root", f"ansys_help={corpus}",
                  "--db", str(db_path), "--json"])
    result = _invoke(["vendor-docs", "search", "wave port",
                      "--db", str(db_path)])
    assert result.exit_code == 0
    compact = "".join(result.output.split())
    assert "✓" in compact
    assert "WavePortSetup" in compact.replace(" ", "")


# ── CLI 负例（usage 信封/服务信封）──────────────────────────────────────────


def test_cli_build_db_required_no_default_db(corpus: Path,
                                             tmp_path: Path,
                                             monkeypatch) -> None:
    """--db 必填：缺省 exit 2 + --json 信封；工作目录零缺省库位（#144）。"""
    monkeypatch.chdir(tmp_path)  # cwd 隔离：缺省库位若被落盘即现形
    rc, payload = _invoke_json([
        "vendor-docs", "build", "--root", f"ansys_help={corpus}", "--json"])
    assert rc == 2
    assert payload["ok"] is False
    assert payload["errors"] and "db_path 必填" in payload["errors"][0]
    assert not (tmp_path / "vendor.sqlite").exists()
    assert not list(tmp_path.glob("*.sqlite"))  # 零缺省库位


def test_cli_build_roots_required(db_path: Path) -> None:
    rc, payload = _invoke_json([
        "vendor-docs", "build", "--db", str(db_path), "--json"])
    assert rc == 2
    assert payload["ok"] is False
    assert "roots 必填" in payload["errors"][0]


def test_cli_build_root_format_error(db_path: Path) -> None:
    """--root 缺 '=' 或空段 → usage 信封 exit 2。"""
    rc, payload = _invoke_json([
        "vendor-docs", "build", "--root", "no_separator",
        "--db", str(db_path), "--json"])
    assert rc == 2
    assert payload["ok"] is False
    assert "source=语料根目录" in payload["errors"][0]


def test_cli_build_missing_root_error_envelope(db_path: Path,
                                               tmp_path: Path) -> None:
    """语料根不存在 → 服务层错误信封 exit 1（usage 与服务失败分码）。"""
    rc, payload = _invoke_json([
        "vendor-docs", "build", "--root",
        f"ansys_help={tmp_path / 'nope'}", "--db", str(db_path), "--json"])
    assert rc == 1
    assert payload["ok"] is False
    assert "语料根不存在" in payload["errors"][0]
    assert not db_path.exists()  # 失败路径零库落盘


def test_cli_search_missing_db_error(corpus: Path, tmp_path: Path) -> None:
    _invoke_json(["vendor-docs", "build", "--root", f"ansys_help={corpus}",
                  "--db", str(tmp_path / "real.sqlite"), "--json"])
    rc, payload = _invoke_json([
        "vendor-docs", "search", "wave", "--db",
        str(tmp_path / "ghost.sqlite"), "--json"])
    assert rc == 1
    assert payload["ok"] is False
    assert "索引库不存在" in payload["errors"][0]


def test_cli_search_empty_query_error(corpus: Path, db_path: Path) -> None:
    _invoke_json(["vendor-docs", "build", "--root", f"ansys_help={corpus}",
                  "--db", str(db_path), "--json"])
    rc, payload = _invoke_json([
        "vendor-docs", "search", "", "--db", str(db_path), "--json"])
    assert rc == 1
    assert payload["ok"] is False
    assert "query 必填" in payload["errors"][0]


def test_cli_audit_missing_db_error(tmp_path: Path) -> None:
    rc, payload = _invoke_json([
        "vendor-docs", "audit", "--db", str(tmp_path / "ghost.sqlite"),
        "--json"])
    assert rc == 1
    assert payload["ok"] is False
    assert payload["errors"]


# ── help 卫生（#305 家族：help 构建成功+零裸 %）────────────────────────────


def test_cli_vendor_docs_help_hygiene() -> None:
    assert _invoke(["vendor-docs", "--help"]).exit_code == 0
    for leaf in ("build", "search", "audit"):
        r = _invoke(["vendor-docs", leaf, "--help"])
        assert r.exit_code == 0, leaf
        assert "%" not in r.output, leaf


# ── MCP 工具面（vendor_docs 三工具 + format_overview）───────────────────────


def test_mcp_new_tools_registered() -> None:
    """MCP 注册面：四新工具在册且全表无重名（facade import 序归一后实枚举）。"""
    import asyncio

    import rfauto.mcp_server as m

    tools = asyncio.run(m.mcp.list_tools())
    names = [t.name for t in tools]
    for expected in ("format_overview", "vendor_docs_build",
                     "vendor_docs_search", "vendor_docs_audit"):
        assert expected in names
    assert len(names) == len(set(names))


def test_mcp_vendor_docs_build_search_same_source(
        corpus: Path, tmp_path: Path) -> None:
    """MCP 直调=CLI 同源：同语料同 db 面双入口信封同键。"""
    from rfauto.mcp_tools.vendor_docs import (
        vendor_docs_build,
        vendor_docs_search,
    )
    from rfauto.service.vendor_doc_service import (
        build_vendor_index,
        search_vendor_docs,
    )

    db_mcp = tmp_path / "mcp.sqlite"
    db_svc = tmp_path / "svc.sqlite"
    r_mcp = vendor_docs_build({"ansys_help": str(corpus)}, db_path=str(db_mcp))
    r_svc = build_vendor_index({"ansys_help": corpus}, db_path=db_svc)
    assert r_mcp["ok"] is True and r_svc["ok"] is True
    assert r_mcp["indexed_files"] == r_svc["indexed_files"] == 2
    assert r_mcp["total_chunks"] == r_svc["total_chunks"]
    s_mcp = vendor_docs_search("wave port", db_path=str(db_mcp))
    s_svc = search_vendor_docs("wave port", db_path=db_svc)
    assert s_mcp["ok"] is True and s_svc["ok"] is True
    assert [(h["title"], h["path"]) for h in s_mcp["hits"]] == [
        (h["title"], h["path"]) for h in s_svc["hits"]]


def test_mcp_vendor_docs_audit_same_source(corpus: Path,
                                           tmp_path: Path) -> None:
    from rfauto.mcp_tools.vendor_docs import (
        vendor_docs_audit,
        vendor_docs_build,
    )

    db = tmp_path / "audit.sqlite"
    vendor_docs_build({"ansys_help": str(corpus)}, db_path=str(db))
    r = vendor_docs_audit(db_path=str(db))
    assert r["ok"] is True
    assert r["within_chunk_limit"] is True


def test_mcp_vendor_docs_build_missing_root_error(tmp_path: Path) -> None:
    """MCP 面负例：语料根不存在 → 错误信封（不裸抛）。"""
    from rfauto.mcp_tools.vendor_docs import vendor_docs_build

    r = vendor_docs_build(
        {"ansys_help": str(tmp_path / "nope")},
        db_path=str(tmp_path / "x.sqlite"))
    assert r["ok"] is False
    assert "语料根不存在" in r["errors"][0]


def test_mcp_format_overview_fixture_end_to_end() -> None:
    """件 2 端到端：format_overview 工具直调 fixture .ds → ads_ds 信封。"""
    from rfauto.mcp_tools.format_overview import format_overview

    ds = (Path(__file__).resolve().parent / "fixtures" / "format_overview"
          / "minimal_dataset.ds")
    r = format_overview(str(ds))
    assert r["ok"] is True
    assert r["kind"] == "ads_ds"
    assert r["stats"]["magic_form"] == "full"
    assert r["stats"]["byte_order_marker"] == "DCBA"
    assert r["stats"]["n_variables"] == 4


def test_mcp_format_overview_unknown_format_error(tmp_path: Path) -> None:
    from rfauto.mcp_tools.format_overview import format_overview

    mystery = tmp_path / "mystery.xyz"
    mystery.write_text("hello world\n", encoding="utf-8")
    r = format_overview(str(mystery))
    assert r["ok"] is False
    assert r["kind"] is None


# ── 计数链（CLI=305 / MCP=171 + 域映射）─────────────────────────────────────

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_numbers.py"
_SPEC = importlib.util.spec_from_file_location("check_numbers_gate_vd",
                                               _SCRIPT)
check_numbers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_numbers)


def test_count_chain_cli_305():
    """CLI 315（Q-X39 +2：layer-3d render 逐层渲染导出叶+Q-X37
    exploded-view 桥接口径折入，上锚 Q-X36 sdc 两叶 313）；vendor-docs
    域恰 3 叶。"""
    # +2（T-Q26e Q-X39 2026-11-07：layer-3d render 单叶→314；同窗已落树
    #   未钉面 T-Q37 exploded-view render 单叶桥接折入→315（Q-X33 spice
    #   桥接同款）；上锚 Q-X36 sdc 两叶+Q-X32 skill 三叶+Q-X34 liberty
    #   两叶+Q-X33 spice 一叶同窗并行落树）
    assert check_numbers.count_cli() == 357  # aurora_r M-6 统一重钉 358 后，v0.14.0 移除笔 loop run 摘除 -1（锚历史链见 test_cli/test_check_numbers 主锚）
    counts = check_numbers.cli_leaf_counts()
    assert counts["vendor-docs"] == 3
    assert sum(counts.values()) == check_numbers.count_cli()


def test_count_chain_mcp_171():
    """MCP 171（@mcp.tool 正则口径；check_numbers 同源；Q-W9-3 +4）。"""
    assert check_numbers.count_mcp() == 208  # aurora_r M-6 终合流统一重钉（原 171）


def test_mcp_domain_mapping() -> None:
    """域映射钉：format_overview→版图；vendor_docs 三面→知识（九处 grep
    面 mcp_interop_matrix 单源）。"""
    p = (Path(__file__).resolve().parents[2] / "scripts"
         / "mcp_interop_matrix.py")
    spec = importlib.util.spec_from_file_location("mcp_interop_matrix_vd", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.our_tool_domain("format_overview") == "版图"
    assert mod.our_tool_domain("vendor_docs_build") == "知识"
    assert mod.our_tool_domain("vendor_docs_search") == "知识"
    assert mod.our_tool_domain("vendor_docs_audit") == "知识"
    for name in ("format_overview", "vendor_docs_build",
                 "vendor_docs_search", "vendor_docs_audit"):
        assert mod.our_tool_domain(name) in mod.DOMAINS, name


def test_help_panel_mapping_covers_vendor_docs() -> None:
    """help 面板映射：vendor-docs 入 数据与知识 面板（wave_ui_c 集合钉镜像）。"""
    from rfauto.cli.help_groups import HELP_PANEL_OF

    assert HELP_PANEL_OF["vendor-docs"] == "数据与知识"
