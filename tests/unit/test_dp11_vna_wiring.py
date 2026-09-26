"""DP-11 P2：health 门测量分支 + dataset 分支⑥ + service 面（G8/G9）。

- 测量 run 落 runs/<id> 同构产物（meta adapter="vna" + study_name=工作
  目录名 + Touchstone/掩码 csv + vna_measure.json），health/数据集零改动
  消费；
- 未校准 → suspect（门禁口径不变：仅 unhealthy 禁入）；
- 分支⑥：vna_measure.json → 统一行式 schema，E1 指纹 study_name=工作
  目录名（#322）；
- chdir 隔离（#144），run 目录落 tmp。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import skrf
import yaml

from rfauto.measurement.librevna import parse_trace_data

# 连接失败负例走 pyvisa-sim 异常路径，资源缺失时的读告警与断言无关
pytestmark = [
    pytest.mark.filterwarnings("ignore::UserWarning:pyvisa"),
]

VNA_SIM_YAML = Path(__file__).resolve().parents[1] / "fixtures" / "vna_sim.yaml"
SIM_ADDR_CAL = "TCPIP0::sim-vna::10001::INSTR"
SIM_ADDR_UNCAL = "TCPIP0::sim-vna-uncal::10001::INSTR"


@pytest.fixture()
def workdir(tmp_path, monkeypatch):
    """chdir 隔离（#144）：runs/ 落 tmp，不动工作区真实 runs/。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def ref_s2p(workdir) -> Path:
    """参考网络 = fixture 应答同一批数据（En 全链零差路径）。"""
    fixture = yaml.safe_load(
        VNA_SIM_YAML.read_text(encoding="utf-8"))
    dialogues = fixture["devices"]["librevna_vna"]["dialogues"]
    responses = {d["q"]: d.get("r") for d in dialogues}
    freq = None
    s = np.zeros((5, 2, 2), dtype=complex)
    for name in ("S11", "S12", "S21", "S22"):
        f, v = parse_trace_data(responses[f"VNA:TRACe:DATA? {name}"])
        i, j = int(name[1]) - 1, int(name[2]) - 1
        s[:, i, j] = v
        freq = f
    net = skrf.Network(frequency=skrf.Frequency.from_f(freq, unit="hz"), s=s)
    path = workdir / "ref.s2p"
    net.write_touchstone(str(path))
    return path


def _measure(workdir, ref_s2p=None, address=SIM_ADDR_CAL):
    from rfauto.service.vna_service import run_vna_measure

    return run_vna_measure(
        address=address, model="librevna",
        freq_range_ghz=(1.0, 3.0), n_points=5, ifbw_hz=1000.0,
        calkit_id="wl_2g5_solt_smoke",
        visa_library=f"{VNA_SIM_YAML}@sim",
        params={"model": "mline"},
        runs_dir=workdir / "runs",
        ref_s2p=ref_s2p,
        markdown_path=workdir / "en.md" if ref_s2p else None,
    )


class TestMeasurementRunArtifacts:
    """G8①：runs/<id> 同构产物。"""

    def test_artifacts_laid_out(self, workdir, ref_s2p):
        out = _measure(workdir, ref_s2p)
        assert out["ok"] is True
        run_dir = Path(out["run_dir"])
        assert (run_dir / "meta.json").exists()
        assert (run_dir / "vna_measure.json").exists()
        assert (run_dir / "results" / "params.s2p").exists()
        # 全矩阵测量 → 掩码 csv 不写（诚实边界：全矩阵由 Touchstone 承载）
        assert out["artifacts"]["sparams_csv"] is None
        assert not (run_dir / "results" / "sparams.csv").exists()

        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["adapter"] == "vna"
        assert meta["status"] == "done"
        # E1 指纹（#322）：study_name = 工作目录名（写侧契约）
        assert meta["study_name"] == run_dir.name

        vm = json.loads(
            (run_dir / "vna_measure.json").read_text(encoding="utf-8"))
        assert vm["adapter"] == "vna"
        assert vm["calibration"]["calibrated"] is True
        assert vm["calibration"]["calkit_id"] == "wl_2g5_solt_smoke"
        assert vm["measured_mask"] == [[True, True], [True, True]]

    def test_partial_matrix_gets_masked_csv(self, workdir):
        """迹线缺失 → 掩码 sparams.csv（#314 载体）。"""
        import rfauto.adapters  # noqa: F401
        from rfauto.adapters.em_solver_base import (
            EMSolverConfig,
            EMSolverType,
            get_global_registry,
        )

        # 缺迹线仪器（脚本化 transport，直接注入 adapter）
        class _PartialTransport:
            def __init__(self):
                self.written: list[str] = []

            def write(self, cmd):
                self.written.append(cmd)

            def query(self, cmd):
                if cmd == "*IDN?":
                    return "LibreVNA,LibreVNA-GUI,SN000,1.0.4"
                if cmd == "VNA:ACQuisition:FINished?":
                    return "TRUE"
                if cmd == "VNA:CALibration:ACTIVE?":
                    return "SOLT"
                if cmd == "VNA:TRACe:LIST?":
                    return "S11,S21"   # S12/S22 缺测
                if cmd.startswith("VNA:TRACe:DATA? S11"):
                    return "[1e9,0.1,0.0],"
                if cmd.startswith("VNA:TRACe:DATA? S21"):
                    return "[1e9,0.0,-0.9],"
                raise AssertionError(cmd)

        cfg = EMSolverConfig(
            solver_type=EMSolverType.VNA, freq_range_ghz=(1.0, 1.0),
            extra_params={"model": "librevna", "n_points": 1,
                          "transport": _PartialTransport(),
                          "calkit_id": "k"})
        adapter = get_global_registry().create(EMSolverType.VNA, cfg)
        try:
            result = adapter.solve()
            assert result.success is True
            mask = result.measured_mask
            assert mask[0, 0] is np.True_ or bool(mask[0, 0]) is True
            assert bool(mask[0, 1]) is False   # S12 缺测 → 掩码 False
        finally:
            adapter.close()

    def test_connect_failure_reported(self, workdir):
        out = _measure(workdir, address="TCPIP0::no-such-host::10001::INSTR")
        assert out["ok"] is False
        assert out.get("errors")


class TestHealthGateBranch:
    """G8②：校准态因子 + 未校准 → suspect；门禁口径不变。"""

    def test_calibrated_run_healthy(self, workdir, ref_s2p):
        out = _measure(workdir, ref_s2p)
        health = out["health"]
        assert health["verdict"] == "healthy"
        factor = next(f for f in health["factors"]
                      if f["factor"] == "measurement_calibration")
        assert factor["status"] == "PASS"

    def test_uncalibrated_run_suspect(self, workdir):
        out = _measure(workdir, address=SIM_ADDR_UNCAL)
        assert out["ok"] is True
        health = out["health"]
        assert health["verdict"] == "suspect"   # 未校准 → suspect（G4 决议）
        factor = next(f for f in health["factors"]
                      if f["factor"] == "measurement_calibration")
        assert factor["status"] == "WARN"
        # 门禁口径不变：suspect 不等于 unhealthy
        assert health["verdict"] != "unhealthy"

    def test_health_gate_semantics_only_unhealthy_blocks(self, workdir):
        """物化侧门禁（health_gate=True）对 suspect 放行（#209 口径）。"""
        out = _measure(workdir, address=SIM_ADDR_UNCAL)
        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(name="dp11_suspect",
                                  run_ids=[out["run_id"]],
                                  out_dir=workdir / "ds",
                                  health_gate=True)
        assert res["ok"] is True
        assert res["n_points"] == 1   # suspect 不拦（unhealthy 才拦）
        assert out["run_id"] not in (res.get("unhealthy_runs") or [])


class TestDatasetBranch6:
    """G8③：vna_measure.json → 统一行式 schema + E1 指纹。"""

    def test_branch6_row_and_fingerprint(self, workdir, ref_s2p):
        out = _measure(workdir, ref_s2p)
        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(name="dp11_branch6",
                                  run_ids=[out["run_id"]],
                                  out_dir=workdir / "ds")
        assert res["ok"] is True
        assert res["n_points"] == 1
        import duckdb

        con = duckdb.connect()
        parquet = (workdir / "ds" / "dp11_branch6" / "points.parquet")
        rows = con.execute(
            f"SELECT adapter, study_name, source, algorithm, model "
            f"FROM read_parquet('{parquet.as_posix()}')").fetchall()
        assert len(rows) == 1
        adapter, study_name, source, algorithm, model = rows[0]
        assert adapter == "vna"
        assert study_name == out["run_id"]      # E1 指纹 = 工作目录名（#322）
        assert source == "vna_measure"
        assert algorithm == "vna_measure"
        assert model == "mline"
        # provenance 带测量摘要 + Touchstone 指针
        prov = con.execute(
            f"SELECT provenance_json FROM read_parquet('{parquet.as_posix()}')"
        ).fetchone()[0]
        p = json.loads(prov)
        assert p["run_id"] == out["run_id"]
        assert p["calibrated"] == "True"
        assert p["touchstone_path"].endswith("params.s2p")
        assert p["n_ports"] == 2

    def test_no_double_counting_with_branch5(self, workdir, ref_s2p):
        """⑥ 触发的 run 不被 ⑤（run_once）重复计点。"""
        out = _measure(workdir, ref_s2p)
        run_dir = Path(out["run_dir"])
        assert (run_dir / "results" / "metrics.json").exists() is False
        from rfauto.service.dataset_service import _collect_run_points

        pts, _errs, _ = _collect_run_points(run_dir)
        assert len(pts) == 1
        assert pts[0]["source"] == "vna_measure"


class TestEnReportService:
    """En 报告 service 面（JSON 进出 + Markdown 落盘）。"""

    def test_en_report_full_chain(self, workdir, ref_s2p):
        out = _measure(workdir, ref_s2p)
        en = out["en_report"]
        assert en["ok"] is True
        assert set(en["traces"]) == {"S11", "S21"}
        assert en["traces"]["S11"]["max_abs_en"] == pytest.approx(0.0)
        assert en["summary"]["u_sim_source"] == "fallback"
        assert "gum_budget" in en["summary"]["u_meas_source"]
        assert (workdir / "en.md").exists()
        md = (workdir / "en.md").read_text(encoding="utf-8")
        assert "En 相关性报告" in md

    def test_en_report_missing_file(self, workdir):
        from rfauto.service.vna_service import vna_en_report

        res = vna_en_report(workdir / "nope.s2p", workdir / "nope.s2p")
        assert res["ok"] is False
        assert res["errors"]
