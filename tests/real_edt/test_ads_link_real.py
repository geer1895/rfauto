"""P3 real_edt: 真机 ADS 2027 B 档链路（hpeesofsim + keysight.ads.dataset）。

需本机 ADS 安装（RFAUTO_HPEESOF_DIR 指定）。用 p3 阶段合成的
wilkinson_like.s3p 跑 run_from_snp N=2, 验证系统指标与输入一致；样例默认
位于 scripts/spike_b_ads/p3_d5_out/，可经 RFAUTO_TEST_WILKINSON_SNP 指定。
"""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_edt

_ADS = Path(os.environ.get("RFAUTO_HPEESOF_DIR", r"C:\Program Files\Keysight\ADS2027"))
_SNP = Path(os.environ.get(
    "RFAUTO_TEST_WILKINSON_SNP",
    str(Path(__file__).resolve().parents[2] / "scripts" / "spike_b_ads"
        / "p3_d5_out" / "wilkinson_like.s3p")))


@pytest.mark.skipif(not (_ADS / "bin" / "hpeesofsim.exe").exists(),
                    reason="ADS 2027 未安装")
@pytest.mark.skipif(not _SNP.exists(),
                    reason="wilkinson_like.s3p 测试数据缺失"
                           "（可经 RFAUTO_TEST_WILKINSON_SNP 提供）")
def test_real_ads_b_tier_two_rounds(tmp_path):
    os.environ["RFAUTO_HPEESOF_DIR"] = str(_ADS)
    from rfauto.core.contracts import AdsExchangeContract, TouchstoneContract
    from rfauto.linkage.hfss_ads_link import HfssAdsLink

    contract = AdsExchangeContract(
        touchstone=TouchstoneContract(port_order=["input", "output_1", "output_2"])
    )
    link = HfssAdsLink(output_dir=tmp_path, ads_dir=_ADS)
    summary = link.run_from_snp(_SNP, contract, rounds=2)
    assert summary["rounds_completed"] == 2
    for r in summary["results"]:
        p2 = r["phase2"]
        assert p2["status"] == "b_ok", p2
        m = p2["metrics"]
        assert m["system_gain_db"] == pytest.approx(-3.0103, abs=1e-3)
        assert m["input_vswr"] == pytest.approx(1.2727, abs=1e-3)
    assert (tmp_path / "ads_link_report.md").exists()
