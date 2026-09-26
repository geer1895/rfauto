"""DP-11 P1：IEEEP370 2x-thru AFR 夹具去嵌（测量链的 fix-DUT-fix 剥离）。

定位（规格书 §2）：VNA 测得的复合件是 ``FIX ** DUT ** FIX``，DUT 本体
经 2x-thru AFR（automatic fixture removal）剥离：测一个 fix-fix 直通件
（2x-thru），按 IEEEP370 口径去嵌。缺省 **SE_NZC**（单端、无夹具先验，
仅需 2x-thru 实测件）；多端口走 **MM_NZC**；**ZC**（需 fix-dut-fix 第二
实测件）为 opt-in——DP-15 C2 实证合成语料上 ZC 不达标（gated=False，
不设门，#122 不凑绿），本模块沿该结论只做薄透传。

skrf 接入点（runs/df6_a3/skrf2x_audit.md §1 注）：IEEEP370 类在
``skrf.calibration.deembedding`` 子模块，**不在** ``skrf.calibration``
顶层（顶层 import 即 ImportError——tests 钉）。

DC 预处理（DP-15 C2 坑预声明）：P370 内部 IFFT/时域剥离对带限合成网络
DC 敏感，缺省做 ``extrapolate_to_dc``（runs/df6_dp15c2/criteria.md §0.2
实测：IEEE370 合规语料三模式无差异，守卫保留）。

预检（规格书 §2：预检不过 → ok=False 如实，不出去嵌结果）：
- **对称性**：2x-thru 是互易对称件——max‖S21|−|S12‖ ≤ sym_tol（线性域，
  缺省 1e-3；理想语料实测 ≤1e-12 量级，门留 3 个量级余量）；
- **|S21| 平滑性**：|S21|_dB 的二阶差分 max ≤ smooth_tol（dB，缺省 0.5；
  合规语料实测 ≪0.01）——2x-thru 应是均匀传输线段，物理上不可能有
  谐振尖峰/台阶，非平滑=测错件或夹具违规。

全部确定性：纯 numpy + skrf，无随机、无网络、无全局状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import skrf

#: P370 类导入路径钉（审计 §1 注：不在 skrf.calibration 顶层）
_DEEMBEDDING_MODULE = "skrf.calibration.deembedding"

#: 缺省 DC 预处理（沿 core/deembed_referee.DEFAULT_DC_MODE 口径；
#: 显式常量复制避免 import 其私有面）
DEFAULT_DC_MODE = "extrapolate_to_dc"

#: 预检缺省门（判据预声明见模块 docstring）
DEFAULT_SYM_TOL = 1e-3
DEFAULT_SMOOTH_TOL_DB = 0.5

#: 深度阈值：|S| 低于此值（线性域）时 dB 平滑性二阶差分噪声放大，
#: 平滑性只在 |S21|_lin ≥ SMOOTH_FLOOR 的频点判（谷底 dB 波动非物理信息）
SMOOTH_FLOOR_LIN = 1e-3  # -60 dB


@dataclass
class PrecheckResult:
    """2x-thru 预检结果（对称性 + 平滑性，门值显式随结果走）。"""

    ok: bool
    symmetry_max: float
    smoothness_max_db: float
    sym_tol: float
    smooth_tol_db: float
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "symmetry_max": self.symmetry_max,
            "smoothness_max_db": self.smoothness_max_db,
            "sym_tol": self.sym_tol,
            "smooth_tol_db": self.smooth_tol_db,
            "failures": list(self.failures),
        }


def _as_2port(net: Any, arg_name: str) -> skrf.Network:
    """Network 类型 + 2 端口守卫（不等 skrf 晚报）。"""
    if not isinstance(net, skrf.Network):
        raise TypeError(f"{arg_name} 须为 skrf.Network，实际 {type(net).__name__}")
    if net.nports != 2:
        raise ValueError(f"{arg_name} 须为 2 端口网络，实际 {net.nports} 端口")
    return net


def _dc_preprocess(net: skrf.Network, dc_mode: str | None) -> skrf.Network:
    """P370 输入 DC 预处理（同 core/deembed_referee 语义；显式白名单）。"""
    from skrf.calibration.deembedding import IEEEP370_SE_NZC_2xThru

    if dc_mode is None:
        return net
    if dc_mode == "extrapolate_to_dc":
        return IEEEP370_SE_NZC_2xThru.extrapolate_to_dc(net)
    if dc_mode == "add_dc":
        return IEEEP370_SE_NZC_2xThru.add_dc(net)
    raise ValueError(
        f"dc_mode 只能是 'extrapolate_to_dc'/'add_dc'/None，实际 {dc_mode!r}")


def _back_to_grid(net: skrf.Network, freq: skrf.Frequency) -> skrf.Network:
    """P370 结果（DC 扩展栅格）插值回原栅格。"""
    if net.frequency == freq:
        return net
    return net.interpolate(freq)


def check_2xthru_preconditions(
    twoxthru: skrf.Network,
    *,
    sym_tol: float = DEFAULT_SYM_TOL,
    smooth_tol_db: float = DEFAULT_SMOOTH_TOL_DB,
) -> PrecheckResult:
    """2x-thru 件预检：对称性（线性域）+ |S21| dB 平滑性（二阶差分）。

    判据（预声明，criteria.md G3）：
    - 对称性 max‖S21|−|S12‖_lin ≤ sym_tol（互易对称件）；
    - 平滑性 max|Δ²(|S21|_dB)| ≤ smooth_tol_db，仅在线性域
      |S21| ≥ SMOOTH_FLOOR_LIN 的频点上判（深谷 dB 噪声非物理信息）。
    """
    twoxthru = _as_2port(twoxthru, "twoxthru")
    s21 = np.abs(twoxthru.s[:, 1, 0])
    s12 = np.abs(twoxthru.s[:, 0, 1])
    sym_max = float(np.max(np.abs(s21 - s12))) if s21.size else 0.0

    smooth_max = 0.0
    if s21.size >= 3:
        s21_db = 20.0 * np.log10(np.maximum(s21, 1e-300))
        # 平滑性只在连续三个 |S21| ≥ SMOOTH_FLOOR_LIN 的频点上判二阶差分
        # （任一点入深谷即跳过该三元组——谷缘 dB 台阶是深谷本身，不是
        # 独立的物理不 smooth 证据）
        d2 = np.abs(s21_db[2:] - 2.0 * s21_db[1:-1] + s21_db[:-2])
        keep = ((s21[:-2] >= SMOOTH_FLOOR_LIN)
                & (s21[1:-1] >= SMOOTH_FLOOR_LIN)
                & (s21[2:] >= SMOOTH_FLOOR_LIN))
        if d2[keep].size:
            smooth_max = float(np.max(d2[keep]))

    failures: list[str] = []
    if sym_max > sym_tol:
        failures.append(
            f"对称性不过：max||S21|-|S12||={sym_max:.3e} > {sym_tol:.1e}（非对称/"
            f"非互易件不能当 2x-thru 用）")
    if smooth_max > smooth_tol_db:
        failures.append(
            f"|S21| 平滑性不过：max 二阶差分={smooth_max:.3f} dB > "
            f"{smooth_tol_db:.1f} dB（均匀直通不该有谐振尖峰/台阶）")
    return PrecheckResult(
        ok=not failures,
        symmetry_max=sym_max,
        smoothness_max_db=smooth_max,
        sym_tol=float(sym_tol),
        smooth_tol_db=float(smooth_tol_db),
        failures=failures,
    )


def deembed_2xthru(
    dut_fdf: skrf.Network,
    twoxthru: skrf.Network,
    *,
    dc_mode: str | None = DEFAULT_DC_MODE,
    sym_tol: float = DEFAULT_SYM_TOL,
    smooth_tol_db: float = DEFAULT_SMOOTH_TOL_DB,
    zc_fix_dut_fix: skrf.Network | None = None,
) -> dict[str, Any]:
    """2x-thru AFR 去嵌：``(FIX DUT FIX)`` + 2x-thru → DUT 本体。

    预检不过 → ``ok=False`` + ``precheck`` 明细，**不产出**去嵌网络
    （规格书 §2：如实失败，不静默装成功）。ZC 变体（opt-in，
    ``zc_fix_dut_fix`` 给定时）结果只进 ``zc_variant`` 子字典且
    ``gated=False``（DP-15 C2 结论：合成语料不达标，不设门）。

    Returns:
        {ok, network | None, precheck, dc_mode, n_points, deembedder,
        zc_variant?, error?}
    """
    dut_fdf = _as_2port(dut_fdf, "dut_fdf")
    twoxthru_in = _as_2port(twoxthru, "twoxthru")
    if dut_fdf.frequency != twoxthru_in.frequency:
        raise ValueError(
            f"频率栅格不一致：dut_fdf {len(dut_fdf.f)} 点 vs "
            f"twoxthru {len(twoxthru_in.f)} 点")

    pre = check_2xthru_preconditions(
        twoxthru_in, sym_tol=sym_tol, smooth_tol_db=smooth_tol_db)
    out: dict[str, Any] = {
        "ok": False,
        "network": None,
        "precheck": pre.to_dict(),
        "dc_mode": dc_mode,
        "n_points": int(np.asarray(dut_fdf.f).size),
        "deembedder": "IEEEP370_SE_NZC_2xThru",
    }
    if not pre.ok:
        out["error"] = "2x-thru 预检不过：" + "；".join(pre.failures)
        return out

    from skrf.calibration.deembedding import IEEEP370_SE_NZC_2xThru

    try:
        th = _dc_preprocess(twoxthru_in, dc_mode)
        ff = _dc_preprocess(dut_fdf, dc_mode)
        deembedder = IEEEP370_SE_NZC_2xThru(
            dummy_2xthru=th, name="rfauto_dp11_afr_nzc",
            z0=float(np.real(np.mean(dut_fdf.z0[:, 0]))),
        )
        deembedded = _back_to_grid(deembedder.deembed(ff), dut_fdf.frequency)
    except Exception as exc:
        out["error"] = f"P370 NZC 去嵌失败: {exc}"
        return out
    out["ok"] = True
    out["network"] = deembedded

    # ── ZC 变体（opt-in，只记不门；DP-15 C2 结论沿袭）───────────────────────
    if zc_fix_dut_fix is not None:
        from skrf.calibration.deembedding import IEEEP370_SE_ZC_2xThru

        zc_in = _as_2port(zc_fix_dut_fix, "zc_fix_dut_fix")
        zc_entry: dict[str, Any] = {"ran": False, "gated": False}
        try:
            th_z = _dc_preprocess(twoxthru_in, dc_mode)
            ff_z = _dc_preprocess(zc_in, dc_mode)
            zc = IEEEP370_SE_ZC_2xThru(
                dummy_2xthru=th_z, dummy_fix_dut_fix=ff_z,
                name="rfauto_dp11_afr_zc", z0=50.0,
            )
            zc_net = _back_to_grid(zc.deembed(ff_z), dut_fdf.frequency)
            zc_entry.update({"ran": True, "network": zc_net})
        except Exception as exc:
            zc_entry["error"] = str(exc)
        out["zc_variant"] = zc_entry
    return out


def recovery_delta_s21_db(deembedded: skrf.Network,
                          reference: skrf.Network) -> float:
    """去嵌回收残差：|ΔS21| dB 幅度逐频最大值（G3 门 ≤1e-3 dB 的口径）。"""
    deembedded = _as_2port(deembedded, "deembedded")
    reference = _as_2port(reference, "reference")
    if deembedded.frequency != reference.frequency:
        raise ValueError("两网络频率栅格不一致")
    a = 20.0 * np.log10(np.abs(deembedded.s[:, 1, 0]) + 1e-300)
    b = 20.0 * np.log10(np.abs(reference.s[:, 1, 0]) + 1e-300)
    return float(np.max(np.abs(a - b)))
