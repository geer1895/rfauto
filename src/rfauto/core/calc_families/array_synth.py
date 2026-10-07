"""阵列综合族（RB-ALG-1 差波束三法 + RB-ALG-2 MIP 量化阵列，Phase3 W3-E）。

内核：core/array_synthesis.py（bayliss_weights/villeneuve_weights/
schelkunoff_nulls，Bayliss 1968/Villeneuve 1984/Schelkunoff 1943，出处逐字
见内核 docstring 与 tests/unit/test_w3_e_array_synth.py 数表锚）与
core/quantized_array_milp.py（scipy.optimize.milp/HiGHS 精确 MIP，spec
sa_specs2 §七）。本模块只做注册壳（ris_cascade 同款：惰性导入内核、
返回 JSON 化 dict）。四键 reciprocal=False（spec §7.3-5：阵列方向图非端口
网络，不产出 S/ABCD——QM-1 §D-7 豁免位显式标注，豁免清单封闭断言由
test_physics_invariants 消费，主代理合流同步）。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator


@register_calculator(
    "array.bayliss_weights",
    "RB-ALG-1 Bayliss 差波束权向量（单脉冲低副瓣差方向图四参数闭式；"
    "Bayliss 1968 BSTJ 47(4):623-650 原文数表，Doerry SAND-2025-07335 "
    "转载双源锚定）。2N 元偶数阵奇对称实权，PSLL 回收=声明电平；文献"
    "值回收/恒等式门见 test_w3_e_array_synth",
    (("n_elements", "int 单元数（偶数，≥8；差波束奇对称 2N 元阵）"),
     ("sidelobe_level_db", "float 副瓣电平声明值 dB（负值，相对差主瓣峰）"),
     ("nbar", "int 等纹波零点对数（缺省 0=自动 min(7, N/2)；须 4 至 N/2）")),
    required=("n_elements", "sidelobe_level_db"),
    reciprocal=False,
)
def array_bayliss_weights(n_elements: int, sidelobe_level_db: float,
                          nbar: int = 0) -> dict[str, Any]:
    import numpy as np

    from rfauto.core.array_synthesis import (
        bayliss_weights,
        difference_pattern_psll_db,
    )

    nbar_arg = None if int(nbar) == 0 else int(nbar)
    w = bayliss_weights(int(n_elements), float(sidelobe_level_db),
                        nbar=nbar_arg)
    psll = difference_pattern_psll_db(w)
    half = int(n_elements) // 2
    aperture_imbalance = float(np.max(np.abs(w[:half] + w[half:][::-1])))
    return {
        "ok": True,
        "n_elements": int(n_elements),
        "sidelobe_level_db": float(sidelobe_level_db),
        "nbar": int(nbar_arg) if nbar_arg is not None else min(7, half),
        "weights": [float(v) for v in w],
        "weights_sum": float(w.sum()),
        "psll_db_realized": float(psll),
        "broadside_null_mag": float(abs(w.sum())),
        "antisymmetry_max_violation": aperture_imbalance,
        "notes": [
            "权向量=[a_N..a_1, -a_1..-a_N]（奇对称，max|w|=1）；",
            "PSLL 为稠密网格回代口径（相对差主瓣峰）；零点位置出自 "
            "Bayliss 数表，单一膨胀标量经确定性二分精化兑现声明电平"
            "（内核 docstring 如实声明）",
        ],
    }


@register_calculator(
    "array.villeneuve_weights",
    "RB-ALG-1 Villeneuve 和波束权向量（Taylor 零点的离散阵精确修正；"
    "Villeneuve 1984 IEEE TAP 32(10):1089-1093）。nbar=1 退化为均匀阵；"
    "PSLL 收敛带与单调钉见 test_w3_e_array_synth",
    (("n_elements", "int 单元数（≥2 且 ≥2·nbar）"),
     ("sidelobe_level_db", "float 副瓣电平目标 dB（负值）"),
     ("nbar", "int 内侧修正零点边界（缺省 4；nbar=1 均匀阵）")),
    required=("n_elements", "sidelobe_level_db"),
    reciprocal=False,
)
def array_villeneuve_weights(n_elements: int, sidelobe_level_db: float,
                             nbar: int = 4) -> dict[str, Any]:
    import numpy as np

    from rfauto.core.array_synthesis import array_factor, villeneuve_weights

    w = villeneuve_weights(int(n_elements), float(sidelobe_level_db),
                           int(nbar))
    u = np.linspace(-1.0, 1.0, 120001)
    mag = np.abs(array_factor(u, w))
    pk = np.nonzero((mag[1:-1] >= mag[:-2]) & (mag[1:-1] >= mag[2:]))[0] + 1
    main = float(mag[pk[0]])
    psll = float(20.0 * np.log10(float(mag[pk[1:]].max()) / main))
    return {
        "ok": True,
        "n_elements": int(n_elements),
        "sidelobe_level_db": float(sidelobe_level_db),
        "nbar": int(nbar),
        "weights": [float(v) for v in w],
        "weights_sum": float(w.sum()),
        "psll_db_realized": psll,
        "symmetry_max_violation": float(np.max(np.abs(
            w - w[::-1]))) if int(n_elements) % 2 == 0 else 0.0,
        "notes": [
            "和波束对称实权（max|w|=1）；nbar=1 时=均匀阵（多项式恒等）",
            "PSLL 为稠密网格回代口径；设计零点=Taylor 零点×膨胀 σ，"
            "外侧保持均匀阵自然零点",
        ],
    }


@register_calculator(
    "array.schelkunoff_nulls",
    "RB-ALG-1 Schelkunoff 单位圆零点置放权向量（Schelkunoff 1943 BSTJ "
    "22:80-107）。给 n-1 个零方向（方向余弦）得阵列多项式系数=激励；"
    "全自然零点=均匀阵恒等式钉见 test_w3_e_array_synth",
    (("n_elements", "int 单元数（≥2；零方向数须=n-1）"),
     ("null_positions", "array 零方向方向余弦序列（任意实数，按 2π wrap）"),
     ("spacing_lambda", "float 单元间距 d/lambda（缺省 0.5）")),
    required=("n_elements", "null_positions"),
    reciprocal=False,
)
def array_schelkunoff_nulls(n_elements: int, null_positions: list[float],
                            spacing_lambda: float = 0.5) -> dict[str, Any]:
    import numpy as np

    from rfauto.core.array_synthesis import schelkunoff_nulls

    w = schelkunoff_nulls(int(n_elements), list(null_positions),
                          spacing_lambda=float(spacing_lambda))
    is_real = not np.iscomplexobj(w)
    return {
        "ok": True,
        "n_elements": int(n_elements),
        "null_positions": [float(v) for v in null_positions],
        "spacing_lambda": float(spacing_lambda),
        "weights_real": [float(v) for v in w] if is_real else None,
        "weights_complex": None if is_real else [
            [float(v.real), float(v.imag)] for v in w],
        "weights_max_mag": float(np.abs(w).max()),
        "is_real": bool(is_real),
        "notes": [
            "零点共轭对称（±ψ 成对）时权重为实，否则为复（如实返回）；",
            "阵列多项式 E(z)=Σ w_m z^m，零点 z_k=exp(j2π·d/λ·u_k)；",
            "全 (n-1) 个自然零点 u_k=k·λ/(N·d) 时退化为均匀阵（恒等）",
        ],
    }


@register_calculator(
    "array.quantized_milp",
    "RB-ALG-2 量化约束阵列综合=MIP 精确解（scipy.milp/HiGHS，零新依赖）。"
    "移相器 b-bit/衰减器离散档/阵元开关 二进制选择+方向图约束线性化；"
    "目标=线性化峰值副瓣场，主瓣相干增益损失带内；回代 PSLL=真非线性"
    "口径；码字直连 firmware beam_codeword_table/beam_backsub_audit。"
    "不可行如实 ok=False（spec §7.4 风险③）",
    (("n_elements", "int 单元数（2-128；16-64 秒-分级）"),
     ("sidelobe_level_db", "float 副瓣电平声明值 dB（负值；亦定参考锥削）"),
     ("n_bits", "int 移相器位宽 1-8（码本 2^b；64 元建议 ≤4）"),
     ("atten_steps", "int 衰减器档数 G（≥1；1=无衰减自由度）"),
     ("atten_step_db", "float 每档衰减 dB（缺省 0.5）"),
     ("element_switch", "bool 是否启用阵元开关（缺省 False）"),
     ("spacing_lambda", "float 单元间距 d/lambda（缺省 0.5）"),
     ("scan_u0", "float 扫描方向余弦（缺省 0 侧射）"),
     ("max_mainlobe_loss_db", "float 主瓣相干增益损失上限 dB（缺省 1.0）"),
     ("mainlobe_half_u", "float 主瓣半宽（方向余弦；缺省=参考锥削第一零点自动探测，探测失败回退 1.6×均匀阵第一零点）"),
     ("n_sidelobe_points", "int 副瓣约束网格点数（缺省 min(720, max(60, 6N))）"),
     ("n_tangent", "int 切平面旋转角数 K（缺省 16，保守带约 0.166dB）"),
     ("mip_rel_gap", "float MIP 相对间隙（缺省 1e-4，与内核 options 同源）"),
     ("time_limit_s", "float 求解墙钟上限 s（缺省 0=不设；G15 确定性钉"
      "要求 fixture 规模瞬完）")),
    required=("n_elements", "sidelobe_level_db", "n_bits", "atten_steps"),
    reciprocal=False,
)
def array_quantized_milp(n_elements: int, sidelobe_level_db: float,
                         n_bits: int, atten_steps: int,
                         atten_step_db: float = 0.5,
                         element_switch: bool = False,
                         spacing_lambda: float = 0.5,
                         scan_u0: float = 0.0,
                         max_mainlobe_loss_db: float = 1.0,
                         mainlobe_half_u: float | None = None,
                         n_sidelobe_points: int | None = None,
                         n_tangent: int = 16,
                         mip_rel_gap: float = 1e-6,
                         time_limit_s: float = 0.0) -> dict[str, Any]:
    from rfauto.core.quantized_array_milp import quantized_array_milp

    result = quantized_array_milp(
        int(n_elements), float(sidelobe_level_db),
        n_bits=int(n_bits), atten_steps=int(atten_steps),
        atten_step_db=float(atten_step_db),
        element_switch=bool(element_switch),
        spacing_lambda=float(spacing_lambda), scan_u0=float(scan_u0),
        max_mainlobe_loss_db=float(max_mainlobe_loss_db),
        mainlobe_half_u=mainlobe_half_u,
        n_sidelobe_points=n_sidelobe_points, n_tangent=int(n_tangent),
        mip_rel_gap=float(mip_rel_gap),
        time_limit_s=(None if float(time_limit_s) <= 0.0
                      else float(time_limit_s)),
    )
    if not result.get("ok"):
        raise ValueError(
            "array.quantized_milp 不可行/求解失败: "
            f"{result.get('reason')}（{result.get('solver_status', '')[:120]}）"
            "——spec 过紧时如实拒绝，不凑")
    return result
