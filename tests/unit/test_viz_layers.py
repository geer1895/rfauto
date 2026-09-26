"""DP-16 C5 可视化三层单测（L1 Smith / L2 出版静态图 / L3 场切片 PNG）。

确定性、零网络、零真机：
- L1 Smith：skrf 例题（skrf.data.line）Γ 数据透传与 skrf 直读逐位对拍；
- L2 出版图：venv 无 scienceplots → 缺依赖显式 RuntimeError 指明
  `pip install rfauto[report]`（不静默降级；已装环境走正向用例）；
- L3 场切片：合成 DumpHDF5（契约复刻真机产物）→ 切片点值与 h5 原值
  逐位；非结构 gmsh .msh（meshio 写）→ pyvista 切片点值可对拍，PNG
  off_screen 落盘（best-effort #105）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

skrf = pytest.importorskip("skrf")
h5py = pytest.importorskip("h5py")

from rfauto.infra import visualization as V

# ─── L1 Smith：skrf 薄包装 ────────────────────────────────────────────────


class TestSmithWrapper:
    def test_gamma_passthrough_bitwise_skrf_example(self, tmp_path):
        """skrf 例题（data.line）：包装返回 Γ 与网络 S 直读逐位同。"""
        net = skrf.data.line  # skrf 自带例题（2 端口）
        res = V.plot_smith_png(net, tmp_path / "smith.png", m=1, n=1)
        assert res["ok"] and res["n_points"] == net.frequency.npoints
        s11 = np.asarray(net.s)[:, 0, 0]
        assert res["gamma_re"] == s11.real.tolist()  # tolist 透传，无算术
        assert res["gamma_im"] == s11.imag.tolist()
        assert Path(res["path"]).is_file()
        assert Path(res["path"]).stat().st_size > 0

    def test_port_selection_mn(self, tmp_path):
        net = skrf.data.line
        res = V.plot_smith_png(net, tmp_path / "smith22.png", m=2, n=2)
        s22 = np.asarray(net.s)[:, 1, 1]
        assert res["gamma_re"] == s22.real.tolist()
        assert res["gamma_im"] == s22.imag.tolist()

    def test_rejects_non_network(self, tmp_path):
        with pytest.raises(TypeError, match=r"skrf\.Network"):
            V.plot_smith_png([1, 2, 3], tmp_path / "x.png")

    def test_index_bounds(self, tmp_path):
        net = skrf.data.line
        with pytest.raises(IndexError, match="越界"):
            V.plot_smith_png(net, tmp_path / "x.png", m=3, n=1)


# ─── L2 出版静态图：SciencePlots 惰性 + 显式报错 ─────────────────────────

_HAS_SCIENCEPLOTS = importlib.util.find_spec("scienceplots") is not None


class TestPublication:
    @pytest.mark.skipif(_HAS_SCIENCEPLOTS,
                        reason="scienceplots 已安装：缺依赖报错路径不可测")
    def test_missing_dependency_explicit_error(self, tmp_path):
        """缺 scienceplots → RuntimeError 指明 extras [report]，不静默降级。"""
        with pytest.raises(RuntimeError, match=r"rfauto\[report\]"):
            V.plot_s_params_publication(
                np.array([2.0, 2.5, 3.0]), {"S21": np.array([-0.1, -0.2, -0.3])},
                tmp_path / "pub.png")
        assert not (tmp_path / "pub.png").exists()  # 失败不落半成品图

    @pytest.mark.skipif(not _HAS_SCIENCEPLOTS,
                        reason="scienceplots 未安装（extras [report]）")
    def test_publication_renders(self, tmp_path):
        p = V.plot_s_params_publication(
            np.linspace(2.0, 3.0, 11),
            {"S11": np.linspace(-15, -25, 11), "S21": np.linspace(-0.5, -0.3, 11)},
            tmp_path / "pub.png")
        assert Path(p).is_file() and Path(p).stat().st_size > 0


# ─── L3 规则网格：合成 DumpHDF5 → 切片点值逐位 + PNG ─────────────────────

X_MM = np.linspace(-2.0, 2.0, 5)
Y_MM = np.linspace(-1.0, 1.0, 3)
Z_MM = np.linspace(-0.5, 0.5, 3)


def _write_fd_vector_dump(path: Path) -> tuple[Path, np.ndarray]:
    """FD 矢量 dump：vec[0]=f·0.6、vec[1]=1j·f·0.8 → |E|=f（0.36+0.64=1）。"""
    X, Y, Z = np.meshgrid(X_MM, Y_MM, Z_MM, indexing="ij")
    field = np.exp(-(X**2 + Y**2 + Z**2) / 2.0) + 0.25 * X * Y * Z
    with h5py.File(path, "w") as h:
        m = h.create_group("Mesh")
        m.attrs["mesh_scaling"] = np.float64(1.0)
        for name, arr in (("x", X_MM), ("y", Y_MM), ("z", Z_MM)):
            m.create_dataset(name, data=arr * 1e-3)
        vec = np.zeros((3, *field.shape), dtype=np.complex64)
        vec[0] = field * 0.6
        vec[1] = 1j * field * 0.8
        ds = h.create_dataset("FieldData/FD/f0", data=vec)
        ds.attrs["d_order"] = "NXYZ"
    return path, field


class TestRegularGridSlices:
    def test_slice_values_bitwise_vs_h5(self, tmp_path):
        """切片定量点值与 h5 原值逐位：take 转置无算术；|E| 公式同源。"""
        path, _field = _write_fd_vector_dump(tmp_path / "dump.h5")
        vol = V.read_field_dump(path)
        # h5 原值 → |E| 逐位（与 _vector_magnitude 同式同输入）
        with h5py.File(path, "r") as h:
            raw = np.asarray(h["FieldData/FD/f0"][...])
        expected_mag = np.sqrt(np.sum(np.abs(raw) ** 2, axis=0)).astype(float)
        assert np.array_equal(vol.magnitude, expected_mag)
        # 切片=原数组 take+T（无算术）→ 逐位
        idx, u_name, v_name, u_m, v_m, vals = V._raw_slice(vol, "y", 1)
        assert idx == 1 and u_name == "x" and v_name == "z"
        assert np.array_equal(vals, np.take(vol.magnitude, 1, axis=1).T)
        assert np.array_equal(u_m, vol.x_m) and np.array_equal(v_m, vol.z_m)

    def test_slices_json_linear_contract(self, tmp_path):
        """field_slices(db=False) 六位有效数字契约逐点复核（独立实现）。"""
        path, _ = _write_fd_vector_dump(tmp_path / "dump.h5")
        vol = V.read_field_dump(path)
        slices = {s["axis"]: s for s in V.field_slices(vol, db=False)}
        sl = slices["x"]
        raw = np.take(vol.magnitude, sl["index"], axis=0).T  # [v][u]
        for vi in range(raw.shape[0]):
            for ui in range(raw.shape[1]):
                expect = float(f"{raw[vi, ui]:.6g}") if raw[vi, ui] else 0.0
                assert sl["values"][vi][ui] == expect

    def test_field_slices_png_written(self, tmp_path):
        path, _ = _write_fd_vector_dump(tmp_path / "dump.h5")
        vol = V.read_field_dump(path)
        paths = V.field_slices_png(vol, tmp_path / "figs")
        assert len(paths) == 3
        for p in paths:
            assert Path(p).is_file() and Path(p).stat().st_size > 0
        assert [Path(p).stem for p in paths] == [
            "slice_x_idx2", "slice_y_idx1", "slice_z_idx1"]  # 各轴中面

    def test_db_slice_point_value(self, tmp_path):
        """db 口径点值=20·log10(v/peak) 钳到 floor（独立算一行对照）。"""
        path, _ = _write_fd_vector_dump(tmp_path / "dump.h5")
        vol = V.read_field_dump(path)
        slices = {s["axis"]: s for s in V.field_slices(vol, db=True)}
        sl = slices["x"]
        raw = np.take(vol.magnitude, sl["index"], axis=0).T
        peak = vol.peak
        v0 = raw[0, 0]
        expect = max(round(float(20.0 * np.log10(v0 / peak)), 3), V.FIELD_DB_FLOOR)
        assert sl["values"][0][0] == expect


# ─── L3 非结构网格：gmsh .msh → pyvista 切片点值 + PNG ───────────────────

pv = pytest.importorskip("pyvista")
meshio = pytest.importorskip("meshio")

# 单位立方体 Kuhn 六四面体分解（顶点按 xyz 位编码）
_CUBE_PTS = np.array([
    [0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0],
    [2.0, 2.0, 0.0], [2.0, 0.0, 2.0], [0.0, 2.0, 2.0], [2.0, 2.0, 2.0],
])
_KUHN_TETS = np.array([
    [0, 1, 4, 7], [0, 1, 5, 7], [0, 2, 4, 7],
    [0, 2, 6, 7], [0, 3, 5, 7], [0, 3, 6, 7],
])
_LINEAR_F = (2.0, 3.0, 4.0)  # f(p) = 2x+3y+4z（四面体上线性插值精确）


def _write_gmsh_cube(path: Path) -> Path:
    """纯几何 gmsh 2.2（meshio NodeData 回读有 quirk，标量由测试侧回挂）。"""
    mesh = meshio.Mesh(_CUBE_PTS, {"tetra": _KUHN_TETS})
    meshio.gmsh.write(path, mesh, fmt_version="2.2", binary=False)
    return path


def _cube_grid(path: Path):
    grid = V.read_unstructured_mesh(path)
    grid.point_data["temp"] = _CUBE_PTS @ np.array(_LINEAR_F)  # 线性标量场
    return grid


class TestUnstructuredMesh:
    def test_read_gmsh_meshio_fallback(self, tmp_path):
        """.msh 走 meshio 兜底读 → pyvista 网格点数/bounds 与原网格一致。"""
        path = _write_gmsh_cube(tmp_path / "cube.msh")
        grid = V.read_unstructured_mesh(path)
        assert grid.n_points == len(_CUBE_PTS)
        assert grid.n_cells == len(_KUHN_TETS)
        np.testing.assert_allclose(np.asarray(grid.bounds),
                                   [0.0, 2.0, 0.0, 2.0, 0.0, 2.0], atol=1e-12)

    def test_slice_point_values_linear_exact(self, tmp_path):
        """切片点值可对拍：线性标量在四面体线性插值下逐点精确回收。"""
        path = _write_gmsh_cube(tmp_path / "cube.msh")
        grid = _cube_grid(path)
        res = V.unstructured_slice(grid, normal="z", origin=(1.0, 1.0, 1.0),
                                   scalar="temp")
        assert res["n_points"] >= 3
        pts = np.asarray(res["points_mm"])
        assert np.all(np.abs(pts[:, 2] - 1.0) < 1e-9)  # 切面 z=1.0
        got = np.asarray(res["values"])
        expect = pts @ np.array(_LINEAR_F)
        np.testing.assert_allclose(got, expect, atol=1e-9)

    def test_slice_png_written(self, tmp_path):
        path = _write_gmsh_cube(tmp_path / "cube.msh")
        grid = _cube_grid(path)
        res = V.unstructured_slice_png(grid, tmp_path / "slice.png",
                                       normal="z", origin=(1.0, 1.0, 1.0),
                                       scalar="temp")
        assert res["ok"] is True, res.get("errors")
        assert Path(res["path"]).is_file()
        assert Path(res["path"]).stat().st_size > 0
        assert res["n_points"] >= 3

    def test_missing_pyvista_explicit_error(self, tmp_path, monkeypatch):
        """pyvista 缺失 → RuntimeError 指明 extras [viz3d]，不静默降级。"""
        path = _write_gmsh_cube(tmp_path / "cube.msh")
        monkeypatch.setitem(sys.modules, "pyvista", None)
        with pytest.raises(RuntimeError, match=r"rfauto\[viz3d\]"):
            V.read_unstructured_mesh(path)
        with pytest.raises(RuntimeError, match=r"rfauto\[viz3d\]"):
            V.unstructured_slice_png(path, tmp_path / "x.png")
