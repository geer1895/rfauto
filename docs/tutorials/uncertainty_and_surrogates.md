# UQ 与代理模型：从灵敏度面到良率收口

> 参数公差会不会把良品打成废品？真跑一遍蒙特卡洛太贵，代理模型免费——
> 前提是代理本身可信。本文讲 rfauto 的完整链路：Sobol/Morris 灵敏度筛
> 参数 → Taguchi/LHS 采样 + poly_ridge 代理 + 留一交叉验证 ρ 门自动校
> 准 → 校准产物 samples.json 复用到良率/设计中心化/稳健性四件收口命令。
> 文中旗标、退出语义、样本格式、真实工件（含一个 ρ=0.38 的 FAIL 校准）
> 均为当前工作区实测；执行类命令给读法不代跑，读完你可以在 fake 通道
> 零 license 复制整条链。
> 英文版（English version）：docs/tutorials/uncertainty_and_surrogates_en.md
> （W9-S3 译，2026-10-19 全旗标复测同笔）。

## 0. 前置

- 已按 docs/tutorials/getting-started.md 装好环境，工作目录在仓库根
  （`runs/`、`recipes/` 相对 cwd 解析）。
- 全文命令一律走 console script 入口 `.venv/Scripts/rfauto.exe`；
  `python -m rfauto` 不是有效 CLI 入口。
- 有一条铁律贯穿全文（AGENTS 规则 7）：**物理数字只出自确定性内核**——
  采样执行、代理拟合、LOOCV、良率 MC 全部是确定性函数，LLM/agent 只编
  排不产生数值。

## 1. 全景：一条校准链，两段消费

```
配方(optimization.params+bounds+objectives)
  │
  ├─ 灵敏度筛参   rfauto sensitivity  （Sobol/Morris，fake/真机各跑 N 点）
  │
  ├─ 校准链       calibrate_surrogate（服务层；战役 calibrate 阶段同款）
  │     采样设计(taguchi/lhs/full_factorial) → 逐点执行(fake/openems)
  │     → PolyRidge 拟合 → LOOCV ρ≥0.8 门 → LHS 验证点复核 → FSV 门
  │     产物：runs/<rid>/calibration/{samples,gate,surrogate,report}.*
  │
  └─ 代理收口（拿到 samples.json 后全部免费，不再碰求解器）
        rfauto surrogate uq      良率 + 指标分布 + 敏感性排序
        rfauto uq yield-at       显式名义点良率
        rfauto uq design-center  设计中心化（良率最大化平移）
        rfauto uq temp-zone      温区良率（D9 环境包络）
        rfauto uq robustness     良率 MC + FORM Pf + 角点 + 逐规范 Cpk
```

校准一次，收口无限次——**校准数据是资产**（calibration_service 原文），
换代理类型重拟合不用重跑采样。

## 2. 灵敏度面：rfauto sensitivity（Sobol/Morris）

```bash
.venv/Scripts/rfauto.exe sensitivity --help
```

实测旗标：`recipe` 位置参数；`--method/-m sobol|morris`（缺省 sobol）、
`--samples/-n`（缺省 100）、`--seed`（42）、`--adapter/-a`（缺省
**fake**）、`--json`。它读配方的 `optimization.params`（bounds）与
`objectives`，对 cost 函数做方差分解，输出逐参数一阶/总阶重要度。

方法语义（`optimization/sensitivity.py` 模块头，读法要点）：

- **Sobol**：Saltelli (2002) 采样 + 经典一阶/Jansen 总阶估计量（numpy
  自实现，无 SALib 依赖）。**总求值次数 = N×(d+2)**（d=参数个数）——
  `--samples 100` 对 3 参数配方是 500 次求解，fake 通道秒级，真机通道
  按单点耗时折算预算。历史坑 #234：目标均值远大于带内标准差时一阶估
  计量大数相减失效，实现已内置常数居中（结果里 `centering_shift` 键可
  查），直接信输出即可。
- **Morris**：OAT 初等效应筛选（mu_star/sigma），轨迹数 =
  max(5, N//d)。便宜、定性，适合真机通道先粗筛再对 top 参数上 Sobol。

执行类命令本文不代跑；跑完后 `--json` 信封里 `sensitivity` 键是
`{param: {S1, ST}}` 排序面。另有一个常被混淆的面：`rfauto surrogate
analyze` 的"参数重要度"在 isotropic GP 内核下**不可辨识，如实输出
N/A 不画假排行**（§6），需要重要度排序一律走本节的 Sobol/Morris。

## 3. 校准链：calibrate_surrogate 与 LOO 门

校准链没有独立 CLI 叶——两个触达面（#222 实测）：

1. **战役 calibrate 阶段**：`rfauto campaign plan` 生成的阶段队列里
   第一站就是 calibrate（六段状态机 calibrate→prefilter→tune→tolerance
   →report→final_verify，`rfauto campaign --help` 实测口径），
   `--calibrate-samples` 给样本预算；执行器按通道映射 sampler（fake 通
   道适配器→sampler="fake"）。
2. **服务层直调**（`service/calibration_service.calibrate_surrogate`），
   想控 `design_kind`/`n_samples` 等参数时用这条：

```bash
.venv/Scripts/python.exe -c "
from rfauto.service.calibration_service import calibrate_surrogate
r = calibrate_surrogate('recipes/branchline_tune_light.yaml',
                        sampler='fake',              # fake 零 license
                        design_kind='lhs',           # 采样设计（见下）
                        n_samples=20,                # 仅 lhs 消费
                        n_validation=2, seed=42)
print(r['verdict'], r['loocv'], r['run_id'])
"
```

（执行类，本文不代跑——它会真建 runs/<rid>/ 并逐点执行采样。）

流程六步（模块头原文口径）：读配方 → 采样设计 → 逐点执行 → 拟合 +
LOOCV → LHS 验证点实跑复核 → 产物落盘。三个关键读法：

- **采样设计 `design_kind`**：`taguchi`（缺省，L9 正交表 3 水平 9 点，
  素数幂有限域线性型构造，两两因子水平均衡）/ `lhs`（拉丁超立方，
  scipy qmc，**n_samples ≥ 5**，密集化采样）/ `full_factorial`（现仅
  支持 3 因子 3³=27 点）。选型直觉：因子少用缺省 L9；怀疑 L9 网格太
  粗（角邻域解析不了）换 lhs 密集化。
- **LOO 门**：留一交叉验证（每折留 1 点预测、其余拟合），预测 cost 与
  实际 cost 的 Spearman ρ，**ρ ≥ rho_threshold（缺省 0.8）才算代理可
  信**；样本 <4 直接 ok=False 拒判。ρ 门之外还有 LHS 验证点实跑对账
  （预测 vs 实际逐指标 Δ）与 FSV 曲线级等级门，任一不过 verdict=FAIL。
  **FAIL 是正常返回不是异常**——如实修数据或加密采样，不凑绿。
- **产物四件套**（runs/<rid>/calibration/）：`samples.json`（下节消费
  主角）、`gate.json`（verdict/loocv/阈值/验证 Δ）、`surrogate.json`
  （代理 kind+config）、`report.md`（人读报告）。meta 登记
  `algorithm=surrogate_calibration`、`adapter=calibration:<sampler>`。

仓内真实 FAIL 工件走读（`runs/20260903_235147_cb982df7/calibration/`，
实测照录）：`gate.json` 判 `verdict: FAIL, loocv.rho: 0.3833
（9 折）`——0.3mm 网格下 L9 采样秩相关退化，正是 calibration_service
注释里那个诊断案例，后续走 `augment_calibration`（LHS 增广：旧样本原
样复用、只补采 n_new 点再重拟合过门）把样本量补上去。`samples.json`
关键结构实测：

```json
{"bounds": {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45],
            "shunt_w_mm": [0.9, 1.3]},
 "objectives": [ …配方 objectives 原文… ],
 "samples": [{"params": {"arm_len_mm": 18.0, …}, "metrics": {…}}, …],
 "validation": […LHS 验证点 actual/predicted/abs_delta…],
 "design": {"kind": "taguchi", "n_levels": 3, "array_rows": 9}}
```

## 4. 代理收口：samples.json 的五条消费命令

### 4.1 rfauto surrogate uq（良率 + 分布 + 排序，一页读全）

```bash
.venv/Scripts/rfauto.exe surrogate uq runs/<rid>/calibration/samples.json \
  --tol arm_len_mm=0.3 --tol series_w_mm=0.05 --tol shunt_w_mm=0.05 \
  --n 10000 --kind poly_ridge
```

旗标实测：`--tol 参数名=σ` 可多次（σ 与参数同单位，**必给**——缺公差
直接报"缺少 tolerances"）、`--n` MC 抽样数（缺省 10000）、`--seed`、
`--kind`（帮助文本写 `poly_ridge|nn`，实现走注册表，实际收 §5 全部
12 种已注册 kind）。语义三件：名义点 = 样本集中 **cost 最小者**（确定
性，不是手工指定）；良率 = 公差盒内 MC 抽样逐点代理预测、按 objectives
判违约的比例；敏感性排序 = 逐参数 ±1σ 扰动的指标响应幅值求和。输出还
带 `uncertainty_status`：代理能给不确定性估计且 σ-误差秩相关 ρ≥0.5 才
标 `quantitative`，否则 `qualitative`（poly_ridge 无 σ 估计，恒为
qualitative——如实标注，数据不删）。

### 4.2 uq 子应用另外三件

`rfauto uq --help` 实测四个子命令（均吃 samples.json，缺省即 JSON 信
封）：`yield-at`（显式 `--at 参数=值` 指定名义点，评估"这个点"而不是
样本最优点）、`design-center`（容差盒网格坐标搜索把名义点挪到良率最大
处，MC 只做前后认证）、`temp-zone`（D9 环境包络键 → 温度轴 σ 并入 MC
+ 温区两端角点确定性评估；样本须含温敏维）。

### 4.3 uq robustness（一张稳健性报告）

```bash
.venv/Scripts/rfauto.exe uq robustness runs/<rid>/calibration/samples.json \
  --spec "s11_db_max_in_band,max_below,-15" \
  --tol arm_len_mm=0.3 --n-mc 100000
```

`source` 除 samples.json 外还收**数据集名或 run id**（数据工厂点级数
据直接进稳健性分析）；`--spec 'metric,op,value[,weight]'` 可多次；
`--profile` 给 fab 公差剖面（YAML 路径或内联 JSON）时 σ 由剖面单源派
生、与 `--tol` 二选一；输出 = 向量化 MC 良率 + FORM 失效概率
（`--form-engine auto|internal|openturns|uqpy`）+ worst-case 角点 +
逐规范 Cpk；`--persist/--store-name` 可把 MC 抽样落成数据集。

### 4.4 没有校准 run 也能手写 samples.json

格式只要三键：`{"samples": [{"params": {...}, "metrics": {...}}, …],
"objectives": […], "bounds": {…}}`，**≥5 个样本**即过装载校验（内核
build_yield_context 实测：5 点玩具样本 + 手写 objective 正常出名义点
并预测）。真机历史曲线、外部数据、合并多源样本都走这条路。

### 4.5 对照面：真跑蒙特卡洛

`rfauto tolerance <recipe> --samples 200`（`--help` 实测，读配方
`tolerance.tolerances` 段）对适配器**真跑** MC——代理收口的数字可信度
存疑时，用它小样本抽验代理结论；`--dry-run` 先看计划面零执行。

## 5. 代理模型注册表：14 种内置 + 自定义接入

注册表实测清单（装饰器注册全集，2026-10-19 W9-S3 复核；`available()`
反映已 import 模块——裸 `available()` 为 13 种，`gnn_geom` 经模块
import 触发注册后 14 种全貌；saas_gp/warped_kriging 为 2026-10-18
架构批 W5-S22 新入）：

```
['deeponet', 'fno', 'fno_lite', 'gbdt', 'gnn_geom', 'huber_ridge',
 'mapes_pixel_analytic', 'nn', 'pod_rom', 'poly_ridge', 'saas_gp',
 'smt_kriging', 'smt_mfk', 'warped_kriging']
```

- **poly_ridge** 是校准链缺省（二阶多项式 + ridge，样本需求最小、
  LOOCV 门就是为它定的口径）；**nn** 是小 MLP（`--kind nn` 切换）。
  其余面向进阶用途（算子学习 deeponet/fno、POD-ROM、SMT kriging/多保
  真、GBDT、huber ridge、几何输入 GNN gnn_geom、SAAS 稀疏 ARD 高维
  saas_gp、HEBO 式输入 warping warped_kriging 等），实现见
  `optimization/surrogate/` 子包，
  每个模块头自带适用域说明。
- **第三方代理接入** = 实现三方法 + 装饰器注册（base.py 契约原文）：

```python
from rfauto.optimization.surrogate import SurrogateModel, surrogate_registry

@surrogate_registry.register("my_nn")
class MySurrogate(SurrogateModel):
    KIND = "my_nn"
    def fit(self, samples): ...          # [{"params":…, "metrics":…}]
    def predict(self, params): ...       # 返回与 objectives 指标同名 dict
    def uncertainty(self, params): ...   # 可选；None=无 σ 估计
```

  注册后 `surrogate uq/uq robustness --kind my_nn`、校准链
  `surrogate_kind="my_nn"` 全线可用（uq_service 建模走注册表工厂，
  poly_ridge 专属 config 键例外单独处理——实测源码口径）。
- **注册表服务面**（`service/surrogate_registry_service.py`，RB-ML-1）：
  战役级模型台账（champion/版本/heldout 误差）、锚漂移自动标 stale、
  跨战役检索。#222 如实注记：**该服务面 v1 零 CLI/MCP 接线**，用户侧
  唯一开关是 tune 的三态旗标（§6）；其余走 service 函数调用。

## 6. 代理环与离线诊断

### 6.1 tune --sampler sbo：代理寻优环

```bash
.venv/Scripts/rfauto.exe tune recipes/branchline_tune_light.yaml \
  --adapter fake --sampler sbo --max-trials 30
```

`--sampler tpe|cmaes|sbo`（`tune --help` 实测）；sbo = WP3.2 代理寻优
环（`optimization/surrogate_loop.py`）：LHS 初始采样 → 代理拟合 → 代理
面上 Optuna 大规模**虚拟寻优**（缺省 2000 试验，零成本）→ top-K 多样
性筛选 → K 点批量真跑 → refit，直到收敛或预算用尽。适用判断：单点评估
贵、参数维度低（3-8 维）、有校准样本可热启动——三者不满足就留在 tpe。

### 6.2 注册表 warm-start：tune --warm-start-registry

三态旗标（`--warm-start-registry/--no-warm-start-registry`，缺省读
env `RFAUTO_WARM_START_REGISTRY` 与配置——#277 形态：显式开关 > env >
配置 > 关）：把注册表 champion 模型的近优点注入优化先验（相似度门在
既有 warm_start 通道内）。注意 `--help` 同页注记：**仅单目标路径生效**，
多目标/多保真下按未设置处理并给 note。注入收益由配对裁判
`judge_registry_warm_start_benefit` 判定（首 trial cost 中位改善 ≥30%
或达标 trial 数减少；无改善如实 FAIL，verdict 带 channel 字段）。

### 6.3 rfauto surrogate analyze：离线体检（只读，实测）

```bash
.venv/Scripts/rfauto.exe surrogate analyze 20260831_125228_db3856cb --json
```

对一个已完成的 tune run（≥10 trials）离线拟合 GP 报告质量，不进在线
调优路径。真实输出节选（当前工作区实测）：

```json
{"ok": true, "data": {"n_samples": 15, "n_params": 3,
  "best_cost": 3.5987, "prediction_error": 0.0,
  "param_importance": {"feed_offset_mm": null, …},
  "param_importance_note": "isotropic RBF 内核下逐参数重要性不可辨识
    （旧 1/n 归一化=假排行已撤，D1-1）；替代口径=core/sensitivity
    Morris/Sobol",
  "quality": {"available": true, "rms_error": 2.535, "r2": -1.80,
              "spearman_rho": 0.111, …}}}
```

读法：`quality` 是 5 折交叉验证 out-of-fold 口径——r2 为负说明该 run
的 15 个 trial 不足以支撑可信 GP（如实报告，不是报错）；参数重要度
N/A 是诚实降级，要排行回 §2 跑 Sobol/Morris。**何时用**：tune 完想判
"样本量够不够再上一轮"时看 `spearman_rho`/`rms_error` 趋势。

### 6.4 PCE 的位置（如实边界）

稀疏多项式混沌（D8）在确定性内核 `core/pce.py`（OMP 稀疏回归 +
Legendre/Hermite 基，Sobol 系数直读、worst-case、设计中心化）与
`core/sparse_pce.py`（sklearn LassoLars，Blatman-Sudret），经
robustness 服务的 worst-case 面消费；**无独立 CLI 叶**。模块头自报
诚实边界：强不连续/窄带谐振上 PCE 是全局多项式代理，代理不准则指数
不准——这类器件回 §2 的采样法 Sobol。

## 7. 低成本复制流程（fake 通道，全程分钟级）

```bash
# ① 灵敏度筛参（fake，~40 次评估）
.venv/Scripts/rfauto.exe sensitivity recipes/branchline_tune_light.yaml \
  -m morris -n 30 --adapter fake --json

# ② 校准链（fake；产物 runs/<新rid>/calibration/samples.json）
#    服务直调见 §3 代码块；或走战役：
.venv/Scripts/rfauto.exe campaign plan recipes/branchline_tune_light.yaml \
  --calibrate-samples 9 --out-dir runs/my_uq_campaign
.venv/Scripts/rfauto.exe campaign run runs/my_uq_campaign

# ③ 代理良率（免费，不再碰求解器）
.venv/Scripts/rfauto.exe surrogate uq runs/<rid>/calibration/samples.json \
  --tol arm_len_mm=0.3 --tol series_w_mm=0.05 --tol shunt_w_mm=0.05 --n 5000

# ④ 稳健性报告（FORM + Cpk）
.venv/Scripts/rfauto.exe uq robustness runs/<rid>/calibration/samples.json \
  --spec "s11_db_max_in_band,max_below,-15" --tol arm_len_mm=0.3 --n-mc 20000

# ⑤（可选）代理环寻优 / 代理体检
.venv/Scripts/rfauto.exe tune recipes/branchline_tune_light.yaml \
  --adapter fake --sampler sbo --max-trials 30
.venv/Scripts/rfauto.exe surrogate analyze <tune_run_id> --json
```

判读顺序建议：② 的 verdict=FAIL 先修（ρ<0.8 → `augment_calibration`
补样本或 `design_kind='lhs'` 加密），代理过门后再信 ③④ 的良率数字；
③ 的敏感性排序若与 ① 的 Sobol/Morris 排序矛盾，优先怀疑代理在公差盒
内失真而不是参数不重要。

## 8. 下一步

- tune→refine→replay 优化闭环主线：docs/tutorials/first_optimization_loop.md
- 校准产物行级入册与健康门：docs/tutorials/datasets_and_health_gates.md
- MCP 里同源工具（uq_yield_at/robustness_report 等）：
  docs/tutorials/mcp_in_practice.md
- 设计文档全貌（v1 契约与采样设计数学）：
  docs/surrogate_calibration_design.md（方案类，以代码为准）

## 附：本文核对清单

| 项 | 核对方式 | 结果 |
|---|---|---|
| `rfauto sensitivity --help`（sobol/morris/seed/adapter 旗标） | 实跑 | 过 |
| Sobol 总求值 = N×(d+2)、Morris 轨迹 max(5,N//d)、#234 居中 | `optimization/sensitivity.py` 模块头+docstring 实读 | 过 |
| `rfauto surrogate --help`（analyze/uq 两子命令） | 实跑 | 过 |
| `rfauto surrogate uq --help`（--tol/--n/--kind/--seed） | 实跑 | 过 |
| 名义点=min cost 样本、±1σ 排序、缺 tolerances 报错、R1 spread-skill 门 | `service/uq_service.py` surrogate_yield/build_yield_context 实读 | 过 |
| `rfauto uq --help`（yield-at/design-center/temp-zone/robustness） | 实跑（四子命令旗标逐条对） | 过 |
| robustness source 三形态（samples.json/数据集/run）与 --profile 二选一 | `uq robustness --help` + uq_service tolerance_source 分支实读 | 过 |
| samples.json ≥5 样本即可装载 | build_yield_context 玩具样本内存实调 | 过（名义点/预测正常，无盘写） |
| 校准链六步/design_kind 三态/lhs 需 n_samples≥5/LOOCV ρ≥0.8/FAIL=正常返回 | `service/calibration_service.py` 模块头+calibrate_surrogate 实读 | 过 |
| 校准产物四件套与 meta 登记（algorithm=surrogate_calibration） | calibration_service 落盘段实读 | 过 |
| 真实 FAIL 工件（ρ=0.3833/9 折/L9/taguchi） | `runs/20260903_235147_cb982df7/calibration/{gate,samples}.json` 实读 | 过 |
| 注册表 14 种 kind 清单（裸 available()=13，gnn_geom 模块 import 后 14） | `surrogate_registry.available()` 实调+装饰器注册面 grep | 过 |
| 第三方注册三方法契约 | `optimization/surrogate/base.py` docstring 实读 | 过 |
| uq --kind 收全注册表（帮助文本仅写 poly_ridge\|nn） | `calibration_service._make_model` 经 uq_service 调用链实读 | 过 |
| 注册表服务面 v1 零 CLI/MCP 接线（tune 三态开关除外） | `surrogate_registry_service.py` 模块头实读 + cli/mcp_tools grep | 过 |
| tune --sampler sbo / --warm-start-registry 三态 / 仅单目标生效 | `tune --help` 实跑 + `cli/domains/workflow.py` 声明实读 | 过 |
| surrogate analyze 真实输出（D1-1 N/A + 5 折 quality） | 只读实跑 20260831_125228_db3856cb | 过（§6.3 节选照录） |
| PCE 无独立 CLI、经 robustness worst-case 消费 | `core/pce.py`/`core/sparse_pce.py` 头实读 + 消费面 grep | 过 |
| campaign calibrate 阶段与 sampler 通道映射 | `campaign --help`/`campaign plan --help` 实跑 + `campaign_executor._exec_calibrate` 实读 | 过 |
