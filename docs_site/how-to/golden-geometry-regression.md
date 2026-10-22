<!-- PR-10 文档站同步副本：源=docs/how-to/golden-geometry-regression.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 如何使用模板 golden 几何回归仓（diff / accept 全流程）

**场景**：你改了模板渲染面（`adapters/openems_templates/` 的几何段、
网格段、守卫阈值），要确认"除你有意改动的那几族外，72 族渲染产物
零漂移"；或你有意改动后要把新基线入库。golden 仓是内置能力，对
全部注册族（TEMPLATE_META=72，2026-10-18 实测）逐族钉住四类摘要。

## 1. golden 快照里钉了什么

每族一份 `tests/golden/template_geometry/<族>.yaml`（实测 0.40–3.16KB
量级，零时间戳，同树重算 diff 恒空）：

| 摘要 | 粒度 | 抓什么 |
|---|---|---|
| 渲染脚本全文 sha256 | 逐字节 | 脚本文本任何改动 |
| CSX 几何摘要 | 原语按（属性,类型）计数 + 逐原语包围盒 1e-9 m（nm 级）舍入排序哈希 | 任意几何改动；对浮点噪声免疫 |
| 网格摘要 | 三轴线数 + 最小间距 + 线坐标 1e-6 m（µm 级）舍入哈希 | 网格加密/吞线类改动（#368 族） |
| 端口号集合 | 脚本 `_portN` 绑定去重 | 端口增删/重编号 |

渲染以标称参数（`TEMPLATE_NOMINAL`，与 docs/templates/<族>/meta.yaml
`nominal_params` 双侧严格相等）+ 缺省网格（meta
`mesh_resolution_mm=0.0` 自动档）执行；判断面在 CSXCAD 实测对象上
（#212 的做法：渲染 → exec 几何段 → 实测，秒级零仿真）。

## 2. 日常三连：diff → 改代码 → 再 diff

```bash
# 全族对比（只读，零写盘；输出 JSON 信封）
rfauto templates golden-diff
# → {"ok": true, "n_total": 72, "n_clean": 72,
#    "n_guard_blocked_clean": 7, "n_drift": 0, "n_missing": 0,
#    "verdict": "clean", "drifts": {...}, ...}

# 只看单族（未知族名报错信封，不静默）
rfauto templates golden-diff --template mline
```

`verdict` 取值：`clean`（全部一致）/ `drift`（有族差异）/ `missing`
（有族缺 golden 文件）/ `error`（渲染抛错）。`drifts` 是逐族人读差异
摘要（脚本哈希/几何/网格/端口四类，新旧值对照）——按它定位你无意
碰到的族。

**7 个 `guard_blocked` 族是预期态**：combline/interdigital/sir_bpf/
ring_resonator/xcheb_bpf4（缝分辨）、isl_shielded/sicl（孔径分辨）
的缺省档渲染被守卫拒绝（#266 NEAR≤缝/3 族）——golden 如实记
`status: guard_blocked` + 守卫原文，不伪造哈希。守卫拒绝本身也被钉住：
**守卫阈值漂移同样红**。

## 3. 有意改动后：accept 重生成（显式意图门）

```bash
# 确认 drifts 清单里只有你有意改的族，再接受新基线
rfauto templates golden-diff                     # 先看
rfauto templates golden-diff --accept            # 重生成（可 --template 限单族）
rfauto templates golden-diff                     # 复核 verdict=clean
```

测试面等价入口：`RFAUTO_REGEN_GOLDEN=1` 环境变量跑
`tests/unit/test_template_golden.py`（test_golden_regression 先例）。

`--accept` 是显式意图门，设计动机是**防误吞真回归**：渲染面的意外
改动（重构时碰了几何常量、网格守卫阈值漂移）必须先在人眼前以
`drifts` 形态出现、被评审，然后才允许成为新基线。直接改 golden 文件
没有意图门，会静默放行真回归——**永远走 --accept，不要手编 yaml**。

## 4. 判读纪律

1. **drift 面前先问归属**：这次 diff 里的每个漂移族，能不能对回你这轮
   有意改动？对不回来的就是真回归（或别人正在改——先 `git status`
   看有没有未提交改动，别急着 accept）；
2. **accept 与源改动同笔 commit**：新基线 + 造成它的源改动 +
   （如适用）meta/regen 面一起提交，golden 哈希才可追溯；
3. **守卫拒绝不是绕过的理由**：guard_blocked 族要换审计档渲染走
   既有审计 helper 的网格查表（#297），不是放松守卫；
4. 服务层单源在 `service/template_golden_service.py`（模块 docstring
   是能力权威出处）；新模板注册后跑一次 `--accept` 即入册（缺文件
   =verdict missing 提示你补）。

## 5. 与其他门的分工

| 门 | 管什么 | golden 仓管什么 |
|---|---|---|
| 模板几何离线审计（#212 的做法） | 单族几何连通性/带宽实测 | 72 族全量的**回归**（改动检测） |
| test_template_meta_consistency | TEMPLATE_NOMINAL ↔ meta.yaml 双侧相等 | 不重复（nominal 键集另一层面） |
| docs_site/kernel_cards 再生 | 文档数字面 | 渲染产物几何面 |

渲染流程总览见 docs/how-to/run-openems-smoke.md；新表面交付清单见
docs/how-to/new-surface-checklist.md。
