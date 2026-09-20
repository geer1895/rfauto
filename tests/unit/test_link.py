"""P3-D6: HFSS-ADS 二阶段链路编排（FakeAdapter 驱动, 无 license）。

- run_two_phase 编排 + 报告生成（B 档成功路径, sim_fn 注入）;
- C 档保底产物（port_map.json + ads_import_guide.md）是 B 档实现内部回退,
  直接测 _write_c_fallback 与 write_report;
- 契约违规（端口数不匹配）必须显式报错, 不降级 C 档（验收项 2）。
"""

import json
from pathlib import Path

import pytest

from rfauto.adapters.fake_adapter import FakeAdapter
from rfauto.core.contracts import AdsExchangeContract, TouchstoneContract
from rfauto.linkage.hfss_ads_link import HfssAdsLink


def _contract():
    return AdsExchangeContract(
        touchstone=TouchstoneContract(port_order=["input", "output_1", "output_2"])
    )


def _make_fake_network(n_ports=3):
    fa = FakeAdapter(n_ports=n_ports)
    fa.connect({})
    fa.solve("test")
    return fa


class TestTwoPhaseLink:
    def test_two_rounds_b_ok(self):
        def sim_ok(snp_path, out_dir, contract):
            return {"status": "b_ok",
                    "metrics": {"system_gain_db": -3.0103, "input_vswr": 1.2727,
                                "amplitude_balance_db": 3.4744},
                    "n_ports": 3}

        out = Path(__import__("tempfile").mkdtemp())
        link = HfssAdsLink(output_dir=out)
        summary = link.run_two_phase(_make_fake_network(), None, _contract(),
                                     rounds=2, ads_sim_fn=sim_ok)
        assert summary["rounds_completed"] == 2
        assert len(summary["results"]) == 2
        for r in summary["results"]:
            assert r["phase2"]["status"] == "b_ok"
            assert Path(r["snp_path"]).exists()
        report = out / "ads_link_report.md"
        assert report.exists()
        text = report.read_text(encoding="utf-8")
        assert "system_gain_db" in text
        assert "-3.0103" in text

    def test_custom_sim_exception_propagates(self):
        def sim_fail(snp_path, out_dir, contract):
            raise RuntimeError("custom sim exploded")

        out = Path(__import__("tempfile").mkdtemp())
        link = HfssAdsLink(output_dir=out)
        try:
            link.run_two_phase(_make_fake_network(), None, _contract(),
                               rounds=1, ads_sim_fn=sim_fail)
            raised = False
        except RuntimeError:
            raised = True
        assert raised


class TestCFallbackArtifacts:
    def test_write_c_fallback_artifacts(self, tmp_path):
        link = HfssAdsLink(output_dir=tmp_path)
        fa = _make_fake_network()
        snp = fa.export_touchstone(tmp_path / "probe.s3p", _contract().touchstone)
        round_dir = tmp_path / "round1"
        round_dir.mkdir(parents=True, exist_ok=True)
        link._write_c_fallback(snp, round_dir, _contract(),
                               RuntimeError("hpeesofsim not found (simulated)"))
        pm = json.loads((round_dir / "port_map.json").read_text(encoding="utf-8"))
        assert pm["port_order"] == ["input", "output_1", "output_2"]
        guide = (round_dir / "ads_import_guide.md").read_text(encoding="utf-8")
        assert "SnP:SNP1  P1 P2 P3 NumPorts=3" in guide
        assert "hpeesofsim not found" in guide

    def test_ads_import_guide_snp_line(self):
        contract = _contract()
        link = HfssAdsLink()
        guide = link._ads_import_guide(Path("x.s3p"), contract, RuntimeError("no ads"))
        assert 'Type="touchstone"' in guide
        assert "P1 P2 P3" in guide

    def test_report_marks_c_fallback(self, tmp_path):
        link = HfssAdsLink(output_dir=tmp_path)
        summary = {
            "rounds_completed": 1,
            "results": [{"round": 1, "phase2": {"status": "c_fallback",
                                                 "metrics": {},
                                                 "solve_time_s": 0.1,
                                                 "sim_time_s": 0.2}}],
            "status": "ok",
        }
        path = link.write_report(summary)
        text = path.read_text(encoding="utf-8")
        assert "c_fallback" in text


class TestContractViolationPropagates:
    def test_port_mismatch_raises_not_c_fallback(self, tmp_path):
        """契约违规（端口数不匹配）必须显式报错, 不降级到 C 档保底（验收项 2）。"""
        from rfauto.core.errors import ContractViolationError

        link = HfssAdsLink(output_dir=tmp_path)
        fa = FakeAdapter(n_ports=2)
        fa.connect({})
        fa.solve("test")
        snp2 = fa.export_touchstone(tmp_path / "probe.s2p",
                                    TouchstoneContract(port_order=["input", "output_1"]))
        contract3 = AdsExchangeContract()  # 默认 3 端口

        with pytest.raises(ContractViolationError):
            link._default_ads_sim(snp2, tmp_path / "out", contract3)
