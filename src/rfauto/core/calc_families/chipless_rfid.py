"""chipless RFID 频域零点编码族（内核在 core/chipless_rfid.py，本模块只做注册壳）。"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator

# ─── r6 池「chipless RFID 编码标签」（ge6 pool3，2026-09-30）─────────────────
# 滤波器组零点编码：码字→谐振器组规划（等 Q 深谷）/频点→码字/扫频谱→
# 码字反解（谷深判据+汉明距离）。内核出处与级联口径见 core/chipless_rfid.py
# docstring（Matthaei 斜率参数 + 并联串联 RLC 陷波精确式；Karmakar 系
# chipless 频域编码惯例）。与 rfid.py 链路预算族互补（tag 端谐振器组 vs
# 读写器链路），域无重叠。


@register_calculator(
    "chipless_tag_plan",
    "chipless RFID 码字→谐振器组规划（等 Q 假设深谷）：code 槽位 0/1 →"
    "各谐振器频率（槽中心）/R=x/Q/预期谷深 20lg(2R/(2R+Z0))/无耗近似"
    "带宽 f·Z0/(2x)（Matthaei 电抗斜率口径，core/chipless_rfid.py）",
    (("code", "list[int] 码字（每槽 0/1，长度=n_slots）"),
     ("f_start_hz", "float Hz 扫描带下缘"),
     ("f_stop_hz", "float Hz 扫描带上缘（>f_start）"),
     ("q_unloaded", "float - 谐振器无载 Q（统一等 Q，>1）"),
     ("slope_ohm", "float Ω 电抗斜率参数 x=ω0·L（统一）"),
     ("z0_ohm", "float Ω 读出线特性阻抗（默认 50）")),
    required=("code", "f_start_hz", "f_stop_hz", "q_unloaded", "slope_ohm"),
)
def chipless_tag_plan(code: list[int], f_start_hz: float, f_stop_hz: float,
                      q_unloaded: float, slope_ohm: float,
                      z0_ohm: float = 50.0) -> dict:
    from rfauto.core.chipless_rfid import plan_resonator_bank

    return plan_resonator_bank(code, f_start_hz, f_stop_hz, q_unloaded,
                               slope_ohm, z0_ohm)


@register_calculator(
    "chipless_tag_encode",
    "chipless RFID 实测谐振频点→码字：每频点映最近槽位（容差="
    "tol_frac×槽距）；越容差/带外/两频点同槽显式报错（不静默丢位）",
    (("resonance_freqs_hz", "list[float] 检测到的谐振频率（Hz）"),
     ("f_start_hz", "float Hz 扫描带下缘"),
     ("f_stop_hz", "float Hz 扫描带上缘"),
     ("n_slots", "int - 编码槽位数（≥2）"),
     ("tol_frac", "float - 映射容差（×槽距，默认 0.4）")),
    required=("resonance_freqs_hz", "f_start_hz", "f_stop_hz", "n_slots"),
)
def chipless_tag_encode(resonance_freqs_hz: list[float], f_start_hz: float,
                        f_stop_hz: float, n_slots: int,
                        tol_frac: float = 0.4) -> dict:
    from rfauto.core.chipless_rfid import encode_tag_code

    return encode_tag_code(resonance_freqs_hz, f_start_hz, f_stop_hz,
                           int(n_slots), tol_frac)


@register_calculator(
    "chipless_tag_decode",
    "chipless RFID 扫频谱→码字反解：逐槽窗内谷深（max−min |S21|dB）"
    ">阈值→1；给 codebook 时附最近合法码字与汉明距离；窗内采样<2 的"
    "槽如实记 unresolved（#314 掩码纪律同源：不猜）",
    (("freq_hz", "list[float] 扫频轴（Hz，单调递增）"),
     ("s21_db", "list[float] |S21|（dB，与 freq_hz 等长）"),
     ("f_start_hz", "float Hz 扫描带下缘"),
     ("f_stop_hz", "float Hz 扫描带上缘"),
     ("n_slots", "int - 编码槽位数（≥2）"),
     ("codebook", "list[list[int]] 合法码字表（可选，给则报汉明距离）"),
     ("depth_threshold_db", "float dB 谷深门限（默认 3）"),
     ("window_frac", "float - 谷检窗宽（×槽距，≤1，默认 0.8）")),
    required=("freq_hz", "s21_db", "f_start_hz", "f_stop_hz", "n_slots"),
)
def chipless_tag_decode(freq_hz: list[float], s21_db: list[float],
                        f_start_hz: float, f_stop_hz: float, n_slots: int,
                        codebook: list[list[int]] | None = None,
                        depth_threshold_db: float = 3.0,
                        window_frac: float = 0.8) -> dict[str, Any]:
    from rfauto.core.chipless_rfid import decode_from_spectrum

    return decode_from_spectrum(freq_hz, s21_db, f_start_hz, f_stop_hz,
                                int(n_slots), codebook=codebook,
                                depth_threshold_db=depth_threshold_db,
                                window_frac=window_frac)
