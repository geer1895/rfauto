# 数据工厂：从采集到代理模型的全链

> "要训代理模型，先得有数据；要采数据，先得有判据。"数据工厂就是这条
> 链的工程化：**预声明判据 → 批量采集 → 物化成数据集 → 判读（三门/双口径）
> → 代理模型训练与寻优 → 消费（查询/warm-start）**。本文带你把这条链的
> 离线面亲手跑一遍（真机采集腿用档案数字讲），全部命令在开发环境实测过
> （退出码 0，输出为实测摘录）。前置：docs/tutorials/getting-started.md
> （CLI 入门）、docs/tutorials/datasets_and_health_gates.md（数据集与体检
> 机制）；代理模型的采样/验证数学见
> docs/tutorials/uncertainty_and_surrogates.md，数据湖查询面见
> docs/tutorials/data_lake.md——本文不重复，只讲"工厂"这条全链。
> 英文版（English version）：docs/tutorials/data_factory_en.md。

## 1. 工厂的四条腿

| 腿 | 干什么 | 仓内驱动（scripts/） | 产物档（runs/） |
|---|---|---|---|
| M1 库存 | mline 一维 w 扫描 120 点（openEMS 真机） | `factory_m1_collect.py` | `runs/data_factory_m1/` |
| A 批 2D | w×line_len 二维扩展采集 120 点 | `factory_a2d_collect.py` | `runs/datafactory_a2d/` |
| M3 谷区加密 | 深谷区定向加密（先规划后真机） | `factory_m3_valley.py` | `runs/datafactory_m3/` |
| M2 判读 | 数据集 → GP/MFK 代理 → 三门/双口径判读 | `factory_m2_mfk_rejudge.py` | `runs/datafactory_m2/` |
| M4 寻优 | 代理寻优（查库存）vs HFSS 基线墙钟账 | `factory_m4_bench.py` | `runs/datafactory_m4/` |

两条铁纪律贯穿全链（违反即返工，项目规则 立规）：

1. **判据预声明（先写后算）**：每个批次的判据/口径先写进
   `runs/<批次>/criteria.md`（写死再跑），判读脚本只消费它——事后改门
   属于篡改验收标准。看一个真实例子：

   ```bash
   head runs/datafactory_m2/criteria_linear.md
   ```

   实测首行：`# datafactory M2 消费面线性域判据（预声明，先写后算）`，
   第二行写明"日期：2026-09-20（本文写入时刻先于任何线性域真实数据 GP
   拟合）"——这就是"先写后算"的落痕。

2. **数值只在确定性内核**：采集驱动、判读门、代理训练全部是确定性函数；
   不用 LLM 产数字。脚本自带**合成回收钉**（往已知答案的合成双保真族上
   回收，#118 家法——"拟合斜率→物理量"换算错了当场抓住）。

## 2. 动手：采样计划（离线，秒级）

```bash
.venv/Scripts/python.exe scripts/factory_a2d_collect.py --plan
```

实测输出（节选）：

```
{
 "n_anchors": 9,
 "n_lhs_requested": 111,
 "n_lhs_kept": 111,
 "n_lhs_dropped": 0,
 "n_plan_total": 120,
 "lhs_seed": 20260921,
 "bounds": {
  "w_mm": [0.5, 2.0],
  "line_len_mm": [20.0, 60.0]
 }
}
锚点 9: a2d_w0500_l20000(corner), a2d_w0500_l60000(corner), ...（共 9 个）
LHS 111 点前 5: (0.5070,33.482), (0.5187,28.664), (0.5275,20.805), ...
  ...（共 120 点，全量见 D:\rf_workspace\runs\datafactory_a2d\plan.json）
```

读法：**9 个锚点**（角点/名义/边界，保物理覆盖）+ **111 个 LHS 点**
（拉丁超立方，seed 写死=可复现）= 120 点计划。计划落盘即**不可变契约**
——计划文件已存在时本命令只读回打印，不重写（再跑一遍验证：输出逐位
一致）。换 seed = 换一批新点（#158：同种子重跑秒回是合法缓存，新轨迹
必须换 study/seed）。

## 3. 动手：判据修正的重导（离线，零重仿真）

数据工厂的经典一课：**eps_eff 列曾经系统性虚大 ~5.4×**——原判据用 S21
相位斜率 × L=40mm 反演 εeff，但 mline 模板的 S21 参考面在板缘端口面
（总电跨度 ~93mm 含馈段），L 语义失效（#364②：S21 对照长度=参考面跨度
非名义线长）。修复=改用引擎 CalcPort 的 β（参考面无关）重导：
(β·c/ω)²。这个修正器留在仓里，`--dry-run` 全程只读：

```bash
.venv/Scripts/python.exe scripts/factory_m1_eps_eff_beta.py --dry-run
```

实测输出（节选）：

```
[fix] m1_w0500 w=0.500 eval=0001 eps_eff_beta=2.7686 zl1=64.3 zl2=64.4
[fix] m1_w0503 w=0.503 eval=0012 eps_eff_beta=2.7696 zl1=64.2 zl2=64.2
...
[fix] m1_w2000 w=2.000 eval=0002 eps_eff_beta=3.0525 zl1=31.3 zl2=31.3
[fix] n=120 eps_eff_beta min/med/max=2.7427/2.9225/3.0525
[fix] dry-run：未写任何文件
```

读法：120 点重导秒级完成（每点只读归档 `port_beta.csv`），εeff 中位
2.92 落在 rogers4350b 微带物理区间——而修复前的 S21 斜率口径中位是
15.98（虚大 5.4×）。末行明示"未写任何文件"；去掉 `--dry-run` 才回写
数据集（旧列保留不删，note 记失效语义——**判据修正不抹历史证据**）。

## 4. 动手：MFK 多保真判读（离线，约 1 分钟）

M2 判读的 MFK 腿：低保真库存（150 行数据集）+ 高保真 HFSS 锚点（9 行）
训多保真代理，对锚点做三门判读（线性域 |ΔΓ| / εeff / S21），外带**基线
对照腿**（同锚点直接对低保真——证明"多保真确实增值了"）：

```bash
.venv/Scripts/python.exe scripts/factory_m2_mfk_rejudge.py --judge \
    --out runs/aurora_d/tut/mfk_verdict.json
```

实测输出（约 49s，节选）：

```
[mfk] 低保真数据集：D:\rf_workspace\runs\datasets\datafactory_m1m3_merged_20260920（消费栅格 21 点）
[mfk] 低保真行数 150（εeff 缺行如实跳过）
[mfk] 高保真锚点 9 行
[mfk] 合成回收钉（Forrester 式仿射双保真族，#118）
[mfk] 合成钉 pass=True gamma_max=0.00058 eps_max=0.0000%
  MFK fit：lo=150 hi=7 heads=43
[mfk] verdict → D:\rf_workspace\runs\aurora_d\tut\mfk_verdict.json

===== MFK 多保真判读摘要（overall=FAIL） =====
             smt_mfk: |ΔΓ|max=0.06291 εeff_max=1.0114% S21_max=0.0058dB
  baseline_oe_direct: |ΔΓ|max=0.08751 εeff_max=3.9742% S21_max=0.0863dB
门: {'gamma_lin': False, 'eps_eff_rel': False, 's21_db': True} 增值门=True
合成钉: True
```

三个读法，一个都不能省：

- **overall=FAIL 如实落档**：gamma_lin / eps_eff_rel 两门未达（MFK 预测
  |ΔΓ| 最大 0.063 > 门 0.04），S21 门与增值门（MFK 比低保真基线好：
  0.063 < 0.088）是过的。**FAIL 不凑绿**——这次 MFK FAIL 如实落档正是
  二期战果"B2（HFSS 锚 6/6 + MFK FAIL 如实 + 扩锚登记）"的口径；
- **合成回收钉 pass=True**：判据内核先在已知答案的合成族上自证（γ 最大
  残差 0.00058），裁判本身可信才有资格裁判真实数据（#300 同源纪律）；
- `--out` 显式重定向判读产物：不指定会写进默认锚点档——**复算/实验性
  判读一律 out 到自己的工作目录**，历史档案零改写（#325/#326）。

## 5. 动手：M4 判据内核自检（离线，秒级）

M4 是"代理寻优 vs HFSS 基线"的墙钟/cost 双门裁判。它把判据公式全部
复用 `service/wp39_benchmark.py` 内核（不内联公式），并带 33 项自检：

```bash
.venv/Scripts/python.exe scripts/factory_m4_bench.py --selftest
```

实测输出（2.4s，节选）：

```
  [ok] m4_cost(-51 vs -52.83) PASS  (deg=3.4579)
  [ok] m4_cost(-40 vs -52.83) FAIL  (deg=24.2807)
  [ok] m4_cost(None) fail-closed
  [ok] 内核钉 cost_degradation_pct(0,0)==0.0（违约量口径两零=劣化 0 非缺失）
  [ok] m4_account 197.9s PASS  (ratio=0.1358)
  [ok] m4_account 311.7s FAIL  (ratio=0.2481)
[selftest] 33/33 过
```

`--offline`（库存加载+GP 训练+代理寻优，零真机）与 `--verify`（真机验证
腿）本文不现场跑——真机腿见下一节的档案数字。

## 6. 真机采集腿长什么样（档案数字，不现场跑）

真机采集（`--collect`）在共享锁+#261 命令行互斥内逐点发射 openEMS，带
QuotaGuard（预算上限）、首点 ingest 探针（先跑 1 点核对成行再放量，
#251④）与崩溃安全 resume（points_index.json）。A 批 2D 的判读档案
`runs/datafactory_m2d_20260921/judgment.json` 实测摘录：

```json
{
 "verdict": "PASS",
 "gates": {
  "G1_row_rate_100pct":  {"pass": true, "n_attempted": 120, "n_rows": 120, "row_rate": 1.0},
  "G2_real_wall_median_le_60s_and_max_le_120s": {
      "pass": true, "median_wall_s": 36.24, "max_wall_s": 88.58, "n_cached_excluded": 3},
  "G3_rows_ge_100":      {"pass": true, "n_rows": 120, "gate": 100}
 },
 "meta": { "batch_wall_s": 4859.7, "budget_status": "within_target(0.45×)" }
}
```

读法：G1=成行率（120/120 全部物化成数据集行）、G2=时长门（真机点中位
36.24s，**缓存命中的 3 点不计入时长统计**——(w,40) 与 M1 库存重合由
引擎缓存秒回，#158）、G3=行数下限。整批 81 分钟，0.45× 于预算。

## 7. 消费：查询、覆盖度与代理寻优账

数据集消费面（DuckDB 直查，只读）：

```bash
rfauto datasets query datafactory_a2d_mline_20260921 \
    --where "model = 'mline'" --limit 3 --columns "run_id,point_index,source"
rfauto datasets coverage datafactory_a2d_mline_20260921
```

实测输出：

```
数据集 datafactory_a2d_mline_20260921（3 行，过滤后共 120 行，where: model = 'mline'）
┌──────────────────────────┬─────────────┬──────────┐
│ run_id                   │ point_index │ source   │
├──────────────────────────┼─────────────┼──────────┤
│ 20260922_002725_289c6424 │ 0           │ run_once │
│ 20260922_002758_ebb147b9 │ 0           │ run_once │
│ 20260922_002835_2ab2f13b │ 0           │ run_once │
└──────────────────────────┴─────────────┴──────────┘
✓ datafactory_a2d_mline_20260921（120 行）
  mean occupancy: 1.0  min: 1.0  最弱维: line_len_mm
```

代理寻优的最终账在 `runs/datafactory_m4/m4_verdict.json`（档案实测摘录）：
G2 墙钟门 **PASS**——工厂全链 203.8s vs HFSS 基线 1457.7s（ratio=0.1398
< 0.2，约 7× 提速）；G2 cost 门 **FAIL**——代理寻优验证点 -48.38dB 对
库存最优 -52.83dB 劣化 +8.42% > 门 5%，**verdict=FAIL 如实落档**，并附
口径并列诊断（环 objective 违约量口径两零=劣化 0，criteria 预声明以 dB
真值定义库存最优，不事后改门）。

消费的最后一站是把库存喂回优化：`rfauto warm-start <数据集> <配方>` 把
历史样本按相似度门注入新战役作先验（热启动续调的机制见
docs/tutorials/first_optimization_loop.md）。

## 8. 纪律速查

- 判据先写后算（criteria.md 落盘再跑）；事后改门=篡改验收标准；
- 合成回收钉先自证裁判，再裁判数据（#118/#300）；
- 计划/判读复算一律 out 到自己的工作目录，档案零改写（#325/#326）；
- 缓存命中合法但不入时长统计（#158）；新轨迹换 study/seed；
- 首点探针核对成行再放量（#251④）；真机批量必挂共享锁+#261 互斥。

## 下一步

- 体检与三态判读的语义细节：docs/tutorials/verdict_semantics.md
- 数据湖/SQL 查询进阶：docs/tutorials/data_lake.md
- 代理模型数学（Sobol/LHS/poly_ridge/LOO 门）：docs/tutorials/uncertainty_and_surrogates.md
