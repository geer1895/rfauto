# 5.6 生态抽取（最小口径）：可独立复用模块清单与抽取方案

> 定位：roadmap 5.6「把 openEMS 模板库/校准数据集抽成独立 repo（社区可复用）」
> 的**方案与证据文档**——本项**不真正拆包**，只给出：① 可独立复用模块清单
> （依赖边界实测）；② 每个候选的抽取方案（入口 API / 外部依赖 / 内部耦合 /
> 建议粒度）；③ 依赖边界 lint 证据的来源与复核命令。
>
> 红线：本文与配套脚本零发布动作。抽取成独立 repo 是用户决策。

## 1. 依赖边界证据（实测，非断言）

- **分层契约**：`.importlinter`（`layers` 契约 cli → mcp_server → service →
  linkage → optimization → models → adapters → pipeline → infra → core，
  core 为无内部依赖叶子）；CI `quality` job 每次 push/PR 跑
  `lint-imports --config .importlinter`（`.github/workflows/ci.yml`）。
- **候选模块第三方/内部 import 实测**：`python scripts/release_readiness.py --build`
  产出 `runs/release_staging/ecosystem/import_boundaries.json`（`ast.walk` 收集
  顶层+函数内 import，stdlib 判据 `sys.stdlib_module_names`）。2026-09-16 实测：

| 模块 | 第三方依赖 | rfauto 内部依赖（实测 import 目标） |
|---|---|---|
| `core/objectives.py` | numpy, pydantic | **无**（零内部依赖，可直接抽） |
| `core/anchor_benchmark.py` | 无 | `core.anchor_verdict`（常数 `S11_HEALTH_DB`） |
| `core/calculators.py` | numpy, scipy, skrf | `core.synthesis`（Stackup/forward_z0/inverse_width）、`core.deembed`、`core.symbolic_fit`、`core.solid_mesh`（均函数内惰性 import） |
| `core/synthesis.py` | numpy, scipy, skrf, yaml | `core.calculators`（多处惰性）、`core.coupled_microstrip` |
| `infra/visualization.py` | numpy, matplotlib, h5py, pyvista（惰性，viz3d extra） | `core.farfield`（惰性） |
| `service/dataset_insights.py` | pyarrow, yaml | `service.dataset_service`（顶层 import，强耦合） |

复核命令（离线）：

    python scripts/release_readiness.py --build
    python -c "import json;print(json.load(open('runs/release_staging/ecosystem/import_boundaries.json',encoding='utf-8'))['modules'])"

## 2. 抽取候选与方案（按就绪度排序）

### 2.1 `rfauto-templates`（openEMS/HFSS 模板库 + 官方例口径）——就绪度高

- **素材**：`docs/templates/*/meta.yaml`（38 模板）、`docs/rf_template_references.md`、
  `recipes/*.yaml`；打包结果即 H1 PDK 包（`runs/release_staging/pdk/`，含 SHA256SUMS）。
- **抽取粒度**：纯数据 repo（YAML/Markdown），无 Python 依赖；渲染脚本
  （`adapters/openems_templates.py`，他轨在制，本项不动）**不随首版抽取**——
  它依赖 CSXCAD/openEMS 绑定与 rfauto 的 physics_roles，耦合面大。
- **入口**：meta.yaml schema（template / f0_ghz / n_ports / params / substrate /
  nominal_params / extraction）——由 `tests/unit/test_template_meta_consistency.py` 钉住。
- **风险**：线宽数字禁止沿用（AGENTS 1c）——README 必须写明"几何由综合内核按基底精算"。

### 2.2 `rfauto-calc`（闭式计算器 + 线宽综合）——就绪度中

- **模块**：`core/calculators.py` + `core/synthesis.py`（互相惰性 import，需一起抽）
  + `core/coupled_microstrip.py` + `core/deembed.py` + `core/symbolic_fit.py`
  + `core/solid_mesh.py`（calculators 惰性依赖闭包）。
- **第三方**：numpy / scipy / scikit-rf / pyyaml——全部 PyPI 可得，无 EDA SDK。
- **入口 API**：`CALCULATOR_REGISTRY`（35 键，`@register_calculator`）、
  `synthesis.forward_z0 / inverse_width / Stackup`。
- **前置**：把 calculators↔synthesis 的双向惰性 import 收敛为单向（synthesis 为底、
  calculators 为上），否则独立包内循环依赖仍在（只是从 rfauto 命名空间搬到新包）。
- **测试随迁**：`tests/unit/test_calculators.py`、`test_physics_invariants.py`、
  `test_synthesis*.py`（注册表消费者三件套，#231）。

### 2.3 `rfauto-objectives`（目标/成本函数 schema）——就绪度高但价值低

- `core/objectives.py` 零内部依赖（numpy+pydantic），可零改动抽出；但单独成包
  意义有限——建议并入 2.2 作为 `rfauto_calc.objectives`。

### 2.4 `rfauto-datasets`（校准数据集导出面）——就绪度低

- `service/dataset_insights.py` 顶层强依赖 `service/dataset_service.py`（注册表/
  物化/查询），后者又依赖 `infra/run_store`（runs/index.db）——抽取需先切断
  run_store 耦合（改为传入 DataFrame/Arrow 表的纯函数层）。
- 首版建议：**只抽数据不抽代码**——公开集经 `export_hf_dataset` 导出为 HF
  布局（`runs/release_staging/dataset/<name>/`），社区用 `datasets.load_dataset`
  直读即可，无需 rfauto 代码。当前公开集为 0（内容决策待用户）。

### 2.5 `infra/visualization.py`——不建议抽取

- 与 `core/farfield`（他轨在制）耦合且依赖可选 pyvista/h5py；绘图风格与 rfauto
  内部报告一体，独立价值不足。

## 3. 抽取时的硬约束（沿用仓库规则）

1. 新 repo 各自 `pyproject` 必须声明全部第三方依赖（`scripts/check_env_deps.py`
   口径），extras 分组沿用 rfauto（如 viz3d）。
2. 抽出模块在 rfauto 内改为可选依赖回接（`rfauto[calc]` 指向新包），保留
   `rfauto.core.calculators` 作为 re-export 薄壳一个大版本周期，避免 #116 类
   "本地同名 def 遮蔽 re-export"死代码。
3. 数字铁律不变：新包不得内置任何来自其他模型/文档的毫米数常量。
4. 发布仍由用户手动执行（README「发布就绪与手动发布步骤」）。

## 4. 本项产物

- 本文（方案）；`runs/release_staging/ecosystem/import_boundaries.json`（证据，
  `--build` 生成，gitignore 内不入库）；`scripts/release_readiness.py` 5.6 节判定
  （文档存在 + 六候选模块可 AST 解析）。
