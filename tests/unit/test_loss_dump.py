"""D3-1 实档损耗 dump 读取器单测（infra/loss_dump，§10.21 第九轮 D3-1）。

两道门并存：
- **合成 fixture 门（CI 恒跑）**：tmp_path 手写 openEMS dump_type=29 布局
  （FieldData/FD/f0 + CellData + CellWidth + Mesh），裁判 = 闭式
  P = 0.5·σ·|E0|²·V（Jackson §6.9，#118 独立来源）与可分离求和闭式；
- **实档锚门（归档在则跑，缺则 skip 不 fail）**：runs/nf2ff_smoke_sar_dipole/
  fdtd/SAR_raw.h5 逐 cell 积分 vs 同目录 openEMS 自算 SAR_1g.h5 的 power
  属性（独立实现裁判），rel ≤ 1e-3。runs/ 为 git-ignored，CI 无归档。

h5py 走 pytest.importorskip（extras [openems]，test_field_webviz 同款）。
确定性、零网络、零真机。
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

from rfauto.core.loss_density import (
    LossMaterial,
    integrate_loss_density,
    loss_density,
    uniform_cell_measure,
)
from rfauto.infra.loss_dump import (
    KIND_PROCESSED_SAR,
    KIND_RAW_FIELD,
    SAR_RAW_DUMP_TYPE,
    LossDump,
    find_volume_loss_dumps,
    read_loss_dump,
)

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_RAW = ROOT / "runs" / "nf2ff_smoke_sar_dipole" / "fdtd" / "SAR_raw.h5"
ARCHIVE_SAR = ROOT / "runs" / "nf2ff_smoke_sar_dipole" / "fdtd" / "SAR_1g.h5"
#: 实档 ∫q dV vs openEMS 自算 power 的门（float32 存储下实测 2.1e-8）
ARCHIVE_TOL = 1e-3


# ─── 合成 dump 写入（逐字段复刻实档契约）────────────────────────────────────

def _write_raw_dump(
    path: Path,
    e_field: np.ndarray,
    sigma: np.ndarray,
    widths: tuple[np.ndarray, np.ndarray, np.ndarray],
    freq_hz: float = 2.5e9,
    *,
    dump_type: int = SAR_RAW_DUMP_TYPE,
    with_volume: bool = True,
    with_cellwidth: bool = True,
    split_real_imag: bool = False,
    density: np.ndarray | None = None,
) -> Path:
    wx, wy, wz = widths
    with h5py.File(path, "w") as h:
        h.attrs["dump_type"] = np.int32(dump_type)
        h.attrs["dual_mesh"] = np.uint8(1)
        h.attrs["openEMS_HDF5_version"] = np.float64(0.3)
        mesh = h.create_group("Mesh")
        mesh.attrs["mesh_scaling"] = np.float64(1.0)
        mesh.attrs["mesh_type"] = np.int32(0)
        for name, w in zip("xyz", (wx, wy, wz), strict=True):
            mesh.create_dataset(name, data=np.cumsum(w) - w[0])
        if with_cellwidth:
            cw = h.create_group("CellWidth")
            cw.attrs["mesh_scaling"] = np.float64(1.0)
            cw.attrs["mesh_type"] = np.int32(0)
            for name, w in zip("xyz", (wx, wy, wz), strict=True):
                cw.create_dataset(name, data=np.asarray(w, dtype=np.float64))
        fd = h.create_group("FieldData").create_group("FD")
        fd.attrs["frequency"] = np.array([freq_hz])
        if split_real_imag:
            r = fd.create_dataset("f0_real", data=np.asarray(e_field.real, dtype=np.float32))
            fd.create_dataset("f0_imag", data=np.asarray(e_field.imag, dtype=np.float32))
            r.attrs["d_order"] = "NXYZ"
        else:
            ds = fd.create_dataset("f0", data=np.asarray(e_field, dtype=np.complex64))
            ds.attrs["d_order"] = "NXYZ"
        cd = h.create_group("CellData")
        cd.create_dataset("Conductivity", data=np.asarray(sigma, dtype=np.float32)).attrs["d_order"] = "XYZ"
        if with_volume:
            vol = wx[:, None, None] * wy[None, :, None] * wz[None, None, :]
            cd.create_dataset("Volume", data=np.asarray(vol, dtype=np.float32)).attrs["d_order"] = "XYZ"
        if density is not None:
            cd.create_dataset("Density", data=np.asarray(density, dtype=np.float32)).attrs["d_order"] = "XYZ"
    return path


def _write_processed_sar(path: Path, shape: tuple[int, int, int], power_w: float,
                         freq_hz: float = 2.5e9) -> Path:
    with h5py.File(path, "w") as h:
        h.attrs["openEMS_HDF5_version"] = np.float64(0.3)
        h.attrs["mass"] = np.float64(0.07425)
        mesh = h.create_group("Mesh")
        for name, n in zip("xyz", shape, strict=True):
            mesh.create_dataset(name, data=np.linspace(0.0, 1.0, n))
        fd = h.create_group("FieldData").create_group("FD")
        fd.attrs["frequency"] = np.array([freq_hz], dtype=np.float32)
        fd.attrs["used_cubes"] = np.uint64(11600)
        ds = fd.create_dataset("f0", data=np.ones(shape, dtype=np.float32))
        ds.attrs["d_order"] = "XYZ"
        ds.attrs["frequency"] = np.float32(freq_hz)
        ds.attrs["power"] = np.float32(power_w)
        ds.attrs["maxSAR"] = np.float32(3.48e-25)
        ds.attrs["maxSAR_idx"] = np.array([1, 1, 1], dtype=np.uint32)
    return path


def _uniform_case(shape=(4, 3, 2), e0=40.0, sigma=0.02):
    """均匀场/均匀 σ/均匀步长：闭式 P = 0.5·σ·|E0|²·V。"""
    e = np.zeros((3, *shape), dtype=complex)
    e[0] = e0
    sig = np.full(shape, sigma)
    spacing = (0.5e-3, 0.5e-3, 1.0e-3)
    widths = tuple(np.full(n, s) for n, s in zip(shape, spacing, strict=True))
    volume = int(np.prod(shape)) * uniform_cell_measure(spacing)
    analytic = 0.5 * sigma * e0**2 * volume
    return e, sig, widths, analytic


# ─── 合成 fixture 门 ──────────────────────────────────────────────────────────

class TestSyntheticRawDump:
    def test_uniform_field_matches_closed_form(self, tmp_path):
        """均匀场闭式 P = 0.5σ|E0|²V（Jackson §6.9）；与 core 内核标量路径同值。"""
        e, sig, widths, analytic = _uniform_case()
        dump = read_loss_dump(_write_raw_dump(tmp_path / "SAR_raw.h5", e, sig, widths))
        assert dump.kind == KIND_RAW_FIELD
        assert dump.dump_type == SAR_RAW_DUMP_TYPE
        assert dump.freq_hz == pytest.approx(2.5e9)
        assert dump.shape == (4, 3, 2)
        p = dump.integrate_power_w()
        assert p is not None
        # float32 存储 σ=0.02 → 2e-8 级舍入；门 1e-6
        assert abs(p - analytic) / analytic < 1e-6
        # 与 core 标量材料路径（loss_density + integrate_loss_density）一致
        q_kernel = loss_density(e, freq_hz=2.5e9, material=LossMaterial(sigma=0.02))
        p_kernel = integrate_loss_density(q_kernel, cell_measure=uniform_cell_measure((0.5e-3, 0.5e-3, 1.0e-3)))
        assert abs(p - p_kernel) / p_kernel < 1e-6

    def test_separable_nonuniform_alignment(self, tmp_path):
        """场沿 x 变、σ 沿 y 变、步长各轴不均：可分离闭式
        P = 0.5·(Σ_i |E_i|² wx_i)·(Σ_j σ_j wy_j)·(Σ_k wz_k)——抓 XYZ 轴序/广播错。"""
        shape = (5, 3, 2)
        ex = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        sy = np.array([0.01, 0.02, 0.04])
        wx = np.array([1e-3, 2e-3, 1e-3, 3e-3, 1e-3])
        wy = np.array([0.5e-3, 1e-3, 2e-3])
        wz = np.array([1e-3, 4e-3])
        e = np.zeros((3, *shape), dtype=complex)
        e[1] = ex[:, None, None] * (1.0 + 0.0j)  # y 分量携场
        sig = np.broadcast_to(sy[None, :, None], shape).copy()
        analytic = 0.5 * float(np.sum(ex**2 * wx)) * float(np.sum(sy * wy)) * float(np.sum(wz))
        dump = read_loss_dump(_write_raw_dump(tmp_path / "SAR_raw.h5", e, sig, (wx, wy, wz)))
        p = dump.integrate_power_w()
        assert p is not None
        assert abs(p - analytic) / analytic < 1e-6

    def test_volume_fallback_from_cellwidth(self, tmp_path):
        """无 CellData/Volume 时用 CellWidth 三轴外积作测度，结果同闭式。"""
        e, sig, widths, analytic = _uniform_case()
        dump = read_loss_dump(_write_raw_dump(tmp_path / "d.h5", e, sig, widths, with_volume=False))
        assert dump.cell_volume is not None
        assert dump.total_volume_m3 == pytest.approx(analytic / (0.5 * 0.02 * 40.0**2), rel=1e-9)
        p = dump.integrate_power_w()
        assert p is not None and abs(p - analytic) / analytic < 1e-6

    def test_split_real_imag_layout(self, tmp_path):
        """f0_real/f0_imag 拆分布局（visualization.read_field_dump 同款变体）。"""
        e, sig, widths, analytic = _uniform_case()
        e = e * np.exp(1j * 0.7)  # 复相位不影响 |E|²
        dump = read_loss_dump(_write_raw_dump(tmp_path / "d.h5", e, sig, widths, split_real_imag=True))
        assert dump.kind == KIND_RAW_FIELD and dump.freq_hz == pytest.approx(2.5e9)
        p = dump.integrate_power_w()
        assert p is not None and abs(p - analytic) / analytic < 1e-6

    def test_density_optional_and_summary_json(self, tmp_path):
        e, sig, widths, _ = _uniform_case()
        rho = np.full(sig.shape, 1000.0)
        with_rho = read_loss_dump(_write_raw_dump(tmp_path / "a.h5", e, sig, widths, density=rho))
        without = read_loss_dump(_write_raw_dump(tmp_path / "b.h5", e, sig, widths))
        assert with_rho.density is not None and np.allclose(with_rho.density, 1000.0)
        assert without.density is None
        summary = with_rho.summary()
        json.dumps(summary, ensure_ascii=False)
        assert summary["kind"] == KIND_RAW_FIELD and summary["shape"] == [4, 3, 2]
        assert "dump_type" not in summary["attrs"]  # 已提升为字段，不重复
        assert summary["attrs"]["dual_mesh"] == 1

    def test_ohmic_loss_density_is_peak_phasor_convention(self, tmp_path):
        """q = 0.5·σ·|E|²（峰值相量，与 core.loss_density rms=False 同口径）。"""
        e, sig, widths, _ = _uniform_case(shape=(2, 2, 2), e0=3.0, sigma=0.5)
        dump = read_loss_dump(_write_raw_dump(tmp_path / "d.h5", e, sig, widths))
        q = dump.ohmic_loss_density()
        assert q is not None and q.shape == (2, 2, 2)
        assert np.allclose(q, 0.5 * 0.5 * 9.0, rtol=1e-6)


class TestProcessedSar:
    def test_reads_openems_power_attr(self, tmp_path):
        dump = read_loss_dump(_write_processed_sar(tmp_path / "SAR_1g.h5", (4, 3, 2), 9.619087e-27))
        assert dump.kind == KIND_PROCESSED_SAR
        assert dump.dump_type is None
        assert dump.openems_power_w == pytest.approx(9.619087e-27, rel=1e-6)
        assert dump.freq_hz == pytest.approx(2.5e9, rel=1e-6)
        assert dump.integrate_power_w() is None  # SAR 不是 E，不可积
        assert dump.e_field is None and dump.conductivity is None
        assert dump.attrs["maxSAR"] == pytest.approx(3.48e-25, rel=1e-6)
        assert dump.attrs["mass"] == pytest.approx(0.07425)
        assert dump.attrs["maxSAR_idx"] == [1, 1, 1]
        json.dumps(dump.summary(), ensure_ascii=False)


class TestReadErrors:
    def test_missing_fielddata_raises(self, tmp_path):
        p = tmp_path / "nf2ff.h5"
        with h5py.File(p, "w") as h:
            h.create_group("Mesh")
        with pytest.raises(ValueError, match="FieldData/FD"):
            read_loss_dump(p)

    def test_scalar_without_power_attr_raises(self, tmp_path):
        p = tmp_path / "scalar.h5"
        with h5py.File(p, "w") as h:
            fd = h.create_group("FieldData").create_group("FD")
            fd.create_dataset("f0", data=np.ones((2, 2, 2), dtype=np.float32))
        with pytest.raises(ValueError, match="power"):
            read_loss_dump(p)

    def test_wrong_vector_shape_raises(self, tmp_path):
        p = tmp_path / "bad.h5"
        with h5py.File(p, "w") as h:
            fd = h.create_group("FieldData").create_group("FD")
            fd.create_dataset("f0", data=np.ones((2, 4, 3, 2), dtype=np.complex64))
        with pytest.raises(ValueError, match=r"\(3, nx, ny, nz\)"):
            read_loss_dump(p)

    def test_missing_celldata_raises(self, tmp_path):
        p = tmp_path / "nocell.h5"
        with h5py.File(p, "w") as h:
            h.attrs["dump_type"] = np.int32(SAR_RAW_DUMP_TYPE)
            fd = h.create_group("FieldData").create_group("FD")
            fd.create_dataset("f0", data=np.ones((3, 2, 2, 2), dtype=np.complex64))
        with pytest.raises(ValueError, match="CellData"):
            read_loss_dump(p)

    def test_conductivity_shape_mismatch_raises(self, tmp_path):
        e, sig, widths, _ = _uniform_case()
        p = _write_raw_dump(tmp_path / "d.h5", e, sig, widths)
        with h5py.File(p, "a") as h:
            del h["CellData/Conductivity"]
            h["CellData"].create_dataset("Conductivity", data=np.ones((4, 3, 3), dtype=np.float32))
        with pytest.raises(ValueError, match="不对齐"):
            read_loss_dump(p)

    def test_no_volume_no_cellwidth_raises(self, tmp_path):
        e, sig, widths, _ = _uniform_case()
        p = _write_raw_dump(tmp_path / "d.h5", e, sig, widths, with_volume=False, with_cellwidth=False)
        with pytest.raises(ValueError, match="积分测度"):
            read_loss_dump(p)

    def test_nan_field_raises(self, tmp_path):
        e, sig, widths, _ = _uniform_case()
        e[0, 0, 0, 0] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            read_loss_dump(_write_raw_dump(tmp_path / "d.h5", e, sig, widths))

    def test_negative_conductivity_raises(self, tmp_path):
        e, sig, widths, _ = _uniform_case()
        sig[1, 1, 1] = -1.0
        with pytest.raises(ValueError, match="负值"):
            read_loss_dump(_write_raw_dump(tmp_path / "d.h5", e, sig, widths))

    def test_non_hdf5_file_raises_valueerror(self, tmp_path):
        p = tmp_path / "text.h5"
        p.write_text("not hdf5", encoding="utf-8")
        with pytest.raises(ValueError, match="HDF5"):
            read_loss_dump(p)


class TestFindVolumeLossDumps:
    def test_only_raw_dump_type_29_returned(self, tmp_path):
        run = tmp_path / "run"
        (run / "fdtd").mkdir(parents=True)
        e, sig, widths, _ = _uniform_case()
        raw = _write_raw_dump(run / "fdtd" / "SAR_raw.h5", e, sig, widths)
        _write_processed_sar(run / "fdtd" / "SAR_1g.h5", (4, 3, 2), 1e-27)
        # dump_type 不是 29 的同布局文件（如 AddDump E 场 FD dump）不算
        _write_raw_dump(run / "fdtd" / "Et.h5", e, sig, widths, dump_type=10)
        (run / "fdtd" / "garbage.h5").write_text("nope", encoding="utf-8")
        with h5py.File(run / "fdtd" / "nf2ff_E_0.h5", "w") as h:  # 无 FieldData/FD
            h.create_group("Mesh")
        found = find_volume_loss_dumps(run)
        assert found == [raw]

    def test_missing_dir_and_empty_dir(self, tmp_path):
        assert find_volume_loss_dumps(tmp_path / "ghost") == []
        (tmp_path / "empty").mkdir()
        assert find_volume_loss_dumps(tmp_path / "empty") == []

    def test_sorted_deterministic(self, tmp_path):
        run = tmp_path / "run"
        run.mkdir()
        e, sig, widths, _ = _uniform_case()
        b = _write_raw_dump(run / "b.h5", e, sig, widths)
        a = _write_raw_dump(run / "a.h5", e, sig, widths)
        assert find_volume_loss_dumps(run) == [a, b]


# ─── 实档锚门（缺归档 skip，不 fail）────────────────────────────────────────

@pytest.mark.skipif(not (ARCHIVE_RAW.exists() and ARCHIVE_SAR.exists()),
                    reason="实档归档 runs/nf2ff_smoke_sar_dipole 不在本机（runs/ git-ignored）")
class TestArchiveAnchor:
    def test_integral_matches_openems_power_attr(self):
        """∑0.5σ|E|²·Volume vs openEMS 自算 SAR_1g.h5 power 属性（独立实现裁判）。"""
        raw = read_loss_dump(ARCHIVE_RAW)
        sar = read_loss_dump(ARCHIVE_SAR)
        assert raw.kind == KIND_RAW_FIELD and raw.dump_type == SAR_RAW_DUMP_TYPE
        assert sar.kind == KIND_PROCESSED_SAR and sar.openems_power_w is not None
        assert raw.shape == (110, 29, 23)
        assert raw.freq_hz == pytest.approx(2.5e9)
        assert raw.density is not None  # 实档带 Density
        p = raw.integrate_power_w()
        assert p is not None and p > 0.0
        rel = abs(p - sar.openems_power_w) / sar.openems_power_w
        assert rel <= ARCHIVE_TOL, (p, sar.openems_power_w, rel)

    def test_find_returns_archive_raw_dump_only(self):
        found = find_volume_loss_dumps(ARCHIVE_RAW.parents[1])
        assert found == [ARCHIVE_RAW]

    def test_cellwidth_product_matches_celldata_volume(self):
        """CellData/Volume 与 CellWidth 三轴外积一致（实档 4.5e-8 相对差）。"""
        with h5py.File(ARCHIVE_RAW, "r") as h:
            vol = np.asarray(h["CellData/Volume"][...], dtype=float)
            w = [np.asarray(h[f"CellWidth/{a}"][...], dtype=float) for a in "xyz"]
        prod = w[0][:, None, None] * w[1][None, :, None] * w[2][None, None, :]
        assert float(np.max(np.abs(prod - vol) / vol)) < 1e-6


def test_lossdump_is_frozen():
    d = LossDump(path="p", kind=KIND_PROCESSED_SAR, freq_hz=None, dump_type=None,
                 e_field=None, conductivity=None, density=None, cell_volume=None,
                 openems_power_w=1.0)
    with pytest.raises(AttributeError):
        d.kind = "x"  # type: ignore[misc]
    assert d.shape is None and d.total_volume_m3 is None and d.integrate_power_w() is None
