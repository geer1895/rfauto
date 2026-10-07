"""scripts/mtrl_kit_kicad.py 定向测试（F-A P2 尾件：SMA-PCB mTRL 校准件）。

零 pcbnew 依赖为主（设计参数链 / 判据 / dry-run / DFM 字典面）；
KiCad 生成面 skipif（KiCad Python 不可达时如实跳过，不假装通过）。
"""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mtrl_kit_kicad.py"
_KICAD_SKIP_REASON = (
    "KiCad Python 不可达（RFAUTO_KICAD_PYTHON / 默认安装位 E:\\KiCad\\bin\\python.exe）"
)


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("_mtrl_kit_kicad_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MOD = _load_module()
_KICAD_AVAILABLE = _MOD.resolve_kicad_python() is not None


@pytest.fixture(scope="module")
def mod() -> Any:
    return _MOD


@pytest.fixture(scope="module")
def design(mod: Any) -> dict[str, Any]:
    """缺省设计点（er=4.4 / h=1.6 / f0=5GHz）。"""
    return mod.compute_design(4.4, 1.6, 5.0)


@pytest.fixture(scope="module")
def design_ring(mod: Any) -> dict[str, Any]:
    return mod.compute_design(4.4, 1.6, 5.0, with_ring=True)


# ─── 设计参数链：HJ 线宽一致性（#1c：射频线宽只出自 synthesis）────────────────

def test_width_matches_inverse_width_direct(mod: Any, design: dict[str, Any]) -> None:
    """w_mm 与 synthesis.inverse_width 直算一致（同 stackup 同频，rtol 1e-9）。"""
    from rfauto.core.synthesis import Stackup, inverse_width

    stackup = Stackup(name="kit_er4.4_h1.6", epsilon_r=4.4, thickness_mm=1.6)
    w_direct, _z0, status = inverse_width(50.0, 5.0, stackup)
    assert status == "ok"
    assert design["w_mm"] == pytest.approx(w_direct, rel=1e-9)


def test_er_eff_is_phase_velocity_consistent(mod: Any, design: dict[str, Any]) -> None:
    """设计端 εeff 必须是相速口径（β 直取），与介质提取链（ep_reff_f）同源。

    测试侧独立自建 skrf 正向复算（不经被测 helper——#118 独立来源精神）；
    并钉住 synthesis.forward_z0 的 ``ep_reff`` 属性（准静态）与相速口径的
    分叉（本设计点 ~3.9%）——core 侧日后续一口径时本测试红=提醒重核
    ``_er_eff_phase`` 的口径注释。
    """
    import numpy as np
    import skrf

    from rfauto.core.synthesis import Stackup, forward_z0

    m = skrf.media.MLine(
        frequency=skrf.Frequency(5.0, 5.0, 1, unit="GHz"),
        w=design["w_mm"] * 1e-3,
        h=design["h_mm"] * 1e-3,
        ep_r=design["er"],
        tand=0.0,
        model="hammerstadjensen",
    )
    omega = 2.0 * math.pi * 5.0e9
    er_eff_beta = (float(np.real(m.beta[0])) * 299792458.0 / omega) ** 2
    assert design["er_eff_f0"] == pytest.approx(er_eff_beta, rel=1e-9)
    stackup = Stackup(name="kit_er4.4_h1.6", epsilon_r=4.4, thickness_mm=1.6)
    _z0, er_eff_reff = forward_z0(design["w_mm"], 5.0, stackup)
    assert abs(er_eff_reff - er_eff_beta) / er_eff_beta > 0.01, (
        "synthesis.forward_z0 的 ep_reff 已与 β 相速口径一致——模型分叉消失，"
        "复核 scripts/mtrl_kit_kicad._er_eff_phase 注释后可放宽本断言"
    )


def test_multimodal_length_criterion(design: dict[str, Any]) -> None:
    """线长组合多模态基判据（模块 docstring 预声明）：

    ① ΔL = λg(f0)/4（带心设计目标，按构造恒等）；
    ② coverage = ΔL/λg(f_hi) ≥ 0.25，即 ΔL ≥ λg(f_hi)/4（带缘覆盖下限）；
    ③ LINE1/LINE2 中段长 = ΔL / 2ΔL（thru 基准 + n·ΔL）。
    """
    lam_g0 = design["lam_g0_mm"]
    lam_g_hi = design["lam_g_hi_mm"]
    delta = design["delta_l_mm"]
    assert delta == pytest.approx(lam_g0 / 4.0, rel=1e-12)
    assert delta >= lam_g_hi / 4.0
    assert design["coverage_ratio"] == pytest.approx(delta / lam_g_hi, rel=1e-12)
    assert design["coverage_ratio"] >= 0.25
    assert design["line1_mid_mm"] == pytest.approx(delta, rel=1e-12)
    assert design["line2_mid_mm"] == pytest.approx(2.0 * delta, rel=1e-12)
    assert math.isfinite(design["upper_ratio"])


def test_lambda_g_consistent_with_er_eff(design: dict[str, Any]) -> None:
    """λg 与 εeff 同源自洽：λg(f)·√εeff(f) = c0/f（带心/带缘分别验证）。"""
    c0 = 299792458.0
    for f_ghz, lam, eff in (
        (design["f0_ghz"], design["lam_g0_mm"], design["er_eff_f0"]),
        (design["f_hi_ghz"], design["lam_g_hi_mm"], design["er_eff_fhi"]),
    ):
        assert lam * math.sqrt(eff) == pytest.approx(c0 / (f_ghz * 1e9) * 1e3, rel=1e-9)


def test_layout_rows_and_blocks(
    mod: Any, design: dict[str, Any], design_ring: dict[str, Any]
) -> None:
    """四区块缺省齐备、--with-ring 增 RING；行版图坐标合法。"""
    assert [r["name"] for r in design["rows"]] == ["THRU", "REFLECT", "LINE1", "LINE2"]
    ring_names = [r["name"] for r in design_ring["rows"]]
    assert ring_names == ["THRU", "REFLECT", "LINE1", "LINE2", "RING"]
    assert design["ring"] is None and design_ring["ring"] is not None
    for d in (design, design_ring):
        for r in d["rows"]:
            assert r["x0"] < r["x1"] and r["y0"] < r["y1"]
        assert d["board_w_mm"] > 0 and d["board_h_mm"] > 0


def test_ring_roundtrip_er_recovery(mod: Any, design_ring: dict[str, Any]) -> None:
    """ring 样片与 core 提取链互逆：r_mean(f0) 经 ring_resonator_f0_to_er
    回收 εr ≈ 输入 er（同 skrf MLine HJ 正向模型，紧密一致）。"""
    from rfauto.core.dielectric_extract import ring_resonator_f0_to_er

    ring = design_ring["ring"]
    result = ring_resonator_f0_to_er(
        design_ring["f0_ghz"] * 1e9,
        [ring["n_harmonic"]],
        ring["r_mean_mm"],
        design_ring["w_mm"],
        design_ring["h_mm"],
    )
    assert result.er == pytest.approx(design_ring["er"], rel=1e-4)


# ─── 守卫 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("er", "h", "f0", "f_hi"),
    [
        (1.0, 1.6, 5.0, None),   # er<=1
        (0.5, 1.6, 5.0, None),
        (4.4, 0.0, 5.0, None),   # h<=0
        (4.4, -1.0, 5.0, None),
        (4.4, 1.6, 0.0, None),   # f0<=0
        (4.4, 1.6, 5.0, 5.0),    # f_hi<=f0
        (4.4, 1.6, 5.0, 4.0),
    ],
)
def test_invalid_params_raise_value_error(
    mod: Any, er: float, h: float, f0: float, f_hi: float | None
) -> None:
    with pytest.raises(ValueError):
        mod.compute_design(er, h, f0, f_hi)


def test_coverage_ratio_scales_with_band_edge(mod: Any) -> None:
    """覆盖判据方向性：f_hi 收窄到 1.05·f0 → coverage = 0.25·(f_hi/f0) ≈ 0.2625，
    仍须 ≥0.25 门（无色散时 coverage = 0.25·f_hi/f0·√(εeff_hi/εeff_f0)）。"""
    d = mod.compute_design(4.4, 1.6, 5.0, 1.05 * 5.0)
    assert d["coverage_ratio"] == pytest.approx(0.25 * 1.05, rel=0.02)
    assert d["coverage_ratio"] >= 0.25


# ─── dry-run CLI（离线主力路径，子进程端到端）────────────────────────────────

def test_dry_run_cli_outputs_all_blocks() -> None:
    """--dry-run 子进程端到端：参数表含全部区块 + JSON 行可解析 + DFM 门绿。"""
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--dry-run", "--with-ring", "--dfm"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    for block in ("THRU", "REFLECT", "LINE1", "LINE2", "RING"):
        assert block in out
    json_line = next(
        line for line in out.splitlines() if line.startswith("MTRLKIT_PARAMS_JSON: ")
    )
    params = json.loads(json_line.removeprefix("MTRLKIT_PARAMS_JSON: "))
    assert params["w_mm"] > 0.0 and params["delta_l_mm"] > 0.0
    assert params["ring"] is not None and params["ring"]["r_mean_mm"] > 0.0
    dfm_line = next(
        line for line in out.splitlines() if line.startswith("DFM_REPORT_JSON: ")
    )
    dfm = json.loads(dfm_line.removeprefix("DFM_REPORT_JSON: "))
    assert dfm["ran"] is True and dfm["ok"] is True
    assert dfm["violations"] == [] and dfm["gap_violations"] == []


def test_dry_run_writes_no_files(tmp_path: Path) -> None:
    """--dry-run 零文件写出承诺。"""
    before = sorted(p.name for p in tmp_path.iterdir())
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--dry-run", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# ─── DFM 字典面（service 契约形状）───────────────────────────────────────────

def test_dfm_dict_shape(mod: Any, design: dict[str, Any]) -> None:
    d = mod.design_to_dfm_dict(design)
    assert d["traces"] == [{"width": design["w_mm"]}]
    drills = sorted(v["drill"] for v in d["vias"])
    assert drills == [0.6, 3.2]
    assert d["board_thickness_mm"] == design["h_mm"]


def test_run_dfm_report_shape(mod: Any, design: dict[str, Any]) -> None:
    report = mod.run_dfm(design)
    assert report["ran"] is True
    assert report["ok"] is True
    assert report["violations"] == []
    assert mod.GND_GAP_MM in report["gaps_mm"]


# ─── KiCad 生成面（skipif KiCad Python 不可达）───────────────────────────────

@pytest.mark.skipif(not _KICAD_AVAILABLE, reason=_KICAD_SKIP_REASON)
class TestKiCadGeneration:
    def test_generate_file_text_assertions(
        self, mod: Any, design_ring: dict[str, Any], tmp_path: Path
    ) -> None:
        """真生成 .kicad_pcb：s-expr 头 / 全区块名 / 线宽字面值 / 安装孔在档。"""
        result = mod.generate_kicad_pcb(design_ring, tmp_path)
        assert result["ok"], result.get("errors")
        text = Path(result["path"]).read_text(encoding="utf-8")
        assert text.lstrip().startswith("(kicad_pcb")
        for block in ("THRU", "REFLECT", "LINE1", "LINE2", "RING"):
            assert f'gr_text "{block}"' in text
        # 线宽字面值（KiCad 10 s-expr 以 mm 6 位小数落盘）
        assert f'(width {design_ring["w_mm"]:.6f})' in text
        assert "(drill 3.2)" in text  # M3 安装孔
        assert "(drill 0.6)" in text  # 地焊盘接地孔
        assert '(layer "B.Cu")' in text  # 每行整块地平面
        assert '(layer "Edge.Cuts")' in text  # 板框

    def test_generated_file_opens_in_kicad(
        self, mod: Any, design_ring: dict[str, Any], tmp_path: Path
    ) -> None:
        """LoadBoard 回读（实测可打开；#331：以引擎读回为准）。"""
        result = mod.generate_kicad_pcb(design_ring, tmp_path)
        assert result["ok"], result.get("errors")
        check = mod.verify_kicad_pcb_opens(result["path"])
        assert check["ok"], check.get("errors")

    def test_missing_kicad_python_reports_not_ok(
        self,
        mod: Any,
        design_ring: dict[str, Any],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """KiCad 不可达 → ok=False + 明确错误，不抛不静默。"""
        monkeypatch.delenv("RFAUTO_KICAD_PYTHON", raising=False)
        result = mod.generate_kicad_pcb(
            design_ring, tmp_path, kicad_python=str(tmp_path / "no_such_python.exe")
        )
        assert result["ok"] is False
        assert result["errors"]


def test_ring_pad_clearance_is_gap():
    """审查轨 B P1-3 回归钉：RING 耦合焊盘近缘距环带外缘 == gap（不重叠）。

    旧式焊盘中心差 w/2 致焊盘嵌入环金属 1.255mm（短路 stub 而非间隙耦合）。
    """
    import importlib.util
    from pathlib import Path as _P

    spec = importlib.util.spec_from_file_location(
        "mtrl_kit", _P("scripts/mtrl_kit_kicad.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    design = mod.compute_design(er=4.4, h_mm=1.6, f0_ghz=5.0, with_ring=True)
    ops = mod.build_ops(design)
    row = design["rows"][-1]
    xc = (row["x0"] + row["x1"]) / 2.0
    yc = (row["y0"] + row["y1"]) / 2.0
    w = design["w_mm"]
    r_out = design["ring"]["r_mean_mm"] + w / 2.0
    gap = design["ring"]["gap_mm"]
    coupled = []
    for o in ops:
        if o.get("op") != "rect":
            continue
        if abs((o["y1"] + o["y2"]) / 2.0 - yc) > 1e-9:
            continue
        near = min(abs(o["x1"] - xc), abs(o["x2"] - xc))
        clearance = near - r_out
        if 0.0 < clearance < w + 2.0 * gap:
            coupled.append(clearance)
    # 近缘不许侵入环金属（无负/零间隙）；恰 2 块间隙 == gap 的耦合焊盘
    assert min(coupled) == pytest.approx(gap, abs=1e-9), coupled
    at_gap = [c for c in coupled if abs(c - gap) <= 1e-9]
    assert len(at_gap) == 2, f"间隙==gap 的耦合焊盘应恰 2 块，实得 {at_gap}"
