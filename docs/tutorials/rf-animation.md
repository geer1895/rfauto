# 动图渲染：让 run 数据自己"动"起来

> 静态曲线回答"长什么样"，**动图回答"怎么变的"**——S 参数沿频点生长、
> 两个 campaign 的参数竞速、场分布逐帧展开。`rfauto anim render` 把一份
> 声明式 spec JSON 渲染成 SVG 动画：**全部数字只从确定性数据源读出**
> （run 湖/仿真产物/锚点 JSON），缺数据显式报错、禁示意数据兜底；同
> spec 两跑逐字节同（sha256 钉）。零 LLM 零网络。本文 spec 均为可复制的
> 最小骨架，三个真数据走查例出自仓内 run 湖实测（形态单源：
> `runs/aurora_q/qw41_examples/`，只读引用）。前置：
> `docs/tutorials/getting-started.md`（会跑通一条仿真链）。
> 英文版（English version）：`docs/tutorials/rf-animation_en.md`。

## 0. 你将完成

1. 理解 spec 的四段结构（chart_type / source(s) / style / animation），
   以及"17 图型 × 12 数据源 kind"的选型表；
2. 用 CLI 与 MCP 两个同源出口各渲染一次动图（含 `--self-check` 体检）；
3. 认识三种失败分类（io / spec / data）与它们的修复路径；
4. 走通三个真数据例（S 参数生长 / 参数竞速 / 场热力演进）。

## 1. 两个同源出口

CLI 与 MCP 转发**同一个** service 函数（`service/anim_render_service.anim_render`），
同输入逐字节同输出：

```bash
# CLI：缺省写 spec 同目录同名 .svg
rfauto anim render spec.json --json

# 显式输出路径 + 渲染后自检体检（warn 级提示不拦路）
rfauto anim render spec.json --out out.svg --self-check --json

# 不落盘：SVG 原文进信封 svg_str 字段（管道/Agent 文本信道消费）
rfauto anim render spec.json --out - --json
```

```text
# MCP 工具（Agent 侧同名同参）
anim_render(spec_path="spec.json", out=None, self_check=False)
```

成功信封（节选）：`svg_path`（落盘路径）、`sha256`（SVG 字节指纹）、
`chart_type`、`frame_count`、`duration_s`、`data_sources`（逐源清单），
`--self-check` 时附 `self_check` 报告；`file_sha256_matches=true` 表示
信封 sha256 与盘上文件字节一致（确定性钉）。

## 2. spec 四段结构（最小骨架）

```json
{
  "chart_type": "sparam_evolution",
  "title": "可选标题",
  "canvas": {"width": 960, "height": 540},
  "style": {
    "colors": ["#1f77b4", "#d62728"],
    "font_size": 13,
    "labels": ["measured"],
    "y_mode": "db"
  },
  "source":  {"kind": "sparams_csv", "path": "runs/<run_id>/results/sparams.csv",
              "columns": ["S11", "S21"]},
  "animation": {"fps": 8, "duration_s": 4.0}
}
```

（上面骨架是单源图型形态；多源图型把 `source` 换成 `sources` 列表——
两键并存会显式报错 `spec.source 与 spec.sources 互斥`。）

- `chart_type` 必填（渲染器注册键）；`source`/`sources` 互斥二选一
  （多源图型用 `sources` 列表，源数量/角色约束见 §3 表）；
- `canvas` 像素 200..4096；`style` 全部可选（`y_mode` 仅幅值族图型消费）；
- `animation`：`duration_s` 优先于 `fps`；
- 未知键/缺必填/图型未注册/源数量不合 → **spec 分类显式报错**（schema
  权威出口=本表 + `rfauto.service.animation.spec` 模块 docstring）。

## 3. 17 图型 × 12 数据源 kind 选型表

数据源 kind 词表（loaders 单源）：`sparams_csv`（run 湖 S 参数表）、
`snip`（Touchstone sNp，skrf 读入）、`trials`（run 目录/单 trial/JSON
数组，须含 `trial_number`/`params`/`cost`）、`anchor_json`（锚点/导出
JSON 原始 dict）、`field_dump`（场帧序列）、`layout_json`（图元坐标）、
`cascade_json`（级联级表 `gain_db`/`nf_db`）、`nf2ff_cut`（方向图切面）、
`chain_json`（链路框图节点/边）、`symbols_json`（调制符号序列）、
`budget_json`（预算级表 `value_db`）、`cfc_state`（CfC 隐态轨迹
`hidden`/`time`，标准化网络空间）。

| chart_type | 动画语义 | source(s) 形态 |
| --- | --- | --- |
| `sparam_evolution` | S 参数沿频点逐帧生长 | 单源 `sparams_csv`/`snip`；或多源同栅同列集（steps 模式） |
| `param_race` | 多 campaign 参数轨迹竞速 | `sources` 恰 N≥2 个 `trials` |
| `fit_compare` | 实测/仿真/代理三线对拍 | `sources` 2..3 个（`sparams_csv`/`snip`/`anchor_json`） |
| `smith_trajectory` | Smith 圆图轨迹逐点描画 | 单源 `sparams_csv`/`snip` 恰一列，或 `anchor_json` `{"points":[...]}` |
| `vswr_history` | VSWR=(1+\|Γ\|)/(1−\|Γ\|) 沿频点揭示 | 单源 `sparams_csv`/`snip` 恰一列（缺省 S11） |
| `before_after` | 改参前后同轴双色对比 | `sources` 恰 2 个 `sparams_csv`/`snip`（同栅同列名） |
| `filter_morphing` | 滤波响应族形变演化 | 多源 `sparams_csv`/`snip`（同栅同列集） |
| `tuning_replay` | 调参历程回放（曲线+trial 落点） | `sources` 恰 2：1 个 `trials` + 1 个 `sparams_csv`/`snip` |
| `field_heatmap` | 场分布热力图逐帧展开 | 单源 `field_dump` |
| `structure_explode` | 版图图元分层爆炸 | 单源 `layout_json` |
| `stackup_growth` | 叠层逐层生长 | 单源 `layout_json` |
| `nf_cascade` | 级联 NF 瀑布（Friis 累计） | 单源 `cascade_json` |
| `pattern_scan` | 方向图切面扫描 | 单源 `nf2ff_cut` |
| `signal_flow` | 链路框图逐级点亮 | 单源 `chain_json` |
| `constellation_eye` | 星座/眼图符号逐帧落入 | 单源 `symbols_json` |
| `budget_funnel` | 链路预算漏斗（负值累计） | 单源 `budget_json` |
| `cfc_state` | CfC 隐态轨迹逐 step 生长（标准化网络空间） | 单源 `cfc_state` |

图型清单可用 `rfauto.service.animation.available_chart_types()` 实测
（注册表口径，17 内建）。渲染零算术改写——坐标映射/幅值口径（dB）/
VSWR 公式等是**声明式显示变换**，逐渲染器 docstring 单源声明。

## 4. 三种失败分类（error 信封 `category`）

| category | 触发 | 典型修复 |
| --- | --- | --- |
| `io` | spec 文件缺失/不可读/非 JSON 对象；SVG 落盘失败 | 核对路径；省略 `--out` 用缺省落点 |
| `spec` | 缺 `chart_type`/未知图型/未知键/源数量不合 | 按 §2 schema 修 spec（信封第二行带指引） |
| `data` | 数据源文件缺失/残缺/列名不符/不同栅 | 核对 kind 与产物表头；run 是否 `status=done` |

失败信封不抛裸异常（`ok=false` + `errors` 列表 + `category`），Agent
侧可按 category 分诊重试。

## 5. 自检体检（`--self-check`）

`self_check=true` 时渲染后追加**声明式估算**体检（结构完整性/帧序单调/
文字盒挤压与越界），信封附 `self_check` 字段：

```json
{"ok": true, "n_errors": 0, "n_warnings": 2,
 "issues": [{"level": "warn", "kind": "text_overlap",
             "locator": "text[7]×text[10]", "message": "…"}]}
```

- `warn` 级=提示不拦路（SVG 输出不受开关影响，逐字节同）；`error` 级
  才是结构问题；
- 典型 warn：长标题/长轴标在 960×540 缺省画幅的文字盒挤压——换更短
  `title` 或加大 `canvas`。

## 6. 真数据走查三例（runs/aurora_q/qw41_examples，只读引用）

### 例 1：S 参数逐频点生长（`sparam_evolution`）

数据=branchline_coupler openEMS run 湖产物
`runs/20260922_221941_e2d813d9/results/sparams.csv`（401 频点）：

```json
{"chart_type": "sparam_evolution",
 "title": "branchline_coupler openEMS run 20260922_221941",
 "source": {"kind": "sparams_csv",
            "path": "runs/20260922_221941_e2d813d9/results/sparams.csv",
            "columns": ["S11", "S21"]},
 "animation": {"fps": 12}}
```

指纹：401 帧 / 33.42 s / self_check ok（0 warn，三类检测全净，与
`SOURCE.md`/`selfcheck.json` 在档值一致）。

### 例 2：两个 campaign 的参数竞速（`param_race`）

数据=两个真机 run 的 `trials/`（wilkinson p0_single vs mf_p1 各 40 trial）：

```json
{"chart_type": "param_race",
 "title": "wilkinson tune campaign: p0 vs mf_p1",
 "sources": [{"kind": "trials", "path": "runs/<run_a>"},
             {"kind": "trials", "path": "runs/<run_b>"}],
 "style": {"labels": ["p0_single_42", "mf_p1"]},
 "animation": {"fps": 8}}
```

### 例 3：场热力演进（`field_heatmap`）

数据=openEMS 时域场 dump 折帧（140 步→10 帧）：

```json
{"chart_type": "field_heatmap",
 "source": {"kind": "field_dump",
            "path": "runs/aurora_q/qw41_examples/ex3_field_heatmap_td/td_field_dump.json"},
 "style": {"colormap": "iron", "colorbar_label": "|E| (V/m, raw)"},
 "animation": {"fps": 4}}
```

三例 spec/SOURCE.md/selfcheck.json 均在 `runs/aurora_q/qw41_examples/`
在档（sha256 指纹可复核）；本教程只读引用，零回写。

## 7. 数据源纪律（红线）

- 全部数字只从确定性数据源读出：spec 声明路径，渲染零算术改写（§3 声明
  变换除外）；缺数据 → `AnimationDataError` 显式报错，**禁静默画空图、
  禁示意数据兜底**；
- `trials` 源的 `cost` 缺失=显式报错不猜代理量；`snip` 依赖 skrf（懒
  import，sNp 缺席不影响其他源）；
- 确定性：同 spec 两跑逐字节同（sha256 钉）——SVG 纯手写零 matplotlib
  依赖，全部迭代序 sorted。

## 8. 常见问题

- **SVG 放浏览器不播放**：SVG 动画依赖 SMIL/CSS 帧时序，极老浏览器或
  严格 CSP 站点可能禁用；导出后可用浏览器直接打开 file:// 验证；
- **帧数太多文件太大**：`sparams_csv` 每频点一帧，401 点 ≈ 数百 KB；
  可先 `columns` 裁列或对源数据抽点（抽点属数据预处理，在数据源侧做，
  渲染器不隐式抽点）；
- **多源不同栅**：渲染器不做隐式插值（require_common_grid 显式报错）——
  先在数据源侧统一重采样再引用；
- **MCP 侧不落盘**：`anim_render(out="-")` 把 SVG 原文放进信封 `svg_str`
  字段，适合 Agent 直接消费文本，再由调用方决定落盘位置。
