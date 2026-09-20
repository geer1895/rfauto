"""A8 MAPES 探针装配侧根因修复定向单测（#257；确定性、离线、零真机）。

覆盖 core/mapes.py stage-5b 节 + scripts/mapes_s2_zall.py 文件面：
1. ``port_probe_axes``：缝隙口按缝隙跨度取 x/y、竖直口恒 z，与渲染脚本
   ``exc_dir`` 逐端口一致（150/150，单一事实源回归钉）；
2. ``probe_midlines``：每端口盒三轴中线齐备（u 探针横断面中心 + i 探针激励
   轴中面）、排序去重、确定性；6×6 板实测中线数 x/y/z=22/23/2；
3. ``probe_box_guard``：结构线∪中线 PASS（实测最小半跨/中线邻距 0.1mm）；仅
   结构线 → 360 处违例（=450 中线 − 90 个竖直口 z 中线恰与既有 h/2 线重合）；
   零跨盒、中线贴邻线（≤1µm 去重阈值）逐轴定位；入参校验；
4. 渲染接线：脚本 mesh.AddLine 含中线坐标（io1 中心 (0.5,1.0)mm、像素中心、
   缝隙中心、z=h/2 与 0.75h）、守卫注释、违例 raise、``nr_ts`` 覆盖；
5. ``ui_cross_round_drift``：轮不变合成 ≈0（≤1e-12）；逐端口探针因子注入
   定位到注入端口且其余端口不受扰、端口中位数的中位对单坏口鲁棒；激励轮
   （k=p）不参与；无效样本 NaN；形状非法显式报错；
6. 脚本接入：``drift_report_json`` NaN→None 且可 json.dumps；``drift_by_class``
   逐类汇总；``load_raw_ui`` 缓存复用/形状不符重读；``stage_reassemble`` 报告
   含 ``cross_round_drift`` 且先于装配阶段；``drift`` 子命令落 drift_report.json。

阈值依据：中线/守卫为纯几何（浮点精确成员），断言严格；漂移合成路径为纯
线性代数（随机复矩阵实测 1e-15 量级），断言 1e-12；注入 ±2% 电流因子 →
Z_ui 相对偏差 ≈ 2%/(1∓0.02)，断言 >1e-2。
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.errors import ConfigError
from rfauto.core.mapes import (
    PROBE_MIN_GAP_M,
    PixelLayout,
    PortGeom,
    fake_mesh,
    pixel_board_geom,
    port_probe_axes,
    probe_box_guard,
    probe_midlines,
    ui_cross_round_drift,
    z_to_s,
)

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "mapes_s2_zall.py"
Z0 = 50.0
FREQ_HZ = np.array([1.0e9, 3.5e9, 6.0e9])
Q = 9


def _stage2_module():
    spec = importlib.util.spec_from_file_location("mapes_s2_zall", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _layout66() -> PixelLayout:
    return PixelLayout(6, 6, 1, 2, ((0, 5, "via_ground"), (5, 0, "via_ground")))


def _geom66():
    return pixel_board_geom(_layout66(), sub_h_mm=0.508, edge_pad_mm=6.0)


def _merged_lines(mod, geom):
    xs, ys, zs = mod.mesh_lines(geom)
    mx, my, mz = probe_midlines(geom)
    return (sorted(set(xs) | set(mx)), sorted(set(ys) | set(my)), sorted(set(zs) | set(mz)))


def _addline_set(text: str, axis: str) -> set[float]:
    m = re.search(rf'mesh\.AddLine\("{axis}", (\[.*?\])\)', text)
    assert m is not None
    return set(float(v) for v in ast.literal_eval(m.group(1)))


def _has(vals, x: float, tol: float = 1.0e-12) -> bool:
    """期望坐标是否在线集中（ULP 容差：中线由 0.5·(lo+hi) 生成，期望由 a/2 等直算）。"""
    return any(abs(float(v) - x) <= tol for v in vals)


def _true_s(q: int = Q, n_cols: int = 3) -> np.ndarray:
    mesh = fake_mesh(q, n_cols=n_cols)
    z = np.stack([mesh.z_all(f) for f in FREQ_HZ])
    return z_to_s(z, reference_impedance=Z0)


def _synth_ui(s: np.ndarray):
    """由 S_true 合成轮转原始 (uf, if)：轮 k 入射 a=e_k，U=a+b，I=(a−b)/Z0。"""
    nf, q, _ = s.shape
    uf = np.zeros((q, q, nf), dtype=complex)
    if_ = np.zeros((q, q, nf), dtype=complex)
    for k in range(q):
        a = np.zeros(q, dtype=complex)
        a[k] = 1.0
        b = s[:, :, k]
        uf[k] = (a[None, :] + b).T
        if_[k] = ((a[None, :] - b) / Z0).T
    return uf, if_


# ─── 1. port_probe_axes ──────────────────────────────────────────────────────

def test_port_probe_axes_per_kind_and_matches_rendered_exc_dir():
    geom = _geom66()
    layout = geom.layout
    slots = layout.load_slots()
    for port in geom.ports:
        ax = port_probe_axes(port)
        if port.slot_index < 0:
            assert ax == 2  # io 竖直口
            continue
        cat = slots[port.slot_index].category
        if cat == "pixel_h":
            assert ax == 0
        elif cat == "pixel_v":
            assert ax == 1
        else:
            assert ax == 2
    with pytest.raises(ConfigError):
        port_probe_axes("io1")  # type: ignore[arg-type]
    # 单一事实源：渲染脚本 exc_dir 逐端口与 port_probe_axes 一致（150/150）
    mod = _stage2_module()
    text = mod.render_round_script(geom, excite_port=1, virtual_ports=True)
    lines = text.splitlines()
    n_checked = 0
    for port in geom.ports:
        i = next(k for k, ln in enumerate(lines) if ln.startswith(f"_port{port.number} ="))
        m = re.search(r"exc_dir='(.)'", "\n".join(lines[i:i + 4]))
        assert m is not None
        assert m.group(1) == ("x", "y", "z")[port_probe_axes(port)], port.label
        n_checked += 1
    assert n_checked == layout.n_ports == 150


# ─── 2. probe_midlines ───────────────────────────────────────────────────────

def test_probe_midlines_cover_every_box_sorted_unique_deterministic():
    geom = _geom66()
    mids = probe_midlines(geom)
    assert probe_midlines(geom) == mids  # 确定性
    for ax in range(3):
        vals = mids[ax]
        assert vals == sorted(vals) and len(vals) == len(set(vals))
    for port in geom.ports:
        s, t = port.start, port.stop
        for ax in range(3):
            assert 0.5 * (float(s[ax]) + float(t[ax])) in mids[ax], (port.label, ax)
    # 6×6 板实测：x/y 各 22/23 条、z 两条（竖直口 h/2 + 缝隙口 0.75h）
    assert (len(mids[0]), len(mids[1]), len(mids[2])) == (22, 23, 2)
    h = geom.sub_h_m
    assert mids[2] == pytest.approx([0.5 * h, 0.75 * h])
    with pytest.raises(ConfigError):
        probe_midlines(geom.layout)  # type: ignore[arg-type]


# ─── 3. probe_box_guard ──────────────────────────────────────────────────────

def test_probe_box_guard_passes_on_merged_lines_with_measured_margins():
    mod = _stage2_module()
    geom = _geom66()
    guard = probe_box_guard(geom, _merged_lines(mod, geom))
    assert guard["pass"] is True and guard["n_violations"] == 0
    assert guard["n_ports"] == 150 and guard["min_gap_m"] == PROBE_MIN_GAP_M
    # 最小半跨 = 盒半宽 hx=0.1mm（io/像素/对角/缝隙口共同下限）；中线到最近
    # 邻线亦 0.1mm（远大于 1µm 去重阈值 → 平滑/去重后必存活）
    assert guard["min_half_span_m"] == pytest.approx(0.1e-3, rel=1e-9)
    assert guard["min_mid_gap_m"] == pytest.approx(0.1e-3, rel=1e-9)
    assert guard["min_mid_gap_m"] > 50 * PROBE_MIN_GAP_M  # 远高于去重阈值
    # 信息项：结构线间存在 ULP 级近重合（渲染端 #152 去重收敛），z 轴 0.127mm
    adj = guard["min_adjacent_gap_m"]
    assert adj["z"] == pytest.approx(0.127e-3, rel=1e-6)
    assert 0.0 < adj["x"] < PROBE_MIN_GAP_M and 0.0 < adj["y"] < PROBE_MIN_GAP_M
    json.dumps(guard)  # JSON 友好


def test_probe_box_guard_flags_missing_midlines_on_structure_only_lines():
    mod = _stage2_module()
    geom = _geom66()
    guard = probe_box_guard(geom, mod.mesh_lines(geom))
    assert guard["pass"] is False
    # 450 条中线中 90 个竖直口的 z 中线 (h/2) 恰与缝隙口底线重合 → 360 缺失
    assert guard["n_violations"] == 360
    assert all("缺中心硬线" in v["reason"] for v in guard["violations"])
    first = guard["violations"][0]
    assert first["port"] == 1 and first["label"] == "io1" and first["axis"] == "x"
    assert {v["axis"] for v in guard["violations"]} == {"x", "y", "z"}
    n_z = sum(1 for v in guard["violations"] if v["axis"] == "z")
    assert n_z == 60  # 仅 60 个缝隙口的 0.75h 中线缺失


def test_probe_box_guard_flags_degenerate_and_crowded_boxes():
    mod = _stage2_module()
    geom = _geom66()
    io1 = geom.ports[0]
    h = geom.sub_h_m
    # (a) 零跨盒：x 向 start==stop → 半跨 0（探针退化）
    zero = PortGeom("io1", io1.kind, io1.number, io1.slot_index,
                    (io1.start[0], io1.start[1], 0.0), (io1.start[0], io1.stop[1], h))
    bad = dataclasses.replace(geom, ports=(zero, *geom.ports[1:]))
    guard = probe_box_guard(bad, _merged_lines(mod, bad))
    assert guard["pass"] is False
    zero_v = [v for v in guard["violations"] if v["port"] == 1]
    assert zero_v and all(v["axis"] == "x" for v in zero_v)
    assert any("半跨" in v["reason"] for v in zero_v)
    assert guard["min_half_span_m"] == 0.0
    # (b) 中线贴邻线：盒跨 0.6µm 且骑在贴片边 2.0mm 上 → 中线离 2.0mm 线 1e-7m
    edge = 2.0e-3
    crowd = PortGeom("io1", io1.kind, io1.number, io1.slot_index,
                     (edge - 2.0e-7, io1.start[1], 0.0), (edge + 4.0e-7, io1.stop[1], h))
    bad2 = dataclasses.replace(geom, ports=(crowd, *geom.ports[1:]))
    guard2 = probe_box_guard(bad2, _merged_lines(mod, bad2))
    assert guard2["pass"] is False
    reasons = [v["reason"] for v in guard2["violations"] if v["port"] == 1 and v["axis"] == "x"]
    assert any("去重会吞中线" in r for r in reasons)
    assert any("半跨" in r for r in reasons)
    assert guard2["min_mid_gap_m"] == pytest.approx(1.0e-7, rel=1e-6)
    # 其余 149 口不受影响
    assert {v["port"] for v in guard2["violations"]} == {1}
    # 入参校验
    with pytest.raises(ConfigError):
        probe_box_guard(geom, ([], [0.0], [0.0]))
    with pytest.raises(ConfigError):
        probe_box_guard(geom, ([0.0], [0.0]))  # type: ignore[arg-type]
    with pytest.raises(ConfigError):
        probe_box_guard(geom, _merged_lines(mod, geom), min_gap_m=-1.0)
    with pytest.raises(ConfigError):
        probe_box_guard(geom.layout, _merged_lines(mod, geom))  # type: ignore[arg-type]


# ─── 4. 渲染接线 ─────────────────────────────────────────────────────────────

def test_render_embeds_probe_midlines_and_guard_comment():
    mod = _stage2_module()
    geom = _geom66()
    text = mod.render_round_script(geom, excite_port=1, virtual_ports=True)
    xs, ys, zs = (_addline_set(text, ax) for ax in ("x", "y", "z"))
    a, p, h = geom.cell_m, geom.pitch_m, geom.sub_h_m
    # io1 中心 (a/4, a/2)=(0.5,1.0)mm：病理档 u 探针吸附盒角 (0.4,0.85) 的修复点
    assert _has(xs, a / 4.0) and _has(ys, a / 2.0)
    # 像素口中心、缝隙口中心（x0+g/2）、对角锚中心
    assert _has(xs, 2 * p + a / 2.0) and _has(ys, 3 * p + a / 2.0)
    assert _has(xs, a + geom.gap_m / 2.0) and _has(ys, a + geom.gap_m / 2.0)
    assert _has(xs, a - 0.25e-3)
    # z：竖直口 i 探针中面 h/2（病理档被吸附到 z=0 PEC）与缝隙口 0.75h
    assert _has(zs, 0.5 * h) and _has(zs, 0.75 * h)
    # 全部中线都进了脚本线集
    mx, my, mz = probe_midlines(geom)
    assert set(mx) <= xs and set(my) <= ys and set(mz) <= zs
    marker = [ln for ln in text.splitlines() if ln.startswith("# probe midlines")]
    assert len(marker) == 1 and "#257" in marker[0] and "PASS" in marker[0]
    assert "x=22 y=23 z=2" in marker[0]
    # 既有接线不变：#152 去重守卫、单激励、Q 个口
    assert "SetLines(_ax" in text and text.count("excite=1") == 1
    assert text.count("LumpedPort(CSX") == 150
    # 图案模式（仅 io 探针）同样带全部中线（参考轮与图案轮网格一致，对拍口径）
    text_p = mod.render_round_script(geom, excite_port=2, virtual_ports=False,
                                     short_numbers=(18,))
    assert _addline_set(text_p, "x") == xs and _addline_set(text_p, "z") == zs


def test_render_nr_ts_override_and_guard_failure_raises():
    mod = _stage2_module()
    geom = _geom66()
    text = mod.render_round_script(geom, excite_port=1, virtual_ports=True)
    assert f"openEMS(NrTS={mod.NR_TS!r})" in text
    text2 = mod.render_round_script(geom, excite_port=1, virtual_ports=True, nr_ts=60000)
    assert "openEMS(NrTS=60000)" in text2 and text2 != text
    with pytest.raises(ValueError):
        mod.render_round_script(geom, excite_port=1, virtual_ports=True, nr_ts=0)
    io1 = geom.ports[0]
    zero = PortGeom("io1", io1.kind, io1.number, io1.slot_index,
                    (io1.start[0], io1.start[1], 0.0), (io1.start[0], io1.stop[1], geom.sub_h_m))
    bad = dataclasses.replace(geom, ports=(zero, *geom.ports[1:]))
    with pytest.raises(ValueError, match="≥2 格守卫失败"):
        mod.render_round_script(bad, excite_port=1, virtual_ports=True)
    with pytest.raises(ValueError, match="#257"):
        mod.render_mesh_lines(bad)


# ─── 5. ui_cross_round_drift ─────────────────────────────────────────────────

def test_drift_is_zero_for_round_invariant_terminations():
    uf, if_ = _synth_ui(_true_s())
    d = ui_cross_round_drift(uf, if_)
    assert d["n_ports"] == Q and d["n_freq"] == len(FREQ_HZ)
    assert d["n_ports_defined"] == Q
    assert d["median_of_port_median"] < 1.0e-12
    assert d["max_of_port_max"] < 1.0e-12
    assert np.all(d["n_valid_samples"] == (Q - 1) * len(FREQ_HZ))
    assert d["max_of_port_max_freqmedian"] < 1.0e-12
    assert np.all(np.isfinite(d["port_zui_abs_median"]))
    # 匹配端接 Z_ui 量级 = |uf/if| = Z0·|(1+s)/(1−s)|-型量，非零有限
    assert np.all(d["port_zui_abs_median"] > 0.0)


def test_drift_localizes_injected_port_and_is_robust_in_median():
    s = _true_s()
    uf, if_ = _synth_ui(s)
    p0 = 4
    for k in range(Q):
        if k != p0:
            if_[k, p0, :] *= 1.0 + 0.02 * (1.0 if k % 2 == 0 else -1.0)
    d = ui_cross_round_drift(uf, if_)
    # 注入口最大偏差 ≈ 2%/(1∓0.02) 量级；其余口精确 0
    assert d["port_max_rel"][p0] > 1.0e-2
    others = np.delete(d["port_max_rel"], p0)
    assert np.max(others) < 1.0e-12
    assert d["worst_port"] == p0 + 1
    assert d["max_of_port_max"] == pytest.approx(d["port_max_rel"][p0])
    # 逐轮频中位的跨轮最大：每轮因子恒定 → 频中位 = 该轮偏差 ≈ 0.02/(1∓0.02)
    fm = d["port_max_freqmedian_rel"]
    assert 0.015 < fm[p0] < 0.025
    assert np.max(np.delete(fm, p0)) < 1.0e-12
    assert d["max_of_port_max_freqmedian"] == pytest.approx(fm[p0])
    # 端口中位数的中位对单坏口鲁棒（8/9 口为 0）
    assert d["median_of_port_median"] < 1.0e-12
    # 激励轮（k=p）不参与：对角污染不改任何数字
    uf_c, if_c = uf.copy(), if_.copy()
    for k in range(Q):
        uf_c[k, k, :] *= 1.0e6
        if_c[k, k, :] *= 1.0e-6
    d2 = ui_cross_round_drift(uf_c, if_c)
    assert np.allclose(d2["port_max_rel"], d["port_max_rel"])
    assert np.allclose(d2["port_median_rel"], d["port_median_rel"])
    assert np.allclose(d2["port_max_freqmedian_rel"], fm)


def test_drift_freqmedian_suppresses_single_frequency_spike():
    """单频尖峰（同贴片激励轮单点拾取形态）：(轮,频) 原始最大被拉高，频中位口径不动。"""
    uf, if_ = _synth_ui(_true_s())
    p0, k0 = 6, 1
    if_[k0, p0, 1] *= 5.0  # 单轮单频 ×5 → 该点 Z_ui 偏 −80%
    d = ui_cross_round_drift(uf, if_)
    assert d["port_max_rel"][p0] > 0.5
    assert d["port_max_freqmedian_rel"][p0] < 1.0e-12  # 3 频点取中位压掉单点
    assert d["max_of_port_max"] > 0.5 and d["max_of_port_max_freqmedian"] < 1.0e-12


def test_drift_snr_buckets_and_rel_floor_separate_weak_coupling_noise():
    """弱耦合轮（|if| 远低于该口跨轮中位）的比值噪声只落在低信噪桶；rel_floor
    把它剔出逐端口统计，强信号桶/统计不变——真机档"远端缝隙口激励轮拉高最大"
    形态的离线复现。"""
    uf, if_ = _synth_ui(_true_s())
    p0, k0 = 3, 7
    # 轮 k0 对端口 p0 的 u/i 同缩 1e-3（弱耦合）并给电流加 30% 比值噪声
    uf[k0, p0, :] *= 1.0e-3
    if_[k0, p0, :] *= 1.0e-3 * 1.3
    d = ui_cross_round_drift(uf, if_)
    b = d["snr_buckets"]
    assert [x["snr_lo"] for x in b] == [0.0, 1e-2, 1e-1, 1.0, 10.0]
    assert b[-1]["snr_hi"] is None and sum(x["n"] for x in b) == int(d["n_valid_samples"].sum())
    low = b[0]
    assert low["n"] == len(FREQ_HZ) and low["rel_median"] == pytest.approx(0.3 / 1.3, rel=1e-6)
    assert all(x["rel_max"] is None or x["rel_max"] < 1.0e-12 for x in b[1:])
    assert d["port_max_freqmedian_rel"][p0] == pytest.approx(0.3 / 1.3, rel=1e-6)
    # rel_floor=0.1：弱耦合轮样本剔除 → 该口统计回到 0，样本数减 nf
    dg = ui_cross_round_drift(uf, if_, rel_floor=0.1)
    assert dg["rel_floor"] == 0.1
    assert dg["port_max_rel"][p0] < 1.0e-12 and dg["port_max_freqmedian_rel"][p0] < 1.0e-12
    assert dg["n_valid_samples"][p0] == d["n_valid_samples"][p0] - len(FREQ_HZ)
    assert dg["max_of_port_max"] < 1.0e-12
    assert dg["snr_buckets"][0]["n"] == 0 and dg["snr_buckets"][0]["rel_median"] is None
    json.dumps(dg["snr_buckets"], allow_nan=False)
    with pytest.raises(ConfigError):
        ui_cross_round_drift(uf, if_, rel_floor=-0.5)


def test_drift_handles_invalid_samples_and_validates_input():
    uf, if_ = _synth_ui(_true_s())
    # 端口 2 的全部非激励轮电流为 0 → 无有效样本 → NaN、n_valid=0、汇总仍定义
    if_[:, 2, :] = 0.0
    d = ui_cross_round_drift(uf, if_)
    assert np.isnan(d["port_median_rel"][2]) and np.isnan(d["port_max_rel"][2])
    assert np.isnan(d["port_max_freqmedian_rel"][2])
    assert d["n_valid_samples"][2] == 0 and d["n_ports_defined"] == Q - 1
    assert d["median_of_port_median"] < 1.0e-12 and d["worst_port"] is not None
    # 全部无效 → 汇总 None
    d0 = ui_cross_round_drift(uf, np.zeros_like(if_))
    assert d0["n_ports_defined"] == 0 and d0["worst_port"] is None
    assert d0["median_of_port_median"] is None and d0["max_of_port_max"] is None
    assert d0["max_of_port_max_freqmedian"] is None
    with pytest.raises(ConfigError):
        ui_cross_round_drift(uf[:, :4], if_[:, :4])
    with pytest.raises(ConfigError):
        ui_cross_round_drift(uf, if_[:, :, :2])
    with pytest.raises(ConfigError):
        ui_cross_round_drift(uf[0], if_[0])
    with pytest.raises(ConfigError):
        ui_cross_round_drift(uf, if_, floor=-1.0)


# ─── 6. 脚本接入：报告/子命令 ─────────────────────────────────────────────────

def test_drift_report_json_and_by_class():
    mod = _stage2_module()
    uf, if_ = _synth_ui(_true_s())
    if_[:, 2, :] = 0.0
    d = ui_cross_round_drift(uf, if_)
    rep = mod.drift_report_json(d)
    text = json.dumps(rep, allow_nan=False)  # 严格 JSON：NaN 已转 None
    assert rep["port_median_rel"][2] is None and rep["n_valid_samples"][2] == 0
    assert rep["port_max_freqmedian_rel"][2] is None
    assert rep["n_ports_defined"] == Q - 1 and "definition" in rep
    assert rep["max_of_port_max_freqmedian"] is not None
    assert json.loads(text)["worst_port"] == d["worst_port"]
    classes = {n + 1: ("io" if n < 2 else "pixel") for n in range(Q)}
    by = mod.drift_by_class(d, classes)
    assert by["io"]["n"] == 2 and by["pixel"]["n"] == Q - 2
    assert by["pixel"]["n_defined"] == Q - 3  # 端口 3 无效
    assert by["io"]["median_of_port_median"] < 1.0e-12
    assert by["io"]["max_of_port_max_freqmedian"] < 1.0e-12
    assert by["pixel"]["worst_port"] in range(3, Q + 1)
    json.dumps(by, allow_nan=False)


def _write_cache(out_dir: Path, mod, uf: np.ndarray, if_: np.ndarray) -> np.ndarray:
    out_dir.mkdir(parents=True, exist_ok=True)
    freqs = mod._analysis_freqs()
    np.savez_compressed(out_dir / "raw_ui.npz", freq_hz=freqs, uf_all=uf, if_all=if_)
    return freqs


def test_load_raw_ui_reuses_cache_and_rejects_shape_mismatch(tmp_path):
    mod = _stage2_module()
    uf, if_ = _synth_ui(_true_s())
    freqs = _write_cache(tmp_path, mod, uf, if_)
    assert freqs.size == mod.N_FREQ_POINTS
    # 频轴不符（缓存 nf=3 vs 分析轴 41）→ 走重读 → 缺档显式报错
    with pytest.raises(RuntimeError):
        mod.load_raw_ui(tmp_path / "rounds", tmp_path, Q, freqs)
    # 形状/频轴一致 → 复用
    uf41 = np.repeat(uf[:, :, :1], freqs.size, axis=2)
    if41 = np.repeat(if_[:, :, :1], freqs.size, axis=2)
    _write_cache(tmp_path, mod, uf41, if41)
    got_u, got_i, meta = mod.load_raw_ui(tmp_path / "rounds", tmp_path, Q, freqs)
    assert meta == {"cache": str(tmp_path / "raw_ui.npz")}
    assert np.array_equal(got_u, uf41) and np.array_equal(got_i, if41)
    with pytest.raises(RuntimeError):
        mod.load_raw_ui(tmp_path / "rounds", tmp_path, Q, freqs, fresh=True)


def test_reassemble_and_drift_subcommand_report_cross_round_drift(tmp_path, monkeypatch):
    """q=150 合成轮不变档（缓存直读，不触任何 rounds/）：reassemble 报告含
    cross_round_drift（≈0）且四阶段仍在；drift 子命令落 drift_report.json 含逐类汇总。"""
    mod = _stage2_module()
    layout = mod.build_layout()
    q = layout.n_ports
    freqs = mod._analysis_freqs()
    mesh = fake_mesh(q)
    s1 = z_to_s(mesh.z_all(float(freqs[0]))[None], reference_impedance=Z0)
    s = np.repeat(s1, freqs.size, axis=0)  # 单频 S 铺满 41 点（轮不变性与频无关）
    uf, if_ = _synth_ui(s)
    _write_cache(tmp_path, mod, uf, if_)
    args = argparse.Namespace(rounds_dir=str(tmp_path / "no_rounds"), s5_out=str(tmp_path),
                              fresh=False, numerator="current", no_gain_cal=True,
                              gauge=None, no_project=True)
    assert mod.stage_reassemble(args) == 0
    rep = json.loads((tmp_path / "reassemble_report.json").read_text(encoding="utf-8"))
    drift = rep["cross_round_drift"]
    assert drift["n_ports"] == q and drift["n_ports_defined"] == q
    assert drift["max_of_port_max"] < 1.0e-10
    assert set(rep["stages"]) == {"S1_current", "S3_sym"}
    assert (tmp_path / "z_all_s5.npz").exists()
    # 缺省 caliber="raw"（Namespace 未带 caliber）→ 报告零新增键（现状逐字节不变）
    assert "caliber" not in rep and "caliber_gate" not in rep
    # drift 子命令（经 main 走 argparse）
    monkeypatch.setattr(mod.sys, "argv", ["mapes_s2_zall.py", "drift", "--s5-out", str(tmp_path),
                                          "--rounds-dir", str(tmp_path / "no_rounds")])
    assert mod.main() == 0
    drep = json.loads((tmp_path / "drift_report.json").read_text(encoding="utf-8"))
    assert drep["drift"]["max_of_port_max"] < 1.0e-10
    by = drep["by_class"]
    assert set(by) == {"io", "pixel", "pixel_h", "pixel_v", "diag_main", "diag_anti", "via_ground"}
    assert by["io"]["n"] == 2 and by["pixel"]["n"] == 36 and by["via_ground"]["n"] == 2
    assert all(v["n_defined"] == v["n"] for v in by.values())

# ------------------------------------------------------------------------- #
# stage-5c：激励口参考面重定标（SREF 探针链自提取）
# ------------------------------------------------------------------------- #

def _synth_probe_case(
    q: int = 6, nf: int = 9, *, with_m: bool = False, seed: int = 11,
):
    """合成与真机 150 轮同构的 u/i 原始档：互易真网络 + 已知逐口探针误差。

    误差模型与 stage-5c docstring 同口径：接收口集总律 u_t=−z0·i_t、激励口
    inc_t=E、ref_t=Γ·E；u=e^a·u_t、i=e^b·i_t、a=m+Δ/2、b=m−Δ/2、
    Δ_p(f)=c_p+j·2πf·τ_p（复常数 + 纯延时）。真网络
    T_ik(f)=c_ik·exp(−j2πf·d_ik)（c/d 对称 → 逐频严格互易）。
    """
    rng = np.random.default_rng(seed)
    freqs = np.linspace(1.0e9, 6.0e9, nf)
    w = 2.0 * np.pi * freqs
    cu = np.triu(rng.uniform(0.05, 0.9, (q, q)), k=1)
    cmat = cu + cu.T
    np.fill_diagonal(cmat, rng.uniform(0.3, 0.8, q))
    du = np.triu(rng.uniform(-2.0e-10, 2.0e-10, (q, q)), k=1)
    dmat = du + du.T
    np.fill_diagonal(dmat, rng.uniform(-1.0e-10, 1.0e-10, q))
    tm = cmat[None, :, :] * np.exp(-1j * w[:, None, None] * dmat[None, :, :])
    for f in range(nf):  # 缩到无源域内（σmax≤0.95），非本测试判定项
        smax = float(np.linalg.norm(tm[f], ord=2))
        if smax > 0.95:
            tm[f] *= 0.95 / smax
    tau_p = rng.uniform(-0.5e-12, 0.5e-12, q)
    c_p = rng.uniform(-0.02, 0.02, q) + 1j * rng.uniform(-0.05, 0.05, q)
    delta_p = c_p[None, :] + 1j * w[:, None] * tau_p[None, :]
    if with_m:
        m_p = (rng.uniform(-0.01, 0.01, q)
               + 1j * rng.uniform(-0.03, 0.03, q))[None, :] + np.zeros((nf, 1))
    else:
        m_p = np.zeros((nf, q))
    a_p = m_p + delta_p / 2.0
    b_p = m_p - delta_p / 2.0
    e_exc = 1.0 + 0.5j * np.sin(w / 1e9)  # 激励幅度逐频非平凡
    uf = np.empty((q, q, nf), dtype=complex)
    imf = np.empty((q, q, nf), dtype=complex)
    for k in range(q):
        for p in range(q):
            if p == k:
                ut = e_exc * (1.0 + tm[:, k, k])
                it = e_exc * (1.0 - tm[:, k, k]) / Z0
            else:
                ut = e_exc * tm[:, p, k]
                it = -ut / Z0
            uf[k, p] = np.exp(a_p[:, p]) * ut
            imf[k, p] = np.exp(b_p[:, p]) * it
    return {
        "freqs": freqs, "uf": uf, "if": imf, "T": tm,
        "delta": delta_p, "tau": tau_p, "c_const": c_p, "m": m_p,
    }


def test_termination_delta_recovers_synthetic_pair_error():
    """合成已知 Δ 注入 → 端接律提取逐位回收（含退化样本路径与异常校验）。"""
    from rfauto.core.mapes import termination_delta

    case = _synth_probe_case()
    delta, info = termination_delta(case["uf"], case["if"], reference_impedance=Z0)
    assert info["n_no_valid"] == 0
    assert info["n_rounds_used_median"] == case["uf"].shape[0] - 1
    np.testing.assert_allclose(delta, case["delta"], rtol=0, atol=1e-12)
    # snr 门极高 → 全部样本被剔：Δ=0 中性 + n_no_valid 如实计数
    d2, info2 = termination_delta(case["uf"], case["if"], snr_min=1e9)
    assert info2["n_no_valid"] == case["delta"].size
    assert np.all(d2 == 0)
    with pytest.raises(ConfigError):
        termination_delta(case["uf"], case["if"][:, :5, :])
    with pytest.raises(ConfigError):
        termination_delta(case["uf"], case["if"], reference_impedance=-1.0)


def test_delay_model_delta_recovers_tau():
    """合成纯延时 Δ → 3 参数模型回收 τ/常数项，Im 线性 R²≈1。"""
    from rfauto.core.mapes import delay_model_delta

    case = _synth_probe_case(nf=15)
    dhat, info = delay_model_delta(case["delta"], case["freqs"])
    np.testing.assert_allclose(info["tau_s"], case["tau"], rtol=0, atol=1e-18)
    np.testing.assert_allclose(info["im_const"], case["c_const"].imag,
                               rtol=0, atol=1e-12)
    np.testing.assert_allclose(info["re_const"], case["c_const"].real,
                               rtol=0, atol=1e-12)
    assert info["r2_imag_linear_median"] > 1.0 - 1e-9
    assert info["resid_max"] < 1e-10
    np.testing.assert_allclose(dhat, case["delta"], rtol=0, atol=1e-9)
    with pytest.raises(ConfigError):
        delay_model_delta(case["delta"], case["freqs"][:-1])


def test_sref_recal_recovers_reciprocity_synthetic():
    """合成固定相位/复增益底注入 → 已辨识差分修正回收互易（m=0 精确）。

    current 口径的已辨识修正 = 列 C_k（激励口）× 行 exp(+Δ_i/2)（接收口，
    **仅非对角条目**——对角分子是波分解不载电流探针误差）。逐口常数 Δ
    （合成即此）时非对角精确回收真网络；对角另走模型反演
    Γ̂=(Ŝ·ch−sh)/(ch−Ŝ·sh)。m≠0 时共模规范原理性不可辨识 → 残留恰为
    m 差分项，改善但**不精确归零**（如实口径，不凑绿）。
    """
    from rfauto.core.mapes import (
        apply_sref_recal,
        assemble_s_from_ui,
        sref_column_factors,
        z_all_gate,
    )

    case = _synth_probe_case()
    uf, imf = case["uf"], case["if"]
    s_cur = assemble_s_from_ui(uf, imf, reference_impedance=Z0, numerator="current")
    raw = z_all_gate(s_cur)
    assert raw["reciprocity_max"] > 5.0e-3  # 底已注入且可观测
    diag = np.diagonal(s_cur, axis1=1, axis2=2)
    fixed = apply_sref_recal(s_cur, sref_column_factors(case["delta"], diag))
    off = ~np.eye(case["uf"].shape[0], dtype=bool)
    fixed = fixed * np.where(off[None], np.exp(case["delta"] / 2.0)[:, :, None], 1.0)
    got = z_all_gate(fixed)
    assert got["reciprocity_max"] < 1.0e-10
    # 非对角逐位回收真网络；对角走模型反演回收真 Γ
    np.testing.assert_allclose(fixed[:, off], case["T"][:, off], rtol=0, atol=1e-9)
    sh, chh = np.sinh(case["delta"] / 2.0), np.cosh(case["delta"] / 2.0)
    gam = (diag * chh - sh) / (chh - diag * sh)
    np.testing.assert_allclose(
        gam, np.diagonal(case["T"], axis1=1, axis2=2), rtol=0, atol=1e-10)
    # wave 口径 + 列因子：行侧残留 cosh(Δ/2)≈1+Δ²/8 → 大幅改善但不精确
    s_wav = assemble_s_from_ui(uf, imf, reference_impedance=Z0, numerator="wave")
    fixed_wav = apply_sref_recal(s_wav, sref_column_factors(
        case["delta"], np.diagonal(s_wav, axis1=1, axis2=2)))
    got_wav = z_all_gate(fixed_wav)
    assert got_wav["reciprocity_max"] < raw["reciprocity_max"] / 20.0
    assert 1e-8 < got_wav["reciprocity_max"] < 1e-2
    # m≠0：残留非零（不可辨识部分如实保留，只要求严格改善）
    case_m = _synth_probe_case(with_m=True)
    s_cur_m = assemble_s_from_ui(case_m["uf"], case_m["if"], reference_impedance=Z0)
    col_m = sref_column_factors(case_m["delta"],
                                np.diagonal(s_cur_m, axis1=1, axis2=2))
    fixed_m = apply_sref_recal(s_cur_m, col_m)
    fixed_m = fixed_m * np.where(
        off[None], np.exp(case_m["delta"] / 2.0)[:, :, None], 1.0)
    got_m = z_all_gate(fixed_m)
    assert got_m["reciprocity_max"] < z_all_gate(s_cur_m)["reciprocity_max"]
    assert got_m["reciprocity_max"] > 1e-8


def test_assemble_sref_recal_optin_matches_apply_and_default_unchanged():
    """装配链 opt-in 参数与 apply_sref_recal 同效；缺省 None 行为逐位不变。"""
    from rfauto.core.mapes import apply_sref_recal, assemble_s_from_ui

    case = _synth_probe_case(q=5, nf=4)
    uf, imf = case["uf"], case["if"]
    base = assemble_s_from_ui(uf, imf, reference_impedance=Z0)
    assert np.array_equal(base, assemble_s_from_ui(
        uf, imf, reference_impedance=Z0, sref_recal=None))
    col = np.exp(0.01 * np.arange(base.shape[0])[:, None]
                 + 1j * 0.02 * np.ones((1, base.shape[1])))
    via_param = assemble_s_from_ui(uf, imf, reference_impedance=Z0, sref_recal=col)
    np.testing.assert_array_equal(via_param, apply_sref_recal(base, col))
    for bad in (np.ones((3, 3)), col[:-1],
                np.full((base.shape[0], base.shape[1]), np.nan)):
        with pytest.raises(ConfigError):
            assemble_s_from_ui(uf, imf, reference_impedance=Z0, sref_recal=bad)
        with pytest.raises(ConfigError):
            apply_sref_recal(base, bad)


def test_refix150_sref_recal_regression_pin():
    """150 轮真机档回归钉（runs/mapes_zall_refix；无档机器 skip 不算绿）。

    钉死三组数（与 runs/mapes_sref_study/evidence.json 同源）：current/wave
    基线与 runs/mapes_zall_refix/verdict.json 逐位一致；wav+colC 修正上限
    0.0070774（≤5e-3 目标未达，钉 2.06× 改善与上限值本身；7.0892e-3 系被弃用
    一阶捷径值，断言实钉 SREF 全链复算值）；wave≡current
    恒等式（逐样本精确去 Δ）。
    """
    from rfauto.core.mapes import (
        apply_sref_recal,
        assemble_s_from_ui,
        sref_column_factors,
        termination_delta,
        z_all_gate,
    )

    raw_npz = REPO / "runs" / "mapes_zall_refix" / "s5_diag" / "raw_ui.npz"
    if not raw_npz.exists():
        pytest.skip("真机档 runs/mapes_zall_refix/s5_diag/raw_ui.npz 不在本机")
    with np.load(raw_npz) as data:
        uf = np.asarray(data["uf_all"], dtype=complex)
        imf = np.asarray(data["if_all"], dtype=complex)
    s_cur = assemble_s_from_ui(uf, imf, reference_impedance=Z0, numerator="current")
    s_wav = assemble_s_from_ui(uf, imf, reference_impedance=Z0, numerator="wave")
    assert z_all_gate(s_cur)["reciprocity_max"] == pytest.approx(
        0.014603526405276387, rel=1e-9)
    assert z_all_gate(s_wav)["reciprocity_max"] == pytest.approx(
        0.00896490993934581, rel=1e-9)
    # 恒等式：num_wav = num_cur + inc^meas（逐样本精确）
    ident = np.max(np.abs(0.5 * (uf - Z0 * imf)
                          - (-Z0 * imf + 0.5 * (uf + Z0 * imf))))
    assert ident <= 1e-20
    delta, info = termination_delta(uf, imf, reference_impedance=Z0)
    assert info["n_no_valid"] == 0 and info["n_ports"] == 150
    col = sref_column_factors(delta, np.diagonal(s_wav, axis1=1, axis2=2))
    got = z_all_gate(apply_sref_recal(s_wav, col))
    assert got["reciprocity_max"] == pytest.approx(0.0070773704118137, rel=1e-6)
    assert got["reciprocity_max"] < z_all_gate(s_cur)["reciprocity_max"] / 2.0


# ------------------------------------------------------------------------- #
# stage-5c+：互易判读口径显式消费（S2 数值口径；2026-09-19 定案：
# τ 口径不纳入消费挂起，S2 做成 raw/wave 并列第三档）
# ------------------------------------------------------------------------- #

def test_caliber_gate_default_raw_unchanged_and_wave_matches():
    """三档缺省钉：缺省/显式 raw 门指标与 z_all_gate(原始装配) 逐位一致，
    wave 档同理；verdict 恒带 caliber 出处字段且为纯 JSON 标量。"""
    import json as _json

    from rfauto.core.mapes import (
        RECIPROCITY_TARGET_STAGE5C,
        assemble_s_from_ui,
        z_all_gate,
        z_all_gate_caliber,
    )

    case = _synth_probe_case(q=5, nf=4)
    uf, imf = case["uf"], case["if"]
    ref_cur = z_all_gate(assemble_s_from_ui(uf, imf, reference_impedance=Z0))
    ref_wav = z_all_gate(assemble_s_from_ui(
        uf, imf, reference_impedance=Z0, numerator="wave"))
    for v in (z_all_gate_caliber(uf, imf, reference_impedance=Z0),
              z_all_gate_caliber(uf, imf, reference_impedance=Z0, caliber="raw")):
        assert v["caliber"] == "raw" and v["caliber_circular"] is False
        assert {k: v[k] for k in ref_cur} == ref_cur  # 门指标逐位一致（缺省不变）
        assert v["reciprocity_target"] == RECIPROCITY_TARGET_STAGE5C == 5.0e-3
        assert v["reciprocity_target_met"] == (v["reciprocity_max"] <= 5.0e-3)
    v_wav = z_all_gate_caliber(uf, imf, reference_impedance=Z0, caliber="wave")
    assert v_wav["caliber"] == "wave" and v_wav["caliber_circular"] is False
    assert {k: v_wav[k] for k in ref_wav} == ref_wav
    _json.dumps(v_wav, allow_nan=False)  # verdict 纯 JSON 标量，可直接落盘


def test_caliber_gate_s2_consumes_gain_fit_and_absorbs_gauge():
    """s2 档消费路径：纯逐口规范底（含不可辨识 m 规范）被互易势场循环口径
    吸收 → rec→求解器噪声级（这正是"循环"的含义）；门指标与对 S2 矩阵
    直接 z_all_gate 的手工链逐位一致（消费的就是该矩阵）。"""
    from rfauto.core.mapes import (
        apply_port_gain,
        apply_sref_recal,
        assemble_s_from_ui,
        fit_reciprocity_gain,
        sref_column_factors,
        termination_delta,
        z_all_gate,
        z_all_gate_caliber,
    )

    case = _synth_probe_case(with_m=True)
    uf, imf = case["uf"], case["if"]
    raw = z_all_gate(assemble_s_from_ui(uf, imf, reference_impedance=Z0))
    assert raw["reciprocity_max"] > 5.0e-3  # 底已注入且可观测
    v = z_all_gate_caliber(uf, imf, reference_impedance=Z0, caliber="s2")
    assert v["caliber"] == "s2" and v["caliber_circular"] is True
    assert "gain_fit" in v and "delta_info" in v
    assert v["gain_fit"]["fit_resid_wrms_median"] < 1.0e-6  # 纯势场底无旋度
    assert v["delta_info"]["n_no_valid"] == 0
    assert v["reciprocity_max"] < 1.0e-6  # 循环口径精确吸收（raw > 5e-3 对照）
    assert v["reciprocity_target_met"] is True
    assert v["pass_reciprocity"] is True  # 合成档连预声明 1e-3 门同过
    # 手工链复现：verdict 门指标 == 对 S2 矩阵直接 z_all_gate（逐位）
    s_wav = assemble_s_from_ui(uf, imf, reference_impedance=Z0, numerator="wave")
    delta, _ = termination_delta(uf, imf, reference_impedance=Z0)
    col = sref_column_factors(delta, np.diagonal(s_wav, axis1=1, axis2=2))
    s_base = apply_sref_recal(s_wav, col)
    x, _ = fit_reciprocity_gain(s_base)
    ref = z_all_gate(apply_port_gain(s_base, x), reference_impedance=Z0)
    assert {k: v[k] for k in ref} == ref


def test_caliber_gate_rejects_unknown_and_suspended_tau_caliber():
    """未知量径显式报错；τ 延迟模型口径按 2026-09-19 定案挂起——
    不在枚举内（RECIPROCITY_CALIBERS 恰为 raw/wave/s2 三档）。"""
    from rfauto.core.mapes import RECIPROCITY_CALIBERS, z_all_gate_caliber

    assert RECIPROCITY_CALIBERS == ("raw", "wave", "s2")
    case = _synth_probe_case(q=4, nf=3)
    uf, imf = case["uf"], case["if"]
    for bad in ("tau", "delay", "current", "S2", "", None):
        with pytest.raises(ConfigError):
            z_all_gate_caliber(uf, imf, caliber=bad)


def test_refix150_caliber_gate_regression_pin():
    """150 轮真机档三档口径钉（无档机器 skip，不算绿；与
    runs/mapes_sref_study/evidence.json 同源）：raw 1.460e-2 / wave 8.965e-3
    均超 ≤5e-3 目标，s2（wav+colC→互易势场）3.2722e-3 达标——S2 数值口径
    消费使互易判读可用达标档（2026-09-19 定案）。"""
    from rfauto.core.mapes import z_all_gate_caliber

    raw_npz = REPO / "runs" / "mapes_zall_refix" / "s5_diag" / "raw_ui.npz"
    if not raw_npz.exists():
        pytest.skip("真机档 runs/mapes_zall_refix/s5_diag/raw_ui.npz 不在本机")
    with np.load(raw_npz) as data:
        uf = np.asarray(data["uf_all"], dtype=complex)
        imf = np.asarray(data["if_all"], dtype=complex)
    v_raw = z_all_gate_caliber(uf, imf, caliber="raw")
    v_wav = z_all_gate_caliber(uf, imf, caliber="wave")
    v_s2 = z_all_gate_caliber(uf, imf, caliber="s2")
    assert v_raw["reciprocity_max"] == pytest.approx(0.014603526405276387, rel=1e-9)
    assert v_wav["reciprocity_max"] == pytest.approx(0.00896490993934581, rel=1e-9)
    assert v_s2["reciprocity_max"] == pytest.approx(0.0032721506007460125, rel=1e-9)
    assert v_raw["reciprocity_target_met"] is False
    assert v_wav["reciprocity_target_met"] is False
    assert v_s2["reciprocity_target_met"] is True
    assert (v_s2["reciprocity_max"] < v_wav["reciprocity_max"]
            < v_raw["reciprocity_max"])
    assert v_s2["caliber"] == "s2" and v_s2["caliber_circular"] is True


def test_reassemble_caliber_option_and_s2_matrix_persisted(tmp_path):
    """reassemble --caliber 显式消费：报告增 caliber/caliber_gate、npz 顺带
    落盘 S2 矩阵（管线 S2_gain_cal + 消费口径矩阵）；缺省路径零新增键由
    test_reassemble_and_drift_subcommand_report_cross_round_drift 钉。"""
    mod = _stage2_module()
    layout = mod.build_layout()
    q = layout.n_ports
    freqs = mod._analysis_freqs()
    mesh = fake_mesh(q)
    s1 = z_to_s(mesh.z_all(float(freqs[0]))[None], reference_impedance=Z0)
    s = np.repeat(s1, freqs.size, axis=0)  # 单频 S 铺满 41 点（轮不变性）
    uf, if_ = _synth_ui(s)
    _write_cache(tmp_path, mod, uf, if_)
    args = argparse.Namespace(rounds_dir=str(tmp_path / "no_rounds"),
                              s5_out=str(tmp_path), fresh=False, numerator="wave",
                              no_gain_cal=False, gauge=None, no_project=True,
                              caliber="s2")
    assert mod.stage_reassemble(args) == 0
    rep = json.loads((tmp_path / "reassemble_report.json").read_text(encoding="utf-8"))
    assert rep["caliber"] == "s2"
    cg = rep["caliber_gate"]
    assert cg["caliber"] == "s2" and cg["caliber_circular"] is True
    assert cg["reciprocity_target_met"] is True  # 合成干净档，s2 消费路径全净
    assert cg["pass"] is True
    with np.load(tmp_path / "z_all_s5.npz") as data:
        assert "s2_gain_cal" in data  # 管线 S2_gain_cal 阶段矩阵顺带落盘
        assert "s_caliber_matrix" in data  # 消费口径矩阵落盘
        assert data["s2_gain_cal"].shape == (freqs.size, q, q)
        assert data["s_caliber_matrix"].shape == (freqs.size, q, q)
