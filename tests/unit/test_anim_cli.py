"""T-Q3 接线席 Q-W5-2R（aurora_q 方向 B）——动图管线接线单测。

覆盖面（任务书 ≥14 条）：
- CLI ``rfauto anim render`` 信封正负例（tmp spec fixture；零 runs/ 湖写入、
  零网络——spec 路径与 --out 全落 tmp_path）；
- 三分类失败信封（io/spec/data）+ 修复指引文案；
- help 卫生（--help 构建成功 + 零裸 %，#305 家族）；
- 计数链（CLI 304 / MCP 171 + 域映射 后处理）；
- MCP ``anim_render`` 工具注册面 + 直调同源同输出；
- 教程章（zh/en + docs_site 同步副本 + mkdocs nav）存在性。

前任件消费判定：service/anim_render_service.py（Q-W5-2 首任留树）完整可用
——本测试按其已定契约（ok 信封字段/file_sha256_matches/category 分类）
消费，零续作缺口。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app

# ── fixtures（tmp spec；零湖写入）────────────────────────────────────────────


def _make_sparams_csv(tmp_path: Path) -> Path:
    """最小 sparams.csv（50 点双列；openEMS 导出表头惯例）。"""
    rows = []
    for i in range(50):
        f = 2.3e9 + i * 5e5
        s11_re = 0.6 * math.cos(0.1 * i)
        s11_im = 0.1 * math.sin(0.1 * i)
        rows.append(f"{f}, {s11_re:.6f}, {s11_im:.6f}, 0.500000, 0.000000")
    csv = tmp_path / "sparams.csv"
    csv.write_text(
        "freq_hz,re_S11,im_S11,re_S21,im_S21\n" + "\n".join(rows) + "\n",
        encoding="utf-8")
    return csv


@pytest.fixture()
def spec_path(tmp_path: Path) -> Path:
    csv = _make_sparams_csv(tmp_path)
    spec = {
        "chart_type": "sparam_evolution",
        "title": "anim cli smoke",
        "source": {"kind": "sparams_csv", "path": str(csv),
                   "columns": ["S11", "S21"]},
        "animation": {"fps": 12},
    }
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    return p


def _invoke(args: list[str]):
    return CliRunner().invoke(app, args)


def _invoke_json(args: list[str]) -> tuple[int, dict]:
    result = _invoke(args)
    payload = json.loads(result.output)
    return result.exit_code, payload


# ── CLI 正例 ─────────────────────────────────────────────────────────────────


def test_cli_anim_render_default_out_ok_envelope(spec_path: Path):
    """正例：缺省落点=spec 同目录同名 .svg；ok 信封字段齐+sha256=盘上字节。"""
    rc, payload = _invoke_json(["anim", "render", str(spec_path), "--json"])
    assert rc == 0, payload
    assert payload["ok"] is True
    svg = spec_path.with_suffix(".svg")
    assert Path(payload["svg_path"]) == svg
    assert svg.is_file() and svg.stat().st_size > 0
    assert payload["chart_type"] == "sparam_evolution"
    assert payload["frame_count"] == 50
    assert payload["duration_s"] == pytest.approx(50 / 12)
    assert payload["file_sha256_matches"] is True
    disk = hashlib.sha256(svg.read_bytes()).hexdigest()
    assert payload["sha256"] == disk


def test_cli_anim_render_explicit_out(spec_path: Path, tmp_path: Path):
    """--out 显式路径：落点=指定文件（父目录自动创建）。"""
    out = tmp_path / "nested" / "anim.svg"
    rc, payload = _invoke_json(
        ["anim", "render", str(spec_path), "--out", str(out), "--json"])
    assert rc == 0, payload
    assert Path(payload["svg_path"]) == out
    assert out.is_file()


def test_cli_anim_render_out_dash_svg_str_no_write(spec_path: Path):
    """--out -：不落盘，SVG 原文进信封 svg_str（文本信道消费）。"""
    rc, payload = _invoke_json(
        ["anim", "render", str(spec_path), "--out", "-", "--json"])
    assert rc == 0, payload
    assert payload["svg_path"] == "-"
    assert "<svg" in payload["svg_str"]
    assert hashlib.sha256(payload["svg_str"].encode("utf-8")).hexdigest() == (
        payload["sha256"])
    assert not spec_path.with_suffix(".svg").exists()


def test_cli_anim_render_self_check_field(spec_path: Path):
    """--self-check：信封附 self_check 报告（ok/n_errors/n_warnings/issues）。"""
    rc, payload = _invoke_json(
        ["anim", "render", str(spec_path), "--self-check", "--json"])
    assert rc == 0, payload
    sc = payload["self_check"]
    assert set(sc) >= {"ok", "n_errors", "n_warnings", "issues"}


def test_cli_anim_render_deterministic_two_runs(spec_path: Path, tmp_path: Path):
    """确定性钉：同 spec 两跑 sha256 逐位同。"""
    a = tmp_path / "a.svg"
    b = tmp_path / "b.svg"
    _, pa = _invoke_json(["anim", "render", str(spec_path),
                          "--out", str(a), "--json"])
    _, pb = _invoke_json(["anim", "render", str(spec_path),
                          "--out", str(b), "--json"])
    assert pa["sha256"] == pb["sha256"]
    assert a.read_bytes() == b.read_bytes()


def test_cli_anim_render_human_output_no_json(spec_path: Path):
    """无 --json：人读信道 ✓ 行+SVG 路径（rich 窄幅折行→全去空白归一匹配）。"""
    result = _invoke(["anim", "render", str(spec_path)])
    assert result.exit_code == 0
    compact = "".join(result.output.split())
    assert "✓" in compact
    assert str(spec_path.with_suffix(".svg")) in compact


# ── CLI 负例（三分类信封）────────────────────────────────────────────────────


def test_cli_anim_render_missing_spec_io(spec_path: Path, tmp_path: Path):
    """缺文件 → category=io。"""
    rc, payload = _invoke_json(
        ["anim", "render", str(tmp_path / "nope.json"), "--json"])
    assert rc == 1
    assert payload["ok"] is False
    assert payload["category"] == "io"
    assert payload["errors"]


def test_cli_anim_render_invalid_json_io(tmp_path: Path):
    """非合法 JSON → category=io（第二行带 schema 指引）。"""
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    rc, payload = _invoke_json(["anim", "render", str(p), "--json"])
    assert rc == 1
    assert payload["category"] == "io"
    assert "rf-animation.md" in "\n".join(payload["errors"])


def test_cli_anim_render_non_object_spec_io(tmp_path: Path):
    """JSON 数组（非对象）→ category=io。"""
    p = tmp_path / "arr.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    rc, payload = _invoke_json(["anim", "render", str(p), "--json"])
    assert rc == 1
    assert payload["category"] == "io"


def test_cli_anim_render_unknown_chart_type_spec(spec_path: Path):
    """未知图型 → category=spec（schema 指引）。"""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["chart_type"] = "no_such_chart"
    p = spec_path.with_name("spec_bad.json")
    p.write_text(json.dumps(spec), encoding="utf-8")
    rc, payload = _invoke_json(["anim", "render", str(p), "--json"])
    assert rc == 1
    assert payload["category"] == "spec"


def test_cli_anim_render_missing_chart_type_spec(tmp_path: Path):
    """缺 chart_type 必填 → category=spec。"""
    p = tmp_path / "spec_nochart.json"
    p.write_text(json.dumps({"title": "x"}), encoding="utf-8")
    rc, payload = _invoke_json(["anim", "render", str(p), "--json"])
    assert rc == 1
    assert payload["category"] == "spec"


def test_cli_anim_render_data_source_missing_data(spec_path: Path):
    """数据源文件不存在 → category=data（内核 AnimationDataError 透传）。"""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["source"] = {"kind": "sparams_csv",
                      "path": str(spec_path.parent / "ghost.csv"),
                      "columns": ["S11"]}
    p = spec_path.with_name("spec_ghost.json")
    p.write_text(json.dumps(spec), encoding="utf-8")
    rc, payload = _invoke_json(["anim", "render", str(p), "--json"])
    assert rc == 1
    assert payload["category"] == "data"
    assert "不存在" in "\n".join(payload["errors"])


# ── help 卫生（#305 家族：help 构建成功+零裸 %）──────────────────────────────


def test_cli_anim_render_help_hygiene():
    """--help 构建成功且零裸 %（rich markup 安全；%% 转义纪律）。"""
    result = _invoke(["anim", "render", "--help"])
    assert result.exit_code == 0
    assert "%" not in result.output
    top = _invoke(["anim", "--help"])
    assert top.exit_code == 0
    assert "%" not in top.output


# ── 计数链（CLI=301 / MCP=167 + 域映射）─────────────────────────────────────


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_numbers.py"
_SPEC = importlib.util.spec_from_file_location("check_numbers_gate_anim",
                                               _SCRIPT)
check_numbers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_numbers)


def test_count_chain_cli_301():
    """CLI 315（Q-X39 +2：layer-3d render 逐层渲染导出叶+Q-X37
    exploded-view 桥接口径折入，上锚 Q-X36 sdc 两叶 313）；anim 域恰 1 叶。"""
    # +2（T-Q26e Q-X39 2026-11-07：layer-3d render 单叶→314；同窗已落树
    #   未钉面 T-Q37 exploded-view render 单叶桥接折入→315（Q-X33 spice
    #   桥接同款）；上锚 Q-X36 sdc 两叶+Q-X32 skill 三叶+Q-X34 liberty
    #   两叶+Q-X33 spice 一叶同窗并行落树）
    assert check_numbers.count_cli() == 357  # aurora_r M-6 统一重钉 358 后，v0.14.0 移除笔 loop run 摘除 -1（锚历史链见 test_cli/test_check_numbers 主锚）
    counts = check_numbers.cli_leaf_counts()
    assert counts["anim"] == 1
    assert sum(counts.values()) == check_numbers.count_cli()


def test_count_chain_mcp_167():
    """MCP 171（@mcp.tool 正则口径；check_numbers 同源；Q-W9-3 +4）。"""
    assert check_numbers.count_mcp() == 208  # aurora_r M-6 终合流统一重钉（原 171）


def test_mcp_anim_render_registered():
    """MCP 注册面：anim_render 在册（facade import 序归一后实枚举）。"""
    import asyncio

    import rfauto.mcp_server as m

    tools = asyncio.run(m.mcp.list_tools())
    names = [t.name for t in tools]
    assert "anim_render" in names
    assert len(names) == len(set(names))


def test_mcp_anim_render_domain_mapping():
    """域映射钉：anim_render→后处理（与 design_report/compare_runs 同域）。"""
    import importlib.util
    from pathlib import Path as _P

    p = _P(__file__).resolve().parents[2] / "scripts" / "mcp_interop_matrix.py"
    spec = importlib.util.spec_from_file_location("mcp_interop_matrix", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.our_tool_domain("anim_render") == "后处理"
    assert mod.our_tool_domain("anim_render") in mod.DOMAINS


def test_mcp_anim_render_direct_call_same_source(spec_path: Path, tmp_path: Path):
    """MCP 工具直调=CLI 同源：同 spec 同 sha256（信封逐键同值）。"""
    from rfauto.mcp_tools.anim import anim_render
    from rfauto.service.anim_render_service import anim_render as svc

    out_mcp = tmp_path / "mcp.svg"
    out_cli = tmp_path / "cli.svg"
    r_mcp = anim_render(str(spec_path), out=str(out_mcp))
    r_cli = svc(str(spec_path), out=str(out_cli))
    assert r_mcp["ok"] is True and r_cli["ok"] is True
    assert r_mcp["sha256"] == r_cli["sha256"]
    assert out_mcp.read_bytes() == out_cli.read_bytes()


# ── service 观测面 + 教程章存在性 ────────────────────────────────────────────


def test_anim_chart_types_service_ok_envelope():
    """service 观测面：17 内建图型清单（注册表口径；Q-R3R cfc_state 接线
    e3853b04 +1 重钉，Q-X5 2026-11-07 隐蔽基数钉顺手清偿）。"""
    from rfauto.service.anim_render_service import anim_chart_types

    payload = anim_chart_types()
    assert payload["ok"] is True
    assert payload["n_chart_types"] == 17
    assert "sparam_evolution" in payload["chart_types"]
    assert "cfc_state" in payload["chart_types"]
    assert len(payload["chart_types"]) == 17


def test_tutorial_chapters_and_nav_in_place():
    """教程章 zh/en + docs_site 同步副本 + mkdocs nav 双语条目在位。"""
    repo = Path(__file__).resolve().parents[2]
    for rel in ("docs/tutorials/rf-animation.md",
                "docs/tutorials/rf-animation_en.md",
                "docs_site/tutorials/rf-animation.md",
                "docs_site/tutorials/rf-animation_en.md"):
        assert (repo / rel).is_file(), rel
    nav = (repo / "mkdocs.yml").read_text(encoding="utf-8")
    assert "tutorials/rf-animation.md" in nav
    assert "tutorials/rf-animation_en.md" in nav
    # 同步副本带溯源横幅（build_docs_pages SYNC_BANNER 单源）
    site = (repo / "docs_site/tutorials/rf-animation.md").read_text(
        encoding="utf-8")
    assert site.startswith("<!-- PR-10 文档站同步副本")
    # 教程内容锚：17 图型与 12 数据源 kind 双语在档（cfc_state=Q-R3R 批次）
    zh = (repo / "docs/tutorials/rf-animation.md").read_text(encoding="utf-8")
    assert "budget_funnel" in zh and "symbols_json" in zh and "cfc_state" in zh
