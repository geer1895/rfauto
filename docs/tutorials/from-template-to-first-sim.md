# 从模板到第一次仿真（pifa 全程实录）

> 本文每条命令都在开发环境实测过（退出码 0，2026-11-04）。它解决一个
> 真实用户卡过的死胡同：**模板页看到的器件族名（如 `pifa`）不等于优化
> 模型注册表名**——按模板族名写 `model: pifa` 配方，`rfauto validate`
> 会报"未知模型"。根因是两张注册表：openEMS 模板注册表有 **76 族**
> （TEMPLATE_META），优化模型注册表只有 **4 模型**。T-Q14 通路把两条
> 表接通了：76 族逐族映射（有模型的 4 族出 `model:` 形态、其余 72 族出
> `template:` 模板直跑形态），一条命令导出正确形态的配方，validate →
> run 全链可用。
> 英文版（English version）：docs/tutorials/from-template-to-first-sim_en.md。

赶时间的话：第 2 节一条命令导出 pifa 配方，第 4 节一条命令零 license
跑完第一次仿真。

## 0. 前置

- 已完成 `docs/tutorials/getting-started.md` 第 1-2 节（安装 + `rfauto
  doctor` 体检）。
- 全程不需要 HFSS/ADS license（fake 通道是离线解析近似；openEMS 真引擎
  见第 6 节）。

## 1. 查族：你要的器件在不在 76 族里

```bash
rfauto template-spec list --json | jq -r '.templates[].name'   # 需已装 jq
# 没装 jq 用 python 代替（效果相同，零新依赖）：
rfauto template-spec list --json | python -c "import json,sys; [print(t['name']) for t in json.load(sys.stdin)['templates']]"
```

列出全部注册族（76 族，附每族组件齐备性）；只想确认某个名字在不在，
直接试导出即可（未知族名会给 did-you-mean，例如 `pifaX` → "你是不是想
写 'pifa'？"）。

76 族里哪些有对应优化模型（`model:` 形态）、哪些走模板直跑
（`template:` 形态）？映射表是 service 层单源（幂等可复算）：

```bash
python -c "from rfauto.service.template_recipe_service import \
    template_model_mapping as m; \
    [print(r['family'], '->', r['model'] or '(模板直跑)') for r in m()['mapping']]"
```

实测输出（有模型的恰四对，其余 72 族全部模板直跑）：

```text
wilkinson -> wilkinson_power_divider
patch -> patch_antenna
branchline -> branchline_coupler
dipole -> (模板直跑)
stepped_impedance -> (模板直跑)
coupled_line -> (模板直跑)
mline -> mline
...
monopole -> (模板直跑)
pifa -> (模板直跑)
ifa -> (模板直跑)
...
```

判定依据写在每族 `rationale` 字段里（TemplateSpec.hfss_plugin 绑定 /
models 注册表同名匹配 / 无绑定=openEMS 模板直跑），不拍脑袋。

## 2. 一键导出配方

```bash
rfauto templates export-recipe pifa
```

信封里 `form: template` 表示模板直跑形态；`yaml` 字段就是配方全文。
要落盘用 `--out`：

```bash
rfauto templates export-recipe pifa --out my_pifa.yaml
```

**你会看到**（节选）：

```yaml
recipe_version: 1
notes: pifa 模板导出配方（rfauto templates export-recipe，名义参数=TEMPLATE_NOMINAL 注册表归档值，f0=2.4GHz；单端口族缺省宽带
  ±30%）——整带无谷时应放宽频段复查（谐振可能在带外）
params:
  pifa_l_mm: 17.0785
  pifa_w_mm: 8.0
  pifa_ws_mm: 2.0
  pin_back_mm: 2.0
  pin_y_mm: 2.0
setup:
  solver: openEMS
  freq_range_ghz:
  - 1.68
  - 3.428571
  points: 401
template: pifa
```

要点：

- **参数值全部出自注册表归档名义值**（TEMPLATE_NOMINAL，HJ 精算出处见
  模板注册表头注），导出面零手拍数字；换设计频率时改这些名义参数即可。
- 有模型的 4 族（wilkinson/patch/branchline/mline）导出的是
  `model:` 形态（`form: model`），走既有优化链，`tune` 调参也可用。
- 目标已存在时缺省拒绝覆盖，`--force` 显式覆盖（信封带 `overwritten`
  标记）。

**岔路**：`template: pifaX` 拼错族名 → validate 报"未知模板族"并给
did-you-mean；`params` 里写了族参数面之外的键 → 报"未知参数"并提示
合法面（查合法参数名：`rfauto template-spec list` 或模板注册表 meta）。

## 3. validate

```bash
rfauto validate my_pifa.yaml
```

**你会看到**：`✓ 配方校验通过`。

如果你手里是按老 README 写的 `model: pifa` 形态（真实用户复现形态），
validate 现在会两条一起说清楚：

```text
- 未知模型: pifa（已注册模型清单: rfauto models list）
- 提示: 'pifa' 是 openEMS 模板族名（模板注册表 76 族之一，非 models
  注册表键）——模板直跑配方请写 template: pifa（一键生成: rfauto
  templates export-recipe pifa）
```

把 `model: pifa` 删掉换成 `template: pifa`，或直接用第 2 节导出的配方。

## 4. 第一次仿真（fake 通道，零 license）

```bash
rfauto run my_pifa.yaml --adapter fake
```

**你会看到**：

```text
✓ 仿真完成  run_id: 20261106_035725_14ad6c73   （run_id 每次生成，下同）
  run 目录: runs/20261106_035725_14ad6c73
  cost: 0.0
  指标:
```

（没写 `objectives` 时 cost 恒为 `0.0`（空目标求和）、指标为空——plain
run 语义：出 S 参数与报告，不评 cost。）

**看产物**：`runs/<run_id>/results/params.s1p`（Touchstone）、
`report.md`（S 参数图+报告）、`meta.json`（`"template": "pifa"`）。
fake 通道对 pifa 用的是设计式精确逆模型——S11 谷就落在设计频率 2.4 GHz
附近（实测 -16.1 dB @2.40 GHz），改 `pifa_l_mm` 谷位会真实移动，可以
拿它理解参数物理含义。

**加一个目标**（可选，cost 才有意义）：在配方里加

```yaml
objectives:
  - metric: s11_db_min
    band: [2.35, 2.45]
    op: max_below
    value: -10
```

再 `rfauto validate`（指标名/判据算子拼错当场报）→ `rfauto run`。

## 5. UI 入口（同一条通路）

`rfauto ui` 起工作台后：

- **模板画廊页**：任意模板卡 → 「详情」抽屉 → 参数表下方「导出配方」
  按钮——展示形态与配方 YAML 全文（复制存盘即用）。
- **标定锚页**：锚详情里关联的模板族同样有「导出配方」按钮。

前端与 CLI 消费同一个 service 函数（`service/template_recipe_service`），
两端产物逐字节同源。

## 6. openEMS 真引擎（可选）

fake 通过后想跑真 FDTD：

```bash
rfauto run my_pifa.yaml --adapter openems
```

前置：本机可用 openEMS（`RFAUTO_OPENEMS_BIN` 指到含 openEMS.exe 的
bin 目录；构建见 `docs/openems_build_guide.md`）。真跑时长按模板族而
异（辐射器件族带 λ0/4 空气域，分钟级起）。

## 7. 边界（如实）

- `template:` 形态支持 `run`（fake/openems 双通道）；**`tune` 调参面
  暂不支持**——调参需求请用有优化模型的 4 族（或经 anchor 校准链）。
- 模板直跑链暂未接入结果缓存键面（models 插件版本成分缺位），run 信封
  里 `cache.provenance = "not_applicable"` 如实标注，同参数重跑不命中
  缓存。
- dry-run（`rfauto run --dry-run`）对 template 形态输出简化计划面（无
  缓存键段），真跑前照旧可用。

## 8. 一页速查

| 想做什么 | 命令/入口 |
|---|---|
| 列全部模板族 | `rfauto template-spec list --json` |
| 查 76 族→模型映射 | `service.template_recipe_service.template_model_mapping()` |
| 导出配方 | `rfauto templates export-recipe <族> --out <路径>`（`--force` 覆盖） |
| 校验 | `rfauto validate <配方>` |
| 零 license 冒烟 | `rfauto run <配方> --adapter fake` |
| openEMS 真引擎 | `rfauto run <配方> --adapter openems` |
| UI 导出入口 | 模板画廊详情抽屉 / 标定锚详情页「导出配方」按钮 |
