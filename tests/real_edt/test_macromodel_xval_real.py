"""D13 real_edt：第三方 SPICE 交叉验证真机门——ngspice-47 .AC 对拍。

验收口径（方案冻结行 D13 验收列）：
"ngspice/Xyce 回放 vs 原 S 参数 FSV（D12）评级 ≥Good"。

链路：闭式合成网络（原始 S 由闭式解析式给出，与拟合器/ngspice 无共享代码
路径，#122 裁判不自证）→ VF 拟合 → skrf 导出 .sp → ngspice-47 .AC 逐端口
1V 激励真跑（工作区 tools/ngspice/Spice64/bin，AC 秒级/案例，无真机 EM 预算）
→ wrdata 复数重建 S → vs 原始 S 的 FSV GDM 评级 + max|ΔS|。

ngspice 缺席时 skip（非 fail）；其余失败如实 fail。真机标定与离线编排
测试分别见 adapters/spice_netlist.py docstring 与 tests/unit/test_macromodel_xval.py。
"""

import numpy as np
import pytest

from rfauto.adapters import spice_netlist as sn
from rfauto.core.fsv import grade_index_of
from rfauto.core.macromodel import fit_macromodel

pytestmark = pytest.mark.real_edt

Z0 = 50.0


def _fit_export(tmp_path, freq, s_orig, *, z0, name, subckt_name):
    req = {
        "freq_hz": freq.tolist(),
        "s": [[[[float(v.real), float(v.imag)] for v in row] for row in mat] for mat in s_orig],
        "z0": z0,
        "spice_path": str(tmp_path / name),
        "subckt_name": subckt_name,
    }
    fit = fit_macromodel(req)
    assert fit["ok"] is True, fit["fit"]
    return tmp_path / name, fit


@pytest.mark.skipif(not sn.ngspice_available(),
                    reason="ngspice 未安装（RFAUTO_NGSPICE_BIN / tools/ngspice）")
def test_real_xval_series_rl_two_port(tmp_path):
    """串联 R-L 二端口（闭式 S）：真跑 ngspice 逐端口重建 S → FSV ≥Good。"""
    freq = np.linspace(1e9, 20e9, 41)
    w = 2.0 * np.pi * freq
    z = 3.0 + 1j * w * 3e-9
    den = 2.0 * Z0 + z
    s_orig = np.zeros((freq.size, 2, 2), dtype=complex)
    s_orig[:, 0, 0] = s_orig[:, 1, 1] = z / den
    s_orig[:, 0, 1] = s_orig[:, 1, 0] = 2.0 * Z0 / den

    sp, fit = _fit_export(tmp_path, freq, s_orig, z0=[Z0, Z0], name="rl2.sp", subckt_name="rl2")
    x = sn.xval_macromodel_spice(s_orig, freq, sp, z0=[Z0, Z0], work_dir=tmp_path / "xv")

    assert x["status"] == "ok", x.get("error")
    assert x["tool"]["version"] is not None
    worst_idx = max(
        grade_index_of(float(r["gdm_mean"])) for r in x["fsv"]["per_response"].values()
    )
    assert worst_idx <= 2, x["worst_gdm_grade"]  # 验收判据：GDM 等级下标 ≤ 2（≥Good）
    assert x["gdm_at_least_good"] is True
    max_abs = float(x["xval_vs_reference"]["max_abs"])
    # ngspice 对拍 vs 原始闭式 S：拟合 RMS ~ -300dB + wrdata 15 位精度 → 远小于 1e-6
    assert max_abs < 1e-6, max_abs
    print("\n[D13 real xval] 2port RL: fit rms_db={:.1f} worst_gdm={} max|dS|={:.3e} "
          "tool={}".format(fit["fit"]["rms_db_final"], x["worst_gdm_grade"], max_abs,
                           x["tool"]["version"]))


@pytest.mark.skipif(not sn.ngspice_available(),
                    reason="ngspice 未安装（RFAUTO_NGSPICE_BIN / tools/ngspice）")
def test_real_xval_series_rlc_one_port_with_subfloor_rewrite(tmp_path):
    """1 端口串联 RLC（带内谐振 + 远带外极点 → skrf 泄漏电阻 <1e-12Ω）：
    验证 VCCS 等价改写路径 + ngspice 无钳位警告 + FSV ≥Good。"""
    freq = np.linspace(0.5e9, 10e9, 33)
    w = 2.0 * np.pi * freq
    z = 5.0 + 1j * w * 2e-9 + 1.0 / (1j * w * 0.5e-12)
    s_orig = ((z - Z0) / (z + Z0)).reshape(-1, 1, 1)

    sp, fit = _fit_export(tmp_path, freq, s_orig, z0=Z0, name="rlc1.sp", subckt_name="rlc1")
    x = sn.xval_macromodel_spice(s_orig, freq, sp, work_dir=tmp_path / "xv")

    assert x["status"] == "ok", x.get("error")
    assert x["z0_source"] == "inferred_from_R_i"  # 与回放自检同口径的 z0 推断
    worst_idx = max(
        grade_index_of(float(r["gdm_mean"])) for r in x["fsv"]["per_response"].values()
    )
    assert worst_idx <= 2, x["worst_gdm_grade"]
    max_abs = float(x["xval_vs_reference"]["max_abs"])
    assert max_abs < 1e-6, max_abs
    # 若导出含 <1e-12Ω 电阻：必须走 VCCS 等价改写（记账）且 ngspice 无钳位警告
    rw = x["resistor_rewrite"]
    assert rw["enabled"] is True
    if rw["n_rewritten"] > 0:
        for run in x["runs"]:
            assert not any("too small" in e for e in run["errors"]), run["errors"]
    # 回放自检（另一条证据链）同场对照：两者都须重现原始 S
    from rfauto.core.macromodel import replay_spice_subcircuit_s

    rep = replay_spice_subcircuit_s(sp, freq)
    rep_max = float(np.max(np.abs(rep["s"] - s_orig)))
    assert rep_max < 1e-8, rep_max
    print("\n[D13 real xval] 1port RLC: fit rms_db={:.1f} worst_gdm={} max|dS|={:.3e} "
          "rewritten={} replay_max={:.3e}".format(
              fit["fit"]["rms_db_final"], x["worst_gdm_grade"], max_abs,
              rw["n_rewritten"], rep_max))
