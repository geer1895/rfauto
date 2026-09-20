"""WP4.3 real_edt: 场路协同回归锚真机验收（ADS 2027 hpeesofsim B 档）。

验收口径：branchline S 参数进 ADS 级联
vs skrf 级联，FSV ≥VG。branchline .s4p 用 linkage/field_circuit_anchor 的
闭式基准生成（离线回归同一数据形态；真机 EM 数据接入不改下游）。
需本机 ADS 安装（RFAUTO_HPEESOF_DIR / settings.hpeesof_dir 指定）。

许可欠配时 skip 而非 fail（2026-09-13 实证：本机唯一 EEsof 许可文件
全部 INCREMENT 签名校验失败
"Invalid license key (inconsistent authentication code)"，vendor daemon
"No features to serve"，hpeesofsim 于 circuit set up 报
"Linear features are not licensed ... (0 tokens)"）——许可修复后本测试
自动恢复为真验收。
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_edt

_ADS = Path(os.environ.get("RFAUTO_HPEESOF_DIR", r"C:\Program Files\Keysight\ADS2027"))

_LICENSE_MARKERS = ("not licensed", "0 tokens", "license", "licensed")


def _skip_if_license_blocked(ads_section: dict) -> None:
    """ADS 段 error 且错误串指向许可欠配时 skip（其余错误照常 fail）。

    错误串含 run_hpeesofsim 的 stdout 尾巴（含 "Linear features are not
    licensed ..." 的许可正文）。
    """
    if ads_section.get("status") != "ok":
        err = str(ads_section.get("error", ""))
        low = err.lower()
        if any(m in low for m in _LICENSE_MARKERS):
            pytest.skip(f"ADS 许可不可用（非代码问题）: {err}")


@pytest.mark.skipif(not (_ADS / "bin" / "hpeesofsim.exe").exists(),
                    reason="ADS 2027 未安装")
def test_real_field_circuit_anchor_ads_vs_skrf_fsv(tmp_path):
    from rfauto.linkage import field_circuit_anchor as fca

    snp = fca.build_branchline_touchstone(tmp_path / "branchline.s4p")
    summary = fca.run_field_circuit_anchor(
        snp, tmp_path / "anchor", ads_dir=_ADS,
    )

    _skip_if_license_blocked(summary["ads"])
    assert summary["ads"]["status"] == "ok", summary["ads"]
    assert summary["fsv"]["at_least_vg"] is True, summary["fsv"]
    assert summary["fsv"]["phase_consistent"] is not False, summary["fsv"]
    for chk in summary["fsv"]["phase_checks"].values():
        assert chk["max_abs_deg"] is not None
        assert chk["max_abs_deg"] <= summary["fsv"]["phase_tol_deg"]
    assert summary["macromodel"]["ok"] is True, summary["macromodel"]
    assert summary["macromodel"]["cascade_fsv"]["at_least_vg"] is True
    assert summary["back_annotation"]["consistent"] is True
    assert summary["ok"] is True
