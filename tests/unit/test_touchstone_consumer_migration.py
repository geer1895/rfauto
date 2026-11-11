"""R-27（aurora_r 扩展池）：touchstone 单源消费者迁移等价钉 + 直读散点棘轮。

任务书 §二-8：库内消费者迁移到 touchstone_parser 单源（#248/#287/#309
内核已备）。本文件两件事：

1. **等价钉**：五个迁移散点（core/vendor_passives.load_impedance_curve、
   core/si_channel.load_touchstone_s2p、adapters/ads_netlist._read_snp_meta、
   service/dataset_edb_lane._read_touchstone_meta、
   service/diagnosis_service._load_touchstone）各自历史语料形态
   （本仓 writer/skrf 写盘 RI·MA·DB v1.0 标准形态）下，新单源路径输出
   与旧路径参照（测试内联 ``skrf.Network(file)`` 直读）等价：RI 形态逐位
   一致（双方直取 (re,im)）；MA/DB 形态=解码舍入级一致（skrf 用
   ``mag·exp(1j·deg·π/180)``、parser 用 ``mag·(cos+j·sin)``，数学恒等、
   任意幅角末位舍入差实测 ≤2 ulp/相对 ~1.4e-16）；meta 键逐键相等；
   全离线零网络零真机、tmp_path 隔离零 run 湖写入（#144）。

2. **棘轮**：src/rfauto 全树 AST 扫描 ``skrf.Network(<位置实参>)`` 直读
   形态（keyword-only 构造形态不计），余量名单显式白名单化——**只收
   不放**：新散点入仓（白名单外新增位点）必红；已迁移五文件回归复染
   同红（不在白名单）。

如实不迁登记（语义差，见各条目 reason）：core/com_pam4._validate_s4p
（语料=单行 4 端口 v1.0，skrf 容忍、parser 结构性拒绝——实测证伪，非
能力子集；core 层不可 import adapters，双路不通）、core/macromodel.
request_from_touchstone（z0.ndim==2 检查语义耦合 skrf 文件读形态 + 语料
含任意来源 v2.0 变体，保守不迁）。cli/domains/em 在 R-27 禁改清单。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import skrf

from rfauto.adapters.ads_netlist import _read_snp_meta
from rfauto.core.si_channel import load_touchstone_s2p, save_touchstone_s2p
from rfauto.core.vendor_passives import (
    load_impedance_curve,
    write_touchstone_one_port,
    write_touchstone_series_2port,
)
from rfauto.service.dataset_edb_lane import _read_touchstone_meta
from rfauto.service.diagnosis_service import _load_touchstone

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "rfauto"


# ---------------------------------------------------------------------------
# 语料构造（各散点历史处理的文件形态）
# ---------------------------------------------------------------------------


def _write_ma_s2p(path: Path, freqs: np.ndarray, s: np.ndarray) -> Path:
    """厂商常见 MA 形态 2 端口 v1.0（单行 9 值 legacy 列序）。"""
    lines = ["# GHZ S MA R 50"]
    for k in range(freqs.size):
        parts = [f"{freqs[k] / 1e9:.10e}"]
        for row, col in ((0, 0), (1, 0), (0, 1), (1, 1)):  # S11 S21 S12 S22
            v = s[k, row, col]
            mag = float(np.abs(v))
            ang = float(np.degrees(np.arctan2(v.imag, v.real)))
            parts.append(f"{mag:.10e} {ang:.10e}")
        lines.append(" ".join(parts))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _skrf_write(path: Path, freq: skrf.Frequency, s: np.ndarray,
                form: str = "RI") -> Path:
    """skrf 写盘（散点历史语料主形态：test_ads_netlist 用 DB、edb 用 RI）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    skrf.Network(frequency=freq, s=s, z0=50.0).write_touchstone(
        str(path), form=form)
    return path


def _s_matrix(freq: skrf.Frequency, n: int) -> np.ndarray:
    """合成无源 n 端口 S（对角 0.3、非对角均分——任端口数 σmax<1）。"""
    s = np.zeros((freq.npoints, n, n), dtype=complex)
    off = 0.5 / (n - 1) if n > 1 else 0.0
    for i in range(n):
        s[:, i, i] = 0.3
        for j in range(n):
            if i != j:
                s[:, i, j] = off
    return s


# ---------------------------------------------------------------------------
# 等价钉 1：core/vendor_passives.load_impedance_curve
# ---------------------------------------------------------------------------


class TestVendorPassivesLoadImpedanceCurve:
    def test_one_port_ri_writer_bit_identical(self, tmp_path: Path) -> None:
        freqs = np.linspace(0.1e9, 10e9, 7)
        z = 0.3 + 2j * np.pi * freqs * 10e-9
        path = write_touchstone_one_port(tmp_path / "o.s1p", freqs, z)
        curve = load_impedance_curve(path)
        ref = skrf.Network(str(path))  # 旧路径参照（迁移前直读形态）
        z_ref = 50.0 * (1.0 + ref.s[:, 0, 0]) / (1.0 - ref.s[:, 0, 0])
        assert np.array_equal(curve.freqs_hz, np.asarray(ref.f, dtype=float))
        assert np.array_equal(curve.z, z_ref)
        assert curve.n_ports == 1

    def test_series_2port_ri_writer_bit_identical(self, tmp_path: Path) -> None:
        freqs = np.linspace(0.1e9, 10e9, 7)
        z = 0.3 + 2j * np.pi * freqs * 10e-9
        path = write_touchstone_series_2port(tmp_path / "s.s2p", freqs, z)
        curve = load_impedance_curve(path)
        ref = skrf.Network(str(path))
        assert np.array_equal(curve.z, np.asarray(ref.a[:, 0, 1], dtype=complex))
        cross = -1.0 / np.asarray(ref.y[:, 1, 0], dtype=complex)
        scale = np.maximum(np.abs(curve.z), 1e-300)
        expect = float(np.max(np.abs(curve.z - cross) / scale))
        assert curve.series_crosscheck_rel == pytest.approx(expect)
        assert curve.n_ports == 2

    def test_ma_form_vendor_realism_decode_roundoff(self, tmp_path: Path) -> None:
        # MA 形态等价口径=解码舍入级：skrf 用 mag·exp(1j·deg·π/180)、
        # parser 用 mag·(cos+j·sin)——数学恒等、任意幅角下末位舍入差
        # （实测 ≤2 ulp，相对 ~1.4e-16）；RI 形态双方直取 (re,im) 逐位一致
        # （见各 RI 钉 array_equal）。
        freqs = np.linspace(1e9, 5e9, 5)
        s = np.zeros((5, 2, 2), dtype=complex)
        s[:, 0, 0] = 0.2 * np.exp(0.1j * np.arange(5))
        s[:, 1, 0] = 0.9 * np.exp(-0.3j * np.arange(5))
        s[:, 0, 1] = s[:, 1, 0]
        s[:, 1, 1] = s[:, 0, 0]
        path = _write_ma_s2p(tmp_path / "vendor.s2p", freqs, s)
        curve = load_impedance_curve(path)
        ref = skrf.Network(str(path))
        z_ref = np.asarray(ref.a[:, 0, 1], dtype=complex)
        assert np.array_equal(curve.freqs_hz, np.asarray(ref.f, dtype=float))
        assert np.allclose(curve.z, z_ref, rtol=1e-12, atol=1e-15)
        assert float(np.max(np.abs(curve.z - z_ref))) < 1e-12

    def test_three_port_rejected(self, tmp_path: Path) -> None:
        freq = skrf.Frequency(2.0, 3.0, 5, "GHz")
        path = _skrf_write(tmp_path / "t3.s3p", freq, _s_matrix(freq, 3))
        with pytest.raises(ValueError, match="不支持的模型端口面"):
            load_impedance_curve(path)

    def test_missing_file_keyerror(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError, match="模型文件缺失"):
            load_impedance_curve(tmp_path / "ghost.s2p")


# ---------------------------------------------------------------------------
# 等价钉 2：core/si_channel.load_touchstone_s2p
# ---------------------------------------------------------------------------


class TestSiChannelLoadTouchstoneS2p:
    def test_writer_roundtrip_bit_identical(self, tmp_path: Path) -> None:
        freqs = np.linspace(1e9, 5e9, 5)
        s21 = 0.9 * np.exp(-0.1j * np.arange(5))
        path = save_touchstone_s2p(tmp_path / "ch.s2p", freqs, s21)
        f2, s21_out, z0 = load_touchstone_s2p(path)
        ref = skrf.Network(str(path))
        assert np.array_equal(f2, np.asarray(ref.f, dtype=float))
        assert np.array_equal(s21_out, np.asarray(ref.s[:, 1, 0], dtype=complex))
        assert z0 == float(np.real(np.asarray(ref.z0).ravel()[0]))

    def test_ma_form_decode_roundoff_equivalent(self, tmp_path: Path) -> None:
        # MA 等价口径=解码舍入级（exp(1jθ) vs cos/sin，≤2 ulp）；RI 逐位
        # 见 test_writer_roundtrip_bit_identical。
        freqs = np.linspace(1e9, 5e9, 5)
        s = np.zeros((5, 2, 2), dtype=complex)
        s[:, 0, 0] = 0.1
        s[:, 1, 0] = 0.8 * np.exp(-0.2j * np.arange(5))
        s[:, 0, 1] = s[:, 1, 0]
        s[:, 1, 1] = 0.1
        path = _write_ma_s2p(tmp_path / "ma.s2p", freqs, s)
        f2, s21_out, z0 = load_touchstone_s2p(path)
        ref = skrf.Network(str(path))
        s21_ref = np.asarray(ref.s[:, 1, 0], dtype=complex)
        assert np.array_equal(f2, np.asarray(ref.f, dtype=float))
        assert np.allclose(s21_out, s21_ref, rtol=1e-12, atol=1e-15)
        assert float(np.max(np.abs(s21_out - s21_ref))) < 1e-12
        assert z0 == float(np.real(np.asarray(ref.z0).ravel()[0]))

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_touchstone_s2p(tmp_path / "missing.s2p")

    def test_one_port_rejected(self, tmp_path: Path) -> None:
        freqs = np.linspace(1e9, 2e9, 3)
        path = write_touchstone_one_port(tmp_path / "one.s1p", freqs,
                                         np.full(3, 50.0 + 0j))
        with pytest.raises(ValueError, match="≥2 端口"):
            load_touchstone_s2p(path)

    def test_garbage_fail_loud(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.s2p"
        p.write_bytes(b"this is not a touchstone")
        with pytest.raises(ValueError):
            load_touchstone_s2p(p)


# ---------------------------------------------------------------------------
# 等价钉 3：adapters/ads_netlist._read_snp_meta
# ---------------------------------------------------------------------------


class TestAdsNetlistReadSnpMeta:
    @pytest.mark.parametrize("n_ports,form", [(1, "RI"), (2, "DB"), (3, "DB"),
                                              (4, "RI")])
    def test_meta_matches_skrf_reference(self, tmp_path: Path, n_ports: int,
                                         form: str) -> None:
        freq = skrf.Frequency(1.5, 3.5, 41, "GHz")
        path = _skrf_write(tmp_path / f"t{n_ports}.s{n_ports}p", freq,
                           _s_matrix(freq, n_ports), form=form)
        ref = skrf.Network(str(path))
        meta = _read_snp_meta(path)
        assert meta == {
            "n_ports": ref.nports,
            "fstart_hz": float(ref.f.min()),
            "fstop_hz": float(ref.f.max()),
            "npoints": int(ref.frequency.npoints),
        }

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _read_snp_meta(tmp_path / "missing.s2p")

    def test_garbage_fail_loud(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.s2p"
        p.write_bytes(b"not a touchstone")
        with pytest.raises(ValueError):
            _read_snp_meta(p)


# ---------------------------------------------------------------------------
# 等价钉 4：service/dataset_edb_lane._read_touchstone_meta
# ---------------------------------------------------------------------------


class TestDatasetEdbLaneReadTouchstoneMeta:
    def test_meta_matches_direct_parse(self, tmp_path: Path) -> None:
        # EDB 道语料：skrf 写盘 4 端口（*_export.s4p 真机产物形态）
        freq = skrf.Frequency(2.0, 3.0, 5, "GHz")
        path = _skrf_write(tmp_path / "x_export.s4p", freq, _s_matrix(freq, 4))
        meta = _read_touchstone_meta(path)
        ref = skrf.Network(str(path))
        assert meta == {
            "n_ports": int(ref.s.shape[1]),
            "n_freqs": int(ref.s.shape[0]),
            "f_min_ghz": float(ref.f[0]) / 1e9,
            "f_max_ghz": float(ref.f[-1]) / 1e9,
        }

    def test_corrupt_raises_for_candidate_skip(self, tmp_path: Path) -> None:
        # 调用方约定：异常 → 候选级跳过（坏③语料 bytes 原样）
        p = tmp_path / "corrupt.s4p"
        p.write_bytes(b"this is not a touchstone")
        with pytest.raises(ValueError):
            _read_touchstone_meta(p)


# ---------------------------------------------------------------------------
# 等价钉 5：service/diagnosis_service._load_touchstone
# ---------------------------------------------------------------------------


class TestDiagnosisServiceLoadTouchstone:
    @pytest.mark.parametrize("form", ["RI", "DB"])
    def test_s11_s21_matches_skrf_reference(self, tmp_path: Path,
                                            form: str) -> None:
        freq = skrf.Frequency(1.0, 2.0, 5, "GHz")
        s = _s_matrix(freq, 2)
        path = _skrf_write(tmp_path / f"d.{form.lower()}.s2p", freq, s,
                           form=form)
        out = _load_touchstone(str(path), need_s21=True)
        ref = skrf.Network(str(path))
        assert len(out["freq_ghz"]) == ref.f.size
        assert out["freq_ghz"] == [round(float(v) / 1e9, 12)
                                   for v in ref.frequency.f]
        assert out["s11"] == [[complex(v).real, complex(v).imag]
                              for v in ref.s[:, 0, 0]]
        assert out["s21"] == [[complex(v).real, complex(v).imag]
                              for v in ref.s[:, 1, 0]]

    def test_one_port_need_s21_rejected(self, tmp_path: Path) -> None:
        freqs = np.linspace(1e9, 2e9, 3)
        path = write_touchstone_one_port(tmp_path / "one.s1p", freqs,
                                         np.full(3, 50.0 + 0j))
        with pytest.raises(ValueError, match="2 端口"):
            _load_touchstone(str(path), need_s21=True)

    def test_missing_file_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="不存在"):
            _load_touchstone(str(tmp_path / "missing.s2p"), need_s21=False)


# ---------------------------------------------------------------------------
# 棘轮：src/rfauto 全树 skrf.Network(<位置实参>) 直读散点白名单
# ---------------------------------------------------------------------------

#: 单源入口自身（interchange.read_touchstone/export_touchstone 内部 skrf
#: 解析= sanctioned；strict 契约钩子在此，非散点）。
_SINGLE_SOURCE_ENTRIES: set[tuple[str, str]] = {
    ("adapters/interchange.py", "read_touchstone"),
    ("adapters/interchange.py", "export_touchstone"),
}

#: 当前余量散点名单（file → 外层函数名集合；棘轮只收不放——白名单外新增
#: 位点必红。reason 标注三坑风险与不迁/待迁状态）。
_REMAINING_FILE_READ_SITES: dict[tuple[str, str], str] = {
    # ── 本席如实不迁（语义差登记） ──
    ("core/com_pam4.py", "_validate_s4p"):
        "语料=单行 4 端口 v1.0（skrf 容忍、parser 结构性拒绝，实测证伪）"
        "非能力子集；core 层不可 import adapters 双路不通",
    ("core/macromodel.py", "request_from_touchstone"):
        "z0.ndim==2 检查耦合 skrf 文件读形态+语料含任意来源 v2.0 变体，保守不迁",
    ("core/cable_channel.py", "load_connector"):
        "实测连接器件直读（2 端口校验在先），后续席位候选",
    # ── 本席禁改面 ──
    ("cli/domains/em.py", "_load_network"):
        "cli/ 在 R-27 禁改清单",
    # ── 后续席位候选（按三坑风险排序的余量） ──
    ("adapters/vna_adapter.py", "solve"):
        "2x-thru 实测件直读（#248 外来文件名面）",
    ("linkage/ads_active_chain.py", "chain_manual_reference"):
        "手工链参考件直读",
    ("linkage/ads_active_chain.py", "loadpull_point_closed_form"):
        "loadpull 参考件直读",
    ("linkage/ads_template_family.py", "compare_family_result"):
        "家族对拍参考件直读（#287 对拍面候选）",
    ("linkage/field_circuit_anchor.py", "skrf_reference_cascade"):
        "场路锚参考级联直读",
    ("linkage/field_circuit_nonlinear.py", "y_harmonics_from_touchstone"):
        "谐波 Y 面直读",
    ("measurement/calibration.py", "load_calkit"):
        "校准件 kit 直读（#248 外来文件名面）",
    ("measurement/import_data.py", "import_touchstone"):
        "测量导入（扩展名白名单+错误收敛已在先）",
    ("measurement/vna_capture.py", "from_touchstone"):
        "VNA 捕获直读",
    ("optimization/optimizer.py", "build_objective"):
        "缓存 params.s*p 直读（自产文件，低危）",
    ("service/active_chain_service.py", "_sparams_at_f0"):
        "有源链 f0 采样直读",
    ("service/animation/loaders.py", "load_snip"):
        "动画 snip 源直读",
    ("service/api/reporting.py", "generate_report_for_run"):
        "报告缓存直读（自产文件，低危）",
    ("service/api/run_core.py", "run_once"):
        "run 缓存直读（自产文件，低危）",
    ("service/cascade_service.py", "_extract_il_from_network"):
        "级联 IL 资产直读（2 端口校验在先）",
    ("service/edb_health_gate.py", "_load_touchstone_gate"):
        "健康门直读（corrupt 拦截语义在先，#316 多报方向）",
    ("service/em_diff_service.py", "_load_touchstone"):
        "EM 差分直读",
    ("service/em_metrics_service.py", "extract_touchstone_metrics"):
        "EM 指标提取直读",
    ("service/format_overview_service.py", "_load_touchstone"):
        "格式概览直读",
    ("service/health_service.py", "_load_touchstone"):
        "健康服务候选序直读（自产 params.s*p 为主，低危）",
    ("service/interop_service.py", "ts21_write"):
        "互操作 v2 写出/回读（写出验证面）",
    ("service/si_channel_service.py", "_load_source"):
        "SI 通道源直读（后缀白名单在先）",
    ("service/vna_service.py", "vna_calibrate_standalone"):
        "VNA 校准标准件直读（#248 外来文件名面）",
    ("service/vna_service.py", "vna_en_report"):
        "VNA EN 报告直读",
}


def _scan_file_read_sites(root: Path) -> set[tuple[str, str]]:
    """AST 扫描 ``skrf.Network(<位置实参>)`` 直读形态（keyword-only 构造
    形态不计）→ (相对 file, 外层函数名) 集合。"""
    found: set[tuple[str, str]] = set()
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        tree = ast.parse(py.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "Network"
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id == "skrf" and node.args):
                continue
            cur: ast.AST = node
            func: str | None = None
            while cur in parents:
                cur = parents[cur]
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func = cur.name
            found.add((rel, func or "<module>"))
    return found


class TestTouchstoneFileReadRatchet:
    def test_no_new_scattered_sites(self) -> None:
        found = _scan_file_read_sites(SRC_ROOT)
        allowed = _SINGLE_SOURCE_ENTRIES | set(_REMAINING_FILE_READ_SITES)
        new_sites = found - allowed
        assert not new_sites, (
            "发现白名单外新增 skrf.Network 直读散点（棘轮只收不放）——"
            "请改走 core/touchstone_parser 或 interchange.read_touchstone "
            f"单源，或（语义差如实登记时）同笔更新 "
            f"tests/unit/test_touchstone_consumer_migration.py 白名单："
            f"{sorted(new_sites)}")

    def test_migrated_files_are_clean(self) -> None:
        """本席五迁移文件回归复染即红（不在白名单，new_sites 断言已覆盖；
        本钉显式点名防白名单误收迁移文件）。"""
        migrated = {
            "core/vendor_passives.py", "core/si_channel.py",
            "adapters/ads_netlist.py", "service/dataset_edb_lane.py",
            "service/diagnosis_service.py",
        }
        found = _scan_file_read_sites(SRC_ROOT)
        relapse = sorted(rel for rel, _fn in found if rel in migrated)
        assert not relapse, f"已迁移文件复染直读散点: {relapse}"

    def test_single_source_entries_still_present(self) -> None:
        found = _scan_file_read_sites(SRC_ROOT)
        missing = _SINGLE_SOURCE_ENTRIES - found
        assert not missing, (
            f"单源入口位点消失（interchange 内部 skrf 解析形态变更）: "
            f"{sorted(missing)}")
