<!-- PR-10 文档站同步副本：源=docs/explanation/lazy-import-conventions.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 解释：lazy import 的四种形态与标注约定

> 这是一篇 explanation（解释文）：回答"为什么这样设计、什么时候允许把
> import 写在函数里"。操作细则见下文棘轮门；出处：2026-10-19 全仓
> 架构审计 §3.3。

## 为什么需要一条约定

rfauto 有大量函数体内 import（2026-10-19 复盘实测：src 全域
**1933 处、分布在 403 个文件**；审计口径含三类混合总计 4466 处）。
其中两种是**合法设计**，一种是**临时手段**，剩下的就是**惯性债务**——
但代码本身长得一模一样，人和工具都分不清。本约定用"位置 + 注释"把
四者区分开，让依赖图回归真实、让债务可盘点可收敛。

## 四种形态（判定顺序自上而下）

| 形态 | 写法 | 适用 | 先例 |
|---|---|---|---|
| ① 缺省：模块顶 import | 正常顶层 import | 一切没有下述理由的场景 | 全库主流 |
| ② 注解专用：TYPE_CHECKING 块 | `if TYPE_CHECKING:` + 字符串注解 | import 只为类型注解服务（运行期零成本，解类型环） | core/calculators.py 等已 37 文件 |
| ③ 可选依赖保护：try/except | `try: import X except ImportError:` | 重可选件缺位降级（军规 8：pyaedt/mcp 等只在 adapters 内 import） | adapters 各求解器入口 |
| ④ 函数内 lazy：**必须带标注** | 行尾 `# lazy: <原因>` | 见下方白名单 | cli/domains 三示范文件 |

**④ 的合法原因白名单**（标注原因必须取自这里）：

- `# lazy: startup-cost（cli 注册根轻载）`——cli/main 是 45 个 domains
  的注册组合根，import 任一 domain 即全库注册；把重模块 import 留在
  命令体内，`rfauto --help` 与注册序才能保持轻。**这是壳层（cli/ui）
  命令体的默认合法形态**；service 及以下不允许以此为由 lazy（它们的
  import 面不构成启动路径）。
- `# lazy: optional-dep`——即形态③，try/except 包裹时可省行尾标注
  （块本身即声明）。
- `# lazy: cycle-break`——同层循环依赖的临时破环手段（审计：19 模块
  大环 34 条环边 28 条靠 lazy 掩盖）。**须随行登记消除项**，随 T1 解环
  批次删除，不允许新增。service 层的既有 `# T1 解环：…` 行注已折进本
  标注（消除项=T1 解环台账）。
- `# lazy: run-path（执行面按需取用）`——**service 层专用**：
  服务执行面把下层模块（adapters 引擎面/infra/optimization）或端点
  薄壳的同层取用延后到请求/任务体内，模块 import（路由注册/服务装配）
  保持轻，且"每次执行时经源模块取名"保住 monkeypatch 源模块即可见
  的测试缝（test_w2_c_json_coverage 经 `rfauto.service.api.*` 注入
  实证依赖此缝，#116 家法的反向面）。**本标注不是永久豁免**：廉价
  下层站的迁回模块顶仍是 T2 拆巨石的顺带项，迁移时必须逐站核对
  patch 缝消费面（改测试注入样式或保留函数内取用）。

无标注的函数内 import = 未决债务：新代码禁止新增；存量随 T1（解环）/
T2（拆巨石）顺带迁回模块顶。

## 棘轮门（test_lazy_import_convention.py）

- **示范文件钉零**：cli/domains 的 scattered / bands_uq / workflow
  （cli 层 lazy 前三名，66 站——实测值）已于 2026-10-19 全量标注——这三文件
  出现任何未标注函数内 import 直接红。
- **service 层示范文件钉零**（2026-10-19）：service 层 lazy
  前三名 api/run_core（31 站）/ calibration_service（30 站）/
  rest_api（26 站）已 100% 标注（86 处物理行；同层 T1 解环面=cycle-break，
  其余=run-path）——同款钉零，新增未标注 lazy 直接红。
- **cli 层预算棘轮**：未标注总数只收不放（2026-10-19 实测 271，预算
  300 含同战役并行在制余量；下战役开工按实测收紧）。失败信息会列出
  重灾区文件与补标注/调预算的操作指引。

## 判定速查

```
import 只为注解？ ——是→ ② TYPE_CHECKING
缺了它还跑得起来吗？ ——跑不起来（可选件）→ ③ try/except
在 cli/ui 命令体里、为了 --help 轻？ ——是→ ④ 标 startup-cost
在 service 执行面（端点薄壳/引擎面/任务体）？ ——是→ ④ 标 run-path
在解一条已登记的环？ ——是→ ④ 标 cycle-break + 消除项
其它 ——→ ① 移回模块顶
```
