"""C14 real_edt: 有源链路 ADS 真机验收（ADS 2027 hpeesofsim B 档）。

验收口径: 匹配网络 EM↔ADS 联合 vs 手工口径。
匹配网络用 core/matching 闭式 L 型（离线回归同一数据形态; 真机 EM 数据
接入不改下游）。需本机 ADS 安装（RFAUTO_HPEESOF_DIR / settings.hpeesof_dir 指定）。

许可欠配时 skip 而非 fail——2026-09-13/14 实证: hpeesofsim 650.shp 于
circuit set up 报 "Linear features are not licensed ... (0 tokens)"
（EEsof 许可文件签名校验失败, 见 tests/real_edt conftest 记录; 网表
parsing/flattening 本身已通过）。许可修复后本测试自动恢复为真验收。
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_edt

_ADS = Path(os.environ.get("RFAUTO_HPEESOF_DIR", r"C:\Program Files\Keysight\ADS2027"))

_LICENSE_MARKERS = ("not licensed", "0 tokens", "license", "licensed")


def _skip_if_license_blocked(ads_section: dict) -> None:
    """ADS 段 error 且错误串指向许可欠配时 skip（其余错误照常 fail）。"""
    if ads_section.get("status") != "ok":
        err = str(ads_section.get("error", ""))
        low = err.lower()
        if any(m in low for m in _LICENSE_MARKERS):
            pytest.skip(f"ADS 许可不可用（非代码问题）: {err}")


@pytest.mark.skipif(not (_ADS / "bin" / "hpeesofsim.exe").exists(),
                    reason="ADS 2027 未安装")
def test_real_active_chain_ads_vs_manual(tmp_path):
    import numpy as np
    import skrf

    from rfauto.core.active_chain import HybridPiModel
    from rfauto.core.matching import synthesize_l_match, to_skrf_network
    from rfauto.service import active_chain_service as acs

    # 匹配网络 Touchstone（EM S2P 替身; 生产 = HFSS/openEMS 导出, 下游不变）
    res = synthesize_l_match(z_source=50.0, z_load=15.0, f0_ghz=2.0)
    net = to_skrf_network(res, freqs_ghz=np.linspace(1.8, 2.2, 41))
    net.renormalize([50.0, 50.0])
    match_p = tmp_path / "match.s2p"
    net.write_touchstone(str(match_p), form="ri")

    # 混合π 合成器件 S2P（稳定 LNA 口径, 与离线单测同参数）
    model = HybridPiModel(gm_s=0.02, rds_ohm=300.0, cgs_f=0.5e-12,
                          cds_f=0.12e-12, cgd_f=2e-15, rg_ohm=5.0)
    freqs = np.linspace(1.8e9, 2.2e9, 41)
    s = np.stack([model.to_sparams(f) for f in freqs])
    dnet = skrf.Network(frequency=skrf.Frequency.from_f(freqs, unit="Hz"),
                        s=s, z0=50)
    device_p = tmp_path / "device.s2p"
    dnet.write_touchstone(str(device_p), form="ri")

    summary = acs.run_lna_chain(
        match_p, device_p, 2.0, ads_dir=_ADS, out_dir=tmp_path / "real",
    )
    _skip_if_license_blocked(summary["ads"])
    assert summary["ads"]["status"] == "ok", summary["ads"]
    assert summary["ads"]["vs_manual"]["consistent"] is True, summary["ads"]["vs_manual"]
    assert summary["verdict"]["device_unconditionally_stable"] is True
