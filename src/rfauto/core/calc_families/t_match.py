"""T-match 匹配族（内核在 core/t_match.py，本模块只做注册壳）。"""

from __future__ import annotations

from .registry import register_calculator

# ─── r6 池「T-match 标签天线匹配」（ge6 pool3，2026-09-30）──────────────────
# Balanis 3ed §9.7.3 式 (9-48)–(9-55) 逐位口径（本地原文 PDF 核对，
# 出处与设计闭式推导见 core/t_match.py docstring）。分析=几何+Za→Zin；
# 设计=几何+Za+目标 Rin→T 棒长度+谐振化电容（正根闭式+正向回收）。


@register_calculator(
    "t_match_impedance",
    "T-match 输入阻抗（Balanis 3ed §9.7.3，(9-48)–(9-51)）：α=acosh"
    "((v²−u²+1)/2v)/acosh((v²+u²−1)/2uv)（u=a/a', v=s/a'）；Zt=jZ0·tan"
    "(kl'/2)、Z0=60·acosh((s²−a²−a'²)/(2aa'))；Zin=2Zt(1+α)²Za/"
    "(2Zt+(1+α)²Za)；l'≈λ/2 折合极限 Zin→(1+α)²Za（等半径 α=1→4Za）",
    (("freq_hz", "float Hz 设计频率"),
     ("main_radius_m", "float m 主偶极子半径 a"),
     ("bar_radius_m", "float m T 棒半径 a'"),
     ("spacing_m", "float m 两棒中心距 s（≥a+a'，相交显式拒绝）"),
     ("tbar_length_m", "float m T 棒总长 l'（<λ，tan 主支）"),
     ("dipole_length_m", "float m 主偶极子长度（≥l'，T-match 定义）"),
     ("za_re_ohm", "float Ω 无 T-match 天线中心阻抗实部（默认 73=半波锚）"),
     ("za_im_ohm", "float Ω 同上虚部（默认 42.5=半波锚）")),
    required=("freq_hz", "main_radius_m", "bar_radius_m", "spacing_m",
              "tbar_length_m", "dipole_length_m"),
)
def t_match_impedance(freq_hz: float, main_radius_m: float,
                      bar_radius_m: float, spacing_m: float,
                      tbar_length_m: float, dipole_length_m: float,
                      za_re_ohm: float = 73.0,
                      za_im_ohm: float = 42.5) -> dict:
    from rfauto.core.t_match import tmatch_impedance

    return tmatch_impedance(freq_hz, main_radius_m, bar_radius_m,
                            spacing_m, tbar_length_m, dipole_length_m,
                            za_re_ohm, za_im_ohm)


@register_calculator(
    "t_match_design",
    "T-match 设计闭式：几何+Za+目标 Rin → T 棒长度（正根二次式）与"
    "两只对称串联谐振化电容 C=1/(πf·Xin)（Balanis (9-55)）；含正向"
    "回代复核 rin_re_check；步升 (1+α)²·Re(Za) ≤ 目标显式报错"
    "（并联短截线只能降实部）",
    (("freq_hz", "float Hz 设计频率"),
     ("main_radius_m", "float m 主偶极子半径 a"),
     ("bar_radius_m", "float m T 棒半径 a'"),
     ("spacing_m", "float m 两棒中心距 s"),
     ("za_re_ohm", "float Ω 天线阻抗实部（默认 73=半波锚）"),
     ("za_im_ohm", "float Ω 天线阻抗虚部（默认 0=谐振点设计）"),
     ("target_rin_ohm", "float Ω 目标输入实部（默认 50）")),
    required=("freq_hz", "main_radius_m", "bar_radius_m", "spacing_m"),
)
def t_match_design(freq_hz: float, main_radius_m: float, bar_radius_m: float,
                   spacing_m: float, za_re_ohm: float = 73.0,
                   za_im_ohm: float = 0.0,
                   target_rin_ohm: float = 50.0) -> dict:
    from rfauto.core.t_match import tmatch_design

    return tmatch_design(freq_hz, main_radius_m, bar_radius_m, spacing_m,
                         za_re_ohm, za_im_ohm, target_rin_ohm)
