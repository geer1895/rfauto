r"""§10.4 D6 SI 垂直通道演示——S 参数 → 脉冲响应 → 眼图 → 预加重（确定性内核）。

用法（工作区根目录）：
    .venv\Scripts\python.exe scripts\si_channel_demo.py

输出（确定性、无网络、无真机、无新依赖）：理想无色散通道与 5 个一阶 RC 通道的
插损/群延迟/眼图指标，加 1-tap FFE 预加重前后的眼高对比。所有数字均由
core/si_channel.py 确定性内核产出；RC 闭式最坏情形眼高 1−2·exp(−UI/RC) 作
独立对照列（实测偏差见 tests/unit/test_si_channel.py 文档串）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.core import si_channel as si  # noqa: E402

BAUD = 1.0e9
SPS = 32
N_FFT = 8190
DT = 1.0 / (BAUD * SPS)
FREQS = np.fft.rfftfreq(N_FFT, d=DT)
BITS = si.prbs_bits(127, order=7)


def _eye(freqs: np.ndarray, s21: np.ndarray, alpha: float = 0.0):
    return si.run_channel_eye(
        BITS, SPS, freqs, s21, symbol_rate_baud=BAUD, alpha=alpha
    ).metrics


def main() -> None:
    ui_ps = 1.0e12 / BAUD
    print(
        f"网格: {FREQS.size} 点 0..{FREQS[-1] / 1e9:.1f} GHz, dt={DT * 1e12:.2f} ps, "
        f"baud={BAUD / 1e9:.1f} Gbps, sps={SPS}, PRBS7={BITS.size} bit"
    )
    print(f"PRBS7 平衡: 1 的个数={int(BITS.sum())}（最大长度序列期望 (2^7)/2 = 64）")
    print()

    print("== 理想无色散通道（时延 100·dt，0 dB / 群延迟恒定）==")
    s_id = si.ideal_delay_s21(FREQS, 100 * DT)
    mt = _eye(FREQS, s_id)
    print(
        f"  群延迟={si.group_delay_s(FREQS, s_id)[0] * 1e12:.3f} ps  "
        f"插损@nyq={si.insertion_loss_at_db(FREQS, s_id, 0.5e9):.4f} dB"
    )
    print(
        f"  眼高={mt.eye_height:.6f}（满幅=1） 眼宽={mt.eye_width_ui:.4f} UI  "
        f"抖动={mt.jitter_pp_ui:.4f} UI"
    )
    print()

    print(f"== 一阶 RC 通道（UI = {ui_ps:.1f} ps）==")
    print(
        "  f3(GHz)  RC(ps)  插损@nyq(dB)  群延迟@DC(ps)   眼高   闭式最坏   "
        "眼宽(UI)  抖动(UI)  α=0.5眼高"
    )
    for f3_ghz in (0.15, 0.25, 0.5, 1.0, 2.0):
        f3 = f3_ghz * 1e9
        rc = 1.0 / (2.0 * np.pi * f3)
        s21 = si.rc_lowpass_s21(FREQS, 1.0, rc)
        m0 = _eye(FREQS, s21)
        m1 = _eye(FREQS, s21, alpha=0.5)
        analytic = 1.0 - 2.0 * np.exp(-(1.0 / BAUD) / rc)
        print(
            f"  {f3_ghz:7.2f} {rc * 1e12:7.1f} "
            f"{si.insertion_loss_at_db(FREQS, s21, BAUD / 2):12.2f} "
            f"{si.group_delay_s(FREQS, s21)[0] * 1e12:14.1f} "
            f"{m0.eye_height:6.4f} {analytic:9.4f} {m0.eye_width_ui:10.4f} "
            f"{m0.jitter_pp_ui:9.4f} {m1.eye_height:10.4f}"
        )
    print()

    print("== 1-tap FFE 预加重扫描（f3=0.15 GHz 有损通道；α=0 为无预加重）==")
    rc = 1.0 / (2.0 * np.pi * 0.15e9)
    s21 = si.rc_lowpass_s21(FREQS, 1.0, rc)
    for alpha in (0.0, 0.5, 1.0, 1.5, 2.0):
        metrics = _eye(FREQS, s21, alpha=alpha)
        print(
            f"  α={alpha:4.1f}（{si.alpha_to_deemphasis_db(alpha):5.2f} dB）  "
            f"眼高={metrics.eye_height:.4f}  眼宽={metrics.eye_width_ui:.4f} UI"
        )


if __name__ == "__main__":
    main()
