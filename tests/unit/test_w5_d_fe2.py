"""W5-D 件 1 FE-2 测试：MCP 生态互通能力矩阵生成器（零网络全 mock/synthetic）。

判据（spec §2.5）：①我方格值可 list_tools 复现；②彼方快照带
URL+分支+快照日期锚（commit 缺失在快照内注明）；③域映射零硬塞（未映射
如实披露）；④gap 清单=登记待裁决零自动立项。彼方一律 synthetic 快照
（monkeypatch/fixture 形态，#139——本文件不触网络、不读 runs/ 证据面）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mcp_interop_matrix.py"
_SPEC = importlib.util.spec_from_file_location("mcp_interop_matrix", _SCRIPT)
assert _SPEC and _SPEC.loader
mcp_interop_matrix = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mcp_interop_matrix)


# ── 我方面：live 注册面可复现 ────────────────────────────────────────────────


def test_our_side_matches_live_registry() -> None:
    ours = mcp_interop_matrix.our_side()
    assert ours["tool_count"] == len(ours["tools"])
    assert len(ours["tools"]) == len(set(ours["tools"]))  # 无重名
    assert ours["resource_count"] == 5
    assert any(u.startswith("rfauto://") for u in ours["protocol"]["resource_schemes"])


def test_our_domain_mapping_is_total_and_closed() -> None:
    ours = mcp_interop_matrix.our_side()
    for name in ours["tools"]:
        assert mcp_interop_matrix.our_tool_domain(name) in mcp_interop_matrix.DOMAINS, name


def test_explicit_overrides_applied() -> None:
    assert mcp_interop_matrix.our_tool_domain("read_hfss_touchstone_comments") == "校准"
    assert mcp_interop_matrix.our_tool_domain("marchand_balun_design") == "建模"
    assert mcp_interop_matrix.our_tool_domain("diagnose") == "知识"


# ── 彼方面：synthetic 快照（fixture 形态，零网络） ────────────────────────────


def _write_synthetic_snapshot(snapshot_dir: Path, peer: str) -> Path:
    """合成对拍对象快照（非真实仓——协议面/信封形态/tools 数对照的机制钉）。"""
    payload = {
        "peer": peer,
        "kind": "mcp-server",
        "snapshot": {
            "source_urls": [f"https://example.invalid/{peer}/toolsets.py"],
            "branch": "main",
            "commit": "deadbeef" if peer == "with-commit" else None,
            "captured_at": "2026-10-05",
        },
        "protocol": {"sdk": "synthetic", "transports": ["stdio"], "envelope": "raw"},
        "tool_domains": {"peer_solve_tool": "求解", "peer_model_tool": "建模"},
        "tool_count_note": "2 tools（synthetic）",
    }
    path = snapshot_dir / f"{peer}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_matrix_cells_with_synthetic_snapshots(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _write_synthetic_snapshot(snapshot_dir, "synthetic-peer")
    ours = mcp_interop_matrix.our_side()
    snapshots = mcp_interop_matrix.load_snapshots(snapshot_dir)
    matrix = mcp_interop_matrix.build_matrix(ours, snapshots)

    peers = [c["peer"] for c in matrix["columns"]]
    assert peers == ["rfauto（本仓）", "pyaedt-mcp", "ansys-aedt-mcp", "kicad-mcp"]
    # 快照在档的 synthetic 数据不在预期列——不进矩阵列（诚实口径：只对拍
    # 预声明对象；synthetic 快照仅经 build_matrix 直接注入验证机制）
    kicad_col = next(c for c in matrix["columns"] if c["peer"] == "kicad-mcp")
    assert kicad_col["snapshot"]["missing"] is True
    for row in matrix["rows"]:
        assert row["kicad-mcp"]["status"].startswith("未知（快照缺失")


def test_matrix_accepts_injected_synthetic_column() -> None:
    """机制钉：synthetic 快照注入预期列名下，格值=有/无按域逐格正确。"""
    snap = {
        "peer": "pyaedt-mcp",
        "kind": "mcp-server",
        "snapshot": {"captured_at": "2026-10-05"},
        "tool_domains": {"peer_solve_tool": "求解"},
    }
    ours = mcp_interop_matrix.our_side()
    matrix = mcp_interop_matrix.build_matrix(ours, {"pyaedt-mcp": snap})
    rows = {r["domain"]: r for r in matrix["rows"]}
    assert rows["求解"]["pyaedt-mcp"]["status"] == "有"
    assert "peer_solve_tool" in rows["求解"]["pyaedt-mcp"]["tools"]
    assert rows["建模"]["pyaedt-mcp"]["status"] == "无"


def test_missing_snapshot_dir_yields_all_unknown_columns(tmp_path: Path) -> None:
    ours = mcp_interop_matrix.our_side()
    snapshots = mcp_interop_matrix.load_snapshots(tmp_path / "nope")
    assert snapshots == {}
    matrix = mcp_interop_matrix.build_matrix(ours, snapshots)
    for row in matrix["rows"]:
        for peer in ("pyaedt-mcp", "ansys-aedt-mcp", "kicad-mcp"):
            assert row[peer]["status"].startswith("未知（快照缺失")
    assert any("快照缺失" in g for g in matrix["gaps"])


def test_gap_rules_both_directions() -> None:
    ours = mcp_interop_matrix.our_side()
    # 全域无工具的彼方 → 全部"rfauto 有而彼方无"（独有能力方向）
    empty_peer = {"peer": "pyaedt-mcp", "kind": "mcp-server", "snapshot": {}, "tool_domains": {}}
    matrix = mcp_interop_matrix.build_matrix(ours, {"pyaedt-mcp": empty_peer})
    gap_text = "\n".join(matrix["gaps"])
    assert "rfauto 独有能力" in gap_text
    # 彼方独有域工具 → "彼方 有而 rfauto 无"方向（造一个 rfauto 无的域格：
    # 用本表映射为空的域不可行——基准域 rfauto 有；改用彼方映射到
    # rfauto 全无的合成格不可达，故直接钉 gap 收集函数）
    rows = [
        {
            "domain": "版图",
            "rfauto（本仓）": {"status": "无", "tools": []},
            "peer-x": {"status": "有", "tools": ["k"],
                       "snapshot-note": "synthetic"},
        }
    ]
    cols = [
        {"peer": "rfauto（本仓）", "snapshot": {"live": True}},
        {"peer": "peer-x", "snapshot": {"live": False}},
    ]
    gaps = mcp_interop_matrix._collect_gaps(rows, cols)  # type: ignore[arg-type]
    assert any("peer-x 有而 rfauto 无" in g for g in gaps)


def test_markdown_renders_provenance_and_gaps(tmp_path: Path) -> None:
    ours = mcp_interop_matrix.our_side()
    snapshots = mcp_interop_matrix.load_snapshots(tmp_path / "absent")
    matrix = mcp_interop_matrix.build_matrix(ours, snapshots)
    text = mcp_interop_matrix.render_markdown(matrix)
    assert "快照" in text and "gap 清单" in text
    assert "工具名可复现" in text
    assert "未知（快照缺失，离线降级）" in text


def test_main_writes_artifacts_to_tmp_outdir(tmp_path: Path) -> None:
    rc = mcp_interop_matrix.main(
        ["--snapshots-dir", str(tmp_path / "absent"), "--outdir", str(tmp_path / "out")]
    )
    assert rc == 0
    assert (tmp_path / "out" / "interop_matrix.json").is_file()
    assert (tmp_path / "out" / "interop_matrix.md").is_file()
    payload = json.loads(
        (tmp_path / "out" / "interop_matrix.json").read_text(encoding="utf-8")
    )
    assert payload["schema"] == "rfauto-mcp-interop-matrix-v1"


@pytest.mark.parametrize("peer", ["pyaedt-mcp", "ansys-aedt-mcp", "kicad-mcp"])
def test_expected_peers_declared(peer: str) -> None:
    assert peer in mcp_interop_matrix.EXPECTED_SERVER_PEERS
