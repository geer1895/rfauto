# 如何做级联预算与混频杂散规划

**场景**：接收链路的噪声/线性度预算（Friis NF、IIP3 级联、SFDR、灵敏
度、链路裕量），以及变频方案的杂散落带排查（f_spur = |m·f_RF ± n·f_LO|）。

## 1. 级联预算（CLI）

stage 列表放一个 JSON 文件（或 `-` 读 stdin），按信号流向排序：

```bash
echo '[
 {"type": "atten", "gain_db": -3.0, "nf_db": 3.0},
 {"type": "amp", "gain_db": 20.0, "nf_db": 2.0, "iip3_dbm": -10.0, "p1db_dbm": 5.0},
 {"type": "filter", "gain_db": -2.0, "il_db": 2.0, "bw_hz": 20000000},
 {"type": "amp", "gain_db": 30.0, "nf_db": 3.5, "iip3_dbm": 5.0}
]' | rfauto cascade budget - --rx-power -90 --bw-hz 1e6
```

实测输出（节选）：

```
总增益: 45.00 dB   总 NF: 5.07 dB
IIP3: -11.76 dBm   OIP3: 33.24 dBm   SFDR: 64.76 dB
P1dB(经验幂和): 33.00 dBm (输出参考)
噪声底: -108.91 dBm   灵敏度: -98.91 dBm   (B=1e+06 Hz, T=290 K)
链路裕量: 8.91 dB
```

schema 要点（`rfauto cascade budget --help` 有全文）：

- `type`: amp / mixer / filter / atten / cable；
- 有源级（amp/mixer）必须显式给 `nf_db`；无源级缺省 NF=插损（T0 口径，
  表里"插损来源"列会如实标注）；
- filter/atten 的插损可给 `network_path`（skrf 实取 S21）或常数 `il_db`，
  二选一显式传——不静默默认；
- `bw_hz` 缺省取最后一个带 `bw_hz` 的级（信道滤波器），都没有则报错。

## 2. 混频杂散落带搜索（CLI）

```bash
rfauto cascade spur --rf 2.4e9 --lo 2.1e9 --if-center 600e6 --if-bw 1e5 --max-order 4
```

实测输出：

```
杂散产物表（m+n≤4，共 28 产物，落带 1）
               落带产物（IF 中心 6e+08 Hz）                
┌───┬───┬──────┬────┬─────────────┬──────────────┬────────┐
│ m │ n │ 边带 │ 阶 │ f_spur (Hz) │ 偏离 IF (Hz) │ 危险   │
├───┼───┼──────┼────┼─────────────┼──────────────┼────────┤
│ 2 │ 2 │  -   │  4 │   600000000 │            0 │ medium │
└───┴───┴──────┴────┴─────────────┴──────────────┴────────┘
```

判读：只报**频率几何**（落带/不落带），不报电平——幅度需要器件特性，
超范围就不硬算。危险等级按阶数反比（≤3 high、≤5 medium、其余 low）。
期望产物 (1,1) 标 `fundamental`，不混入杂散计数。带宽线性缩放：
`bw_spur = m·RF带宽 + n·LO带宽`（矩形近似卷积判落带）。

## 3. IF 频率规划扫掠

候选 IF 区间内找连续 spur-free 窗口：

```bash
rfauto cascade plan --rf 2.4e9 --if-lo 200e6 --if-hi 500e6 --json
```

输出逐点判定表 + 连续 `windows`（spur-free 窗首末边界=网格分辨率内，
不外推）。

## 4. Python API（doctest 示例永远可跑）

同一内核的函数形态带可运行示例，直接看 docstring：

```python
from rfauto.core.cascade import cascade_budget, spur_search

r = cascade_budget(stages, snr_min_db=10.0, rx_power_dbm=-90.0, bw_hz=1e6)
spurs = spur_search(2.4e9, 2.1e9, if_center_hz=600e6, if_bw_hz=1e5)
```

`help(spur_search)` / `help(cascade_budget)` 里的示例由 doctest 守护
（`pytest tests/unit/test_docs_doctest.py`），与本文同步——示例跑不过
测试就会红。

## 口径注意（为什么你的数字可能和别处不同）

- IIP3 级联用教科书口径 `1/IIP3_tot = Σ G_pre,i/IIP3_i`（后级 IIP3 折算
  到输入要**除以**前级增益）——`iip3_convention` 键在结果里原样带出；
- P1dB 是**经验幂和**（工程惯例，非教科书闭式），`p1db_dbm` 约定=该级
  **输出** 1dB 压缩点——与其他工具对数时先核对参考面。
