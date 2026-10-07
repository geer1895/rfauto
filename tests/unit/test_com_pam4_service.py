"""W7 台账①态接线批 X3：si_channel_service 扩面（com_pam4 内核）单测。

接线面（2026-10-04，W7 台账行 4 com_pam4→si_channel_service 扩函数）：
``com_pam4_run``——pychopmarg preset 参数重建 + run_com 薄消费，信封进出。

裁判口径（#118 不自证）：COM 数值权威=pychopmarg 内核（精确值不自证，
合理带内断言）；PRZF 模式下 fom_db 与 fom_db_recalc 恒等（93A-36 闭式
复算与内核 FOM 同源恒等——core 测试钉过，此处作 service 透传完好性锚）；
C2-1 口径：fom_db 是优化 FOM 非标准 final-COM，com_db 独立列并报。
信封纪律：契约错误（非 s4p/未知 preset/文件缺失）→ ok=False + errors
list，绝不抛异常；pychopmarg 缺装 → ok=True + status="unavailable"。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.si_channel_service import (
    COM_PAM4_RUN_SCHEMA_VERSION,
    com_pam4_run,
)

F_HZ = np.arange(1e7, 20.001e9, 2e7)  # 0.01–20 GHz，20 MHz 步进（core 测试同款）

#: dj 粗档 PAM4 钉抽头（主抽头 1、其余 0；|v|.sum()=1 在 c0_min=0 可行域上）
DJ_PINS = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]


def _write_s4p_decoupled_pair(path: Path, f: np.ndarray = F_HZ) -> Path:
    """解耦差分对 4 端口（因果 RLC 线；与 test_com_pam4 同款解析式）。"""
    w = 2.0 * np.pi * f
    r_ohm, l_h, c_f, g_s, length = 8.0, 260e-9, 130e-12, 1e-6, 0.25
    gamma = np.sqrt((r_ohm + 1j * w * l_h) * (g_s + 1j * w * c_f))
    zc = np.sqrt((r_ohm + 1j * w * l_h) / (g_s + 1j * w * c_f))
    thru = np.exp(-gamma * length) * (2.0 * zc / (zc + 50.0))
    ref = (zc - 50.0) / (zc + 50.0)
    s = np.zeros((f.size, 4, 4), dtype=complex)
    for i, j in ((0, 1), (1, 0), (2, 3), (3, 2)):
        s[:, i, j] = thru
    for i in range(4):
        s[:, i, i] = ref
    lines = ["# HZ S RI R 50.0"]
    for k in range(f.size):
        parts = [f"{f[k]:.10e}"]
        for i in range(4):
            for j in range(4):
                parts.append(f"{s[k, i, j].real:.10e}")
                parts.append(f"{s[k, i, j].imag:.10e}")
        lines.append(" ".join(parts))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestComPam4RunEndToEnd:
    def test_preset_run_schema_and_przf_identity(self, tmp_path: Path) -> None:
        """合成 4 端口直通链全流程（粗档+钉抽头，秒级—十秒级）。

        service 透传完好性锚：PRZF 下 fom_db == fom_db_recalc（93A-36 闭式
        复算恒等，core 同源钉）；com_db 独立列（C2-1 口径）；verification
        如实 unverified_vs_802com_vectors。
        """
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        out = com_pam4_run(
            str(s4p), preset="8023dj", fb_gbaud=10.0, pinned_taps=DJ_PINS)
        assert out["ok"] is True
        assert out["schema_version"] == COM_PAM4_RUN_SCHEMA_VERSION
        assert out["provenance"]["kernel"] == "rfauto.core.com_pam4"
        res = out["result"]
        assert res["status"] == "ok"
        assert res["com_db"] is not None
        # PRZF（93A 规格路线）下优化 FOM 与闭式复算恒等（同源数字）
        assert res["fom_db"] == pytest.approx(res["fom_db_recalc"], abs=1e-9)
        # final-COM ≤ 优化 FOM 的物理方向带（COM 含 DER/Ani 因子，精确值不自证）
        assert res["com_db"] < res["fom_db"]
        assert res["verification"] == "unverified_vs_802com_vectors"
        assert res["params"]["opt_mode"] == "PRZF"
        assert res["params"]["note"].startswith("preset=8023dj")

    def test_deterministic_rerun(self, tmp_path: Path) -> None:
        """同参重跑逐位一致（确定性内核，无隐藏状态）。"""
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        a = com_pam4_run(str(s4p), preset="8023dj", fb_gbaud=10.0,
                         pinned_taps=DJ_PINS)
        b = com_pam4_run(str(s4p), preset="8023dj", fb_gbaud=10.0,
                         pinned_taps=DJ_PINS)
        assert a["result"]["status"] == "ok"
        assert a["result"]["com_db"] == b["result"]["com_db"]
        assert a["result"]["fom_db"] == b["result"]["fom_db"]


class TestComPam4RunEnvelope:
    def test_non_s4p_rejected_to_envelope(self, tmp_path: Path) -> None:
        """2 端口文件 → ok=False + errors（内核契约错误折信封，不抛）。"""
        s2p = tmp_path / "thru.s2p"
        s2p.write_text("# HZ S RI R 50.0\n1e9 0 0 1 0 0\n", encoding="utf-8")
        out = com_pam4_run(str(s2p))
        assert out["ok"] is False
        assert isinstance(out["errors"], list) and out["errors"]
        assert ".s4p" in out["errors"][0]
        assert out["schema_version"] == COM_PAM4_RUN_SCHEMA_VERSION

    def test_unknown_preset_rejected(self, tmp_path: Path) -> None:
        """802.3ck 未随包发布 → 参数重建失败折信封（不凭记忆造数值）。"""
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        out = com_pam4_run(str(s4p), preset="8023ck")
        assert out["ok"] is False
        assert any("8023ck" in e or "preset" in e for e in out["errors"])

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        out = com_pam4_run(str(tmp_path / "nope.s4p"))
        assert out["ok"] is False
        assert any("不存在" in e for e in out["errors"])

    def test_bad_pinned_taps_shape_rejected(self, tmp_path: Path) -> None:
        """钉抽头长度≠preset 抽头数 → 内核 ValueError 折信封。"""
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        out = com_pam4_run(str(s4p), pinned_taps=[0.0, 1.0, 0.0])
        assert out["ok"] is False
        assert isinstance(out["errors"], list) and out["errors"]

    def test_non_numeric_pinned_taps_rejected(self) -> None:
        out = com_pam4_run("x.s4p", pinned_taps=["a", 1.0, 0, 0, 0, 0])
        assert out["ok"] is False
        assert any("pinned_taps" in e for e in out["errors"])

    def test_non_string_thru_rejected(self) -> None:
        out = com_pam4_run("")
        assert out["ok"] is False
        assert any("thru_s4p" in e for e in out["errors"])


# ─── MCP 薄壳冒烟（facade 直调）─────────────────────────────────────────────


def test_mcp_com_pam4_run_tool_registered():
    import asyncio

    from rfauto.mcp_server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "com_pam4_run" in names


def test_mcp_com_pam4_run_tool_callable_envelope(tmp_path: Path) -> None:
    from rfauto.mcp_server import com_pam4_run as mcp_com_pam4_run

    s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
    out = mcp_com_pam4_run(
        str(s4p), preset="8023dj", fb_gbaud=10.0, pinned_taps=DJ_PINS)
    assert out["ok"] is True
    assert out["result"]["status"] == "ok"
    assert out["result"]["com_db"] is not None
    # 契约错误 → ok=False 信封不抛出（不炸会话）
    assert mcp_com_pam4_run(str(tmp_path / "nope.s4p"))["ok"] is False
