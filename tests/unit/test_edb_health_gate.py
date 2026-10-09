"""EDB 快车道批处理产物健康门测试（service/edb_health_gate.py）——全 fake 零真机。

- 合成 Touchstone（skrf 现场构造写出/读回，test_ads_batch 同款 form="ri"）
  覆盖五路径：健康 / 失配（端口数错）/ 非无源 / 文件缺失 / 文件损坏
  （+skrf 环境缺失环境类路径，NaN 数据损坏路径）。
- 边界浮点余量钉（2026-10-08 W5 复核席，与 s_split_window 同家法）：
  s11_dip 恰等门值（explicit/template 双作用域违约侧门值）与
  passivity 恰等容差带缘——恰等构造经 double 换算/表示噪声可落违约
  侧，闭边界语义须 PASS 不误 FAIL。
- 批处理失败态：rc!=0 / rc=None 前置失败 / watchdog 超时 / 回执缺失 /
  export 未请求（-BatchSolve 断链指纹）——全部手构 hfss_batch 契约
  dict，零 Popen 零真机。
- 判据纪律钉：#122（UNKNOWN 不冒充 FAIL/PASS：verdict 聚合 + 未声明
  f0 + f0 出跨度不外推 + gate=None 族不硬套）、#314（Touchstone 全矩阵
  无掩码载体按全矩阵判但如实声明）、#274（S11 门按模板作用域分派：
  显式 > 模板登记表 > 通用缺省，登记 None=该族不设门）、容差带
  （passivity 1% 容差两侧）、S11@f0 语义（读 f0 处非全带 argmin）。
- s_split_window（W1 冒烟门语义仲裁落档，2026-10-09）：登记族
  |S21|/|S31|@f0 分配窗 [-3.8,-2.5] 双腿判（edb_power_divider/wilkinson）/
  显式窗覆盖与形态非法回退 / 未登记族判据缺席（缺席=不判，非 UNKNOWN
  冒充）/ 窗界两侧各单腿 FAIL 形态 / 2 端口-f0 缺失-出跨度-无数据四路
  UNKNOWN。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.service import edb_health_gate as ehg
from rfauto.service.edb_health_gate import check_edb_batch_health

F0_GHZ = 2.5
SPAN_GHZ = 0.5
N_FREQ = 41


# ---------------------------------------------------------------------------
# 合成数据助手（skrf 现场构造，零真机）
# ---------------------------------------------------------------------------

def _freq_hz(n_freq: int = N_FREQ) -> np.ndarray:
    return np.linspace((F0_GHZ - SPAN_GHZ) * 1e9, (F0_GHZ + SPAN_GHZ) * 1e9,
                       n_freq)


def _passive_s(n_freq: int = N_FREQ, n_ports: int = 2,
               s11_mag: float = 0.1) -> np.ndarray:
    """健康无源互易 S：对角 s11_mag、非对角等幅 b，特征值 |s11±b|≤1
    保证 σmax<1（2 端口 σmax=s11_mag+b；n 端口 all-ones 向量上
    s11_mag+(n-1)b<1）。"""
    s = np.zeros((n_freq, n_ports, n_ports), dtype=complex)
    b = 0.6 / np.sqrt(max(n_ports - 1, 1))
    for i in range(n_ports):
        s[:, i, i] = s11_mag
        for j in range(n_ports):
            if i != j:
                s[:, i, j] = b
    return s


def _write_touchstone(path: Path, s: np.ndarray,
                      freq_hz: np.ndarray | None = None) -> Path:
    import skrf

    freq = skrf.Frequency.from_f(
        _freq_hz(len(s)) if freq_hz is None else freq_hz, unit="Hz")
    path.parent.mkdir(parents=True, exist_ok=True)
    skrf.Network(frequency=freq, s=s, z0=50).write_touchstone(
        str(path), form="ri")
    return path


def _batch_ok(snp: Path | None, n_ports: int | None = None,
              **overrides) -> dict:
    """hfss_batch.solve_project_batch 成功回执（契约 dict，手构零真机）。"""
    export = None
    if snp is not None:
        export = {"ok": True, "rc": 0, "timed_out": False,
                  "out_file": str(snp), "n_ports": n_ports, "errors": []}
    result = {
        "ok": True, "rc": 0, "timed_out": False,
        "project": "fake.aedb", "project_kind": "aedb",
        "logfile": "fake_batch.log", "logfile_tail": "",
        "artifacts": [str(snp)] if snp is not None else [],
        "export": export, "elapsed_s": 12.3, "errors": [],
    }
    result.update(overrides)
    return result


def _spec(n_ports: int, f0_ghz: float | None = F0_GHZ,
          template: str | None = None) -> dict:
    """EDB 声明式 spec 最小形（wave_port 发射族形态，port_nr 1..n）。"""
    spec: dict = {
        "name": "fake_edb",
        "stackup": {"layers": [
            {"name": "GND", "thickness_mm": 0.035, "layer_type": "signal"},
            {"name": "SUB", "thickness_mm": 0.5, "layer_type": "dielectric",
             "permittivity": 4.4},
        ]},
        "ports": [
            {"type": "wave_port", "name": f"p{i}", "port_nr": i,
             "trace": "t1", "point_mm": [0.0, float(i)]}
            for i in range(1, n_ports + 1)
        ],
    }
    if f0_ghz is not None:
        spec["sim_setup"] = {"type": "hfss", "f0_ghz": f0_ghz,
                             "sweep": {"start_ghz": F0_GHZ - SPAN_GHZ,
                                       "stop_ghz": F0_GHZ + SPAN_GHZ}}
    if template is not None:
        spec["template"] = template
    return spec


def _by_factor(report: dict) -> dict:
    return {c["factor"]: c for c in report["criteria"]}


@pytest.fixture()
def snp_ok(tmp_path: Path) -> Path:
    """健康 2 端口 Touchstone：|S11|=0.1（−20dB）、|Sij|=0.8、σmax=0.9。"""
    return _write_touchstone(tmp_path / "out.s2p", _passive_s())


# ---------------------------------------------------------------------------
# solve_status：rc/超时态
# ---------------------------------------------------------------------------

class TestSolveStatus:
    def test_ok_batch_passes(self, snp_ok):
        report = check_edb_batch_health(_batch_ok(snp_ok, 2), spec=_spec(2))
        f = _by_factor(report)["solve_status"]
        assert f["status"] == "PASS"
        assert f["evidence"]["rc"] == 0
        assert f["evidence"]["timed_out"] is False

    def test_rc_nonzero_fails(self, tmp_path):
        report = check_edb_batch_health(_batch_ok(None, rc=1, ok=False),
                                        spec=_spec(2))
        f = _by_factor(report)["solve_status"]
        assert f["status"] == "FAIL"
        assert "rc=1" in f["detail"]
        assert report["verdict"] == "FAIL"

    def test_rc_none_prelaunch_fails(self):
        """rc=None=前置失败（路径/exe/发射，进程未拉起）→ FAIL。"""
        result = _batch_ok(None, rc=None, ok=False)
        report = check_edb_batch_health(result, spec=_spec(2))
        assert _by_factor(report)["solve_status"]["status"] == "FAIL"
        assert "前置失败" in _by_factor(report)["solve_status"]["detail"]

    def test_timed_out_fails(self, snp_ok):
        """watchdog 超时整树击杀（#157 家族）→ FAIL，击杀后产物不可信。"""
        result = _batch_ok(snp_ok, 2, timed_out=True, ok=False, rc=-15)
        report = check_edb_batch_health(result, spec=_spec(2))
        f = _by_factor(report)["solve_status"]
        assert f["status"] == "FAIL"
        assert "超时" in f["detail"]
        assert report["verdict"] == "FAIL"

    def test_missing_batch_result_unknown(self, snp_ok):
        """回执缺失 → 求解态 UNKNOWN（不冒充 FAIL，#122）。"""
        report = check_edb_batch_health(None, touchstone_path=snp_ok,
                                        spec=_spec(2))
        assert _by_factor(report)["solve_status"]["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# touchstone：五路径（健康/缺失/无发现/损坏/环境）+ 断链指纹
# ---------------------------------------------------------------------------

class TestTouchstone:
    def test_healthy_end_to_end_pass(self, snp_ok):
        report = check_edb_batch_health(_batch_ok(snp_ok, 2), spec=_spec(2))
        assert report["verdict"] == "PASS"
        assert report["ok"] is True
        assert report["touchstone"] == str(snp_ok)
        assert all(c["status"] == "PASS" for c in report["criteria"])
        assert report["summary"]["n_pass"] == 6

    def test_file_missing_fails(self, tmp_path):
        """export.out_file 指向不存在路径 → FAIL（不静默）。"""
        ghost = tmp_path / "ghost.s2p"
        report = check_edb_batch_health(_batch_ok(ghost, 2), spec=_spec(2))
        f = _by_factor(report)["touchstone"]
        assert f["status"] == "FAIL"
        assert report["verdict"] == "FAIL"
        assert any("ghost.s2p" in e for e in report.get("errors", []))

    def test_no_discovery_fails(self):
        """export 未请求（None）且 artifacts 无 .sNp → FAIL（-BatchSolve
        只求解不产网络参数的断链指纹）。"""
        result = _batch_ok(None)
        result["export"] = None
        result["artifacts"] = ["fake.aedbresults/some.prof"]
        report = check_edb_batch_health(result, spec=_spec(2))
        f = _by_factor(report)["touchstone"]
        assert f["status"] == "FAIL"
        assert "断链" in f["detail"]
        assert report["verdict"] == "FAIL"

    def test_corrupt_file_fails(self, tmp_path):
        """文件存在但非 Touchstone（证据损坏）→ FAIL（#316 多报方向），
        S 判据族不冒充 PASS。"""
        bad = tmp_path / "bad.s2p"
        bad.write_text("garbage not a touchstone", encoding="ascii")
        report = check_edb_batch_health(_batch_ok(bad, 2), spec=_spec(2))
        assert _by_factor(report)["touchstone"]["status"] == "FAIL"
        for name in ("port_count", "passivity", "s11_dip", "reciprocity"):
            assert _by_factor(report)[name]["status"] == "UNKNOWN"
        assert report["verdict"] == "FAIL"

    def test_skrf_unavailable_unknown(self, snp_ok, monkeypatch):
        """skrf 环境缺失 → 在档不可判读 = UNKNOWN（不可证实≠失败，#122），
        verdict UNKNOWN 非 FAIL。"""
        monkeypatch.setitem(sys.modules, "skrf", None)
        report = check_edb_batch_health(_batch_ok(snp_ok, 2), spec=_spec(2))
        f = _by_factor(report)["touchstone"]
        assert f["status"] == "UNKNOWN"
        assert report["verdict"] == "UNKNOWN"

    def test_artifact_scan_fallback(self, snp_ok):
        """export 缺 out_file 时回执 artifacts 扫 .sNp 兜底发现。"""
        result = _batch_ok(None)
        result["export"] = {"ok": True, "rc": 0, "timed_out": False,
                            "out_file": None, "errors": []}
        result["artifacts"] = [str(snp_ok)]
        report = check_edb_batch_health(result, spec=_spec(2))
        assert _by_factor(report)["touchstone"]["status"] == "PASS"
        assert report["touchstone"] == str(snp_ok)

    def test_explicit_path_overrides_export(self, snp_ok, tmp_path):
        """显式 kwarg 路径优先于回执 export.out_file。"""
        result = _batch_ok(tmp_path / "stale.s2p", 2)
        report = check_edb_batch_health(result, spec=_spec(2),
                                        touchstone_path=snp_ok)
        assert report["verdict"] == "PASS"
        assert report["touchstone"] == str(snp_ok)


# ---------------------------------------------------------------------------
# port_count：vs spec 声明
# ---------------------------------------------------------------------------

class TestPortCount:
    def test_mismatch_fails(self, snp_ok):
        """spec 声明 3 端口 vs 文件 2 端口 → FAIL。"""
        report = check_edb_batch_health(_batch_ok(snp_ok, 2), spec=_spec(3))
        f = _by_factor(report)["port_count"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["observed_ports"] == 2
        assert f["evidence"]["expected_ports"] == 3
        assert report["summary"]["fail_factors"] == ["port_count"]

    def test_match_passes(self, snp_ok):
        report = check_edb_batch_health(_batch_ok(snp_ok, 2), spec=_spec(2))
        assert _by_factor(report)["port_count"]["status"] == "PASS"

    def test_no_spec_declaration_unknown(self, snp_ok):
        """spec 未声明端口 → UNKNOWN 不硬判（实测数留 evidence）。"""
        report = check_edb_batch_health(_batch_ok(snp_ok, 2))
        f = _by_factor(report)["port_count"]
        assert f["status"] == "UNKNOWN"
        assert f["evidence"]["observed_ports"] == 2
        assert f["evidence"]["expected_ports"] is None

    def test_generic_number_form_counted(self, snp_ok):
        """通用形态 number 键同池取最大编号（contract 双形态）。"""
        spec = _spec(2)
        spec["ports"] = [{"number": 1, "type": "circuit"},
                         {"number": 2, "type": "circuit"}]
        report = check_edb_batch_health(_batch_ok(snp_ok, 2), spec=spec)
        assert _by_factor(report)["port_count"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# passivity：σmax≤1+容差（复数域）
# ---------------------------------------------------------------------------

class TestPassivity:
    def test_violation_fails(self, tmp_path):
        """σmax=1.05 > 1.01 → FAIL（对角 0.1 + 非对角 0.95）。"""
        s = _passive_s()
        s[:, 0, 1] = s[:, 1, 0] = 0.95  # σmax = 0.1 + 0.95 = 1.05
        snp = _write_touchstone(tmp_path / "gain.s2p", s)
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        f = _by_factor(report)["passivity"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["sigma_max"] > 1.01
        assert f["evidence"]["metric"].startswith("sigma_max")
        assert report["verdict"] == "FAIL"

    def test_within_tolerance_passes(self, tmp_path):
        """σmax=1.005 ≤ 1.01（1% 容差带内）→ PASS（容差语义钉）。"""
        s = _passive_s(s11_mag=0.1)  # σmax = 0.1 + 0.6 = 0.7 … 抬到 1.005
        s[:, 0, 1] = s[:, 1, 0] = 0.905  # σmax = 0.1 + 0.905 = 1.005
        snp = _write_touchstone(tmp_path / "tol.s2p", s)
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        f = _by_factor(report)["passivity"]
        assert f["status"] == "PASS"
        assert f["evidence"]["sigma_max"] == pytest.approx(1.005, abs=1e-3)

    def test_beyond_tolerance_fails(self, tmp_path):
        """σmax=1.02 > 1.01（容差带外）→ FAIL（带内外界钉）。"""
        s = _passive_s()
        s[:, 0, 1] = s[:, 1, 0] = 0.92  # σmax = 1.02
        snp = _write_touchstone(tmp_path / "tol2.s2p", s)
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        assert _by_factor(report)["passivity"]["status"] == "FAIL"

    def test_nan_data_fails(self, tmp_path):
        """S 含 NaN（数据损坏）→ FAIL（skrf NaN 写出/读回实测在档）。"""
        s = _passive_s()
        s[3, 0, 0] = np.nan
        snp = _write_touchstone(tmp_path / "nan.s2p", s)
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        f = _by_factor(report)["passivity"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["non_finite_count"] >= 1
        assert report["verdict"] == "FAIL"

    def test_tolerance_boundary_exact_value_passes(self, tmp_path):
        """σmax 恰在容差带缘（1.01）→ PASS（2026-10-08 W5 复核席缺陷
        修复钉，与 s_split_window 恰等边界钉同型）。

        暴露实证（门值域广扫 114/201 组合落违约侧）：十进制 d+o=1.01 的
        double 表示 + SVD 舍入使恰等构造读 σmax=1.0100000000000002
        （dev +2.2e-16，比容差粒度 0.01 低 14 个量级）——字面
        ``sigma_max > PASSIVITY_TOLERANCE`` 会把"恰在带缘"（闭语义
        "≤ 容差为过"应 PASS）误判 FAIL。修复=线性域留
        _PASSIVITY_LINEAR_EPS=1e-9（无 dB 换算，噪声源是表示+SVD 舍入，
        暴露面与 dB 门同型）。
        """
        s = np.zeros((N_FREQ, 2, 2), dtype=complex)
        s[:, 0, 0] = s[:, 1, 1] = 0.13
        s[:, 0, 1] = s[:, 1, 0] = 0.88  # 解析 σmax=0.13+0.88=1.01 恰带缘
        # 缺除断面自证：该构造在严格比较下确落违约侧（本机 BLAS 实测）
        sig = float(np.max(np.linalg.svd(s, compute_uv=False)))
        assert sig == pytest.approx(1.01, abs=1e-12)  # 恰等边界形态
        assert sig > 1.01  # 旧字面比较必误 FAIL 的违约侧读数
        snp = _write_touchstone(tmp_path / "bnd_tol.s2p", s)
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        f = _by_factor(report)["passivity"]
        assert f["status"] == "PASS"  # 修复后带缘恰等如实 PASS
        assert f["evidence"]["sigma_max"] == pytest.approx(1.01, abs=1e-6)


# ---------------------------------------------------------------------------
# reciprocity：|Sij−Sji| 掩码纪律 #314
# ---------------------------------------------------------------------------

class TestReciprocity:
    def test_violation_fails(self, tmp_path):
        """S12≠S21（差 0.3）→ FAIL，worst_pair 留证据。"""
        s = _passive_s()
        s[:, 0, 1] = 0.8
        s[:, 1, 0] = 0.5
        snp = _write_touchstone(tmp_path / "nonrecip.s2p", s)
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        f = _by_factor(report)["reciprocity"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["max_symmetry_violation"] == pytest.approx(0.3,
                                                                       abs=1e-6)
        assert f["evidence"]["worst_pair"] == [0, 1]
        assert report["verdict"] == "FAIL"

    def test_full_matrix_semantics_declared(self, snp_ok):
        """#314：无掩码数据按全矩阵判但如实声明（detail+evidence 双面）。"""
        report = check_edb_batch_health(_batch_ok(snp_ok, 2), spec=_spec(2))
        f = _by_factor(report)["reciprocity"]
        assert f["status"] == "PASS"
        assert f["evidence"]["measured_mask"] is None
        assert "全矩阵" in f["evidence"]["mask_semantics"]

    def test_single_port_trivially_reciprocal(self, tmp_path):
        """单端口无跨端口对 → 平凡真如实注记（非 UNKNOWN 冒充）。"""
        s = np.zeros((N_FREQ, 1, 1), dtype=complex)
        s[:, 0, 0] = 0.5
        snp = _write_touchstone(tmp_path / "one.s1p", s)
        spec = _spec(1)
        spec["sim_setup"] = {}  # 单端口无 f0，s11_dip 走 UNKNOWN 不拦
        report = check_edb_batch_health(_batch_ok(snp, 1), spec=spec)
        f = _by_factor(report)["reciprocity"]
        assert f["status"] == "PASS"
        assert "平凡" in f["detail"]


# ---------------------------------------------------------------------------
# s11_dip：S11@f0 谷深 + #274 门作用域分派
# ---------------------------------------------------------------------------

class TestS11Dip:
    def test_deep_dip_passes_default_gate(self, tmp_path):
        """|S11|=0.05（−26dB）≤ 通用缺省门 −10dB（回波损耗 ≥10dB 惯例）。"""
        s = _passive_s(s11_mag=0.05)
        snp = _write_touchstone(tmp_path / "dip.s2p", s)
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "PASS"
        assert f["evidence"]["gate_scope"] == "default"
        assert f["evidence"]["gate_db"] == -10.0
        assert f["evidence"]["s11_db_at_f0"] == pytest.approx(-26.0, abs=0.5)

    def test_shallow_fails_explicit_gate(self, tmp_path):
        """|S11|=0.5（−6dB）> 显式门 −10dB → FAIL。"""
        s = _passive_s(s11_mag=0.5)
        snp = _write_touchstone(tmp_path / "flat.s2p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2), s11_dip_gate_db=-10.0)
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["gate_scope"] == "explicit"

    def test_reads_at_f0_not_band_min(self, tmp_path):
        """带内深谷在 2.2GHz 而 f0=2.5GHz 处 |S11|=0.5 → FAIL——证明读
        f0 处而非全带 argmin（谷深语义按 spec.sim_setup.f0_ghz）。"""
        freq = _freq_hz()
        mag = 0.5 - 0.48 * np.exp(-((freq - 2.2e9) / 0.06e9) ** 2)
        s = np.zeros((len(freq), 2, 2), dtype=complex)
        s[:, 0, 0] = s[:, 1, 1] = mag
        s[:, 0, 1] = s[:, 1, 0] = 0.5  # σmax ≤ 1.0 无源性不拦
        snp = _write_touchstone(tmp_path / "notch.s2p", s, freq)
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2), s11_dip_gate_db=-10.0)
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["s11_db_at_f0"] == pytest.approx(-6.0, abs=0.5)

    def test_f0_outside_span_unknown(self, tmp_path):
        """f0 不在扫频跨度内 → UNKNOWN 不外推（#122）。"""
        s = _passive_s()
        snp = _write_touchstone(tmp_path / "span.s2p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2, f0_ghz=5.0),
            s11_dip_gate_db=-10.0)
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "UNKNOWN"
        assert "外推" in f["detail"]

    def test_no_f0_declared_unknown(self, snp_ok):
        """spec 未声明 f0 → UNKNOWN（未声明判定目标不硬判，#122）。"""
        report = check_edb_batch_health(_batch_ok(snp_ok, 2),
                                        spec=_spec(2, f0_ghz=None))
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "UNKNOWN"
        assert "未声明" in f["detail"]

    def test_template_registry_gate_dispatch(self, tmp_path, monkeypatch):
        """#274 家法：模板登记门生效（gate_scope=template:<名>）。"""
        monkeypatch.setattr(ehg, "S11_DIP_DB_BY_TEMPLATE",
                            {"edb_pdiv": -3.0})
        s = _passive_s(s11_mag=0.5)  # −6dB：过 −3 门、不过 −10 门
        snp = _write_touchstone(tmp_path / "tpl.s2p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2, template="edb_pdiv"))
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "PASS"
        assert f["evidence"]["gate_scope"] == "template:edb_pdiv"
        assert f["evidence"]["gate_db"] == -3.0

    def test_template_registry_none_disables_gate(self, tmp_path,
                                                   monkeypatch):
        """登记值 None=该族显式不设门 → 已测数值 + UNKNOWN（不硬套缺省门）。"""
        monkeypatch.setattr(ehg, "S11_DIP_DB_BY_TEMPLATE",
                            {"edb_broadband": None})
        s = _passive_s(s11_mag=0.5)
        snp = _write_touchstone(tmp_path / "tpl2.s2p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2, template="edb_broadband"))
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "UNKNOWN"
        assert f["evidence"]["s11_db_at_f0"] == pytest.approx(-6.0, abs=0.5)
        assert f["evidence"]["gate_db"] is None

    def test_explicit_gate_overrides_template(self, tmp_path, monkeypatch):
        """显式 kwarg 门 > 模板登记门 > 缺省门（分派序钉）。"""
        monkeypatch.setattr(ehg, "S11_DIP_DB_BY_TEMPLATE",
                            {"edb_pdiv": -3.0})
        s = _passive_s(s11_mag=0.05)  # −26dB
        snp = _write_touchstone(tmp_path / "tpl3.s2p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2, template="edb_pdiv"),
            s11_dip_gate_db=-40.0)
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["gate_scope"] == "explicit"
        assert f["evidence"]["gate_db"] == -40.0

    def test_unregistered_template_falls_back_to_default(self, tmp_path):
        """未登记模板回退通用缺省门（登记表 lookup miss 语义）。"""
        s = _passive_s(s11_mag=0.5)  # −6dB > 缺省 −10dB
        snp = _write_touchstone(tmp_path / "tpl4.s2p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2, template="unregistered_tpl"))
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["gate_scope"] == "default"

    def test_generic_adaptive_freq_form_accepted(self, tmp_path):
        """通用形态 adaptive_freq_ghz 同样作为 f0 口径（两形态契约）。"""
        s = _passive_s(s11_mag=0.05)
        snp = _write_touchstone(tmp_path / "adapt.s2p", s)
        spec = _spec(2)
        spec["sim_setup"] = {"type": "hfss", "adaptive_freq_ghz": F0_GHZ,
                             "f_start_ghz": 2.0, "f_stop_ghz": 3.0}
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=spec, s11_dip_gate_db=-20.0)
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "PASS"
        assert f["evidence"]["f0_ghz"] == F0_GHZ

    def test_gate_boundary_exact_value_passes(self, tmp_path, monkeypatch):
        """门值恰等 → PASS（2026-10-08 W5 复核席缺陷修复钉）。

        缺陷实证（与 s_split_window 恰等边界钉同款）：门值恰等的物理
        幅值 |Γ|=10^(门/20) 经 double 域 20·log10 往返带量化噪声，门值
        域扫描 [-40,-1] 0.1dB 步长 30/391 个门值落违约侧（最大偏差
        +3.6e-15 dB）——字面 ``s11_db > gate_db`` 会把语义上"恰达门"
        （门语义=实测 ≤ 门为过，闭边界）的读数误判 FAIL。修复=比较留
        _S11_DIP_DB_EPS=1e-9（比门粒度 1dB 量级低 9 个数量级）。两个
        门作用域各钉一个实测违约侧门值：-7.2dB（explicit，读
        -7.199999999999999）与 -13.6dB（template 登记，读
        -13.599999999999998）。
        """
        # 先证构造的边界形态：|Γ|=10^(-7.2/20) 的 dB 读数在本机落在
        # 违约侧（旧字面比较必误 FAIL 的断面；skrf ri 写出为全精度
        # repr 无损、np.interp 恰格点返回精确样本，全链读数与此一致）
        raw_db = float(20.0 * np.log10(10.0 ** (-7.2 / 20.0)))
        assert raw_db == pytest.approx(-7.2, abs=1e-12)  # 恰等边界形态
        assert raw_db > -7.2  # 违约侧断面（量化噪声方向实证）
        mag = 10.0 ** (-7.2 / 20.0)
        s = np.zeros((N_FREQ, 2, 2), dtype=complex)
        s[:, 0, 0] = s[:, 1, 1] = mag
        s[:, 0, 1] = s[:, 1, 0] = 0.1  # σmax=0.536 无源性不拦
        snp = _write_touchstone(tmp_path / "bnd.s2p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2), s11_dip_gate_db=-7.2)
        f = _by_factor(report)["s11_dip"]
        assert f["status"] == "PASS"  # 修复后恰达门如实 PASS
        assert f["evidence"]["s11_db_at_f0"] == pytest.approx(-7.2, abs=1e-9)
        assert f["evidence"]["gate_scope"] == "explicit"
        # 模板作用域第二违约侧门值（-13.6dB，dev +1.8e-15）同钉
        monkeypatch.setattr(ehg, "S11_DIP_DB_BY_TEMPLATE", {"edb_bnd": -13.6})
        s2 = np.zeros((N_FREQ, 2, 2), dtype=complex)
        s2[:, 0, 0] = s2[:, 1, 1] = 10.0 ** (-13.6 / 20.0)
        s2[:, 0, 1] = s2[:, 1, 0] = 0.1  # σmax=0.309 无源性不拦
        snp2 = _write_touchstone(tmp_path / "bnd2.s2p", s2)
        report2 = check_edb_batch_health(
            _batch_ok(snp2, 2), spec=_spec(2, template="edb_bnd"))
        f2 = _by_factor(report2)["s11_dip"]
        assert f2["status"] == "PASS"
        assert f2["evidence"]["gate_scope"] == "template:edb_bnd"


# ---------------------------------------------------------------------------
# s_split_window：|S21|/|S31|@f0 等分分配窗（W1 冒烟门语义仲裁落档）
# ---------------------------------------------------------------------------

def _pdiv_s3(s21_db: float, s31_db: float, s11_mag: float = 0.1,
             scale: float = 1.0) -> np.ndarray:
    """3 端口功分器形态 S：对角 S11 + 两分配腿 S21/S31 等幅互易对称。

    scale 压整体幅度保 σmax≤1.01（无耗 3 端口不可能全匹配，Pozar
    §7.3——夹具是判据形态件不是物理样机；缩放计入 dB 断言期望值）。
    """
    b = 10.0 ** (s21_db / 20.0)
    c = 10.0 ** (s31_db / 20.0)
    s = np.zeros((N_FREQ, 3, 3), dtype=complex)
    s[:, 0, 0] = s11_mag
    s[:, 0, 1] = s[:, 1, 0] = b
    s[:, 0, 2] = s[:, 2, 0] = c
    return s * scale


def _spec3(template: str | None = "edb_power_divider",
           f0_ghz: float | None = F0_GHZ) -> dict:
    return _spec(3, f0_ghz=f0_ghz, template=template)


class TestSSplitWindow:
    def test_in_window_passes_on_registered_template(self, tmp_path):
        """健康分配（-3.2/-3.3 经 0.97 无源缩放）双落窗 [-3.8,-2.5] →
        PASS（W1 仲裁窗语义：字面 ≤-3.8 单边门在此必误杀）。"""
        s = _pdiv_s3(-3.2, -3.3, scale=0.97)  # σmax=0.993 无源
        snp = _write_touchstone(tmp_path / "pd_ok.s3p", s)
        report = check_edb_batch_health(_batch_ok(snp, 3), spec=_spec3())
        f = _by_factor(report)["s_split_window"]
        assert f["status"] == "PASS"
        assert f["evidence"]["window_db"] == [-3.8, -2.5]
        assert f["evidence"]["window_scope"] == "template:edb_power_divider"
        assert f["evidence"]["s21_db_at_f0"] == pytest.approx(-3.465, abs=0.02)
        assert f["evidence"]["s31_db_at_f0"] == pytest.approx(-3.565, abs=0.02)
        # 全绿七判据（窗生效族）+ verdict PASS
        assert report["verdict"] == "PASS"
        assert report["summary"]["n_pass"] == 7
        assert {c["factor"] for c in report["criteria"]} == {
            "solve_status", "touchstone", "port_count", "passivity",
            "s11_dip", "reciprocity", "s_split_window"}

    def test_leg_below_window_fails(self, tmp_path):
        """S21=-4.3dB 低于下界（S31 在窗内）→ 单腿 FAIL 点名 + 方向。"""
        s = _pdiv_s3(-4.3, -3.2)  # σmax=0.973 无源
        snp = _write_touchstone(tmp_path / "pd_low.s3p", s)
        report = check_edb_batch_health(_batch_ok(snp, 3), spec=_spec3())
        f = _by_factor(report)["s_split_window"]
        assert f["status"] == "FAIL"
        assert "S21" in f["detail"] and "低于下界" in f["detail"]
        assert "S31" not in f["detail"].split("，")[0]  # S31 未出窗不点名
        assert f["evidence"]["s21_db_at_f0"] == pytest.approx(-4.3, abs=0.02)
        assert report["summary"]["fail_factors"] == ["s_split_window"]
        assert report["verdict"] == "FAIL"

    def test_leg_above_window_fails_excess_gain(self, tmp_path):
        """S21=-2.4dB 高于上界（异常增益语义方向）→ FAIL 点名上界。"""
        s = _pdiv_s3(-2.4, -3.6, s11_mag=0.0)  # σmax=1.006 无源
        snp = _write_touchstone(tmp_path / "pd_hi.s3p", s)
        report = check_edb_batch_health(_batch_ok(snp, 3), spec=_spec3())
        f = _by_factor(report)["s_split_window"]
        assert f["status"] == "FAIL"
        assert "高于上界" in f["detail"]
        assert f["evidence"]["s21_db_at_f0"] > -2.5
        assert f["evidence"]["s31_db_at_f0"] == pytest.approx(-3.6, abs=0.02)

    def test_wilkinson_registry_entry_dispatches(self, tmp_path):
        """wilkinson（插件族同名物理窗）同窗生效：scope=template:wilkinson。"""
        s = _pdiv_s3(-3.2, -3.3, scale=0.97)
        snp = _write_touchstone(tmp_path / "pd_w.s3p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 3), spec=_spec3(template="wilkinson"))
        f = _by_factor(report)["s_split_window"]
        assert f["status"] == "PASS"
        assert f["evidence"]["window_scope"] == "template:wilkinson"
        assert f["evidence"]["window_db"] == [-3.8, -2.5]

    def test_unregistered_template_omits_factor(self, tmp_path):
        """未登记族：判据缺席（缺席=不判，非 UNKNOWN 也非 PASS 冒充），
        其余六判据照常全绿 verdict PASS。"""
        s = _pdiv_s3(-3.2, -3.3, scale=0.97)
        snp = _write_touchstone(tmp_path / "pd_u.s3p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 3), spec=_spec3(template="edb_coupler_x"))
        assert "s_split_window" not in _by_factor(report)
        assert report["summary"]["n_pass"] == 6
        assert report["verdict"] == "PASS"

    def test_registry_none_omits_factor(self, tmp_path, monkeypatch):
        """登记值 None=该族显式不设分配窗 → 判据缺席（#274 值 None 语义
        在窗登记表的同构落地）。"""
        monkeypatch.setattr(ehg, "S_WINDOW_DB_BY_TEMPLATE",
                            {"edb_pdiv_none": None})
        s = _pdiv_s3(-3.2, -3.3, scale=0.97)
        snp = _write_touchstone(tmp_path / "pd_n.s3p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 3), spec=_spec3(template="edb_pdiv_none"))
        assert "s_split_window" not in _by_factor(report)
        assert report["verdict"] == "PASS"

    def test_explicit_window_overrides_registry(self, tmp_path):
        """显式窗 > 登记窗（分派序钉）：窄窗下健康读数也可 FAIL。"""
        s = _pdiv_s3(-3.2, -3.3, scale=0.97)
        snp = _write_touchstone(tmp_path / "pd_e.s3p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 3), spec=_spec3(),
            s_split_window_db=(-3.3, -2.5))
        f = _by_factor(report)["s_split_window"]
        assert f["status"] == "FAIL"
        assert f["evidence"]["window_scope"] == "explicit"
        assert f["evidence"]["window_db"] == [-3.3, -2.5]

    def test_explicit_window_applies_on_unregistered_template(
            self, tmp_path):
        """显式窗对未登记族同样生效（判据随显式窗出现）。"""
        s = _pdiv_s3(-3.2, -3.3, scale=0.97)
        snp = _write_touchstone(tmp_path / "pd_e2.s3p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 3), spec=_spec3(template="no_tpl"),
            s_split_window_db=(-3.7, -2.5))  # 缩放后双腿 -3.465/-3.565 均入窗
        f = _by_factor(report)["s_split_window"]
        assert f["status"] == "PASS"
        assert f["evidence"]["window_scope"] == "explicit"

    def test_malformed_explicit_window_falls_back_to_registry(
            self, tmp_path):
        """显式窗形态非法不抛异常（#105）：errors 留痕 + 回退登记窗。"""
        s = _pdiv_s3(-3.2, -3.3, scale=0.97)
        snp = _write_touchstone(tmp_path / "pd_m.s3p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 3), spec=_spec3(), s_split_window_db="junk")
        assert any("s_split_window_db" in e for e in report.get("errors", []))
        f = _by_factor(report)["s_split_window"]
        assert f["status"] == "PASS"
        assert f["evidence"]["window_scope"] == "template:edb_power_divider"

    def test_two_ports_with_registered_template_unknown(self, tmp_path):
        """登记族 + 2 端口形态：无 S31 分配对 → UNKNOWN（不硬判）。"""
        snp = _write_touchstone(tmp_path / "pd_2p.s2p", _passive_s())
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2, template="edb_power_divider"))
        f = _by_factor(report)["s_split_window"]
        assert f["status"] == "UNKNOWN"
        assert "< 3" in f["detail"]

    def test_f0_missing_unknown(self, tmp_path):
        """登记族 + f0 未声明 → UNKNOWN（未声明判定目标不硬判，#122）。"""
        s = _pdiv_s3(-3.2, -3.3, scale=0.97)
        snp = _write_touchstone(tmp_path / "pd_nf.s3p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 3), spec=_spec3(f0_ghz=None))
        assert _by_factor(report)["s_split_window"]["status"] == "UNKNOWN"

    def test_f0_out_of_span_unknown(self, tmp_path):
        """登记族 + f0 出扫频跨度 → UNKNOWN 不外推（#122）。"""
        s = _pdiv_s3(-3.2, -3.3, scale=0.97)
        snp = _write_touchstone(tmp_path / "pd_span.s3p", s)
        report = check_edb_batch_health(
            _batch_ok(snp, 3), spec=_spec3(f0_ghz=5.0))
        f = _by_factor(report)["s_split_window"]
        assert f["status"] == "UNKNOWN"
        assert "外推" in f["detail"]

    def test_no_s_data_unknown(self, tmp_path):
        """登记族 + Touchstone 损坏 → 判据 UNKNOWN（不冒充 FAIL/PASS）。"""
        bad = tmp_path / "bad.s3p"
        bad.write_text("garbage not a touchstone", encoding="ascii")
        report = check_edb_batch_health(_batch_ok(bad, 3), spec=_spec3())
        assert _by_factor(report)["s_split_window"]["status"] == "UNKNOWN"

    def test_window_boundary_exact_values_pass_closed_interval(self, tmp_path):
        """闭区间边界值恰等腿 → PASS（2026-10-08 回取复核席缺陷修复钉）。

        缺陷实证：物理幅值恰为 10^(-2.5/20) 的腿经 double 域 dB 换算读
        -2.4999999999999996（量化噪声 4.4e-16），字面闭区间比较误判
        "高于上界"→FAIL，违背裁定语义「双边界闭区间」——修复=比较留
        _SPLIT_WINDOW_DB_EPS=1e-9（比窗粒度 0.1dB 低 8 个量级，同
        trl_solt._LINE_PASSIVE_MARGIN 家法）。双腿分别钉在下界 -3.8 与
        上界 -2.5 恰等（两条边界方向都暴露在噪声误判面上）。
        """
        s_lo = _pdiv_s3(-3.8, -3.2)  # S21 恰等下界（scale=1 保恰等；
        # |S|=0.646 σmax<1 无源性不迫）
        f_lo = _by_factor(check_edb_batch_health(
            _batch_ok(_write_touchstone(tmp_path / "pd_blo.s3p", s_lo), 3),
            spec=_spec3()))["s_split_window"]
        assert f_lo["status"] == "PASS"
        s_hi = _pdiv_s3(-3.2, -2.5)  # S31 恰等上界（|S|=0.750）
        f_hi = _by_factor(check_edb_batch_health(
            _batch_ok(_write_touchstone(tmp_path / "pd_bhi.s3p", s_hi), 3),
            spec=_spec3()))["s_split_window"]
        assert f_hi["status"] == "PASS"

    def test_window_factor_json_round_trip(self, tmp_path):
        """窗判据 evidence JSON 可序列化（window_db 落 list 非 tuple）。"""
        s = _pdiv_s3(-3.2, -3.3, scale=0.97)
        snp = _write_touchstone(tmp_path / "pd_j.s3p", s)
        report = check_edb_batch_health(_batch_ok(snp, 3), spec=_spec3())
        doc = json.loads(json.dumps(report))
        f = {c["factor"]: c for c in doc["criteria"]}["s_split_window"]
        assert f["evidence"]["window_db"] == [-3.8, -2.5]


# ---------------------------------------------------------------------------
# verdict 聚合与报告形状（#122 / #105 / JSON 进出）
# ---------------------------------------------------------------------------

class TestVerdictAndShape:
    def test_fail_dominates_unknown(self, tmp_path):
        """FAIL + UNKNOWN 并存 → FAIL（FAIL 主导，UNKNOWN 不降级也不冒充）。"""
        ghost = tmp_path / "ghost.s2p"
        result = _batch_ok(ghost, 2, rc=1, ok=False)
        report = check_edb_batch_health(result, spec=_spec(2))
        assert report["verdict"] == "FAIL"
        assert report["summary"]["n_unknown"] >= 1
        assert report["summary"]["n_fail"] >= 1

    def test_unknown_only_not_fail(self, snp_ok):
        """仅 UNKNOWN（回执缺失）→ verdict UNKNOWN 非 FAIL（#122 不冒充）。"""
        report = check_edb_batch_health(None, touchstone_path=snp_ok,
                                        spec=_spec(2))
        assert report["verdict"] == "UNKNOWN"
        assert report["ok"] is False
        assert report["summary"]["n_fail"] == 0
        assert report["summary"]["n_unknown"] >= 1

    def test_unknown_does_not_masquerade_pass(self, snp_ok, monkeypatch):
        """UNKNOWN 判据存在时 verdict≠PASS（不冒充全绿）。"""
        monkeypatch.setitem(sys.modules, "skrf", None)
        report = check_edb_batch_health(None, touchstone_path=snp_ok,
                                        spec=_spec(2))
        assert report["verdict"] == "UNKNOWN"
        assert report["ok"] is False

    def test_report_shape_json_round_trip(self, snp_ok):
        """报告形状（schema/criteria/summary）+ JSON 可序列化（JSON 进出）。"""
        report = check_edb_batch_health(_batch_ok(snp_ok, 2), spec=_spec(2))
        assert report["schema"] == "edb-health-gate-v1"
        assert report["verdict"] in ("PASS", "FAIL", "UNKNOWN")
        assert set(report) >= {"schema", "ok", "verdict", "template",
                               "touchstone", "criteria", "summary"}
        for c in report["criteria"]:
            assert set(c) >= {"factor", "status", "detail", "lesson_ref"}
            assert c["status"] in ("PASS", "FAIL", "UNKNOWN")
        assert {c["factor"] for c in report["criteria"]} == {
            "solve_status", "touchstone", "port_count", "passivity",
            "s11_dip", "reciprocity"}
        summary = report["summary"]
        assert (summary["n_pass"] + summary["n_fail"] + summary["n_unknown"]
                == len(report["criteria"]))
        # JSON 进出（规则 4）：数值/门/判定全 JSON 友好
        doc = json.loads(json.dumps(report))
        assert doc["verdict"] == report["verdict"]

    def test_best_effort_no_raise_on_malformed_inputs(self):
        """#105：回执/spec 全畸形不抛异常，落结构化 UNKNOWN/FAIL。"""
        report = check_edb_batch_health({"rc": "not-an-int", "ok": "yes"},
                                        spec={"ports": "not-a-list",
                                              "sim_setup": "not-a-dict"})
        assert report["verdict"] in ("FAIL", "UNKNOWN")
        assert isinstance(report["criteria"], list)

    def test_template_kwarg_overrides_spec(self, snp_ok, monkeypatch):
        """template kwarg 覆盖 spec.template（门作用域显式指定）。"""
        monkeypatch.setattr(ehg, "S11_DIP_DB_BY_TEMPLATE",
                            {"kwarg_tpl": -3.0})
        s = _passive_s(s11_mag=0.5)
        snp = _write_touchstone(snp_ok.parent / "kw.s2p", s)
        spec = _spec(2, template="spec_tpl")
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=spec,
                                        template="kwarg_tpl")
        f = _by_factor(report)["s11_dip"]
        assert f["evidence"]["gate_scope"] == "template:kwarg_tpl"
        assert report["template"] == "kwarg_tpl"


# ---------------------------------------------------------------------------
# f0_offset 多谷检测（W7 冒烟语义扩展：ratrace 双谷 1.97/2.67GHz 夹持实证）
# ---------------------------------------------------------------------------

def _dip_s(freq_hz: np.ndarray, dips: list[tuple[float, float, float]],
           base: float = 0.5, offdiag: float = 0.5) -> np.ndarray:
    """带高斯谷的 2 端口无源 S（判据形态件，σmax≤base+offdiag≤1.0 不拦）。

    |S11| = base − Σ depth·exp(−((f−fc)/w)²)（clip 防零）；dips 元素 =
    (谷心 GHz, 深度线性, 宽度 GHz)。offdiag=0.5、base≤0.5 时
    σmax=max_f(|S11|+offdiag) ≤ 1.0（passivity 1% 容差内全绿）。
    """
    mag = np.full(freq_hz.size, base)
    for fc_ghz, depth, w_ghz in dips:
        mag = mag - depth * np.exp(
            -((freq_hz - fc_ghz * 1e9) / (w_ghz * 1e9)) ** 2)
    mag = np.clip(mag, 1e-3, None)
    s = np.zeros((freq_hz.size, 2, 2), dtype=complex)
    s[:, 0, 0] = s[:, 1, 1] = mag
    s[:, 0, 1] = s[:, 1, 0] = offdiag
    return s


class TestMultiDipF0Offset:
    """W7 冒烟语义扩展钉：f0 邻域多谷 → f0_offset UNKNOWN（#122 不冒充）。

    语义终表（s11_dip 既有判据零语义变化承诺下的扩展面）：
    - 多谷（f0 对称窗内谷计数>1，相邻极小间距>窗宽 5% 计独立谷）：
      s11_dip 锚**最深谷**（主谷@f0 典型形态与既有 at-f0 插值读数同值
      =现有行为保持；at-f0 读数保留 evidence 双报）+ 新增 f0_offset
      因子 UNKNOWN（detail/evidence 标 multi_dip_near_f0）→ verdict
      UNKNOWN（不冒充 PASS 也不硬 FAIL，#122）；
    - 单谷/无谷（平响应无严格局部极小）：f0_offset 不出现，s11_dip
      逐字节现行为（回归钉）；
    - 既有 UNKNOWN 路径（无数据/未声明 f0/f0 出跨度）：现 UNKNOWN 不变，
      多谷检测不在这些路径触发。
    """

    def test_double_dip_marks_f0_offset_unknown(self, tmp_path):
        """双谷（主谷@f0 + 副谷偏 8%）→ f0_offset UNKNOWN + verdict
        UNKNOWN；s11_dip 锚最深谷=主谷@f0（现有行为保持读数）。"""
        freq = _freq_hz()  # 2.0–3.0 GHz / 41 点；f0=2.5，8% 偏移=0.2 GHz
        s = _dip_s(freq, [(2.5, 0.45, 0.03), (2.7, 0.30, 0.03)])
        snp = _write_touchstone(tmp_path / "ddip.s2p", s, freq)
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        by = _by_factor(report)
        f = by["f0_offset"]
        assert f["status"] == "UNKNOWN"
        assert "multi_dip_near_f0" in f["detail"]
        assert f["evidence"]["marker"] == "multi_dip_near_f0"
        assert f["evidence"]["n_dips_near_f0"] == 2
        assert f["evidence"]["dip_freqs_ghz"] == pytest.approx(
            [2.5, 2.7], abs=1e-6)
        # s11_dip 锚最深谷（=主谷@f0）：判 PASS，at-f0 读数同值双报
        s11 = by["s11_dip"]
        assert s11["status"] == "PASS"
        assert s11["evidence"]["s11_db_at_f0"] == pytest.approx(-26.0,
                                                                abs=0.5)
        assert s11["evidence"]["s11_db_at_dip"] == pytest.approx(-26.0,
                                                                 abs=0.5)
        assert s11["evidence"]["deepest_dip_freq_ghz"] == pytest.approx(
            2.5, abs=1e-6)
        assert s11["evidence"]["n_dips_near_f0"] == 2
        # verdict UNKNOWN（不冒充 PASS，#122），唯一 UNKNOWN=f0_offset
        assert report["verdict"] == "UNKNOWN"
        assert report["ok"] is False
        assert report["summary"]["n_fail"] == 0
        assert report["summary"]["unknown_factors"] == ["f0_offset"]
        doc = json.loads(json.dumps(report))  # JSON 进出（规则 4）
        doc_by = {c["factor"]: c for c in doc["criteria"]}
        assert doc_by["f0_offset"]["status"] == "UNKNOWN"

    def test_double_dip_anchors_deepest_dip(self, tmp_path):
        """最深谷不在 f0（副谷更深）→ s11_dip 锚副谷 PASS（"取最深谷"
        语义钉），f0_offset UNKNOWN；at-f0 浅读数保留 evidence 双报。"""
        freq = _freq_hz()
        s = _dip_s(freq, [(2.5, 0.20, 0.03), (2.7, 0.45, 0.03)])
        snp = _write_touchstone(tmp_path / "ddip2.s2p", s, freq)
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        by = _by_factor(report)
        s11 = by["s11_dip"]
        assert s11["status"] == "PASS"  # 最深谷@2.7（−26dB）≤ −10 门
        assert s11["evidence"]["deepest_dip_freq_ghz"] == pytest.approx(
            2.7, abs=1e-6)
        assert s11["evidence"]["s11_db_at_dip"] == pytest.approx(-26.0,
                                                                 abs=0.5)
        assert s11["evidence"]["s11_db_at_f0"] == pytest.approx(-10.5,
                                                                abs=0.5)
        assert by["f0_offset"]["status"] == "UNKNOWN"
        assert report["verdict"] == "UNKNOWN"

    def test_single_dip_behavior_unchanged(self, tmp_path):
        """单谷（谷@f0）→ 无 f0_offset 因子，s11_dip 现行为逐字节（回归
        钉：单谷判据零语义变化）。"""
        freq = _freq_hz()
        s = _dip_s(freq, [(2.5, 0.45, 0.03)])
        snp = _write_touchstone(tmp_path / "sdip.s2p", s, freq)
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        by = _by_factor(report)
        assert "f0_offset" not in by
        s11 = by["s11_dip"]
        assert s11["status"] == "PASS"
        assert s11["evidence"]["s11_db_at_f0"] == pytest.approx(-26.0,
                                                                abs=0.5)
        assert "s11_db_at_dip" not in s11["evidence"]  # 单谷不加扩展证据
        assert "多谷" not in s11["detail"]
        assert report["verdict"] == "PASS"
        assert report["summary"]["n_pass"] == 6

    def test_single_dip_off_f0_no_marker(self, tmp_path):
        """单谷不在 f0 → 现行为（at-f0 判 FAIL），无 f0_offset（单谷谷位
        标记无歧义，多谷语义不触发）。"""
        freq = _freq_hz()
        s = _dip_s(freq, [(2.2, 0.48, 0.03)])
        snp = _write_touchstone(tmp_path / "sdip_off.s2p", s, freq)
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2), s11_dip_gate_db=-10.0)
        by = _by_factor(report)
        assert "f0_offset" not in by
        assert by["s11_dip"]["status"] == "FAIL"  # at-f0 −6dB，现行为
        assert report["verdict"] == "FAIL"

    def test_no_dip_flat_no_marker_current_behavior(self, tmp_path):
        """无谷（平响应，无严格局部极小）→ 现行为（深平 PASS/浅平 FAIL）
        ，无 f0_offset——多谷检测零触发，既有判读不被改写。"""
        snp = _write_touchstone(tmp_path / "flat.s2p",
                                _passive_s(s11_mag=0.05))
        report = check_edb_batch_health(_batch_ok(snp, 2), spec=_spec(2))
        by = _by_factor(report)
        assert "f0_offset" not in by
        assert by["s11_dip"]["status"] == "PASS"
        assert report["verdict"] == "PASS"
        snp2 = _write_touchstone(tmp_path / "flat2.s2p",
                                 _passive_s(s11_mag=0.5))
        report2 = check_edb_batch_health(
            _batch_ok(snp2, 2), spec=_spec(2), s11_dip_gate_db=-10.0)
        by2 = _by_factor(report2)
        assert "f0_offset" not in by2
        assert by2["s11_dip"]["status"] == "FAIL"
        assert report2["verdict"] == "FAIL"

    def test_existing_unknown_paths_preserved_with_dip_data(self, tmp_path):
        """既有 UNKNOWN 路径在双谷数据下不变（"无[可判]谷→现 UNKNOWN"
        回归钉）：f0 出跨度/未声明 → UNKNOWN 且无 f0_offset，多谷检测
        不在这些路径触发。"""
        freq = _freq_hz()
        s = _dip_s(freq, [(2.5, 0.45, 0.03), (2.7, 0.30, 0.03)])
        snp = _write_touchstone(tmp_path / "ddip3.s2p", s, freq)
        r1 = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2, f0_ghz=5.0))
        b1 = _by_factor(r1)
        assert b1["s11_dip"]["status"] == "UNKNOWN"
        assert "外推" in b1["s11_dip"]["detail"]
        assert "f0_offset" not in b1
        r2 = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2, f0_ghz=None))
        b2 = _by_factor(r2)
        assert b2["s11_dip"]["status"] == "UNKNOWN"
        assert "未声明" in b2["s11_dip"]["detail"]
        assert "f0_offset" not in b2

    def test_multi_dip_gate_none_still_marks_offset(self, tmp_path,
                                                    monkeypatch):
        """多谷 + gate=None 族 → s11_dip UNKNOWN（如实不判）+ f0_offset
        UNKNOWN（谷位标记与谷深门分派正交，两 UNKNOWN 均 #122 如实）。"""
        monkeypatch.setattr(ehg, "S11_DIP_DB_BY_TEMPLATE",
                            {"edb_multi_dip_nogate": None})
        freq = _freq_hz()
        s = _dip_s(freq, [(2.5, 0.45, 0.03), (2.7, 0.30, 0.03)])
        snp = _write_touchstone(tmp_path / "ddip4.s2p", s, freq)
        report = check_edb_batch_health(
            _batch_ok(snp, 2), spec=_spec(2),
            template="edb_multi_dip_nogate")
        by = _by_factor(report)
        assert by["s11_dip"]["status"] == "UNKNOWN"
        assert "多谷" in by["s11_dip"]["detail"]
        assert by["f0_offset"]["status"] == "UNKNOWN"
        assert report["verdict"] == "UNKNOWN"

    def test_dip_detector_merges_close_minima(self):
        """检测器单测：相邻极小间距 ≤ 窗宽 5% 链式归并为同一谷（单谷
        肩部纹波不误触发），>5% 计独立谷（判据边界钉）。"""
        f0 = 2.5e9
        half = 0.5e9
        freq = np.linspace(f0 - half, f0 + half, 4001)  # 0.25 MHz 分辨

        def curve(dip_sep_hz: float) -> np.ndarray:
            mag = np.full(freq.size, 0.5)
            for fc in (f0 - dip_sep_hz / 2.0, f0 + dip_sep_hz / 2.0):
                mag = mag - 0.4 * np.exp(-((freq - fc) / (0.005e9)) ** 2)
            return mag.astype(complex)

        # 间距 0.04 GHz（=窗宽 4% ≤ 5%）→ 归并 1 谷
        got = ehg._find_dips_near_f0(freq, curve(0.04e9), f0)
        assert got is not None
        assert len(got[0]) == 1
        # 恰等 5%（0.05 GHz）：≤ 阈值仍归并（">窗 5%"计独立谷的边界）
        got_eq = ehg._find_dips_near_f0(freq, curve(0.05e9), f0)
        assert got_eq is not None
        assert len(got_eq[0]) == 1
        # 间距 0.2 GHz（20%）→ 2 独立谷
        got_far = ehg._find_dips_near_f0(freq, curve(0.2e9), f0)
        assert got_far is not None
        assert len(got_far[0]) == 2
        assert got_far[0] == pytest.approx([2.4e9, 2.6e9], abs=1e3)
        # 平响应（常数）→ 无谷空列表（非 None=可判但零谷）
        got_flat = ehg._find_dips_near_f0(
            freq, np.full(freq.size, 0.3).astype(complex), f0)
        assert got_flat == ([], [])
