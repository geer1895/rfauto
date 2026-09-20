"""D11 网格伪象诊断内核测试——三教训回放（ratrace pt8 / via 1.0491 / #152）+ 判据边界。

数据来源（禁止编造，全部带 provenance 注释）：
- ratrace pt8 真实逐点归档 runs/ratrace_smoke/pt8/ratrace.s4p（0.4mm、k=1 原始渲染；
  实测 @2.5GHz S21 −2.75 / S41 −4.08 / S31 −17.01 / S24 −19.09 / S11 −16.46，与
  真机判读记录逐字一致）；带 provenance 的中心 / 等效 εeff / 网格细化记录见常量注释。
- via 1.0491 真实逐点归档 runs/via_smoke/pt3/port_beta.csv（β2/β1 带内恒定 1.0491）
  ；§205 定版口径。
- #152 塌缩值取历史实测（7.7e-19 s）；"正常" CFL 步长由 0.4mm 网格闭式推算
  （dx/(2c)，非编造参考值）。

真实归档缺失时相关用例 pytest.skip（不假装通过）；核心三教训各有一条不依赖文件、
仅用带 provenance 常量的用例（干净检出也必过）。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

from rfauto.core.mesh_artifact import (
    FAIL,
    HEALTHY,
    INCONCLUSIVE,
    MESH_ARTIFACT,
    PASS,
    PROBE_SCALE,
    TIMESTEP_COLLAPSE,
    diagnose_mesh_artifact,
    hybrid_gate_series,
    locate_hybrid_center_ghz,
    locate_tier_center_ghz,
    recovered_scale_from_eps,
)

# ── 带 provenance 的定版常量（禁止改动成"恰好通过"的值）──────────────────
_PT8_TARGET_GHZ = 2.5
# 模板注（openems_templates.py）"pt7/pt8 实测 hybrid 中心 ≈2.28GHz"；
# 定版 k=1.0975 与之互洽：2.5/1.0975=2.2779
_PT8_CENTER_RAW_GHZ = 2.279
_PT8_EPS_EQUIV = 3.28       # 历史判读 "等效 εeff=3.28 超微带物理上限"
_PT8_EPS_CLOSED = 2.7246    # 历史判读 "HJ 直线 2.72"（test_ratrace_template er_eff 独立锚）
_PT8_EPS_R = 3.66           # rogers4350b（runs/ratrace_arbitration/hfss_arbitration.json sub.er）
# runs/ratrace_arbitration/openems_convergence.json f_center_avg_0p4mm/0p2mm
_PT8_MESH_STUDY = [{"mesh_mm": 0.4, "f_center_ghz": 2.3544},
                   {"mesh_mm": 0.2, "f_center_ghz": 2.5225}]
_K_DEFINITION = 1.0975      # openems_templates._RATRACE_RING_MESH_K 定版
_VIA_BETA_RATIO = 1.0491    # §205 定版 "β2/β1 = 1.0491 ± 0.0011 带内恒定"
_TIMESTEP_COLLAPSED_S = 7.7e-19  # #152 CFL 塌缩值
_C0 = 299792458.0

_PT8_S4P = REPO / "runs" / "ratrace_smoke" / "pt8" / "ratrace.s4p"
_VIA_BETA = REPO / "runs" / "via_smoke" / "pt3" / "port_beta.csv"
# 裸数据回放（D11 收口）：多档响应归档
_PT8_ROW = REPO / "runs" / "ratrace_smoke" / "pt8" / "p1" / "sparams.csv"
_MESH02_ROW = REPO / "runs" / "ratrace_arbitration" / "mesh_0p2mm" / "p1" / "sparams.csv"
# runs/ratrace_arbitration/openems_convergence.json center_0p2mm（裸定位数字重建目标）
_CONV_02_BALANCE_GHZ = 2.5525
_CONV_02_S11_GHZ = 2.4925
_CONV_02_AVG_GHZ = 2.5225
_PT8_EDGE_GHZ = 2.25  # 带窗 2.25–2.75GHz 低端边界（pt8 各指标 argmin 均落此）


# ---------------------------------------------------------------------------
# 助手
# ---------------------------------------------------------------------------

def _factor_map(report: dict) -> dict:
    return {f["factor"]: f for f in report["factors"]}


def _ideal_ring_s(freq_ghz: np.ndarray, k: float = 1.0, zr: float = 70.7,
                  f0: float = 2.5, z0: float = 50.0) -> np.ndarray:
    """理想 180° 混合环 S 矩阵（弧 θ,θ,3θ,θ；#208 端口语义）——合成健康对照。"""
    theta = np.pi / 2 * (freq_ghz / f0) * k
    out = np.zeros((len(freq_ghz), 4, 4), dtype=complex)
    for idx, th in enumerate(theta):
        y = np.zeros((4, 4), dtype=complex)
        for i, j, mult in ((0, 1, 1.0), (1, 2, 1.0), (2, 3, 3.0), (3, 0, 1.0)):
            phi = th * mult
            y11 = np.cos(phi) / (1j * zr * np.sin(phi))
            y12 = -1.0 / (1j * zr * np.sin(phi))
            y[i, i] += y11
            y[j, j] += y11
            y[i, j] += y12
            y[j, i] += y12
        out[idx] = (np.eye(4) - z0 * y) @ np.linalg.inv(np.eye(4) + z0 * y)
    return out


def _pt8_packet(**overrides) -> dict:
    """ratrace pt8 回放输入包（默认即判 MESH_ARTIFACT；overrides 单项替换）。"""
    packet: dict = {
        "target_freq_ghz": _PT8_TARGET_GHZ,
        "center_ghz": _PT8_CENTER_RAW_GHZ,
        "equiv_eps_eff": _PT8_EPS_EQUIV,
        "eps_eff_closed_form": _PT8_EPS_CLOSED,
        "eps_r": _PT8_EPS_R,
        "mesh_study": _PT8_MESH_STUDY,
    }
    packet.update(overrides)
    return packet


def _load_pt8():
    """真实 pt8 s4p（缺归档返回 None，调用方 skip）。"""
    if not _PT8_S4P.exists():
        return None
    import skrf

    net = skrf.Network(str(_PT8_S4P))
    return net.frequency.f, net.s


def _pt8_eps_by_port() -> dict[str, float] | None:
    """pt8 各端口 β→εeff（真实归档，@2.5GHz）。"""
    out: dict[str, float] = {}
    for p in (1, 2, 3, 4):
        path = REPO / "runs" / "ratrace_smoke" / "pt8" / f"p{p}" / "port_beta.csv"
        if not path.exists():
            return None
        rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
        data = np.array([[float(x) for x in r] for r in rows[1:]])
        j = int(np.argmin(np.abs(data[:, 0] - _PT8_TARGET_GHZ * 1e9)))
        out[f"port{p}"] = float((data[j, 1] * _C0 / (2 * np.pi * data[j, 0])) ** 2)
    return out


def _via_beta_pair():
    """via pt3 真实归档 @2.5GHz 的 (β1, β2, εeff1, εeff2, f)；缺档返回 None。"""
    if not _VIA_BETA.exists():
        return None
    rows = list(csv.reader(_VIA_BETA.read_text(encoding="utf-8").splitlines()))
    data = np.array([[float(x) for x in r] for r in rows[1:]])
    j = int(np.argmin(np.abs(data[:, 0] - 2.5e9)))
    f_hz = float(data[j, 0])
    b1, b2 = float(data[j, 1]), float(data[j, 2])
    e1 = (b1 * _C0 / (2 * np.pi * f_hz)) ** 2
    e2 = (b2 * _C0 / (2 * np.pi * f_hz)) ** 2
    return b1, b2, e1, e2


def _load_drive_row(path: Path):
    """归档 sparams.csv 驱动行 → (freq_hz, (F,4) 复矩阵 [S11,S21,S31,S41])。

    列按端口序 = 激励口 1 的响应行 S_{j,1}（与全矩阵取激励列同口径）。
    """
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    data = np.array([[float(x) for x in r] for r in rows[1:]])
    f = data[:, 0]
    s = np.column_stack([data[:, 1] + 1j * data[:, 2],
                         data[:, 3] + 1j * data[:, 4],
                         data[:, 5] + 1j * data[:, 6],
                         data[:, 7] + 1j * data[:, 8]])
    return f, s


# ---------------------------------------------------------------------------
# 教训 1：ratrace pt8 回放 → MESH_ARTIFACT + 反推 k≈1.10
# ---------------------------------------------------------------------------

class TestRatracePt8Replay:
    def test_pt8_provenance_fixture_is_mesh_artifact_and_recovers_k(self):
        """带 provenance 定版包 → MESH_ARTIFACT 且反推 k=1.0975±0.01。"""
        report = diagnose_mesh_artifact(**_pt8_packet())
        assert report["status"] == MESH_ARTIFACT
        assert report["recovered_scale"] == pytest.approx(_K_DEFINITION, abs=0.01)
        fmap = _factor_map(report)
        assert fmap["mesh_center_shift"]["status"] == FAIL   # 伪象自证
        assert fmap["equiv_eps_eff"]["status"] == FAIL       # 超物理界
        # 建议动作覆盖验收要求：局部加密 / 更换 BASE / 常数落 provenance
        joined = " ".join(report["actions"])
        assert "加密" in joined and "BASE" in joined and "provenance" in joined

    def test_pt8_k_two_routes_agree(self):
        """反推 k 双路（中心比 f_target/f_center 与 sqrt(εeff/闭式)）互证。"""
        report = diagnose_mesh_artifact(**_pt8_packet())
        routes = report["recovered_scale_routes"]
        assert set(routes) == {"center_ratio", "eps_eff_ratio"}
        assert routes["center_ratio"] == pytest.approx(_PT8_TARGET_GHZ / _PT8_CENTER_RAW_GHZ, rel=1e-9)
        assert routes["eps_eff_ratio"] == pytest.approx(recovered_scale_from_eps(
            _PT8_EPS_EQUIV, _PT8_EPS_CLOSED), rel=1e-12)
        assert abs(routes["center_ratio"] - routes["eps_eff_ratio"]) < 0.002

    def test_pt8_real_s4p_gate_degradation(self):
        """真实 0.4mm k=1 归档：带内低端六门全过、随 f 单调劣化（#219 特征信号）。"""
        loaded = _load_pt8()
        if loaded is None:
            pytest.skip("runs/ratrace_smoke/pt8/ratrace.s4p 归档缺失")
        freq_hz, s_matrix = loaded
        g = hybrid_gate_series(freq_hz, s_matrix)
        assert g["ok"]
        # 低端全过
        assert g["balance_db"][0] <= 1.0
        assert g["match_db"][0] <= -10.0
        assert g["isolation_db"][0] <= -15.0
        # 高端至少一门劣化出界
        assert (g["balance_db"][-1] > 1.0 or g["match_db"][-1] > -10.0
                or g["isolation_db"][-1] > -15.0)
        # badness 单调上（递增步占比 1.0，实测）
        assert float(np.mean(np.diff(g["badness"]) > 0)) >= 0.8
        report = diagnose_mesh_artifact(freq_hz=freq_hz, s_matrix=s_matrix, **_pt8_packet())
        assert _factor_map(report)["gate_degradation"]["status"] == FAIL
        assert report["status"] == MESH_ARTIFACT

    def test_pt8_real_s4p_center_at_band_edge(self):
        """真实归档 badness 最小点在带内低端边界（真中心在带外更低）——记录实况。"""
        loaded = _load_pt8()
        if loaded is None:
            pytest.skip("runs/ratrace_smoke/pt8/ratrace.s4p 归档缺失")
        freq_hz, s_matrix = loaded
        center = locate_hybrid_center_ghz(freq_hz, s_matrix)
        assert center == pytest.approx(2.25, abs=1e-6)  # 带内低端边界
        # 该"边界中心"反推 k=1.111，与定版 1.0975 差 ~1.3%（带沿效应，honest note）
        assert _PT8_TARGET_GHZ / center == pytest.approx(1.111, abs=0.001)

    def test_pt8_real_port_eps_not_probe_window(self):
        """真实 pt8 各端口 εeff 比值 ~1.0008，不在探针窗——排除探针尺度误判。"""
        eps = _pt8_eps_by_port()
        if eps is None:
            pytest.skip("runs/ratrace_smoke/pt8/p*/port_beta.csv 归档缺失")
        report = diagnose_mesh_artifact(**_pt8_packet(eps_eff_by_port=eps))
        assert _factor_map(report)["probe_scale_offset"]["status"] == PASS
        assert report["status"] == MESH_ARTIFACT


# ---------------------------------------------------------------------------
# 裸数据回放（D11 PARTIAL 收口）：多档响应数据直接判伪象
# + 给 k 估计，不要求完整 provenance 链；provenance 退为增强路。
# ---------------------------------------------------------------------------

class TestBareTierReplay:
    """tiers 裸数据路径：数字重建 pt8（0.4mm s4p + 0.2mm 驱动行归档）。"""

    def _pt8_tiers_full(self):
        """0.4mm 全矩阵（s4p）+ 0.2mm 驱动行（sparams.csv）；缺档返回 None。"""
        loaded = _load_pt8()
        if loaded is None or not _MESH02_ROW.exists():
            return None
        f04, s04 = loaded
        f02, s02 = _load_drive_row(_MESH02_ROW)
        return [{"mesh_mm": 0.4, "freq_hz": f04, "s_matrix": s04},
                {"mesh_mm": 0.2, "freq_hz": f02, "s_matrix": s02}]

    def test_pt8_bare_two_tier_replay(self):
        """裸两档回放：判 MESH_ARTIFACT + k 带沿界估计；0.2mm 中心数字重建收敛口径。"""
        tiers = self._pt8_tiers_full()
        if tiers is None:
            pytest.skip("pt8 s4p 或 mesh_0p2mm/p1/sparams.csv 归档缺失")
        report = diagnose_mesh_artifact(tiers=tiers, target_freq_ghz=_PT8_TARGET_GHZ)
        assert report["status"] == MESH_ARTIFACT
        tc = report["tier_centers"]
        assert tc[0]["mesh_mm"] == 0.4 and tc[0]["ok"] is True
        assert tc[0]["f_center_ghz"] == pytest.approx(_PT8_EDGE_GHZ, abs=1e-6)
        assert tc[0]["band_edge_limited"] is True
        assert tc[1]["mesh_mm"] == 0.2 and tc[1]["ok"] is True
        # 数字重建：0.2mm 裸定位中心 == 收敛研究 f_center_avg（balance/s11 均值）
        assert tc[1]["f_center_ghz"] == pytest.approx(_CONV_02_AVG_GHZ, abs=1e-6)
        assert tc[1]["band_edge_limited"] is False
        assert tc[1]["metrics"]["balance_min"]["f_ghz"] == pytest.approx(
            _CONV_02_BALANCE_GHZ, abs=1e-6)
        assert tc[1]["metrics"]["s11_min"]["f_ghz"] == pytest.approx(
            _CONV_02_S11_GHZ, abs=1e-6)
        fmap = _factor_map(report)
        assert fmap["mesh_center_shift"]["status"] == FAIL
        assert fmap["gate_degradation"]["status"] == FAIL  # 最粗档全矩阵供六门判据
        # k 估计 = F0/带沿中心（带沿界，如实打旗）
        assert report["recovered_scale"] == pytest.approx(
            _PT8_TARGET_GHZ / _PT8_EDGE_GHZ, abs=1e-3)
        assert report["recovered_scale"] > 1.0
        assert set(report["recovered_scale_routes"]) == {"center_ratio"}
        assert "带沿" in report["detail"]
        joined = " ".join(report["actions"])
        assert "加密" in joined and "BASE" in joined and "provenance" in joined

    def test_pt8_bare_drive_rows_only(self):
        """两档均只有驱动行：六门判据如实 UNKNOWN，中心漂移仍足以判 MESH_ARTIFACT。"""
        if not _PT8_ROW.exists() or not _MESH02_ROW.exists():
            pytest.skip("驱动行归档缺失")
        f04, s04 = _load_drive_row(_PT8_ROW)
        f02, s02 = _load_drive_row(_MESH02_ROW)
        report = diagnose_mesh_artifact(
            tiers=[{"mesh_mm": 0.4, "freq_hz": f04, "s_matrix": s04},
                   {"mesh_mm": 0.2, "freq_hz": f02, "s_matrix": s02}],
            target_freq_ghz=_PT8_TARGET_GHZ)
        assert report["status"] == MESH_ARTIFACT
        fmap = _factor_map(report)
        assert fmap["gate_degradation"]["status"] == "UNKNOWN"
        assert fmap["mesh_center_shift"]["status"] == FAIL
        assert report["recovered_scale"] == pytest.approx(
            _PT8_TARGET_GHZ / _PT8_EDGE_GHZ, abs=1e-3)
        assert report["located_center_ghz"] is None  # 无全矩阵，badness 定位不可用

    def test_bare_tiers_with_provenance_enhancement(self):
        """裸数据 + provenance 增强路（等效 εeff）→ 双路互证，定版常数不再必需。"""
        tiers = self._pt8_tiers_full()
        if tiers is None:
            pytest.skip("pt8 s4p 或 mesh_0p2mm/p1/sparams.csv 归档缺失")
        report = diagnose_mesh_artifact(
            tiers=tiers, target_freq_ghz=_PT8_TARGET_GHZ,
            equiv_eps_eff=_PT8_EPS_EQUIV, eps_eff_closed_form=_PT8_EPS_CLOSED,
            eps_r=_PT8_EPS_R)
        assert report["status"] == MESH_ARTIFACT
        routes = report["recovered_scale_routes"]
        assert set(routes) == {"center_ratio", "eps_eff_ratio"}
        assert routes["center_ratio"] == pytest.approx(
            _PT8_TARGET_GHZ / _PT8_EDGE_GHZ, abs=1e-3)
        assert routes["eps_eff_ratio"] == pytest.approx(_K_DEFINITION, abs=0.01)
        # 双路差 ~1.3% < 2% 容差 → 无分歧告警；带沿界注仍在
        assert abs(routes["center_ratio"] - routes["eps_eff_ratio"]) < 0.02
        assert report["recovered_scale"] == pytest.approx(
            (routes["center_ratio"] + routes["eps_eff_ratio"]) / 2, rel=1e-9)
        assert "带沿" in report["detail"]

    def test_bare_healthy_two_tier_not_mesh_artifact(self):
        """阴性对照：两档理想环（中心不随细化上移）不得误判 MESH_ARTIFACT。"""
        freq_ghz = np.linspace(2.25, 2.75, 101)
        s = _ideal_ring_s(freq_ghz)
        report = diagnose_mesh_artifact(
            tiers=[{"mesh_mm": 0.4, "freq_hz": freq_ghz * 1e9, "s_matrix": s},
                   {"mesh_mm": 0.2, "freq_hz": freq_ghz * 1e9, "s_matrix": s}],
            target_freq_ghz=2.5)
        fmap = _factor_map(report)
        assert fmap["mesh_center_shift"]["status"] == PASS
        assert fmap["gate_degradation"]["status"] == PASS
        assert report["status"] != MESH_ARTIFACT
        # 裸数据只有门劣化+中心漂移两项证据，全过也不升 HEALTHY（其余项未验证）
        assert report["status"] == INCONCLUSIVE
        assert report["recovered_scale"] is None

    def test_single_bare_tier_insufficient(self):
        """单档裸数据无中心漂移证据（需 ≥2 档）→ 不得仅凭门劣化判 MESH_ARTIFACT。"""
        loaded = _load_pt8()
        if loaded is None:
            pytest.skip("runs/ratrace_smoke/pt8/ratrace.s4p 归档缺失")
        f04, s04 = loaded
        report = diagnose_mesh_artifact(
            tiers=[{"mesh_mm": 0.4, "freq_hz": f04, "s_matrix": s04}],
            target_freq_ghz=_PT8_TARGET_GHZ)
        fmap = _factor_map(report)
        assert fmap["mesh_center_shift"]["status"] == "UNKNOWN"
        assert fmap["gate_degradation"]["status"] == FAIL
        assert report["status"] == INCONCLUSIVE

    def test_corrupt_tier_row_isolated(self):
        """坏档（形状不符）→ 该档 ok=False 带原因，不传染其余档（#105）。"""
        if not _MESH02_ROW.exists():
            pytest.skip("mesh_0p2mm/p1/sparams.csv 归档缺失")
        f02, s02 = _load_drive_row(_MESH02_ROW)
        report = diagnose_mesh_artifact(
            tiers=[{"mesh_mm": 0.4, "freq_hz": [1, 2, 3],
                    "s_matrix": [[1, 2], [3, 4]]},
                   {"mesh_mm": 0.2, "freq_hz": f02, "s_matrix": s02}],
            target_freq_ghz=_PT8_TARGET_GHZ)
        tc = report["tier_centers"]
        assert tc[0]["ok"] is False and tc[0]["reason"]
        assert tc[1]["ok"] is True
        # 仅 1 档有效 → 中心漂移证据不足
        assert _factor_map(report)["mesh_center_shift"]["status"] == "UNKNOWN"
        assert report["status"] == INCONCLUSIVE

    def test_explicit_inputs_override_tier_fallback(self):
        """显式 kwargs > 裸数据定位（provenance 增强语义），tier_centers 仍保留。"""
        freq_ghz = np.linspace(2.25, 2.75, 101)
        s = _ideal_ring_s(freq_ghz)
        report = diagnose_mesh_artifact(
            tiers=[{"mesh_mm": 0.4, "freq_hz": freq_ghz * 1e9, "s_matrix": s},
                   {"mesh_mm": 0.2, "freq_hz": freq_ghz * 1e9, "s_matrix": s}],
            target_freq_ghz=_PT8_TARGET_GHZ,
            center_ghz=_PT8_CENTER_RAW_GHZ,
            mesh_study=[{"mesh_mm": 0.4, "f_center_ghz": 2.35},
                        {"mesh_mm": 0.2, "f_center_ghz": 2.52}])
        assert report["status"] == MESH_ARTIFACT
        # 中心比路用显式定版中心而非裸定位 2.5
        assert report["recovered_scale_routes"]["center_ratio"] == pytest.approx(
            _PT8_TARGET_GHZ / _PT8_CENTER_RAW_GHZ, rel=1e-9)
        # 中心漂移用显式 mesh_study（2.35→2.52 单调上移）
        assert _factor_map(report)["mesh_center_shift"]["status"] == FAIL
        # 裸定位明细仍在场（理想环中心 2.5，带内）
        assert report["tier_centers"][0]["f_center_ghz"] == pytest.approx(2.5, abs=1e-6)

    def test_locate_full_matrix_metrics(self):
        """全矩阵裸定位：三指标在场，pt8 中心落带沿并打界旗。"""
        loaded = _load_pt8()
        if loaded is None:
            pytest.skip("runs/ratrace_smoke/pt8/ratrace.s4p 归档缺失")
        f, s = loaded
        loc = locate_tier_center_ghz(f, s)
        assert loc["ok"] is True
        assert loc["data_shape"] == "full_matrix"
        assert loc["n_freq"] == f.size
        assert set(loc["metrics"]) == {"balance_min", "s11_min", "badness_min"}
        assert loc["f_center_ghz"] == pytest.approx(_PT8_EDGE_GHZ, abs=1e-6)
        assert loc["band_edge_limited"] is True

    def test_locate_drive_row_reconstructs_convergence_center(self):
        """驱动行裸定位：逐指标重建收敛研究 center_0p2mm 口径。"""
        if not _MESH02_ROW.exists():
            pytest.skip("mesh_0p2mm/p1/sparams.csv 归档缺失")
        f, s = _load_drive_row(_MESH02_ROW)
        loc = locate_tier_center_ghz(f, s)
        assert loc["ok"] is True
        assert loc["data_shape"] == "drive_row"
        assert set(loc["metrics"]) == {"balance_min", "s11_min"}
        assert loc["metrics"]["balance_min"]["f_ghz"] == pytest.approx(
            _CONV_02_BALANCE_GHZ, abs=1e-6)
        assert loc["metrics"]["s11_min"]["f_ghz"] == pytest.approx(
            _CONV_02_S11_GHZ, abs=1e-6)
        assert loc["f_center_ghz"] == pytest.approx(_CONV_02_AVG_GHZ, abs=1e-6)
        assert loc["band_edge_limited"] is False

    def test_locate_rejects_bad_input(self):
        """坏输入一律 ok=False（不误报不炸，#105）。"""
        freq = np.linspace(2.25, 2.75, 101) * 1e9
        assert locate_tier_center_ghz(None, None)["ok"] is False
        assert locate_tier_center_ghz(freq, np.zeros((5, 4, 6), dtype=complex))["ok"] is False
        assert locate_tier_center_ghz(freq[:3], np.zeros((3, 4, 4), dtype=complex))["ok"] is False
        assert locate_tier_center_ghz(freq, np.ones((101, 3), dtype=complex))["ok"] is False


# ---------------------------------------------------------------------------
# 教训 2：via 1.0491 → PROBE_SCALE（探针尺度常数，非网格伪象）
# ---------------------------------------------------------------------------

class TestViaProbeScale:
    def test_via_real_archive_is_probe_scale(self):
        """真实 via pt3 归档 β2/β1=1.0491 → PROBE_SCALE。"""
        pair = _via_beta_pair()
        if pair is None:
            pytest.skip("runs/via_smoke/pt3/port_beta.csv 归档缺失")
        b1, b2, e1, e2 = pair
        assert b2 / b1 == pytest.approx(_VIA_BETA_RATIO, abs=0.005)
        report = diagnose_mesh_artifact(
            beta_by_port={"port1": b1, "port2": b2},
            eps_eff_by_port={"port1": e1, "port2": e2},
            equiv_eps_eff=e1, eps_eff_closed_form=e1, eps_r=_PT8_EPS_R)
        assert report["status"] == PROBE_SCALE
        assert _factor_map(report)["probe_scale_offset"]["status"] == FAIL

    def test_via_documented_beta_ratio_is_probe_scale(self):
        """定版 β 比 1.0491（不依赖文件）→ PROBE_SCALE。"""
        report = diagnose_mesh_artifact(
            beta_by_port={"port1": 80.0, "port2": 80.0 * _VIA_BETA_RATIO})
        assert report["status"] == PROBE_SCALE
        pair = _factor_map(report)["probe_scale_offset"]["evidence"]["suspicious_pairs"]
        assert pair and pair[0]["scale"] == pytest.approx(_VIA_BETA_RATIO, rel=1e-6)

    def test_probe_scale_actions_mention_deembedding(self):
        report = diagnose_mesh_artifact(
            beta_by_port={"port1": 80.0, "port2": 80.0 * _VIA_BETA_RATIO})
        joined = " ".join(report["actions"])
        assert "去嵌入" in joined and "provenance" in joined
        # 探针病不应给出"局部加密网格"处方（"勿以加密网格求解"是反向告诫，不算处方）
        assert "局部加密网格" not in joined

    def test_via_not_mesh_artifact_without_mesh_evidence(self):
        """无网格特异证据时即便有探针窗命中也不得误判网格伪象。"""
        report = diagnose_mesh_artifact(
            beta_by_port={"port1": 80.0, "port2": 80.0 * _VIA_BETA_RATIO},
            eps_eff_by_port={"port1": 2.874, "port2": 2.874 * _VIA_BETA_RATIO ** 2})
        assert report["status"] == PROBE_SCALE
        assert _factor_map(report)["mesh_center_shift"]["status"] in ("UNKNOWN", PASS)


# ---------------------------------------------------------------------------
# 教训 3：#152 nm 近重合网格线 → TIMESTEP_COLLAPSE
# ---------------------------------------------------------------------------

def _normal_cfl_step_s(dx_mm: float = 0.4) -> float:
    """0.4mm 网格的 CFL 步长闭式推算 dx/(2c)（非编造参考值）。"""
    return (dx_mm * 1e-3) / (2.0 * _C0)


class TestTimestepCollapse:
    def test_152_timestep_ratio_collapse(self):
        """#152 塌缩值 7.7e-19 s vs 正常 CFL 步长 → TIMESTEP_COLLAPSE。"""
        dt_normal = _normal_cfl_step_s()
        report = diagnose_mesh_artifact(
            timestep_values=[dt_normal, _TIMESTEP_COLLAPSED_S])
        assert report["status"] == TIMESTEP_COLLAPSE
        ev = _factor_map(report)["timestep_collapse"]
        assert ev["status"] == FAIL
        assert ev["evidence"]["timestep_min_max_ratio"] < 1e-3

    def test_152_near_coincident_mesh_lines_are_root_cause(self):
        """nm 级近重合网格线（<1µm 最小间距守卫口径）→ TIMESTEP_COLLAPSE。"""
        report = diagnose_mesh_artifact(mesh_line_gaps_m=[1e-9, 4e-4, 5e-4])
        assert report["status"] == TIMESTEP_COLLAPSE
        ev = _factor_map(report)["timestep_collapse"]["evidence"]
        assert ev["min_mesh_gap_m"] < 1e-6
        joined = " ".join(report["actions"])
        assert "最小间距" in joined

    def test_normal_timesteps_and_gaps_pass(self):
        report = diagnose_mesh_artifact(
            timestep_values=[_normal_cfl_step_s(), _normal_cfl_step_s() * 1.01],
            mesh_line_gaps_m=[4e-4, 5e-4])
        assert _factor_map(report)["timestep_collapse"]["status"] == PASS

    def test_missing_timestep_is_unknown_not_fail(self):
        report = diagnose_mesh_artifact(**_pt8_packet())
        assert _factor_map(report)["timestep_collapse"]["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# 判据边界 / 统一入口
# ---------------------------------------------------------------------------

class TestDiagnosisBoundaries:
    def test_no_evidence_is_inconclusive(self):
        report = diagnose_mesh_artifact()
        assert report["status"] == INCONCLUSIVE
        assert report["recovered_scale"] is None
        assert all(f["status"] == "UNKNOWN" for f in report["factors"])

    def test_healthy_when_all_factors_pass(self):
        freq_ghz = np.linspace(2.25, 2.75, 101)
        report = diagnose_mesh_artifact(
            freq_hz=freq_ghz * 1e9, s_matrix=_ideal_ring_s(freq_ghz),
            target_freq_ghz=2.5, center_ghz=2.5,
            equiv_eps_eff=2.72, eps_eff_closed_form=_PT8_EPS_CLOSED, eps_r=_PT8_EPS_R,
            beta_by_port={"port1": 80.0, "port2": 80.05},
            mesh_study=[{"mesh_mm": 0.4, "f_center_ghz": 2.50},
                        {"mesh_mm": 0.2, "f_center_ghz": 2.50}],
            timestep_values=[_normal_cfl_step_s(), _normal_cfl_step_s() * 1.01],
            mesh_line_gaps_m=[4e-4, 5e-4])
        assert report["status"] == HEALTHY
        assert all(f["status"] == PASS for f in report["factors"])

    def test_center_shift_non_monotone_passes(self):
        report = diagnose_mesh_artifact(mesh_study=[
            {"mesh_mm": 0.4, "f_center_ghz": 2.52},
            {"mesh_mm": 0.2, "f_center_ghz": 2.50}])
        assert _factor_map(report)["mesh_center_shift"]["status"] == PASS

    def test_center_shift_small_shift_warns_not_fails(self):
        report = diagnose_mesh_artifact(mesh_study=[
            {"mesh_mm": 0.4, "f_center_ghz": 2.500},
            {"mesh_mm": 0.2, "f_center_ghz": 2.510}])
        assert _factor_map(report)["mesh_center_shift"]["status"] == "WARN"

    def test_eps_over_substrate_er_fails_on_physical_bound(self):
        report = diagnose_mesh_artifact(equiv_eps_eff=3.9, eps_eff_closed_form=2.72,
                                        eps_r=3.66)
        assert _factor_map(report)["equiv_eps_eff"]["status"] == FAIL
        assert report["status"] == MESH_ARTIFACT

    def test_degradation_only_is_inconclusive_not_mesh_artifact(self):
        """只有频率劣化、无网格特异证据 → INCONCLUSIVE（可能是设计错）。"""
        loaded = _load_pt8()
        if loaded is None:
            pytest.skip("runs/ratrace_smoke/pt8/ratrace.s4p 归档缺失")
        freq_hz, s_matrix = loaded
        report = diagnose_mesh_artifact(freq_hz=freq_hz, s_matrix=s_matrix)
        assert _factor_map(report)["gate_degradation"]["status"] == FAIL
        assert report["status"] == INCONCLUSIVE

    def test_provenance_fallback_supplies_inputs(self):
        """显式 kwargs 缺失时从 provenance 兜底取键。"""
        report = diagnose_mesh_artifact(provenance={
            "target_freq_ghz": _PT8_TARGET_GHZ,
            "center_ghz": _PT8_CENTER_RAW_GHZ,
            "equiv_eps_eff": _PT8_EPS_EQUIV,
            "eps_eff_closed_form": _PT8_EPS_CLOSED,
            "eps_r": _PT8_EPS_R,
            "mesh_study": _PT8_MESH_STUDY,
        })
        assert report["status"] == MESH_ARTIFACT
        assert report["recovered_scale"] == pytest.approx(_K_DEFINITION, abs=0.01)

    def test_recovered_scale_from_eps_helper(self):
        assert recovered_scale_from_eps(3.28, 2.7246) == pytest.approx(1.0972, abs=0.001)
        assert recovered_scale_from_eps(None, 2.72) is None
        assert recovered_scale_from_eps(3.28, 0) is None
