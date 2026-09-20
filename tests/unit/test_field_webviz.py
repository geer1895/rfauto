"""G9 场可视化 3D + Smith 圆图单测（§10.7 G9 余量；D4 联动）。

确定性、零网络、零真机（真机证据独立于测试：runs/nf2ff_smoke_*/fdtd 的
DumpHDF5/CalcNF2FF 产物 2026-09-15 离线审计，本文件的合成 HDF5 逐字段
复刻该契约）：
- 内核（infra.visualization）：DumpHDF5 三变体读取（TD 矢量 NXYZ / FD 复
  矢量 / FD 标量 XYZ）、|E| 时域包络、轴对齐切片、等值面（PyVista 有则
  三角网，无则 matplotlib 等值线降级且 engine 如实）、CalcNF2FF h5 方向图、
  Smith 圆图几何（Γ→Z、恒 r/x 圆闭式）；
- 服务层（ui_service.field_runs/field_view/smith_view/smith_external）：
  tmp runs 隔离（#144），D4 指标/远场 3D 联动，best-effort 不阻塞（#105）；
- UI 路由薄壳契约 + 前端静态契约 + extras 纪律（pyproject viz3d、
  check_env_deps 映射）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

h5py = pytest.importorskip("h5py")

from rfauto.infra import visualization as V

# ─── 合成 DumpHDF5（契约复刻真机产物）────────────────────────────────────────

X_MM = np.linspace(-20.0, 20.0, 21)
Y_MM = np.linspace(-10.0, 10.0, 11)
Z_MM = np.linspace(-6.0, 6.0, 7)


def _blob(x_mm: np.ndarray, y_mm: np.ndarray, z_mm: np.ndarray, sigma_mm: float = 8.0) -> np.ndarray:
    """各向同性高斯团（峰值 1 在原点）：解析等值面为球面 r = σ·sqrt(-2 ln L)。"""
    X, Y, Z = np.meshgrid(x_mm, y_mm, z_mm, indexing="ij")
    return np.exp(-(X**2 + Y**2 + Z**2) / (2.0 * sigma_mm**2))


def _write_mesh(h, x_mm, y_mm, z_mm) -> None:
    m = h.create_group("Mesh")
    m.attrs["mesh_scaling"] = np.float64(1.0)
    m.attrs["mesh_type"] = np.int32(0)
    for name, arr in (("x", x_mm), ("y", y_mm), ("z", z_mm)):
        m.create_dataset(name, data=np.asarray(arr, dtype=float) * 1e-3)  # 米制


def write_fd_vector_dump(path: Path, field: np.ndarray, x_mm=X_MM, y_mm=Y_MM, z_mm=Z_MM) -> Path:
    """dump_type 29 形态：FieldData/FD/f0 (3,nx,ny,nz) complex64，d_order NXYZ。"""
    with h5py.File(path, "w") as h:
        h.attrs["dump_type"] = np.int32(29)
        h.attrs["dual_mesh"] = np.uint8(1)
        h.attrs["openEMS_HDF5_version"] = np.float64(0.3)
        _write_mesh(h, x_mm, y_mm, z_mm)
        vec = np.zeros((3, *field.shape), dtype=np.complex64)
        vec[0] = field * 0.6            # Ex 实
        vec[1] = 1j * field * 0.8       # Ey 虚 → |E| = field（0.36+0.64=1）
        ds = h.create_dataset("FieldData/FD/f0", data=vec)
        ds.attrs["d_order"] = "NXYZ"
    return path


def write_td_vector_dump(path: Path, frames: list[np.ndarray], x_mm=X_MM, y_mm=Y_MM, z_mm=Z_MM) -> Path:
    """dump_type 0 形态：FieldData/TD/<step> (3,nx,ny,nz) float32，逐步 attrs.time。"""
    with h5py.File(path, "w") as h:
        h.attrs["dump_type"] = np.int32(0)
        h.attrs["dual_mesh"] = np.uint8(0)
        _write_mesh(h, x_mm, y_mm, z_mm)
        for k, fr in enumerate(frames):
            vec = np.zeros((3, *fr.shape), dtype=np.float32)
            vec[2] = fr  # 纯 Ez
            ds = h.create_dataset(f"FieldData/TD/{k * 39:08d}", data=vec)
            ds.attrs["d_order"] = "NXYZ"
            ds.attrs["time"] = np.array([k * 1e-11], dtype=np.float32)
    return path


def write_fd_scalar_dump(path: Path, field: np.ndarray, freq_hz: float = 2.5e9,
                         x_mm=X_MM, y_mm=Y_MM, z_mm=Z_MM) -> Path:
    """SAR_1g.h5 形态：FieldData/FD/f0 (nx,ny,nz) float32，d_order XYZ，attrs.frequency。"""
    with h5py.File(path, "w") as h:
        h.attrs["openEMS_HDF5_version"] = np.float64(0.3)
        _write_mesh(h, x_mm, y_mm, z_mm)
        ds = h.create_dataset("FieldData/FD/f0", data=field.astype(np.float32))
        ds.attrs["d_order"] = "XYZ"
        ds.attrs["frequency"] = np.float64(freq_hz)
    return path


def write_nf2ff_h5(path: Path, theta_deg: np.ndarray, phi_deg: np.ndarray,
                   e_theta: np.ndarray, dmax_lin: float = 1.642, f_hz: float = 2.45e9) -> Path:
    """CalcNF2FF 原生产物形态：Mesh/theta|phi 弧度；E_*/FD/f0_real|imag 形状 (n_phi, n_theta)。"""
    with h5py.File(path, "w") as h:
        m = h.create_group("Mesh")
        m.attrs["MeshType"] = np.array([2.0], dtype=np.float32)
        m.create_dataset("theta", data=np.deg2rad(theta_deg).astype(np.float32))
        m.create_dataset("phi", data=np.deg2rad(phi_deg).astype(np.float32))
        m.create_dataset("r", data=np.array([1.0], dtype=np.float32))
        nf = h.create_group("nf2ff")
        nf.attrs["Dmax"] = np.array([dmax_lin])
        nf.attrs["Frequency"] = np.array([f_hz], dtype=np.float32)
        nf.attrs["Prad"] = np.array([1e-3])
        nf.create_dataset("E_theta/FD/f0_real", data=e_theta.real)
        nf.create_dataset("E_theta/FD/f0_imag", data=e_theta.imag)
        nf.create_dataset("E_phi/FD/f0_real", data=np.zeros_like(e_theta.real))
        nf.create_dataset("E_phi/FD/f0_imag", data=np.zeros_like(e_theta.real))
        nf.create_dataset("P_rad/FD/f0", data=np.abs(e_theta) ** 2)
    return path


@pytest.fixture()
def blob():
    return _blob(X_MM, Y_MM, Z_MM)


# ─── 内核：DumpHDF5 读取 ─────────────────────────────────────────────────────

class TestReadFieldDump:
    def test_fd_vector_magnitude_and_axes(self, tmp_path, blob):
        vol = V.read_field_dump(write_fd_vector_dump(tmp_path / "SAR_raw.h5", blob))
        assert vol.shape == (21, 11, 7) and vol.domain == "fd" and vol.dump_type == 29
        np.testing.assert_allclose(vol.magnitude, blob, rtol=1e-6, atol=1e-7)  # |0.6+0.8j|·f = f
        np.testing.assert_allclose(vol.x_m * 1e3, X_MM)
        assert vol.peak == pytest.approx(1.0) and vol.frequency_hz is None

    def test_td_envelope_is_max_over_time(self, tmp_path, blob):
        frames = [0.3 * blob, -1.0 * blob, 0.5 * blob]  # 峰值出现在第二帧且为负
        vol = V.read_field_dump(write_td_vector_dump(tmp_path / "nf2ff_E_0.h5", frames))
        assert vol.domain == "td_envelope" and vol.n_timesteps == 3 and vol.dump_type == 0
        np.testing.assert_allclose(vol.magnitude, blob, rtol=1e-6)

    def test_fd_scalar_keeps_frequency(self, tmp_path, blob):
        vol = V.read_field_dump(write_fd_scalar_dump(tmp_path / "SAR_1g.h5", blob * 3e-25))
        assert vol.domain == "fd_scalar" and vol.dump_type is None
        assert vol.frequency_hz == pytest.approx(2.5e9)
        assert vol.peak == pytest.approx(3e-25, rel=1e-6)

    def test_face_dump_degenerate_axis(self, tmp_path):
        face = _blob(np.array([-20.0]), Y_MM, Z_MM)
        vol = V.read_field_dump(write_td_vector_dump(tmp_path / "f.h5", [face], x_mm=np.array([-20.0])))
        assert vol.shape == (1, 11, 7)

    def test_layout_mismatch_raises(self, tmp_path, blob):
        p = write_fd_vector_dump(tmp_path / "bad.h5", blob)
        with h5py.File(p, "a") as h:
            del h["Mesh/z"]
            h["Mesh"].create_dataset("z", data=np.zeros(3))
        with pytest.raises(ValueError, match="不符"):
            V.read_field_dump(p)
        with h5py.File(tmp_path / "nofd.h5", "w") as h:
            _write_mesh(h, X_MM, Y_MM, Z_MM)
            h.create_group("FieldData")
        with pytest.raises(ValueError, match="既无 FD 也无 TD"):
            V.read_field_dump(tmp_path / "nofd.h5")


# ─── 内核：切片 / 等值面 / 远场 h5 ──────────────────────────────────────────

class TestSlicesAndIso:
    def test_db_normalisation_clamps_and_json_safe(self):
        db = V.field_db(np.array([1.0, 0.1, 0.0, np.nan]))
        assert db.tolist() == pytest.approx([0.0, -20.0, V.FIELD_DB_FLOOR, V.FIELD_DB_FLOOR])
        assert np.all(V.field_db(np.zeros(3)) == V.FIELD_DB_FLOOR)  # 全零场不炸

    def test_mid_plane_slices_geometry(self, tmp_path, blob):
        vol = V.read_field_dump(write_fd_vector_dump(tmp_path / "d.h5", blob))
        sl = {s["axis"]: s for s in V.field_slices(vol)}
        assert set(sl) == {"x", "y", "z"}
        zs = sl["z"]
        assert zs["index"] == 3 and zs["position_mm"] == 0.0 and zs["n"] == 7
        assert (zs["u_axis"], zs["v_axis"]) == ("x", "y")
        vals = np.asarray(zs["values"])
        assert vals.shape == (11, 21)                 # [v][u] = [y][x]
        assert vals[5, 10] == pytest.approx(0.0)      # 原点 = 峰 = 0 dB
        # 解析核对：x=20mm,y=0 处 dB = 20log10(exp(-400/128))
        assert vals[5, 20] == pytest.approx(20 * np.log10(np.exp(-400.0 / 128.0)), abs=2e-3)
        assert zs["unit"] == "dB_rel_peak"
        json.dumps(sl)

    def test_slice_index_clamped_and_linear_sigfig(self, tmp_path, blob):
        vol = V.read_field_dump(write_fd_scalar_dump(tmp_path / "s.h5", blob * 1e-25))
        s = V.field_slices(vol, indices={"x": 999, "y": -5}, axes=("x", "y"), db=False)
        assert [q["index"] for q in s] == [20, 0]
        assert s[0]["unit"] == "linear"
        assert np.asarray(s[0]["values"]).max() > 0.0  # 1e-25 量级不被舍成 0
        with pytest.raises(ValueError, match="未知切片轴"):
            V.field_slices(vol, axes=("q",))

    def test_numpy_contour_fallback_matches_analytic_radius(self, tmp_path):
        x = np.linspace(-20, 20, 81)
        y = np.linspace(-20, 20, 81)
        z = np.linspace(-20, 20, 41)
        vol = V.read_field_dump(write_fd_vector_dump(tmp_path / "g.h5", _blob(x, y, z), x, y, z))
        iso = V.field_isosurface(vol, levels_db=(-6.0,), engine="numpy")
        assert iso["ok"] and iso["engine"] == "numpy_contour"
        assert iso["levels_db"] == [-6.0]
        zc = next(c for c in iso["contours"] if c["axis"] == "z")
        assert zc["position_mm"] == 0.0 and zc["segments"]
        # 中面 z=0 上等值线 = 圆 r = σ·sqrt(-2 ln(10^(-6/20)))
        r_ana = 8.0 * np.sqrt(-2.0 * np.log(10 ** (-6.0 / 20.0)))
        pts = np.vstack([np.asarray(s["points"]) for s in zc["segments"]])
        r = np.hypot(pts[:, 0], pts[:, 1])
        assert np.abs(r - r_ana).max() < 0.15  # 网格 0.5mm，线性插值误差远小于此
        json.dumps(iso)

    def test_engine_pyvista_on_face_dump_is_honest(self, tmp_path):
        face = _blob(np.array([0.0]), Y_MM, Z_MM)
        vol = V.read_field_dump(write_td_vector_dump(tmp_path / "f.h5", [face], x_mm=np.array([0.0])))
        r = V.field_isosurface(vol, engine="pyvista")
        assert r["ok"] is False and "无体积" in r["errors"][0]
        auto = V.field_isosurface(vol)  # auto → 面 dump 走等值线
        assert auto["ok"] and auto["engine"] == "numpy_contour"
        assert [c["axis"] for c in auto["contours"]] == ["x"]  # 仅整面有 ≥2×2 网格
        assert V.field_isosurface(vol, engine="nope")["ok"] is False

    def test_pyvista_isosurface_lies_on_analytic_sphere(self, tmp_path):
        pytest.importorskip("pyvista")
        x = np.linspace(-20, 20, 41)
        y = np.linspace(-20, 20, 41)
        z = np.linspace(-20, 20, 41)
        vol = V.read_field_dump(write_fd_vector_dump(tmp_path / "g.h5", _blob(x, y, z), x, y, z))
        iso = V.field_isosurface(vol, levels_db=(-6.0,), engine="pyvista")
        assert iso["ok"] and iso["engine"] == "pyvista" and iso["n_faces"] > 100
        v = np.asarray(iso["vertices_mm"])
        r = np.linalg.norm(v, axis=1)
        r_ana = 8.0 * np.sqrt(-2.0 * np.log(10 ** (-6.0 / 20.0)))
        # 顶点落在解析球面上 ⇒ Fortran 展平的 (x,y,z) 点序映射正确（乱序会散到全域）
        assert np.abs(r - r_ana).max() < 0.3
        assert np.asarray(iso["vertex_db"]).min() == pytest.approx(-6.0, abs=0.01)
        assert max(max(f) for f in iso["faces"]) < iso["n_vertices"]
        json.dumps(iso)

    def test_viz3d_available_is_probe_only(self):
        assert isinstance(V.viz3d_available(), bool)


class TestFarfieldPatternH5:
    def test_pattern_db_shape_and_dmax(self, tmp_path):
        theta = np.arange(0.0, 181.0, 5.0)
        phi = np.arange(0.0, 360.0, 10.0)
        TH, _ = np.meshgrid(np.deg2rad(theta), np.deg2rad(phi))  # (n_phi, n_theta)
        e = (np.sin(TH) + 1e-6).astype(complex)                     # 偶极型：θ=90° 峰
        p = V.farfield_pattern_from_h5(write_nf2ff_h5(tmp_path / "farfield_3d.h5", theta, phi, e))
        db = np.asarray(p["db"])
        assert db.shape == (theta.size, phi.size)               # theta 行 × phi 列（同 nf2ff_service）
        assert p["theta_deg"][18] == pytest.approx(90.0) and db[18].max() == pytest.approx(0.0)
        assert db[0].max() < -60.0 or db[0].max() == V.FIELD_DB_FLOOR  # θ=0 零点被钳
        assert p["dmax_dbi"] == pytest.approx(10 * np.log10(1.642), abs=1e-3)  # Balanis 半波偶极子锚
        assert p["frequency_ghz"] == pytest.approx(2.45)
        # 图形自归一交叉值（W2⑥a）：F=sinθ → D=4π/∫sin²θdΩ=1.5（1.761 dBi），
        # 与 Dmax 属性（面通量归一）独立；sin²θ 上下半球对称 → 比值 1
        assert p["dmax_pattern_dbi"] == pytest.approx(10 * np.log10(1.5), abs=0.02)
        assert p["lower_upper_power_ratio"] == pytest.approx(1.0, abs=1e-6)
        json.dumps(p)

    def test_cut_file_two_phi_planes_gives_no_pattern_dmax(self, tmp_path):
        theta = np.arange(-180.0, 181.0, 1.0)
        phi = np.array([0.0, 90.0])
        e = np.tile(np.abs(np.sin(np.deg2rad(theta)))[None, :] + 1e-6, (2, 1)).astype(complex)
        p = V.farfield_pattern_from_h5(write_nf2ff_h5(tmp_path / "nf2ff.h5", theta, phi, e))
        assert p["dmax_dbi"] == pytest.approx(10 * np.log10(1.642), abs=1e-3)
        assert p["dmax_pattern_dbi"] is None and p["dmax_pattern_upper_dbi"] is None

    def test_not_nf2ff_file_raises(self, tmp_path, blob):
        with pytest.raises(ValueError, match="CalcNF2FF"):
            V.farfield_pattern_from_h5(write_fd_vector_dump(tmp_path / "d.h5", blob))


# ─── 内核：Smith 圆图几何 ───────────────────────────────────────────────────

class TestSmithKernel:
    def test_gamma_to_impedance_closed_form(self):
        f = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        g = np.array([0.0, -1.0, 1.0, 1.0 / 3.0, 0.5j])
        sm = V.smith_chart_data(f, g, z0=50.0)
        assert sm["z_re_ohm"][:4] == [50.0, 0.0, None, 100.0]      # 匹配 / 短路 / 开路 / 2Z0
        assert sm["z_im_ohm"][2] is None
        z = 50.0 * (1 + 0.5j) / (1 - 0.5j)                           # 纯电抗 Γ=j/2 → 30+j40
        assert sm["z_re_ohm"][4] == pytest.approx(z.real, abs=1e-3)
        assert sm["z_im_ohm"][4] == pytest.approx(z.imag, abs=1e-3)
        assert sm["mag"] == pytest.approx([0.0, 1.0, 1.0, 1 / 3, 0.5], abs=1e-6)
        assert sm["n_points"] == 5 and "grid" in sm

    def test_grid_circles_pozar_closed_form(self):
        g = V.smith_grid()
        r1 = next(c for c in g["r_circles"] if c["r"] == 1.0)
        assert r1["center"] == [0.5, 0.0] and r1["radius"] == 0.5
        pts = np.asarray(r1["points"])
        assert np.abs(np.hypot(pts[:, 0] - 0.5, pts[:, 1]) - 0.5).max() < 1e-4
        x1 = next(a for a in g["x_arcs"] if a["x"] == 1.0)
        assert x1["center"] == [1.0, 1.0] and x1["radius"] == 1.0
        arc = np.asarray(x1["points"])
        assert np.all(np.hypot(arc[:, 0], arc[:, 1]) <= 1.0 + 1e-6)     # 裁剪到单位圆内
        assert 40 <= len(arc) <= 50                                       # x=1 弧 ≈ 1/4 圆周
        assert np.abs(np.diff(arc, axis=0)).max() < 0.1                   # 连续弧，无跨越断口
        xm = next(a for a in g["x_arcs"] if a["x"] == -1.0)
        assert xm["center"] == [1.0, -1.0]
        assert np.asarray(g["unit_circle"])[0].tolist() == [1.0, 0.0]

    def test_decimation_and_length_guard(self):
        n = 5001
        f = np.linspace(1, 3, n)
        sm = V.smith_chart_data(f, np.full(n, 0.2 + 0.1j), max_points=500, with_grid=False)
        assert sm["n_points"] <= 500 and sm["freq_ghz"][0] == 1.0 and sm["freq_ghz"][-1] == 3.0
        with pytest.raises(ValueError, match="长度不符"):
            V.smith_chart_data(f[:3], np.zeros(2))


# ─── 服务层 + UI 路由 ────────────────────────────────────────────────────────

RUN_ID = "20260915_000000_g9demo"
_S2P = """# GHz S RI R 50
1.0  0.5 0.0  0.7 0.0  0.7 0.0  -0.5 0.0
2.0  0.0 0.5  0.7 0.0  0.7 0.0  0.0 -0.5
3.0  0.0 0.0  0.7 0.0  0.7 0.0  0.0 0.0
"""


def _make_field_run(root: Path, run_id: str = RUN_ID, with_farfield: bool = True) -> Path:
    """真跑落盘层级复刻：fdtd/ 下 dump + farfield_3d.h5 + nf2ff.h5；根下 farfield_meta.json。"""
    run = root / "runs" / run_id
    fdtd = run / "fdtd"
    fdtd.mkdir(parents=True, exist_ok=True)
    blob = _blob(X_MM, Y_MM, Z_MM)
    write_fd_vector_dump(fdtd / "SAR_raw.h5", blob)
    write_fd_scalar_dump(fdtd / "SAR_1g.h5", blob * 1e-25)
    write_td_vector_dump(fdtd / "nf2ff_E_0.h5", [_blob(np.array([-20.0]), Y_MM, Z_MM)],
                         x_mm=np.array([-20.0]))
    if with_farfield:
        theta = np.arange(0.0, 181.0, 5.0)
        phi = np.arange(0.0, 360.0, 10.0)
        TH, _ = np.meshgrid(np.deg2rad(theta), np.deg2rad(phi))
        write_nf2ff_h5(fdtd / "farfield_3d.h5", theta, phi, (np.sin(TH) + 1e-6).astype(complex))
        write_nf2ff_h5(fdtd / "nf2ff.h5", theta, np.array([0.0, 90.0]),
                       (np.sin(np.deg2rad(theta))[None, :] + 1e-6).astype(complex))
        (run / "farfield_meta.json").write_text(json.dumps({
            "ok": True, "template": "patch", "f_res_ghz": 2.45, "dmax_dbi": 6.5,
            "gain_max_dbi": 5.9, "efficiency": 0.87, "power_budget_closure": 0.02,
        }), encoding="utf-8")
    return run


@pytest.fixture()
def field_run(tmp_path, monkeypatch):
    from rfauto.service import ui_service

    monkeypatch.chdir(tmp_path)
    _make_field_run(tmp_path)
    monkeypatch.setattr(ui_service, "RUNS_DIR", tmp_path / "runs")
    return RUN_ID


class TestFieldService:
    def test_field_runs_lists_dumps_volume_first(self, field_run, tmp_path):
        from rfauto.service.ui_service import field_runs

        (tmp_path / "runs" / "20260915_000001_nodump" / "results").mkdir(parents=True)
        out = field_runs()
        assert out["ok"] and [r["run_id"] for r in out["runs"]] == [field_run]
        r = out["runs"][0]
        assert r["dumps"] == ["SAR_1g.h5", "SAR_raw.h5", "nf2ff_E_0.h5"]  # 体 dump 先于盒面 dump
        assert r["n_dumps"] == 3 and r["has_farfield_h5"] is True
        assert isinstance(out["viz3d_available"], bool)

    def test_field_view_full_payload_with_d4_linkage(self, field_run):
        from rfauto.service.ui_service import field_view

        v = field_view(field_run, dump="SAR_raw.h5", engine="numpy", levels_db=(-6.0, -12.0),
                       slice_index={"z": 1})
        assert v["ok"] and v["selected"] == "SAR_raw.h5" and v["engine"] == "numpy_contour"
        assert v["volume"]["shape"] == [21, 11, 7] and v["volume"]["domain"] == "fd"
        assert v["volume"]["x_mm"] == [-20.0, 20.0]
        zs = next(s for s in v["slices"] if s["axis"] == "z")
        assert zs["index"] == 1 and zs["position_mm"] == pytest.approx(-4.0)
        assert v["isosurface"]["levels_db"] == [-12.0, -6.0]
        # D4 联动：远场 3D 图（h5）+ meta 指标 + 极坐标页链接
        assert v["pattern3d"]["dmax_dbi"] == pytest.approx(10 * np.log10(1.642), abs=1e-3)
        assert len(v["pattern3d"]["theta_deg"]) == 37 and len(v["pattern3d"]["phi_deg"]) == 36
        fm = v["farfield_metrics"]
        assert {k: fm[k] for k in ("f_res_ghz", "dmax_dbi", "gain_max_dbi", "efficiency",
                                    "power_budget_closure", "template")} == {
            "f_res_ghz": 2.45, "dmax_dbi": 6.5, "gain_max_dbi": 5.9, "efficiency": 0.87,
            "power_budget_closure": 0.02, "template": "patch"}
        # 盒坐标缺失 → 镜像因子不猜测（k=1，原值不动、无 raw）；η 0.87 > 0.79 触伪象上沿
        assert fm["pec_mirror_factor"] == 1.0 and "raw" not in fm
        assert fm["eta_gate"]["ok"] is False and "超上沿" in fm["eta_gate"]["reason"]
        assert fm["eta_gate"]["gate"] == [0.55, 0.79] and fm["eta_gate"]["value"] == 0.87
        assert v["polar_link"] == f"/api/farfield/{field_run}"
        assert v["warnings"] == []
        json.dumps(v)

    def test_field_view_defaults_and_td_dump(self, field_run):
        from rfauto.service.ui_service import field_view

        v = field_view(field_run)
        assert v["selected"] == "SAR_1g.h5" and v["volume"]["frequency_ghz"] == pytest.approx(2.5)
        assert v["engine"] in ("pyvista", "numpy_contour")  # 有 PyVista 则三角网，否则降级
        td = field_view(field_run, dump="nf2ff_E_0.h5")
        assert td["ok"] and td["volume"]["domain"] == "td_envelope" and td["volume"]["n_timesteps"] == 1
        assert td["volume"]["shape"] == [1, 11, 7] and td["isosurface"]["engine"] == "numpy_contour"

    def test_field_view_errors_and_best_effort(self, field_run, tmp_path, monkeypatch):
        from rfauto.service import ui_service

        assert ui_service.field_view("nope")["ok"] is False
        bad = ui_service.field_view(field_run, dump="zzz.h5")
        assert bad["ok"] is False and "可选" in bad["errors"][0]
        # 无远场产物的 run：切片仍可用，pattern3d/metrics 如实 None（#105）
        _make_field_run(tmp_path, "20260915_000002_nff", with_farfield=False)
        v = ui_service.field_view("20260915_000002_nff")
        assert v["ok"] and v["pattern3d"] is None and v["farfield_metrics"] is None
        # 等值面内核抛错 → warning 记账，切片主视图不受影响
        monkeypatch.setattr(V, "field_isosurface", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("vtk boom")))
        v = ui_service.field_view(field_run)
        assert v["ok"] and v["isosurface"]["ok"] is False and any("vtk boom" in w for w in v["warnings"])
        # 无 dump 的 run 明确报错
        (tmp_path / "runs" / "20260915_000003_empty" / "results").mkdir(parents=True)
        assert ui_service.field_view("20260915_000003_empty")["ok"] is False


# ─── 场页远场指标：PEC 镜像修正接线 + patch 族 η 门复议（#249）────────────────
#
# 两份 meta 逐字段复刻真机 runs/ 产物（数字出自判读 json，测试不读 runs/）：
# * 收敛轮 runs/patch_field_smoke_recheck/farfield_meta.json（盒底 z=0 贴 PEC 地）；
# * 全包盒 runs/nf2ff_smoke_ff_dipole/farfield_meta.json（z_start<0，不受镜像影响）。

_RECHECK_META = {
    "ok": True, "template": "patch", "f_res_ghz": 2.212, "freq_band_ghz": [2.0, 2.8],
    "prad_w": 1.2537515654378738e-25, "p_acc_w": 1.0976310123470231e-25,
    "dmax_linear": 2.246764146157283, "dmax_dbi": 3.515574847918346,
    "efficiency": 1.1422340944585958, "gain_max_dbi": 4.09312604037014,
    "power_budget_closure": 0.14223409445859586,
    "nf2ff_box_start_m": [-0.08230535679866299, -0.08230535679866299, 0.0],
    "nf2ff_box_stop_m": [0.08230535679866299, 0.08230535679866299, 0.041027642512948714],
    "radius_m": 1.0,
}
_DIPOLE_META = {
    "ok": True, "template": "dipole", "f_res_ghz": 2.30625, "freq_band_ghz": [2.25, 2.75],
    "prad_w": 3.474200079521432e-27, "p_acc_w": 3.5080921634384726e-27,
    "dmax_linear": 2.058556805692693, "dmax_dbi": 3.1356285581661654,
    "efficiency": 0.9903388844026775, "gain_max_dbi": 3.0934668722444343,
    "power_budget_closure": 0.009661115597322543,
    "nf2ff_box_start_m": [-0.07927272727272727, -0.07927272727272727, -0.01927272727272727],
    "nf2ff_box_stop_m": [0.07927272727272727, 0.07927272727272727, 0.01927272727272727],
    "radius_m": 1.0,
}


def _make_meta_run(root: Path, run_id: str, meta: dict) -> str:
    run = _make_field_run(root, run_id, with_farfield=False)
    (run / "farfield_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return run_id


class TestFieldViewMirrorAndEtaGate:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        from rfauto.service import ui_service

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(ui_service, "RUNS_DIR", tmp_path / "runs")
        self.root = tmp_path

    def test_patch_metrics_use_same_kernel_as_nf2ff_service(self):
        """贴地盒 patch：η/2、Dmax+3.01dB、增益不变、raw 留痕；与 nf2ff_service 逐键一致。"""
        from rfauto.service import nf2ff_service, ui_service

        rid = _make_meta_run(self.root, "20260917_000010_patch", _RECHECK_META)
        fm = ui_service.field_view(rid)["farfield_metrics"]
        assert fm["pec_mirror_factor"] == 2.0 and fm["template"] == "patch"
        assert fm["efficiency"] == pytest.approx(0.5711170472292979, abs=1e-9)   # 1.1422/2
        assert fm["dmax_dbi"] == pytest.approx(6.525874804558159, abs=1e-9)       # +3.0103
        assert fm["gain_max_dbi"] == pytest.approx(4.09312604037014, abs=1e-9)    # 镜像不变量
        assert fm["power_budget_closure"] == pytest.approx(0.4288829527707021, abs=1e-9)
        assert fm["raw"]["efficiency"] == pytest.approx(1.1422340944585958)
        assert fm["raw"]["dmax_dbi"] == pytest.approx(3.515574847918346)
        # 同一内核函数：与 nf2ff_service._read_metrics 的修正值逐键一致（禁逻辑副本）
        ref = nf2ff_service._read_metrics(_RECHECK_META, None)
        for k in ("f_res_ghz", "dmax_dbi", "gain_max_dbi", "efficiency",
                  "power_budget_closure", "pec_mirror_factor", "raw"):
            assert fm[k] == ref[k], k
        # 复议后门：收敛轮 η_corr 0.5711 落 [0.55, 0.79] → PASS
        assert fm["eta_gate"]["ok"] is True and fm["eta_gate"]["gate"] == [0.55, 0.79]
        json.dumps(fm)

    def test_dipole_full_box_untouched_and_not_gated(self):
        """全包盒（z_start<0）：因子 1、原值不动、无 raw；非 patch 模板不套 patch η 窗。"""
        from rfauto.service import ui_service

        rid = _make_meta_run(self.root, "20260917_000011_dipole", _DIPOLE_META)
        fm = ui_service.field_view(rid)["farfield_metrics"]
        assert fm["pec_mirror_factor"] == 1.0 and "raw" not in fm
        assert fm["efficiency"] == pytest.approx(0.9903388844026775)
        assert fm["dmax_dbi"] == pytest.approx(3.1356285581661654)
        assert fm["eta_gate"] is None

    def test_eta_gate_branches(self):
        from rfauto.service.ui_service import patch_eta_gate

        assert patch_eta_gate({"efficiency": None})["ok"] is None
        g = patch_eta_gate({"efficiency": 1.1422})      # 未修正的镜像双计值
        assert g["ok"] is False and "非物理" in g["reason"]
        g = patch_eta_gate({"efficiency": 0.50})
        assert g["ok"] is False and "低于下沿" in g["reason"]
        g = patch_eta_gate({"efficiency": 0.87})
        assert g["ok"] is False and "超上沿" in g["reason"]
        g = patch_eta_gate({"efficiency": 0.5711})
        assert g["ok"] is True and g["value"] == 0.5711 and g["gate"] == [0.55, 0.79]
        assert patch_eta_gate({"efficiency": 0.55})["ok"] is True   # 闭区间边界
        assert patch_eta_gate({"efficiency": 0.79})["ok"] is True

    def test_eta_gate_number_chain(self):
        """门下沿 0.55 由实测锚 + 解析式复现（坑 #118：裁判不是自己的推导）。

        η = Q_d/(Q_d+Q_rad)，Q_d = 1/tanδ（RO4350B 0.0037）；收敛轮 η_corr 反推
        Q_rad≈203（早期口径 ≈200）；紧贴盒轮 η 0.6215 = Prad 虚高 +8.82%，
        守卫带取该观测值 → Q_d/(Q_d+203×1.0882) = 0.5503 → 0.55。
        """
        from rfauto.service.ui_service import PATCH_ETA_GATE, PATCH_ETA_GATE_BASIS

        B = PATCH_ETA_GATE_BASIS
        q_d = 1.0 / B["tan_delta"]
        assert q_d == pytest.approx(270.27, abs=0.01)
        eta_anchor = B["eta_anchor_converged"]
        q_rad = q_d * (1.0 - eta_anchor) / eta_anchor
        assert q_rad == pytest.approx(203.0, abs=0.5)                       # ≈200
        bias = B["eta_tight_box_run"] / eta_anchor - 1.0
        assert bias == pytest.approx(0.0882, abs=5e-4)                      # 紧贴盒 Prad 虚高
        eta_min = q_d / (q_d + q_rad * (1.0 + bias))
        assert eta_min == pytest.approx(0.5503, abs=5e-4)
        assert round(eta_min, 2) == PATCH_ETA_GATE[0] == 0.55
        # 旧门 0.62 假设 Q_rad~60–80 → η 0.77–0.82，被实测 Q_rad 203 否定（2.5×）
        assert q_d / (q_d + 80.0) > 0.62 and q_rad / 80.0 > 2.5
        # 上沿 0.79 保留：对应 Q_rad≈72（Prad 较锚值虚高 ~2.8× 才触线）
        assert q_d * (1.0 - PATCH_ETA_GATE[1]) / PATCH_ETA_GATE[1] == pytest.approx(71.8, abs=0.2)
        # 锚值本身：复议后过门、旧门下沿 0.62 下判失
        assert PATCH_ETA_GATE[0] <= eta_anchor <= PATCH_ETA_GATE[1] and eta_anchor < 0.62

    def test_smoke_script_gate_literal_matches_service(self):
        """scripts/smoke_patch_ff_recheck.py 的 G1 字面值与服务层单源对账（脚本不 import service）。"""
        import re

        from rfauto.service.ui_service import PATCH_ETA_GATE

        src = (SRC.parent / "scripts" / "smoke_patch_ff_recheck.py").read_text(encoding="utf-8")
        m = re.search(r"^ETA_RANGE = \(([0-9.]+), ([0-9.]+)\)", src, re.M)
        assert m is not None
        assert (float(m.group(1)), float(m.group(2))) == PATCH_ETA_GATE

    def test_frontend_renders_mirror_factor_and_eta_gate(self):
        pages = (SRC / "rfauto" / "ui" / "static" / "pages.js").read_text(encoding="utf-8")
        assert "m.pec_mirror_factor" in pages and "m.eta_gate" in pages


class TestSmithService:
    @pytest.fixture()
    def sp_run(self, tmp_path, monkeypatch):
        from rfauto.service import ui_service

        monkeypatch.chdir(tmp_path)
        results = tmp_path / "runs" / RUN_ID / "results"
        results.mkdir(parents=True)
        (results / "data.s2p").write_text(_S2P, encoding="utf-8")
        monkeypatch.setattr(ui_service, "RUNS_DIR", tmp_path / "runs")
        return RUN_ID

    def test_smith_view_traces_per_port(self, sp_run):
        from rfauto.service.ui_service import smith_view

        s = smith_view(sp_run)
        assert s["ok"] and s["z0"] == 50.0 and s["warning"] is None
        assert [(t["file"], t["name"], t["port"]) for t in s["traces"]] == [
            ("data.s2p", "S11", 1), ("data.s2p", "S22", 2)]
        s11 = s["traces"][0]
        assert s11["re"] == [0.5, 0.0, 0.0] and s11["im"] == [0.0, 0.5, 0.0]
        assert s11["z_re_ohm"] == [150.0, 30.0, 50.0] and s11["z_im_ohm"] == [0.0, 40.0, 0.0]
        assert s["traces"][1]["re"][0] == -0.5 and "r_circles" in s["grid"]
        json.dumps(s)

    def test_smith_view_missing_results(self, sp_run):
        from rfauto.service.ui_service import smith_view

        assert smith_view("nope")["ok"] is False

    def test_smith_external_validation(self, tmp_path):
        from rfauto.service.ui_service import smith_external

        ext = tmp_path / "ext.s2p"
        ext.write_text(_S2P, encoding="utf-8")
        r = smith_external(str(ext))
        assert r["ok"] and r["file"] == "ext.s2p" and len(r["traces"]) == 2 and "grid" in r
        assert smith_external(str(tmp_path / "no.s2p"))["ok"] is False
        (tmp_path / "x.txt").write_text("x", encoding="utf-8")
        assert "非 Touchstone" in smith_external(str(tmp_path / "x.txt"))["errors"][0]
        (tmp_path / "bad.s2p").write_text("garbage\n", encoding="utf-8")
        assert smith_external(str(tmp_path / "bad.s2p"))["ok"] is False


class TestUiRoutes:
    def test_field_and_smith_routes_thin_shells(self, field_run, tmp_path):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        results = tmp_path / "runs" / field_run / "results"
        results.mkdir(parents=True)
        (results / "data.s2p").write_text(_S2P, encoding="utf-8")
        client = TestClient(create_ui_app())
        listing = client.get("/api/field").json()
        assert listing["ok"] and listing["runs"][0]["run_id"] == field_run
        view = client.get(
            f"/api/field/{field_run}?dump=SAR_raw.h5&engine=numpy&levels=-6,-12&sz=1").json()
        assert view["ok"] and view["selected"] == "SAR_raw.h5" and view["engine"] == "numpy_contour"
        assert view["isosurface"]["levels_db"] == [-12.0, -6.0]
        assert next(s for s in view["slices"] if s["axis"] == "z")["index"] == 1
        assert client.get(f"/api/field/{field_run}").json()["ok"]  # 缺省参数
        smith = client.get(f"/api/smith/{field_run}").json()
        assert smith["ok"] and [t["name"] for t in smith["traces"]] == ["S11", "S22"]
        ext = client.post("/api/smith/external", json={"path": str(results / "data.s2p")}).json()
        assert ext["ok"] and ext["file"] == "data.s2p"
        assert client.post("/api/smith/external", json={"path": "nope.s2p"}).json()["ok"] is False


# ─── 前端静态契约 + extras 纪律 ─────────────────────────────────────────────

class TestStaticContracts:
    def test_frontend_wires_field_page_and_smith_mode(self):
        static = SRC / "rfauto" / "ui" / "static"
        pages = (static / "pages.js").read_text(encoding="utf-8")
        assert "field: pageField" in pages and "async function pageField()" in pages
        for token in ("function drawSmith", "sp-mode-smith", "/api/smith/", "/api/smith/external",
                      "/api/field", "function drawFieldSlice", "function drawIsoMesh",
                      "function drawPattern3d", 'showPage("farfield")'):
            assert token in pages, token
        html = (static / "index.html").read_text(encoding="utf-8")
        assert 'data-v="field"' in html and 'id="view-field"' in html

    def test_viz3d_extra_declared_and_guarded(self):
        import tomllib

        root = SRC.parent
        py = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        extra = py["project"]["optional-dependencies"]["viz3d"]
        assert any(r.startswith("pyvista") for r in extra) and any(r.startswith("vtk") for r in extra)
        assert not any(d.startswith(("pyvista", "vtk"))
                       for d in py["project"]["dependencies"])  # exclusive：不进核心依赖
        sys.path.insert(0, str(root / "scripts"))
        try:
            import check_env_deps as ced
        finally:
            sys.path.pop(0)
        assert ced.OPTIONAL_MODULE_TO_EXTRA["pyvista"] == "viz3d"
        assert ced.OPTIONAL_MODULE_TO_EXTRA["vtk"] == "viz3d"
        assert ced.check_extras_coverage({"pyvista"}, {"viz3d"}) == []
        assert ced.check_extras_coverage({"pyvista"}, {"ui"})  # 未声明即报缺口

    def test_pyvista_only_imported_lazily(self):
        src = (SRC / "rfauto" / "infra" / "visualization.py").read_text(encoding="utf-8")
        head = src.split("def viz3d_available")[0]
        assert "import pyvista" not in head  # 模块顶层不 import（未安装亦可 import 本模块）
