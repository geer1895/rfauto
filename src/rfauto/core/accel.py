r"""Aitken Δ² 平方收敛加速内核（纯函数，MP-B1）。

数学锚（裁判 = 数值分析标准结果，独立于本模块实现，#118）
------------------------------------------------
对线性收敛序列 x_n → x*（误差 |e_{n+1}| ≈ q|e_n|，0<q<1），Aitken Δ² 变换::

    A_n = x_{n+2} - (x_{n+2}-x_{n+1})² / ((x_{n+2}-x_{n+1}) - (x_{n+1}-x_n))

满足：
1. 纯几何序列 x_n = x* + C·q^n：**精确**（实数算术下 A_n = x*，浮点实现
   残差 ~机器精度）；含次主导项 x_n = x* + C1·q^n + C2·q^{2n} 时残差
   = O(q^{2n})——即每一步把误差带从 q 压到 q²（Süli & Mayers, An
   Introduction to Numerical Analysis, Aitken's Δ² method 节）；
2. 常数序列（不动点已到达）与等差序列（无极限）：差分相等 → 分母为 0
   → 恒等返回 x_{n+2}（不伪造加速值）；
3. 震荡序列（如实，不吞行为）：周期-2 震荡（如 (-1)^n）被映射为双周期
   均值（A((-1)^n) = 0），有限、不产 NaN；对震荡线性收敛（x_n = x* +
   C·(-q)^n）Δ² 同样精确——这是它相对单调序列的适用面优势。

守卫（core 惯例：非法输入显式 ValueError，不静默兜底）：
- 序列长度 < 3、输入为 str/bytes、元素不可转 float 或非有限 → ValueError；
- 加速值非有限（数值溢出/灾难性相消）→ 恒等返回 x_{n+2}（不产出 inf/nan）。

分层与登记
----------
- core 叶子层：只 import 标准库（math/collections.abc/typing），零第三方
  依赖；全部纯函数，无 IO/无随机/无网络。
- **有意不定义 ``__all__``**：公开 API 金快照只钉带 ``__all__`` 模块
  （precision_profiles/shield_cavity_mode 先例）——本模块为内部数值内核，
  入快照属显式评审动作，不在本批文件面内。
- 消费面（MP-B1，研究扩充 round15）：设计为
  core/thermal_iteration.solve_thermal_fixed_point 定点迭代链
  （T_{n+1} = T_amb + R_th·P(T_n)，谱半径 λ = R_th·dP/dT，线性收敛）的
  **后处理加速**——对 result.steps 的温度序列做 Δ² 外推，3 个迭代点即可
  达到纯迭代多轮的残差带（tests/unit/test_accel.py 强耦合案例 λ=0.9
  实证：3 点 Aitken 残差 < 1e-6 K，100 轮纯迭代残差 ~2.6e-3 K）。
  迭代中在线外推（可选开关）按本批文件面约束不接（thermal_iteration
  计算语义禁改），留给后续批次；在线化时语义=对最近三个迭代值外推后
  作为下一初值，缺省关态、开态才改变迭代轨迹。
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def aitken_delta2(seq: Sequence[float]) -> list[float]:
    """Aitken Δ² 加速：线性收敛序列 → 加速序列（长度 = len(seq) - 2）。

    Args:
        seq: 至少 3 个有限实数的迭代历史（list/tuple，如定点迭代温度链
            [T_0, T_1, ..., T_N]）。str/bytes 不是数值序列，显式拒绝。

    Returns:
        加速序列 [A_0, ..., A_{N-2}]（list[float]），A_n 由三点
        (x_n, x_{n+1}, x_{n+2}) 外推；分母为 0（局部常数/等差）或加速值
        非有限时 A_n = x_{n+2}（恒等回退，不产 inf/nan）。

    Raises:
        ValueError: 序列长度 < 3；或含不可转 float/非有限元素。

    例：定点链 T_n = 115 - 90·0.9^n（q=0.9 强耦合）取前三点
    [25.0, 34.0, 42.1] → A_0 = 42.1 - 8.1²/(8.1-9) = 115.0（纯几何序列
    Δ² 一步精确到不动点，浮点实现残差 ~1e-12）。
    """
    if isinstance(seq, (str, bytes, bytearray)):
        raise ValueError(f"seq 必须是数值序列，收到 {type(seq).__name__}")
    values: list[float] = []
    for index, item in enumerate(seq):
        try:
            value = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"seq[{index}] 必须是实数，收到 {item!r}") from exc
        if not math.isfinite(value):
            raise ValueError(f"seq[{index}] 必须是有限数，收到 {item!r}")
        values.append(value)
    if len(values) < 3:
        raise ValueError(
            f"Aitken Δ² 至少需要 3 个迭代点，收到 {len(values)}")

    accelerated: list[float] = []
    for n in range(len(values) - 2):
        x0, x1, x2 = values[n], values[n + 1], values[n + 2]
        delta1 = x1 - x0
        delta2 = x2 - x1
        denominator = delta2 - delta1
        if denominator == 0.0:
            # 局部常数/等差（差分相等）：无加速信息，恒等返回
            accelerated.append(x2)
            continue
        estimate = x2 - delta2 * delta2 / denominator
        if not math.isfinite(estimate):
            # 溢出/灾难性相消守卫：宁可恒等也不产出非物理值
            accelerated.append(x2)
            continue
        accelerated.append(estimate)
    return accelerated
