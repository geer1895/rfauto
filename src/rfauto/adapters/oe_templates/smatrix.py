"""S 矩阵装配/反演/修正链（TL 线基反演、50Ω 重归一、耦合段 ABCD/S4）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass



# ─── 端接口径统一后处理 helper（W2⑤ 定案 (a)，2026-09-16）────────────────────
# 机理（followUps①）：openEMS 端口面贴 PML，非激励端的
# 线由 PML 按**线自身 Z0** 匹配端接，CalcPort(ref_impedance=50) 的 uf_ref/
# uf_inc 只是 50Ω 伪波分解 → 凡端口线 ≠50Ω 的模板（wstep/via/msl_cpw/
# atten/sma_launcher），引擎单激励 'S11' 与 50Ω 双端接裁判（fake Pozar
# ABCD@50、skrf renormalize([50,50])）本非同一量（wstep 实证：引擎口径闭式
# 逐点偏差 0.033/0.029 vs fake 口径 0.171/0.305）。
# 定案 (a)：50Ω 参考是全项目裁判统一口径（fake/skrf/HFSS 仲裁/ADS），不改
# 裁判定义；引擎侧后处理统一——单激励 uf 比值按列反演到各端口线自身 Z0 真
# 波基（等价于 footer CalcPort(ref_impedance=Z_k) 的代数恒等式，无需改 CSV
# 契约）→（线基内纯相位去嵌到 DUT 参考面）→（skrf renormalize）→ 50Ω。
# 全链确定性线性代数，离线验证 vs fake Pozar 独立构造 1e-12 一致
# （tests/unit/test_port_renormalize.py）。
# ⚠ 单激励 uf 比值是**带载比值**（非激励端在 50Ω 基下被 Γ=(Z−50)/(Z+50)
# 端接，a≠0）——对装配矩阵整块 renormalize_s 是错的（合成数据实测误差
# =|Γ_step|=0.176）；必须按列反演（本 helper 的 loaded_ratios_to_line_basis）。
# 本波只接 wstep；其余 ≠50Ω 模板接入列 followUps（renormalize 耦合全端口，
# 须双激励装配全矩阵，#208 进程隔离轮转范式；4 端口模板馈线=50Ω 时反演
# 退化为恒等，天然安全）。
def tl_gamma_per_m(f_hz: Any, eps_eff: float, tan_d: float = 0.0) -> Any:
    """均匀 TL 复传播常数 γ=α+jβ（rad/m；fake `_wstep_sparams` 同式，确定性）。

    α = π·f·√εeff·tanδ/c（一阶介质损耗，fake 同式），β = 2π·f·√εeff/c。
    """
    import numpy as np

    f = np.asarray(f_hz, dtype=float)
    c0 = 299792458.0
    s = math.sqrt(float(eps_eff))
    return np.pi * f * s * float(tan_d) / c0 + 1j * (2.0 * np.pi * f * s / c0)


def loaded_ratios_to_line_basis(s_raw: Any, z_line_ohm: Any,
                                z_ref_ohm: float = 50.0) -> Any:
    """单激励 uf 比值（带载，CalcPort ref=z_ref）→ 各端口线自身 Z0 真波基 S。

    引擎第 j 列（端口 j 激励）的 uf 比值 r_ij=b_i/a_j 中，非激励端 i 被
    PML 按线自身 Z_i 匹配端接——在 z_ref 基下这是负载 Γ_i=(Z_i−z_ref)/
    (Z_i+z_ref)（a_i=Γ_i·b_i≠0），故比值是带载量而非 S^z_ref 矩阵本征列。
    本函数按列恢复物理 u/i 再换到 Z_k 基（≡CalcPort(ref_impedance=Z_k)，
    代数恒等；PML 端接在 Z_k 基=匹配，负载伪象精确消除）：

        S[j,j] = [zr(1+r) − Z_j(1−r)] / [zr(1+r) + Z_j(1−r)]
        S[i,j] = r_ij·2√(zr·Z_i)/(Z_i+zr) / a_j^Z，
        a_j^Z = [zr(1+r_jj) + Z_j(1−r_jj)]/(2√(zr·Z_j))

    `s_raw`：(N,P,P) 复数，第 j 列取自端口 j 激励的 run（P=2 时 S12/S22
    列取激励 2 的 CSV，#208 装配）。`z_line_ohm`：每端口线特征阻抗
    （标量/复数/(N,) 数组均可；HJ 闭式 forward_z0 或引擎自算 ZL，勿写死）。
    Z_k=z_ref 时该端口因子恒等（50Ω 线模板天然无变化）。
    """
    import numpy as np

    s = np.asarray(s_raw, dtype=complex)
    if s.ndim != 3 or s.shape[1] != s.shape[2]:
        raise ValueError(f"s_raw 须为 (N,P,P)，得 {s.shape}")
    n, p, _ = s.shape
    zl = np.asarray(z_line_ohm, dtype=complex)
    zl = np.broadcast_to(zl, (n, p)).copy()
    zr = float(z_ref_ohm)
    out = np.empty_like(s)
    for j in range(p):
        r_jj = s[:, j, j]
        a_j = ((zr * (1.0 + r_jj) + zl[:, j] * (1.0 - r_jj))
               / (2.0 * np.sqrt(zr * zl[:, j])))
        b_j = ((zr * (1.0 + r_jj) - zl[:, j] * (1.0 - r_jj))
               / (2.0 * np.sqrt(zr * zl[:, j])))
        out[:, j, j] = b_j / a_j
        for i in range(p):
            if i == j:
                continue
            # 非激励端：b_i^Z = r_ij·2√(zr·Z_i)/(Z_i+zr)（a_i^Z≡0 自动成立）
            b_i = (s[:, i, j] * 2.0 * np.sqrt(zr * zl[:, i])
                   / (zl[:, i] + zr))
            out[:, i, j] = b_i / a_j
    return out


def renorm_engine_s_to_ref(
    s_raw: Any,
    z_line_ohm: Any,
    z_ref_ohm: float = 50.0,
    deembed_lens_m: list[float] | None = None,
    gamma: list[Any] | None = None,
    z_out_ohm: Any = None,
) -> Any:
    """openEMS 引擎 S 全链统一到参考口径（W2⑤ 定案 (a)，可复用 helper）。

    ① `loaded_ratios_to_line_basis`：单激励带载比值 → 各端口线自身 Z0 真波
    基（PML 端接在线基=匹配，DUT 与端接解耦）；② 线基内去嵌：均匀匹配线移
    参考面=纯指数 e^{+γ_k·l_k} 对角/e^{γ1l1+γ2l2} 交叉（γ 复数时含衰减，
    精确）；③ skrf `renormalize_s`（s_def='traveling'=CalcPort 伪波口径）
    线基 → `z_out_ohm`（默认 [z_ref]*2）——实数 Z 下与 fake Pozar ABCD@50
    精确同一变换。

    - `s_raw`：(N,P,P) 带载 uf 比值（第 j 列=激励 j 的 run，#208 装配）。
    - `z_line_ohm`：每端口线 Z0（HJ 闭式 forward_z0 标量，或引擎自算 ZL 的
      (N,) 复数组——后者基最自洽，HJ-vs-引擎 Z 偏差转为被测 DUT 差异）。
    - `deembed_lens_m`/`gamma`：每端口"测量面→DUT 参考面"长度（米）与复传播
      常数 γ=α+jβ（rad/m，标量或 (N,)）；引擎自算 β（port_beta.csv 金标准
      #162）优先，HJ 闭式（tl_gamma_per_m）兜底。None=不去嵌。
    - `z_out_ohm`：输出基（默认 50Ω 参考；传 z_line_ohm 得线基输出，用于
      幅度镜像/互易的物理判读）。

    离线钉子（test_port_renormalize.py）：Z=50 恒等；理想阶跃真波基闭式
    [[Γ,t],[t,−Γ]] 带载合成 → 全链输出 vs fake Pozar ABCD@50 逐点一致
    （1e-12）；整矩阵 renormalize_s 反例（误差=|Γ_step|）钉死带载陷阱。
    """
    import numpy as np
    from skrf.network import renormalize_s

    s = np.asarray(s_raw, dtype=complex)
    if s.ndim != 3 or s.shape[1] != s.shape[2]:
        raise ValueError(f"s_raw 须为 (N,P,P)，得 {s.shape}")
    s_line = loaded_ratios_to_line_basis(s, z_line_ohm, z_ref_ohm)
    if deembed_lens_m is not None:
        if gamma is None:
            raise ValueError("deembed_lens_m 需配套 gamma（α+jβ rad/m）")
        p = s_line.shape[1]
        if len(deembed_lens_m) != p or len(gamma) != p:
            raise ValueError("deembed_lens_m/gamma 须逐端口给定")
        th = [np.asarray(g, dtype=complex) * float(length)
              for g, length in zip(gamma, deembed_lens_m, strict=True)]
        s_line = s_line.copy()
        # 去嵌因子 e^{+γ_i l_i + γ_j l_j}（γ=α+jβ 复数：e^{αl} 补回衰减、
        # e^{jβl} 退相位；勿写成 exp(1j·γl)——复 γ 下会变成 e^{−βl} 假衰减）
        for i in range(p):
            for j in range(p):
                s_line[:, i, j] = s_line[:, i, j] * np.exp(th[i] + th[j])
    z_out = (np.asarray(z_out_ohm, dtype=complex)
             if z_out_ohm is not None else np.full(s_line.shape[1], float(z_ref_ohm)))
    zl = np.broadcast_to(np.asarray(z_line_ohm, dtype=complex),
                         (s_line.shape[0], s_line.shape[1])).copy()
    zo = np.broadcast_to(z_out, (s_line.shape[0], s_line.shape[1])).copy()
    return renormalize_s(s_line, zl, zo, s_def="traveling")


def wstep_deembed_lens_m(params: dict[str, Any],
                         board_mm: float = 60.0) -> tuple[float, float]:
    """wstep 模板"测量面→画布线端（y=±line_len/2，DUT 面）"去嵌长度（米）。

    模板口径单源（与 _wstep_lines 同式）：端口面=板边 ±board_mm（渲染
    footer BOARD=60e-3），MeasPlaneShift=(Y0+BOARD)/3（Y0=−line_len/2）→
    测量面到线端 = board−half−shift = 2·(board−half)/3（两端同式）。用于把
    引擎测量面对齐到 fake 裁判的 seg_len_mm=line_len/2 面约定。
    """
    half = float(params.get("line_len_mm", 40.0)) * 1e-3 / 2.0
    b = float(board_mm) * 1e-3
    shift = (b - half) / 3.0          # MeasPlaneShift=(Y0+BOARD)/3，Y0=−half
    lens = (b - half) - shift         # 测量面到线端 = 2·(board−half)/3（两端同）
    return (lens, lens)
