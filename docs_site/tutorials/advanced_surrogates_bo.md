<!-- PR-10 文档站同步副本：源=docs/tutorials/advanced_surrogates_bo.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 代理建模与主动学习进阶：六件新武器

> 上一篇《UQ 与代理模型》讲到 poly_ridge + LOO 门的经典链路，本文补齐
> 它留白的三块短板：**不确定性不会撒谎**（conformal 保形区间——给无 σ
> 代理补"边际覆盖有保证"的区间，不伪造高斯 σ）、**模型不确定度**（
> ensemble 集成把模型族间分歧变成免费 σ；mt_gp 跨指标联合建后验；
> rff_gp 让样本量上万时精确 GP 仍有出路）、**把模型推着走**（mo run
> 多目标 BO 环用跨指标联合后验驱动 EHVI 采集；al propose 在小样本标注
> 预算下回答"下一批真机测哪几个点"）。六件全部已落注册表/CLI，文中
> 旗标与 Python 面输出均为当前工作区实测；执行类命令（多目标环、真机
> 采集）给读法不代跑，读完你可以在 fake/toy 数据上分钟级复制全部离线面。
> 英文版（English version）：docs/tutorials/advanced_surrogates_bo_en.md。

## 0. 前置

- 已按 docs/tutorials/getting-started.md 装好环境，工作目录在仓库根
  （`runs/`、`recipes/` 相对 cwd 解析）。
- 全文命令走 console script 入口 `.venv/Scripts/rfauto.exe`。
- 铁律同前（AGENTS 规则 7）：**物理数字只出自确定性内核**——保形分位
  数、softmax 权重、ICM 后验、EHVI 增量、采集打分全部是确定性闭式/数
  值函数，六件的 Python/CLI 面都只是编排。同 seed 同输入逐位复现是每
  一件的出厂契约（各节"验收与守卫"给出验证读法）。
- 六件的关系一句话：conformal 是**包装器**（包任意已注册代理）、
  ensemble 是**组合器**（组合任意已注册代理）、mt_gp/rff_gp 是**两个
  新底座**（注册键直用）、mo run / al propose 是**两个消费入口**（把
  代理的不确定度变成下一步真机动作）。

## 1. 全景：六件武器各自补哪块短板

| # | 名字 | 触达面 | 一句话定位 |
|---|---|---|---|
| 1 | conformal | 注册键（Python 面；AL 采集路径经 `--conformal-fallback` 联动） | split-conformal 包装器：任意代理的预测输出加"边际覆盖 ≥1−α"的对称区间 |
| 2 | ensemble | 注册键（Python 面） | LOOCV ρ softmax 加权集成：成员间预测离散度 = 免费 epistemic σ |
| 3 | mt_gp | 注册键 + `mo run --surrogate mt_gp`（缺省） | ICM 多输出 GP：多指标共享输入核 + 跨指标相关后验协方差 |
| 4 | rff_gp | 注册键（AL/消费面按注册键接入） | 随机傅里叶特征 + 岭读出：样本量上万时精确 GP（O(n³)）的规模化近似档 |
| 5 | mo run | `rfauto mo run`（CLI 单叶） | 内置合成族多目标 BO 环：EHVI 采集 + 超体积裁判 + 帕累托前沿 |
| 6 | al propose | `rfauto al propose`（CLI 单叶） | 主动学习提议门：读湖样本 → σ×距离或采集三族 → 下一批真机点 |

代理注册键没有独立 CLI 叶（注册面=Python `surrogate_registry.create`，
消费面=本文 §2-§5 + 上一篇 §5 的 `surrogate uq/uq robustness --kind`
通道）；mo run / al propose 是两条新 CLI 叶。离线无求解的 Python 面
demo 本文逐个实测过（零文件写、零求解器调用），输出照录。

## 2. conformal：给无 σ 代理补"不撒谎"的区间

poly_ridge/gbdt 这类代理 `predict` 有值、`uncertainty` 是 None——
良率收口时只剩"点估计没有可信度"。conformal 键的解法：把样本劈成
训练/校准两半，在校准半上量"预测 − 真实"的残差分位数 q，之后对任何
预测点给 `预测 ± q` 的对称区间。**q 来自残差分位数，不是伪造的高斯
σ**——语义是"边际覆盖有保证"（交换性成立时 P(Y∈C(X)) ≥ 1−α 对随机
抽到的样本成立），不是逐点条件覆盖，分布漂移会破保证（模块 docstring
原文口径，fit 后 `fit_info["coverage"]` 如实标注）。

最小可复制示例（Python 注册面，离线零文件写；输出为当前工作区实测）：

```python
from rfauto.optimization.surrogate import surrogate_registry

m = surrogate_registry.create("conformal", config={
    "base_kind": "poly_ridge",                    # 被包装代理的注册键
    "base_config": {"bounds": {"x": (0.0, 1.0)}, "order": 2},
    "alpha": 0.1,       # 违覆盖率 → 名义 90% 区间
    "cal_ratio": 0.4,   # 校准集占比（随机划分，seed 固定）
    "seed": 7,
})
info = m.fit(samples)              # samples 同 SurrogateModel 契约
m.predict_interval({"x": 0.5})     # {指标: (lo, hi)}
m.uncertainty({"x": 0.5})          # {指标: q}——保形半宽（非 σ）
```

合成正弦面 + 噪声 30 点样本实测输出：

```text
split: random(seed=7, cal_ratio=0.4)  n_train/n_cal: 18 / 12
target_coverage: 0.9
q(cost) = 0.1278
interval @x=0.5: [0.7416, 0.9972]（均值 0.8694，半宽 0.1278）
coverage: marginal（边际覆盖，非逐点；交换性前提见模块 docstring）
```

参数旋钮表（构造 config，docstring 实读口径）：

| 键 | 缺省 | 语义与读法 |
|---|---|---|
| `base_kind` | 必填 | 被包装代理注册键；`conformal` 自嵌套显式拒绝 |
| `base_config` | `{}` | 透传被包装代理工厂（bounds/order 等） |
| `alpha` | 0.1 | 违覆盖率；0.1 → 名义 90% 区间 |
| `cal_ratio` | 0.5 | 校准占比（0,1) 开区间；随机划分保证 train/cal 各 ≥2 |
| `cal_indices` | None | 显式校准集下标（经典"用户自带校准集"形态；给定后 seed 不参与） |
| `seed` | 0 | 划分种子；同 seed 同样本两次 fit 分位数逐位相等 |
| `metrics` | 全部数值键 | 只建模白名单指标 |

验收与守卫（三条硬行为，实测复现见上）：

- **样本下限 4**（train/cal 各 ≥2）：更小 fit 期显式 ValueError。
- **小校准集诚实上溢**：校准点撑不起 α 时 q=+inf、区间无界、
  `fit_info["coverage_warning"]` 显式报警——上例 12 点样本同参数实测
  `q(cost) = inf` + 1 条报警。这不是 bug 是语义：覆盖保证退化为恒真，
  要么加密采样要么放宽 α。
- **重尾诊断**：校准残差 q90/q25 > 12 时报警"疑似混入分布外点，边际
  覆盖可能破位"（启发式提示，不是覆盖证明——#122 家法：报警不静默，
  也不冒充证明）。

与其他件的组合：① **conformal fallback 联动**——`al propose` 采集
路径 `--source registry --kind poly_ridge` 时，poly_ridge 无原生 σ，
缺省自动走本节的共形包装（信封 `sigma_source: "conformal_interval"`
如实标注，§7 实测）；② ensemble 的成员清单可以含 `"conformal"`
（成员 config 里给 `base_kind`），但更常见的是反过来——conformal 包
ensemble，给"集成 + 保形区间"双层不确定度。

## 3. ensemble：模型族间分歧当免费 σ

第二个诚实缺口：单代理给不出"模型本身有多不确定"。ensemble 键把
若干已注册代理各自做一遍留一交叉验证（LOOCV），拿折外预测 cost 与实
际 cost 的 Spearman ρ 做 softmax 加权（ρ 高的成员权重大），逐指标预
测取凸组合；**成员间预测离散度**（std 或 max−min）作为 epistemic σ
透出 `uncertainty()`——poly_ridge/gbdt 等 std=None 档借此获得"模型族
间分歧"意义的不确定度（不冒充高斯观测噪声，docstring 原文口径）。

最小可复制示例（同一组 12 点正弦样本；输出实测照录）：

```python
e = surrogate_registry.create("ensemble", config={
    "bounds": {"x": (0.0, 1.0)},
    "members": ["poly_ridge", "nn",
                {"kind": "gbdt", "config": {"n_estimators": 30}}],
    "rho_metric": "cost",
})
info = e.fit(samples)          # 成员权重/剔除记录在 info["members"]
e.predict({"x": 0.5})          # 逐指标加权平均
e.uncertainty({"x": 0.5})      # 逐指标成员间离散度
```

```text
ensemble weights: {'poly_ridge': 0.296, 'nn': 0.571, 'gbdt': 0.133}
ensemble rho: {'poly_ridge': 0.329, 'nn': 0.986, 'gbdt': -0.469}
ensemble predict @x=0.5: cost=0.9433  sigma=0.05930
```

读法：nn 的 LOOCV ρ=0.986（bagging σ 在这个面上最可信）拿到 0.571 权
重；gbdt ρ 为负照样进 softmax（ρ∈[−1,1] 直接进指数），只是权重被压
到 0.133——**权重不淘汰成员**，淘汰只发生在成员 fit/LOOCV 失败时
（`members[i].status="dropped"` + error 原文，不静默塌缩；全部失败显
式 RuntimeError；仅 1 席幸存时 `single_member_warning` 如实标注"离散
度 σ 恒 0"）。

参数旋钮表（docstring 实读口径）：

| 键 | 缺省 | 语义与读法 |
|---|---|---|
| `bounds` | 必填 | 注入每个成员工厂 |
| `members` | 必填 | 注册键字符串或 `{kind, config}` 列表；`ensemble` 自嵌套拒绝 |
| `rho_metric` | 唯一数值指标 | LOOCV 裁判指标键；多于一个数值键且未显式给 → ValueError（不替用户猜裁判面） |
| `softmax_temperature` | 1.0 | 权重锐度：→0 收敛 argmax 独占，→∞ 收敛均匀 |
| `dispersion` | "std" | `"std"`=成员间总体标准差；`"range"`=max−min |
| `eval_indices` | None | 透传 loocv_rho 折面下标（虚拟样本进训练集不进裁判折面） |
| `metrics` | None | 透传各成员的指标键白名单 |

验收与守卫：

- **确定性**：权重与预测只依赖样本 + 显式配置（LOOCV 闭式折、softmax
  闭式、成员自身确定性）——同配置同样本两次 fit 权重与预测逐位相等。
- **规模边界（模块头原文）**：单次 fit = 每成员一次 LOOCV（O(n) 次成
  员拟合）；若再对 ensemble 整体套 LOOCV（如 loocv_rho 套 ensemble 工
  厂）就是 O(n²·m) 次成员拟合——poly_ridge 等闭式成员可承受，GP/NN
  成员建议 n≲30 或用 `eval_indices` 收窄折面。
- fit 样本下限 4（LOOCV ρ 在更小样本上无意义），fit 期显式报错。

与其他件的组合：`members` 里放 `{"kind": "conformal", "config":
{"base_kind": "poly_ridge", …}}` 可把保形区间纳入集成；conformal 反向
包 ensemble 得到"集成均值 + 保形区间"。选型直觉：想要"哪个代理可信"
的量化答案用 ensemble 的 weights；想要"这个点该不该信"的区间答案用
conformal 包任意单代理。

## 4. mt_gp：多输出 GP，跨指标相关免费产出

第三个缺口：既有代理面逐指标独立拟合，指标间的联动（比如 S11 谷深与
谐振频率本来就不是独立的）全丢。mt_gp 键用 ICM（intrinsic
coregionalization model，Bonilla et al., NIPS 2007）把多指标联合建模：
输入核 × 指标间共区域化矩阵 B，曲线形状先验跨指标共享，**跨指标后验
协方差由 `predict_joint` 免费产出**（对角=各指标 σ²，非对角=跨指标
相关——多目标采集 mo run 的 mt_gp 缺省消费面）。

最小可复制示例（20 点两指标样本：cost=正弦面、loss=余弦面；输出实测
照录）：

```python
g = surrogate_registry.create("mt_gp", config={
    "bounds": {"x": (0.0, 1.0)}, "kernel": "se", "seed": 20261029})
info = g.fit(samples2)             # metrics 缺省=样本全部数值键并集
g.predict({"x": 0.5})              # 逐指标均值
g.uncertainty({"x": 0.5})          # 逐指标后验 σ
mean, cov = g.predict_joint({"x": 0.5})   # 单点全后验 (means, cov M×M)
```

```text
mt_gp metrics: ['cost', 'loss']  n_obs: [20, 20]
mt_gp B(2x2) 对角: [0.2504, 0.1024]
mt_gp 跨指标相关 corr[0,1]: 0.6328
mt_gp converged: True  nll: -35.54
predict_joint @x=0.5: means=0.9927/0.4269 cov[0,1]=0.000000
mt_gp uncertainty @x=0.5: {'cost': 0.0011, 'loss': 0.00102}
```

读法：`corr[0,1]=0.6328` 是拟合出的指标间相关（正弦/余弦面在本例采样
下确实正相关）；`cov[0,1]≈0` 是 x=0.5 这个点的后验——两个指标在该点
都有 20 个近邻观测，后验方差被压到很小，相关性自然不显现。**跨指标
收益要在观测稀疏处看**（Bonilla 传递抵消警告：无噪声 + 块设计下跨任
务预测不获益；本实现缺省固定 nugget>0 且支持逐指标异位观测，两前提
天然满足——模块头原文口径）。

参数旋钮表（docstring 实读口径）：

| 键 | 缺省 | 语义与读法 |
|---|---|---|
| `bounds` | 必填 | 单元归一化基准（同 warped_kriging/smt_kriging 约定） |
| `metrics` | 全部数值键 | 指标键列表；有效点 <3 的键跳过不硬拟（fit_info `skipped_metrics`） |
| `kernel` | "se" | `"se"` \| `"matern52"`（复用 gp_det 核面） |
| `rank` | =M | 共区域化矩阵因子秩 B=L·Lᵀ（1..M；降秩=限制指标间相关结构） |
| `fixed_B` | None | 先验共区域化矩阵（嵌套 list，按指标键排序序）；给定时 B 不学习 |
| `optimize_noise` | False | log σ² 是否入 MLE（联优有"信号全解释成噪声"退化风险，同 gp_det 契约） |
| `seed` | 20261029 | 因子初值种子；同 seed 同数据逐位复现 |
| `maxiter` | 200 | L-BFGS-B 最大迭代 |

验收与守卫：

- **B 的 PSD 校验不静默**：`fixed_B` 非对称/非半正定显式 ValueError
  （"拒绝修复与静默"，校验单源 `validate_coregionalization_matrix`）。
- **诚实边界**：精确小样本 GP，堆叠 Gram 复杂度 O((Σn)³)——n≲200、
  M≲8 毫秒-秒级，样本量上万请走 §5 的 rff_gp；M=1 自然退化为普通 GP
  不报错；跨指标协方差 B 是潜过程量，指标噪声越大 B̂ 相对真相关的偏
  置越大（噪声归 D 不归 B 的口径后果，如实标注）。

与其他件的组合：`mo run --surrogate mt_gp`（缺省）——多目标 BO 的
EHVI 采集消费 `predict_joint` 的联合后验（§6）；AL 采集路径
`--source registry --kind mt_gp` 用原生后验 σ 提议（§7 实测）。

## 5. rff_gp：样本量上万时，精确 GP 的规模化出路

精确 GP（gp_det 底座）O(n³)，样本量过万不可承载。rff_gp 键走随机傅
里叶特征（Rahimi & Recht, NIPS 2007）+ 线性岭读出：SE 核用 D 个
cos 特征近似（O(n·D²) 训练、O(D+d) 逐点评估，D 缺省 512），ℓ 单源
复用 gp_det.fit_mle（n≤子样本上限时与精确 GP 消费面逐位同源；超过时
固定 seed 子样本上估，fit_info `mle_rows` 如实记）。

最小可复制示例（40 点正弦样本；输出实测照录）：

```python
r = surrogate_registry.create("rff_gp", config={
    "bounds": {"x": (0.0, 1.0)}, "n_features": 256, "seed": 20261030})
info = r.fit(samples)
r.predict({"x": 0.5})       # {"cost": ...}
r.uncertainty({"x": 0.5})   # 近似 σ（见诚实边界）
```

```text
rff_gp keys: ['cost']  n_features: 256  ell_mode: mle  mle_rows: {'cost': 40}
rff_gp ell: [0.0409]
rff_gp predict @x=0.5: 0.9917（真值 0.9987）
rff_gp sigma @x=0.5: 0.00179
```

参数旋钮表（docstring 实读口径）：

| 键 | 缺省 | 语义与读法 |
|---|---|---|
| `bounds` | 必填 | 单元归一化基准 |
| `n_features` | 512 | 特征数 D；<1 显式报错（>10k 档建议 ≥512） |
| `seed` | 20261030 | 特征 ω/b 与 MLE 子样本两路独立固定；同 seed 逐位复现 |
| `ell_mode` | "mle" | `"mle"`（gp_det.fit_mle 单源估）\| `"fixed"`（config["ell"] 显式给） |
| `ell` | 仅 fixed 档 | 标量或逐维列表；任一 ≤0 显式报错 |
| `mle_subsample` | 256 | ℓ-MLE 子样本上限（n>cap 时固定 seed 子样本，诚实近似） |
| `ridge_rel` | 1e-6 | 相对岭正则（λ=ridge_rel·n，镜像 gp_det nugget/var 比量级） |
| `metrics` | 全部数值键 | 建模指标键白名单；有效点 <3 跳过（家族口径） |

验收与守卫：

- **σ 是近似（诚实边界，docstring 原文）**：`uncertainty()` 返回线性
  特征空间岭回归的解析预测方差开方——两层近似（随机特征蒙特卡洛 +
  线性读出）后的近似 σ，**不是**精确 GP 后验；消费面（如良率 MC）把
  它当"可信度分数"用，不当置信区间用。
- 只支持 SE 核（Bochner 谱=高斯闭式可采样；matern52 谱非高斯，无
  kernel 键如实不做）。
- **小样本 MLE 过小 ℓ 教学例**：同面 24 点样本 MLE 选出 ℓ=0.0025、
  x=0.5 处预测 0.8025（真值 0.9987）——过拟合形态；加密到 40 点后
  ℓ=0.0409、预测 0.9917。窄面/小样本时 `ell_mode="fixed"` 显式给 ℓ
  是诚实出路。
- 常数目标键不硬拟：predict 常数、σ=0（残差方差解析为 0，非伪造），
  `constant_keys` 如实记录。

与其他件的组合：AL 采集路径 `--source registry --kind rff_gp`（原生
近似 σ 入采集分）；大规模数据集（数据工厂物化后）+ `al propose
--dataset` 是它设计的消费形态（§7）。

## 6. mo run：模型驱动多目标 BO 环

单目标代理环（`tune --sampler sbo`）解决不了"两个指标怎么折中"。
`rfauto mo run` 是多目标 BO 环的 CLI 门：内置合成族上，代理联合后验
驱动 EHVI（Expected Hypervolume Improvement）采集——候选点的 M 指标
联合后验 → 含观测噪声的 EHVI 增量 → argmax；超体积裁判单源复用
pareto_tools；全程最小化。数值全部来自 mo_bo 确定性内核（2 维 EHVI
解析分片闭式，M>2 走 MC 采样预估），CLI 是薄壳。

```bash
.venv/Scripts/rfauto.exe mo --help
.venv/Scripts/rfauto.exe mo run --help
```

实测旗标（`--help` 层逐条对过）：`--kind zdt1|dtlz2`、`--n-eval`（总
评估预算，缺省 20）、`--n-obj`（仅 dtlz2 消费）、`--n-params`、
`--surrogate mt_gp|smt_kriging`、`--seed`、`--ref-point`（逗号分隔浮
点，长度=指标数）、`--n-init`、`--batch-size`、`--n-candidates`、
`--mc-samples`、`--no-fantasy`、`--no-samples`、`--json`。

执行形态（本篇不代跑——它是真跑的优化环；数字引自 O1 接线席 e2e 实
测档 `runs/aurora_n/o1_mo_bo/EVIDENCE.md`）：

```bash
.venv/Scripts/rfauto.exe mo run --kind zdt1 --n-eval 20 --json
```

O1 实测读法：退出码 0、2.6s；hv_curve 15 点 11.8730 → 13.9491（增益
+2.0761）；帕累托前沿 8 点、采集轨迹 14 点；`--json` 信封含
`front_params`（前沿点的 x0..x{n-1}）与 `samples`（全评估记录）。人读
形态（不带 `--json`）打富文本表：预算/实际评估数、参考点（缺省
`frozen`=初始前沿冻结；跨臂 HV 对比建议显式传同值 `--ref-point`）、
HV 曲线、前沿目标值表。同 seed 同参数两次运行逐位一致（内核 G4 钉：
初始设计/候选池 lhs 固定 seed、2 维解析路径零随机）。

参数旋钮表（`--help` + run_mo_bo docstring 实读口径）：

| 旗标 | 缺省 | 语义与读法 |
|---|---|---|
| `--kind` | zdt1 | zdt1（恒 2 指标，解析前沿 f2=1−√f1）\| dtlz2（指标数 --n-obj 可调，M>2 走 MC 采集） |
| `--n-eval` | 20 | 总评估预算（初始 LHS + 迭代真评估合计）；整批语义，实际评估数 ≥ 预算 − batch + 1 如实回显 |
| `--n-obj` | 问题缺省 | 仅 dtlz2 消费；=1 退化标量显式拒绝并指引 SBO 通道 |
| `--surrogate` | mt_gp | mt_gp 联合后验 \| smt_kriging 逐指标独立；**其余注册键显式拒绝**（对多目标后验无契约保证，不静默放行） |
| `--ref-point` | 冻结 | 超体积参考点；跨臂对比必须显式同值 |
| `--n-init` | 自动 | 初始 LHS 点数（缺省 min(n, max(3, min(10, n//3)))）；显式须 ≥3（代理首拟合下限） |
| `--batch-size` | 1 | q>1 贪心 + 目标空间 plug-in fantasy（批内不确定度不收缩，低估待评点间耦合，如实标注） |
| `--n-candidates` | 256 | 每轮候选池规模（MC 路径大池显著变慢） |
| `--mc-samples` | 128 | 指标数>2 时逐候选 MC 样本数 |
| `--no-fantasy` / `--no-samples` | 关 | 关 fantasy / JSON 信封减载 |

验收与守卫（负例全部信封化显式报错，O1 席逐条实测）：

- 未知合成族 / `n_obj=1` 退化标量 / `poly_ridge` 不在多目标支持面 /
  `n_eval<2` / ref_point 长度不符 / `n_init<3`——每条都有明确 error 文
  案，不抛裸 traceback。
- **目标函数只收内置合成族**（zdt1/dtlz2）：外部真函数不可 JSON 化；
  Python 编程面 `service.mo_bo_service.register_problem` 注册后经
  `kind=<注册名>` 消费（指标数 <2 注册时即拒）。
- 观测缺测（指标部分缺失）样本参与代理拟合但不进前沿/超体积（M 维不
  完整无法定位，如实语义）。

与其他件的组合：`--surrogate mt_gp` 是"跨指标相关进采集"的主通道
（§4）；`--batch-size 3 --no-fantasy` 对照 `--batch-size 3`（默认开
fantasy）可以量 fantasy 的收益——对照实验换 seed 才是新轨迹（#158）。

## 7. al propose：下一批真机测哪几个点

数据工厂的闭环缺最后一环：采了一批数据、判读完了，**下一批点在哪
采**？`rfauto al propose` 读湖样本（samples.json / 物化数据集 / run
trials 三形态），撒 LHS 候选池，按"不确定度 × 距离"或采集函数族打
分，返回 top-k 提议点。两条路：缺省=σ 求和旧路径（宿主
`propose_next_points` 逐字节转发）；`--acquisition` 展开 T-N9 采集三
族 `lcb|ucb|ei|sigma`（置信界两臂 / 期望改进 / 纯不确定度）。

```bash
.venv/Scripts/rfauto.exe al --help
.venv/Scripts/rfauto.exe al propose --help
```

实测旗标：`--samples/--dataset/--run`（互斥恰给一）、`--k`、`--kind`
（代理注册键）、`--acquisition`、`--source gp|bootstrap|nn|registry`、
`--beta`（lcb/ucb 置信界系数）、`--xi`（EI 探索参数）、
`--n-candidates`、`--min-dist`、`--seed`、
`--conformal-fallback/--no-conformal-fallback`（三态）、`--max-rows`、
`--json`。

最小可复制示例（toy 样本 12 点，x∈[0,1] 单参数 cost；输出实测照录）。
先生成玩具样本集（确定性 seed，同命令逐位复现）：

```bash
.venv/Scripts/python.exe -c "
import json
import numpy as np
rng = np.random.default_rng(7)
samples = []
for x in np.linspace(0.02, 0.98, 12):
    y = float(np.sin(3.0*x)*0.5 + 0.5) + rng.normal(0, 0.01)
    samples.append({'params': {'x': round(float(x), 4)},
                    'metrics': {'cost': round(y, 6)}})
doc = {'bounds': {'x': [0.0, 1.0]}, 'objectives': [], 'samples': samples}
with open('runs/al_tut/toy_samples.json', 'w', encoding='utf-8') as f:
    json.dump(doc, f, indent=1)
print('written', len(samples), 'samples')
"
```

第一步先撞一个真实坑：缺省 `--min-dist 0.12` 下 12 个样本已把 [0,1]
铺满（最近邻距 ≤0.044），候选全被距离过滤，`proposed: 0`——样本密时
记得调小 `--min-dist`：

```bash
.venv/Scripts/rfauto.exe al propose \
  --samples runs/al_tut/toy_samples.json \
  --k 3 --min-dist 0.02 --json
```

```text
ok: True  surrogate_kind: nn  n_existing: 12  proposed: 3
   {'x': 0.0404} score= 0.0165
   {'x': 0.0431} score= 0.0161
   {'x': 0.0460} score= 0.0157
```

采集三族实测（同一 toy 样本）：

```bash
# EI：source=gp 的固定超参 GP 后验
.venv/Scripts/rfauto.exe al propose \
  --samples runs/al_tut/toy_samples.json \
  --k 3 --acquisition ei --min-dist 0.02 --json
```

```text
ok: True  mode: acquisition  acq: ei  source: gp
   {'x': 0.2238} score= 0.0  sigma= 0.00013
   {'x': 0.1665} score= 0.0  sigma= 0.00013
   {'x': 0.0404} score= 0.0  sigma= 0.00016
```

EI 全 0 分不是 bug：toy 样本的最优点远优于 GP 后验可达改进量，期望改
进真下溢——排序退化为距离过滤序（O4 接线席在真实数据集上同样复现，
`runs/aurora_n/o4_al/EVIDENCE.md` 如实记录）。判读时看 `score` 量级
与样本最优 cost 的相对位置，别把全 0 当排序。

registry σ 源与 conformal fallback 联动（本节与 §2 的接口）：

```bash
# mt_gp 原生后验 σ（sigma_source: native）
.venv/Scripts/rfauto.exe al propose \
  --samples runs/al_tut/toy_samples.json \
  --k 3 --acquisition ucb --source registry --kind mt_gp \
  --min-dist 0.02 --json

# poly_ridge 无原生 σ → 自动走 conformal 包装（sigma_source:
# conformal_interval）；toy 12 点校准集撑不起 alpha=0.1 → 分数 +inf
# （§2 的诚实上溢在采集面的复现——分数无界=提议退化为过滤序）
.venv/Scripts/rfauto.exe al propose \
  --samples runs/al_tut/toy_samples.json \
  --k 3 --acquisition sigma --source registry --kind poly_ridge \
  --min-dist 0.02 --json
```

```text
# ucb + mt_gp：sigma_source: native  beta: 2.0
   {'x': 0.4362} score= 1.66297  mean= 0.0  sigma= 0.83148
   {'x': 0.1275} score= 1.66297  mean= 0.0  sigma= 0.83148
   {'x': 0.3022} score= 1.66297  mean= 0.0  sigma= 0.83148
# sigma + poly_ridge：sigma_source: conformal_interval，score= inf ×3
```

读法：`sigma_source` 键如实区分 `native`（代理自带 σ）与
`conformal_interval`（共形区间半宽）——共形半宽不是高斯 σ，消费方按
键名标注（#122 家法）。要有限分数：给足样本（校准集 ≥9 点才撑得起
alpha=0.1）或换自带 σ 的注册键（mt_gp/smt_kriging/nn）。

参数旋钮表（`--help` + al_service docstring 实读口径）：

| 旗标 | 缺省 | 语义与读法 |
|---|---|---|
| `--samples/--dataset/--run` | 必给其一 | 三形态互斥；dataset/run 的 bounds 由观测参数范围推导（如实标注） |
| `--k` | 5 | 提议点数 |
| `--kind` | nn | 代理注册键（legacy σ 路径需支持 uncertainty 或开 conformal fallback） |
| `--acquisition` | None（legacy） | `lcb\|ucb\|ei\|sigma`；给任意一个即进采集族模式 |
| `--source` | gp | 不确定度来源（采集路径）：gp=固定超参 GP 后验 / bootstrap=同类代理自助集成 / nn=bagging σ / registry=任意注册键（原生 σ 缺席按 conformal_fallback 走共形包装） |
| `--beta` | 2.0 | lcb/ucb 置信界系数 |
| `--xi` | 0.0 | EI 探索参数 |
| `--min-dist` | 0.12 | 与既有样本最小归一化距离（样本密时下调，见上坑） |
| `--conformal-fallback` | 按路径 | 三态：legacy 缺省 False / 采集缺省 True，同各自内核缺省 |
| `--max-rows` | 5000 | 数据集装载行数上限（超出如实 truncated 标注，不静默截断） |

验收与守卫：

- **确定性**：同 seed 同输入两次运行逐位一致（O4 席 CLI 子进程与
  service 层双面实测 `*_bitwise: true`）。
- **负例显式**：来源未给/多给/不存在、空样本、空参数域、零数值指标、
  未知采集名/来源、registry 缺 kind——全部 ok=False 信封化。
- **提议点必须真机复验后才能并入样本集**（信封 note 原文）——σ 只由
  确定性内核产出，提议不是结论（#7）。

与其他件的组合：`--dataset` 直连数据工厂产物（`rfauto datasets
materialize` 之后小样本提议下一批）；`--source registry --kind rff_gp`
接 §5 的大规模档；legacy 路径 `--conformal-fallback` 把 §2 包装器接到
任意无 σ 注册键上。

## 8. 选型速查与组合矩阵

六件选型速查（按问题找件）：

| 你面临的问题 | 用哪件 | 不适用时 |
|---|---|---|
| 代理没有 σ，但良率收口要区间 | conformal（包它） | 校准集 <9 点撑不起 alpha=0.1（q=+inf）→ 加样本或换自带 σ 的键 |
| 不知道该信哪个代理 | ensemble（看 weights） | GP/NN 成员 + 样本 >30 → eval_indices 收窄或减成员 |
| 多个指标要一起建模/一起收口 | mt_gp | 样本 >200 或 M>8 → 精确 GP 扛不住，rff_gp 无跨指标联合 |
| 样本量上万 | rff_gp | 要跨指标联合后验 → 拆指标或回到 mt_gp 分块 |
| 两个指标的折中寻优 | mo run | 真实器件目标函数 → register_problem Python 面注册 |
| 小样本预算下选下一批真机点 | al propose | 提议必须真机复验后才并样本集 |

组合矩阵（实测过的组合，含联动面）：

| 组合 | 形态 | 实测落点 |
|---|---|---|
| ensemble 包 conformal | members 里放 `{"kind": "conformal", …}` | §3 组合段（注册面合法组合） |
| conformal 包 ensemble | base_kind="ensemble" | §2/§3 互相包（双层不确定度） |
| conformal fallback 联动 | `al propose --source registry --kind <无σ键>` | §7 实测（sigma_source=conformal_interval） |
| mt_gp 进 MO 环 | `mo run --surrogate mt_gp` | §6（缺省通道，predict_joint 消费） |
| mt_gp 进 AL 提议 | `al propose --source registry --kind mt_gp` | §7 实测（sigma_source=native） |
| batch + fantasy 同开 | `mo run --batch-size 3`（fantasy 缺省开） | §6（`--no-fantasy` 可关，对照实验量收益） |
| rff_gp 进 AL 提议 | `al propose --source registry --kind rff_gp` | §5 组合段（大规模档原生近似 σ） |

三条贯穿全文的纪律，收尾再钉一遍：

1. **不确定度不许冒充**：共形半宽是残差分位数不是高斯 σ、集成离散度
   是模型族间分歧不是观测噪声、RFF σ 是两层近似——每件都在
   fit_info/信封里如实标注档位，消费面按标注选口径（#122 家法）。
2. **确定性可复现**：每一件的 seed 都有显式缺省值，同 seed 同输入逐
   位复现是出厂契约——复现实验合法，新轨迹换 seed（#158）。
3. **数值只在确定性内核**：六个键的数学全部单源（保形分位数=core/
   conformal、LOOCV=poly_ridge.loocv_rho、核=gp_det、EHVI=mo_bo、采
   集=acquisition_scores），Python/CLI 面零数值逻辑——这是"agent 只
   编排不产数字"（AGENTS 规则 7）在代理建模面的落点。

## 9. 下一步

- 经典链路（Sobol/校准/良率四件收口）：
  docs/tutorials/uncertainty_and_surrogates.md
- 数据工厂闭环（采集→数据集→判读）：docs/tutorials/data_factory.md
- 代理注册表全貌与第三方接入：上一篇 §5 + docs/tutorials/extending-rfauto.md
- 多目标进化族（NSGA-II/III）与竞赛架：`rfauto mo` 之外的 multiobj
  面见 docs/tutorials/first_optimization_loop.md 与模块 docstring

## 附：本文核对清单

| 项 | 核对方式 | 结果 |
|---|---|---|
| `rfauto mo --help` / `mo run --help` 全旗标 | 实跑（runs/aurora_n/tutorials_adv/help_mo*.txt） | 过 |
| `rfauto al --help` / `al propose --help` 全旗标 | 实跑（help_al*.txt） | 过 |
| `rfauto surrogate --help` / `surrogate uq --help`（注册键消费通道） | 实跑（help_surrogate*.txt） | 过 |
| 四键注册在位（conformal/ensemble/mt_gp/rff_gp） | `surrogate_registry.available()` 实调（registry_available.txt） | 过 |
| conformal：30 点有限 q=0.1278 + 12 点 +inf 上溢与报警 | 内存实调（py_conformal_finite.txt） | 过 |
| ensemble：weights/rho/离散度 σ 实测输出 | 内存实调（py_conformal_ensemble.txt） | 过 |
| mt_gp：corr=0.6328、predict_joint、skipped/PSD 校验口径 | 内存实调（py_mt_gp_rff_gp.txt）+ 模块 docstring 实读 | 过 |
| rff_gp：40 点 ℓ=0.0409 预测 0.9917 + 24 点小 ℓ 过拟合教学例 | 内存实调（py_rff_gp_tune.txt） | 过 |
| mo run e2e 数字（2.6s/hv 11.8730→13.9491/前沿 8 点/负例六条） | O1 席 e2e 档 runs/aurora_n/o1_mo_bo/EVIDENCE.md 实读 | 过 |
| al propose：legacy 三点 + min-dist=0 坑 + EI 下溢 + native/conformal 双 σ 源 | CLI 实跑（al_legacy_md002.json / al_acq_*.json） | 过 |
| al propose 确定性（CLI/service 双面逐位）与负例清单 | O4 席 e2e 档 runs/aurora_n/o4_al/EVIDENCE.md 实读 | 过 |
| 旋钮表逐键 | 各模块 docstring + run_mo_bo/al_propose 签名实读 | 过 |
