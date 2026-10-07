"""噪声相关级联族（MT-1，内核在 core/noise_correlation.py，本模块只做注册壳）。

round17 §二 MT-1 规格「Hillbrand-Russer 1976 ABCD 噪声描述符链式级联——
Friis 仅匹配单通道成立，失配/多端口需相关矩阵」（2026-10-02）。单键
correlated_cascade_nf（级表 + 级间噪声相关系数 → F/NF + 相关−独立差）；
correlation_matrix/cholesky_factor/synthesize_correlated/combine_noise_power
为 core 纯函数不注册（分析面走 core 直调；正定性守卫与蒙特卡洛裁判锚在
tests/unit/test_noise_correlation.py）。rhos 注册面用 JSON 友好形态
[{"i": int, "j": int, "rho": float | [re, im]}]（tuple 键不可 JSON 序列化）；
core 直调面收 {(i, j): ρ} dict。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator


@register_calculator(
    "correlated_cascade_nf",
    "MT-1 相关级联噪声系数（round17 MT-1，Hillbrand-Russer 链式噪声相关"
    "矩阵在匹配 z0 功率波域的显式式）：级表（gain_db/nf_db，信号流向）+ "
    "级间加性噪声相关系数 → F_tot/NF + Friis 独立假设对照 + delta_nf_db"
    "（相关−独立差，核心产出）+ 等效噪声温度 + 逐级/逐对贡献分解。"
    "公式 F_tot = 1 + Σ(Fᵢ−1)/G_pre,ᵢ + 2Σ Re(ρᵢⱼ)√((Fᵢ−1)(Fⱼ−1)/"
    "(G_pre,ᵢ·G_pre,ⱼ))；ρ 全 0 逐位退化 Friis（与 core/cascade 对拍钉），"
    "ρ=±1 两极限有闭式锚，ρ 集合过 PSD 实测守卫（逐对 |ρ|≤1 不保证集合"
    "合法——三对不一致组合显式拒绝）⇒ F_tot≥1 解析保证。相噪相关性语义："
    "共享 LO 双通道 ρ=+1、独立本振 ρ=0。失配/多端口广义 ABCD 噪声矩阵"
    "不在本域（诚实边界，见 core/noise_correlation.py 模块头）",
    (("stages", "list[dict] 级表 [{gain_db: float dB, nf_db: float dB}, …]"
      "（信号流向；多余键忽略）"),
     ("rhos", "list[dict] 可选级间相关系数 [{i: int, j: int, rho: float|"
      "[re, im]}, …]（0≤i<j<n；缺省全独立=Friis）"),
     ("t0_k", "float 参考温度 K（>0，默认 290）")),
    required=("stages",),
)
def correlated_cascade_nf(
    stages: list,
    rhos: list | None = None,
    t0_k: float = 290.0,
) -> dict:
    from rfauto.core.noise_correlation import cascade_noise_factor

    rho_dict: dict[tuple[int, int], Any] = {}
    if rhos is not None:
        if not isinstance(rhos, list):
            raise ValueError(f"rhos 必须是 list[dict]，收到 {type(rhos)!r}")
        for k, item in enumerate(rhos):
            if not isinstance(item, dict):
                raise ValueError(
                    f"rhos[{k}] 必须是 dict（i/j/rho），收到 {type(item)!r}")
            i, j = item.get("i"), item.get("j")
            if isinstance(i, bool) or not isinstance(i, int) \
                    or isinstance(j, bool) or not isinstance(j, int):
                raise ValueError(
                    f"rhos[{k}].i/.j 必须是 int，收到 {(i, j)!r}")
            if i >= j:
                raise ValueError(
                    f"rhos[{k}] 须 i<j（0 起下标），收到 {(i, j)!r}")
            rho = item.get("rho")
            if isinstance(rho, list):
                if len(rho) != 2:
                    raise ValueError(
                        f"rhos[{k}].rho 复数形态必须是 [re, im]，"
                        f"收到 {rho!r}")
                rho = complex(float(rho[0]), float(rho[1]))
            rho_dict[(i, j)] = rho
    return cascade_noise_factor(stages, rho_dict or None, t0_k=t0_k)
