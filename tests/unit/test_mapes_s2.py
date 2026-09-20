"""A8 MAPES stage-2 定向单元测试（确定性、离线、零真机依赖）。

覆盖文件面：
1. ``core/mapes.s_to_z``：与 :func:`z_to_s` 往返一致性（stage-2 装配入口
   的代数正确性）+ 单口解析锚；
2. ``core/mapes.z_all_quality``：互易/无源/条件数诊断对合成好/坏矩阵的
   判别（好=RLC 网格 Z；坏=非对称/负阻）；
3. ``core/mapes.pixel_board_geom``：端口数/编号顺序、竖直口贴片落位与
   互不重叠、缝隙口跨缝、I/O 馈线贴边界、非法布局显式报错；
4. ``scripts/mapes_s2_zall``：渲染脚本接线（参考模式 Q 口单激励/图案模式
   无虚拟口+金属短路体）、逐轮断点缓存语义（monkeypatch 子进程，零真机）。

阈值依据（本文件断言）：s_to_z↔z_to_s 往返为纯线性代数，随机 Hermitian
批矩阵实测 ~1e-14 量级，断言 1e-10；RLC 网格 Z 互由构造保证（对称实部
Hermitian），断言 reciprocity_rel ≤ 1e-12（stage-1 实测 8.95e-16 同量级）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.errors import ConfigError
from rfauto.core.mapes import (
    CATEGORY_DIAG_ANTI,
    CATEGORY_DIAG_MAIN,
    CATEGORY_PIXEL,
    CATEGORY_PIXEL_H,
    CATEGORY_PIXEL_V,
    VIA_GROUND,
    PixelLayout,
    fake_mesh,
    pixel_board_geom,
    s_to_z,
    z_all_quality,
    z_to_s,
)

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "mapes_s2_zall.py"
Z0 = 50.0
FREQ_HZ = np.array([1.0e9, 3.5e9, 6.0e9])


def _stage2_layout() -> PixelLayout:
    return PixelLayout(6, 6, 1, 2, ((0, 5, VIA_GROUND), (5, 0, VIA_GROUND)))


def _stage2_module():
    spec = importlib.util.spec_from_file_location("mapes_s2_zall", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── 1. s_to_z：代数正确性 ────────────────────────────────────────────────

def test_s_to_z_roundtrip_against_z_to_s_batch():
    rng = np.random.default_rng(20260913)
    z = rng.normal(size=(5, 6, 6)) + 1j * rng.normal(size=(5, 6, 6))
    z = 0.5 * (z + np.swapaxes(z, -1, -2))  # Hermitian 化（物理 Z 形态）
    s = z_to_s(z, reference_impedance=Z0)
    z_back = s_to_z(s, reference_impedance=Z0)
    assert np.max(np.abs(z_back - z)) <= 1.0e-10


def test_s_to_z_roundtrip_single_matrix():
    rng = np.random.default_rng(7)
    z = rng.normal(size=(4, 4)) + 1j * rng.normal(size=(4, 4))
    z = 0.5 * (z + z.T)
    assert np.max(np.abs(s_to_z(z_to_s(z, reference_impedance=Z0),
                                reference_impedance=Z0) - z)) <= 1.0e-10


def test_s_to_z_single_port_analytic_anchor():
    s_val = 0.3 + 0.2j
    z = s_to_z(np.array([[s_val]]), reference_impedance=Z0)
    expect = Z0 * (1.0 + s_val) / (1.0 - s_val)
    assert abs(z[0, 0] - expect) <= 1.0e-12 * (1.0 + abs(expect))


def test_s_to_z_rejects_bad_shape_and_reference():
    with pytest.raises(ConfigError):
        s_to_z(np.zeros((3, 4), dtype=complex))
    with pytest.raises(ConfigError):
        s_to_z(np.eye(2, dtype=complex), reference_impedance=-1.0)


# ─── 2. z_all_quality：好/坏判别 ──────────────────────────────────────────

def _rlc_z_all() -> np.ndarray:
    mesh = fake_mesh(10)
    return np.stack([mesh.z_all(float(f)) for f in FREQ_HZ])


def test_z_all_quality_on_passive_reciprocal_rlc_mesh():
    q = z_all_quality(_rlc_z_all(), n_io=2)
    assert q["n_freq"] == len(FREQ_HZ) and q["n_ports"] == 10
    assert q["passive"] is True
    assert q["reciprocity_max_rel"] <= 1.0e-12
    assert q["min_eig_re_min"] >= -1.0e-12
    assert q["cond_z22_max"] < 1.0e12  # 良态（数值健康）


def test_z_all_quality_flags_nonreciprocal():
    z = _rlc_z_all()
    z_bad = z.copy()
    z_bad[:, 0, 5] += 5.0 * np.max(np.abs(z), axis=(1, 2))
    q = z_all_quality(z_bad, n_io=2)
    assert q["reciprocity_max_rel"] > 1.0e-3


def test_z_all_quality_flags_active_device():
    z = _rlc_z_all()
    scale = np.max(np.abs(z[0]))
    z_active = z.copy()
    for k in range(len(z)):  # 对角注入负实部（有源器件），逐频同尺度
        re_part = z_active[k].real.copy()
        np.fill_diagonal(re_part, re_part.diagonal() - 2.0 * scale)
        z_active[k] = re_part + 1j * z_active[k].imag
    q = z_all_quality(z_active, n_io=2)
    assert q["passive"] is False
    assert q["min_eig_re_min"] < 0.0


def test_z_all_quality_input_validation():
    with pytest.raises(ConfigError):
        z_all_quality(np.eye(4, dtype=complex), n_io=4)  # 必须留虚拟端口
    with pytest.raises(ConfigError):
        z_all_quality(np.zeros((3, 4), dtype=complex), n_io=1)


# ─── 3. pixel_board_geom：装配几何 ────────────────────────────────────────

def test_geom_port_count_and_numbering_order():
    layout = _stage2_layout()
    geom = pixel_board_geom(layout)
    assert len(geom.ports) == layout.n_ports == 150
    assert geom.ports[0].label == "io1" and geom.ports[1].label == "io2"
    for idx in range(layout.n_load_ports):
        port = geom.ports[2 + idx]
        assert port.number == idx + 3
        assert port.slot_index == idx
    kinds = {"lumped_v", "lumped_gap"}
    assert {p.kind for p in geom.ports} == kinds
    assert geom.ports[0].kind == "lumped_v"  # io 口与虚拟口同机械
    for idx, slot in enumerate(layout.load_slots()):
        expect_kind = "lumped_gap" if slot.category in (
            CATEGORY_PIXEL_H, CATEGORY_PIXEL_V) else "lumped_v"
        assert geom.ports[2 + idx].kind == expect_kind


def test_geom_vertical_ports_sit_on_assigned_patches_without_overlap():
    layout = _stage2_layout()
    geom = pixel_board_geom(layout)
    n = layout.n_cols
    patch_of: dict[int, int] = {}
    for idx, slot in enumerate(layout.load_slots()):
        r, c = slot.row, slot.col
        if slot.category in (CATEGORY_PIXEL, CATEGORY_DIAG_MAIN, VIA_GROUND):
            patch_of[idx] = r * n + c
        elif slot.category == CATEGORY_DIAG_ANTI:
            patch_of[idx] = (r + 1) * n + (c + 1)
        elif slot.category == VIA_GROUND:
            patch_of[idx] = r * n + c
    by_patch: dict[int, list] = {}
    for idx, p_idx in patch_of.items():
        port = geom.ports[2 + idx]
        assert port.kind == "lumped_v"
        assert port.start[2] == 0.0 and port.stop[2] == pytest.approx(
            geom.sub_h_m)
        px0, py0, px1, py1 = geom.patches[p_idx]
        assert px0 < port.start[0] < port.stop[0] < px1
        assert py0 < port.start[1] < port.stop[1] < py1
        by_patch.setdefault(p_idx, []).append(port)
    for p_idx, ports in by_patch.items():
        for i in range(len(ports)):
            for j in range(i + 1, len(ports)):
                a, b = ports[i], ports[j]
                sep_x = max(a.start[0], b.start[0]) - min(a.stop[0], b.stop[0])
                sep_y = max(a.start[1], b.start[1]) - min(a.stop[1], b.stop[1])
                assert sep_x > 0.0 or sep_y > 0.0, (
                    f"patch {p_idx} 端口盒重叠: {a.label} vs {b.label}")


def test_geom_gap_ports_span_inter_patch_gaps():
    layout = _stage2_layout()
    geom = pixel_board_geom(layout)
    slots = layout.load_slots()
    p = geom.pitch_m
    a, g = geom.cell_m, geom.gap_m
    for idx, slot in enumerate(slots):
        port = geom.ports[2 + idx]
        if slot.category == CATEGORY_PIXEL_H:
            expect_x0 = slot.col * p + a
            assert port.start[0] == pytest.approx(expect_x0)
            assert port.stop[0] == pytest.approx(expect_x0 + g)
            assert port.stop[1] - port.start[1] > 0.0  # 跨缝轴 = x
        elif slot.category == CATEGORY_PIXEL_V:
            expect_y0 = slot.row * p + a
            assert port.start[1] == pytest.approx(expect_y0)
            assert port.stop[1] == pytest.approx(expect_y0 + g)
            # 横截面（x 向）为有限宽度盒，跨度小于贴片
            assert 0.0 < port.stop[0] - port.start[0] < a
        else:
            continue
        assert port.kind == "lumped_gap"
        assert port.start[2] == pytest.approx(geom.sub_h_m / 2.0)
        # 缝隙口盒不得压到任何贴片
        for px0, py0, px1, py1 in geom.patches:
            ox = min(port.stop[0], px1) - max(port.start[0], px0)
            oy = min(port.stop[1], py1) - max(port.start[1], py0)
            assert not (ox > 0.0 and oy > 0.0), f"{slot.label} 压贴片"


def test_geom_io_ports_on_corner_patches_without_crowding():
    layout = _stage2_layout()
    geom = pixel_board_geom(layout)
    n = layout.n_cols
    a = geom.cell_m
    io1, io2 = geom.ports[0], geom.ports[1]
    # io1 = 贴片 (0,0) 的 (a/4, a/2)；io2 = 贴片 (M-1,N-1) 的 (a/2, a/4)
    assert io1.start[:2] == pytest.approx((a / 4 - 0.1e-3, a / 2 - 0.15e-3))
    assert io2.start[:2] == pytest.approx(
        (5 * geom.pitch_m + a / 2 - 0.1e-3, 5 * geom.pitch_m + a / 4 - 0.15e-3))
    for io in (io1, io2):
        assert io.kind == "lumped_v" and io.slot_index == -1
        assert io.start[2] == 0.0 and io.stop[2] == pytest.approx(geom.sub_h_m)
    # 角贴片上全部竖直口两两不重叠（含 io 口与像素/对角/过孔口）
    for p_idx in (0, 5 * n + 5, 5, 5 * n):
        px0, py0, px1, py1 = geom.patches[p_idx]
        ports = [p for p in geom.ports
                 if p.kind == "lumped_v" and px0 <= p.start[0] and p.stop[0] <= px1
                 and py0 <= p.start[1] and p.stop[1] <= py1]
        assert len(ports) >= 2
        for i in range(len(ports)):
            for j in range(i + 1, len(ports)):
                a_, b_ = ports[i], ports[j]
                sep_x = max(a_.start[0], b_.start[0]) - min(a_.stop[0], b_.stop[0])
                sep_y = max(a_.start[1], b_.start[1]) - min(a_.stop[1], b_.stop[1])
                assert sep_x > 0.0 or sep_y > 0.0, (
                    f"patch {p_idx} 端口盒重叠: {a_.label} vs {b_.label}")


def test_geom_rejects_multilayer_and_interlayer_vias():
    with pytest.raises(ConfigError):
        pixel_board_geom(PixelLayout(2, 2, 2, 2))
    with pytest.raises(ConfigError):
        pixel_board_geom(PixelLayout(2, 2, 1, 2, ((0, 0, "via_interlayer"),)))


# ─── 4. 渲染脚本接线（离线）────────────────────────────────────────────────

def test_render_reference_mode_wiring():
    mod = _stage2_module()
    layout = _stage2_layout()
    geom = mod.build_geom(layout)
    text = mod.render_round_script(geom, excite_port=3, virtual_ports=True)
    assert text.count("excite=1") == 1  # 单激励
    assert text.count("LumpedPort(CSX") == layout.n_ports
    assert "MSLPort(" not in text.replace("from openEMS.ports import", "")
    assert text.count("pixels.AddBox(") == layout.n_rows * layout.n_cols
    assert "PML_8" in text and '"PEC"' in text
    assert "SetLines(_ax" in text  # #152 近重合线守卫
    assert "cleanup=True" in text
    for num in range(1, layout.n_ports + 1):
        assert f"port_nr={num}," in text
    # exc_dir 逐类钉死（回归：三元链优先级写反曾把全部竖直口置成 x 向）
    slots = layout.load_slots()
    assert "port_nr=1, R=50.0" in text
    assert "exc_dir='z'" in text

    def port_line(num):
        lines = text.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith(f"_port{num} ="))
        return "\n".join(lines[i:i + 4])  # 语句含 3 行续行

    h_idx = next(i for i, s in enumerate(slots)
                 if s.category == CATEGORY_PIXEL_H)
    v_idx = next(i for i, s in enumerate(slots)
                 if s.category == CATEGORY_PIXEL_V)
    dm_idx = next(i for i, s in enumerate(slots)
                  if s.category == CATEGORY_DIAG_MAIN)
    assert port_line(h_idx + 3).count("exc_dir='x'") == 1
    assert port_line(v_idx + 3).count("exc_dir='y'") == 1
    assert port_line(dm_idx + 3).count("exc_dir='z'") == 1
    assert port_line(1).count("exc_dir='z'") == 1
    assert port_line(2).count("exc_dir='z'") == 1


def test_render_pattern_mode_no_virtual_ports_and_shorts():
    mod = _stage2_module()
    layout = _stage2_layout()
    geom = mod.build_geom(layout)
    pattern = np.zeros((6, 6), dtype=bool)
    pattern[2, 3] = True
    loads = np.full(layout.n_load_ports, np.inf)
    loads[layout.slot_occupancy(pattern, np.zeros(2, dtype=int))] = 0.0
    short_numbers = tuple(int(i) + 3 for i in np.flatnonzero(np.isfinite(loads)))
    assert short_numbers == (18,)  # pixel 槽 (2,3) = 槽 15（行主序 2*6+3），端口号 18
    text = mod.render_round_script(
        geom, excite_port=1, virtual_ports=False,
        short_numbers=short_numbers)
    # 图案结构：无任何虚拟口元件，仅 io1/io2 两个探针口
    assert text.count("LumpedPort(CSX") == 2
    assert f"port_nr={3}," not in text
    assert text.count("shorts.AddBox(") == 1
    assert text.count("excite=1") == 1
    text_e2 = mod.render_round_script(
        geom, excite_port=2, virtual_ports=False,
        short_numbers=short_numbers)
    assert text_e2 != text and text_e2.count("excite=1") == 1


def test_round_resume_reuses_matching_script_and_csv(monkeypatch, tmp_path):
    mod = _stage2_module()
    layout = _stage2_layout()
    geom = mod.build_geom(layout)
    script = mod.render_round_script(geom, excite_port=1, virtual_ports=False)
    work = tmp_path / "p1"
    work.mkdir()
    (work / "simulation.py").write_text(script, encoding="utf-8")
    freqs = np.linspace(1e9, 6e9, 5)
    rows = [["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"]]
    rng = np.random.default_rng(3)
    for f in freqs:
        s1 = complex(rng.normal(), rng.normal())
        s2 = complex(rng.normal(), rng.normal())
        rows.append([repr(float(f)), repr(s1.real), repr(s1.imag),
                     repr(s2.real), repr(s2.imag)])
    csv_path = work / "sparams.csv"
    csv_path.write_text("\n".join(",".join(r) for r in rows) + "\n",
                        encoding="utf-8")
    fh, cols, elapsed, resumed = mod._run_round(work, script, 2, resume=True)
    assert resumed and elapsed == 0.0
    assert np.allclose(fh, freqs)
    assert cols[0].shape == (5,) and cols[1].shape == (5,)

    called = {}

    def fake_run(cmd, **kw):  # 脚本不一致 → 必须走子进程（此处 mock）
        called["cmd"] = cmd
        (work / "sparams.csv").write_text(
            "\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")

        class P:
            returncode = 0
            stderr = ""

        return P()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    modified = script.replace("PML_8", "PML_8", 1) + "\n# touched\n"
    mod._run_round(work, modified, 2, resume=True)
    assert "cmd" in called  # 断点校验失败 → 真的重跑了


# ─── 5. gamma 子命令：任一轮时域档 → 逐口端接质量（合成档，零真机）────────

def _write_ui_dump(dir_path: Path, number: int, tu: np.ndarray, u_t: np.ndarray,
                   ti: np.ndarray, i_t: np.ndarray) -> None:
    """按 openEMS 探针文本格式落档（% 注释头 + 两列）；u/i 各带自己的时间轴。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    np.savetxt(dir_path / f"port_ut_{number}", np.column_stack([tu, u_t]),
               header="t/s\tvoltage", comments="% ", fmt="%.12g")
    np.savetxt(dir_path / f"port_it_{number}", np.column_stack([ti, i_t]),
               header="t/s\tcurrent", comments="% ", fmt="%.12g")


def _ui_from_freq(freq_hz: float, uf: complex, if_: complex, n: int = 4096):
    """单音合成：让各自时间轴上的 DFT 在 freq_hz 频箱处恰等于 (uf, if_)。

    t_k = k·dt、e^{-j2πf·t_k} 恰走整数圈（dt=1/(N·f)）；复振幅经
    F = N·dt·A·e^{jφ} 反解：u(t)=Re(Ũ e^{j2πft})、Ũ = uf/(N·dt)。
    电流轴按引擎口径错半步（ti = tu + dt/2），信号在各自轴上取值。
    """
    dt = 1.0 / (n * freq_hz)
    tu = np.arange(n) * dt
    ti = tu + 0.5 * dt
    scale = 1.0 / (n * dt)
    u_t = np.real((uf * scale) * np.exp(2j * np.pi * freq_hz * tu))
    i_t = np.real((if_ * scale) * np.exp(2j * np.pi * freq_hz * ti))
    return tu, u_t, ti, i_t


def test_gamma_summary_reports_synthetic_termination_quality(tmp_path):
    mod = _stage2_module()
    layout = _stage2_layout()
    geom = mod.build_geom(layout)
    fdtd = tmp_path / "fdtd"
    f_bin = 3.5e9
    freqs = np.array([f_bin])
    rng = np.random.default_rng(5)
    for port in geom.ports:
        n = port.number
        if n == 1:  # 激励口：已知 Γ=0.5 → u_tot=1.5、i_tot=0.5/Z0
            sig = _ui_from_freq(f_bin, 1.5 + 0j, 0.5 / Z0)
        elif n in (3, 39, 100, 149):  # 匹配口（出射约定 U=−Z0·I）→ term_err=0
            b = 0.7 - 0.2j
            sig = _ui_from_freq(f_bin, -Z0 * b, b)
        elif n in (4, 40, 150):  # 近开路口：Z_ui ≈ −1e5·Z0 → term_err ≫ tol
            b = 1e-3 * (1 + 0j)
            sig = _ui_from_freq(f_bin, -1e5 * Z0 * b, b)
        else:  # 其余口：中等偏差（Z_ui=−60Ω）→ term_err=0.2 > tol
            b = rng.uniform(0.2, 1.0) * (1 + 1j)
            sig = _ui_from_freq(f_bin, -60.0 * b, b)
        _write_ui_dump(fdtd, n, *sig)
    rep = mod.summarize_round_gamma(
        tmp_path, geom, freq_hz=freqs, excite_port=1, z0=Z0, tol=0.05)
    import json
    json.dumps(rep)  # JSON 友好（落盘合同）
    assert rep["n_ports_read"] == layout.n_ports and rep["missing_ports"] == []
    assert rep["excite_port"] == 1
    assert rep["ports"]["1"]["excited"] and rep["ports"]["1"]["matched"] is None
    assert rep["ports"]["1"]["gamma_max_abs"] == pytest.approx(0.5, abs=1e-9)
    for k in ("3", "39", "100", "149"):
        entry = rep["ports"][k]
        assert entry["matched"] is True
        assert entry["term_err_max"] == pytest.approx(0.0, abs=1e-9)
    for k in ("4", "40", "150"):
        assert rep["ports"][k]["matched"] is False
        assert rep["ports"][k]["term_err_max"] > 100.0
    for k in ("5", "41", "101"):
        entry = rep["ports"][k]
        assert entry["matched"] is False
        assert entry["term_err_max"] == pytest.approx(0.2, abs=1e-6)
    assert rep["all_non_excited_matched"] is False
    assert rep["non_excited_term_err_max"] > 100.0
    # 激励口尾段指标：纯单音 RMS/峰值 = 1/√2 → −3.01dB（合成档不衰减，如实非 decayed）
    assert rep["excited_ut_tail_rms_db"] == pytest.approx(-3.0103, abs=0.01)
    assert rep["excited_ut_tail_decayed"] is False


def test_gamma_reader_and_edge_cases(tmp_path):
    mod = _stage2_module()
    layout = _stage2_layout()
    geom = mod.build_geom(layout)
    # 缺档 → None + 汇总 missing
    rep = mod.summarize_round_gamma(
        tmp_path, geom, freq_hz=np.array([3.5e9]), excite_port=1)
    assert rep["n_ports_read"] == 0
    assert len(rep["missing_ports"]) == layout.n_ports
    # 读档往返：t/u/i 逐值一致（含 u/i 时间轴错半步的引擎口径）
    tu0, u_t, ti0, i_t = _ui_from_freq(3.5e9, 1.0 + 0j, 0.02 + 0j)
    _write_ui_dump(tmp_path / "fdtd", 1, tu0, u_t, ti0, i_t)
    got = mod.read_port_ui_dump(tmp_path / "fdtd", 1)
    assert got is not None
    (tu, u), (ti, i), _ = got
    assert tu.shape == u_t.shape and ti.shape == i_t.shape
    assert np.allclose(tu, tu0) and np.allclose(ti, ti0)
    assert np.allclose(u, u_t, atol=1e-9)
    assert np.allclose(i, i_t, atol=1e-9)
    # 端口类别映射：io 两个 + via 两个，逐槽类别可检索
    classes = mod.port_classes(geom)
    assert classes[1] == "io" and classes[2] == "io"
    assert sum(1 for v in classes.values() if v == "via_ground") == 2
    assert classes[3] == CATEGORY_PIXEL and classes[39] == CATEGORY_PIXEL_H
    assert classes[100] == CATEGORY_DIAG_MAIN


def test_geom_default_edge_pad_keeps_ports_out_of_pml():
    """回归钉：stage-4 域扩——默认横向空气垫 6mm > PML_8 厚度(~4.8mm@0.6mm
    网格)，任何端口/贴片不再落入 PML 区（外圈口端接失效的真根因）。"""
    mod = _stage2_module()
    geom = mod.build_geom()
    assert geom.edge_pad_m == pytest.approx(6.0e-3)
    dom = geom.domain
    xs = [p[0] for p in geom.patches] + [p[2] for p in geom.patches]
    ys = [p[1] for p in geom.patches] + [p[3] for p in geom.patches]
    assert min(xs) - dom[0] >= 6.0e-3 - 1e-12
    assert dom[2] - max(xs) >= 6.0e-3 - 1e-12
    assert min(ys) - dom[1] >= 6.0e-3 - 1e-12
    assert dom[3] - max(ys) >= 6.0e-3 - 1e-12
    # 覆盖入参仍可用（敏感性冒烟/未来扫描面）
    geom1 = mod.build_geom(edge_pad_mm=1.0)
    assert geom1.edge_pad_m == pytest.approx(1.0e-3)
