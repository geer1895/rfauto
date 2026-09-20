"""A3 real_edt：场-路协同（非线性/谐波平衡）真机验收——对照真 ngspice。

验收口径："对照 ngspice 参考解"。
链路：闭式 L 截面 EM 替身 .s2p → s_to_y 逐谐波 → HB 二极管检波器求解 →
同一物理 RLC 的 ngspice 瞬态+傅里叶参考（ngspice-47 批处理，2026-09-14
本机实测可用；tools/ngspice/Spice64/bin 或 PATH）→ 逐量互差判定。

ngspice 缺席时 skip（非 fail）；其余失败如实 fail。
"""

import pytest

from rfauto.adapters import spice_netlist

pytestmark = pytest.mark.real_edt


@pytest.mark.skipif(not spice_netlist.ngspice_available(),
                    reason="ngspice 未安装（RFAUTO_NGSPICE_BIN / tools/ngspice）")
def test_real_hb_vs_ngspice_detector(tmp_path):
    from rfauto.linkage import field_circuit_nonlinear as fcn

    summary = fcn.run_field_circuit_nonlinear_anchor(tmp_path / "anchor")

    assert summary["harmonic_balance"]["status"] == "ok", summary["harmonic_balance"]
    assert summary["harmonic_balance"]["converged"] is True
    assert summary["harmonic_balance"]["k_refine"]["ok"] is True, \
        summary["harmonic_balance"]["k_refine"]
    assert summary["ngspice"]["status"] == "ok", summary["ngspice"]
    assert summary["ngspice"]["errors"] == [], summary["ngspice"]["errors"]
    # 参考侧内部一致性：.four 0 次均值 vs .meas AVG（稳态窗）必须吻合
    cross = summary["comparison"].get("ngspice_dc_cross_check")
    assert cross is not None and cross["ok"] is True, cross
    # 逐量互差判定（HB 频域 vs ngspice 时域）
    assert summary["comparison"]["all_ok"] is True, summary["comparison"]["quantities"]
    # 相位护栏：p2 基波相位互差（余弦参考换算后）< 0.5°
    ph = summary["comparison"].get("phase_p2_h1_deg")
    assert ph is not None and abs(ph["delta"]) < 0.5, ph

    # 关键数字打进测试输出（供 runs/ 证据引用）
    rows = {(r["node"], r["harmonic"]): r for r in summary["comparison"]["quantities"]}
    print("\n[A3 real] out DC: hb={:.6f} ngspice={:.6f} rel={:.2e}".format(
        rows[("out", 0)]["hb"], rows[("out", 0)]["ngspice"], rows[("out", 0)]["rel_err"]))
    print("[A3 real] p2 h1: hb={:.6f} ngspice={:.6f} rel={:.2e}".format(
        rows[("p2", 1)]["hb"], rows[("p2", 1)]["ngspice"], rows[("p2", 1)]["rel_err"]))
    print("[A3 real] phase p2 h1 delta_deg={:.4f}".format(ph["delta"]))
    assert summary["ok"] is True
