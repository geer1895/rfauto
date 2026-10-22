<!-- PR-10 文档站同步副本：源=docs/how-to/ui-performance-and-contract-gate.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 如何维护 UI 性能基线与前后端契约门

**场景**：你要给 UI 加一个 API 端点、改前端加载面，或怀疑"UI 变慢了"。
本文讲三件事：性能基线钉在哪里、怎么复测（运维视角）；契约棘轮门
`check_ui_contracts.py` 的双向对账口径——新增端点/调用时会发生什么
（贡献者视角）；以及服务端批处理面的 lake index 消费语义。全部命令与
数字实测（2026-10-19 复测；历史数据按当时点保留标注）。

## 1. 性能基线：钉了什么、在哪

### 1.1 全站 GZip（服务端出站压缩）

`src/rfauto/ui/server.py` 装配序：`GZipMiddleware`（最外层，minimum_size
=1024 小响应不压）→ CSP 附加头中间件——响应出站先加 CSP 头再压体，
两者并存（`test_w1e_ui_csp` 头值断言不破）。

SSE 不压：starlette 的 `exclude_content_types` 缺省已含
`text/event-stream`（gzip 缓冲会卡事件流帧），真机已复核——SSE 响应头
只有 `content-type: text/event-stream`、无 `content-encoding`。

**为什么快了**：JS 大件线传约缩 3–5 倍（本机实测 gzip -6 档：

| 文件 | 原始 | gzip 线传 | 比 |
|---|---|---|---|
| vendor/three.module.js | 1,272,972 B | 256,743 B | 5.0× |
| vendor/echarts.min.js | ~1,007 KB | ~326 KB | 3.1× |

**怎么验证**（先 `rfauto ui --port 8643` 起备用端口，#143 别撞常驻实例）：

```bash
# 压缩生效：content-encoding: gzip + 下载字节数 ≈ 原始 1/5
curl -s -H "Accept-Encoding: gzip" -o /dev/null -w "%{size_download}\n" \
    http://127.0.0.1:8643/static/vendor/three.module.js
curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null \
    http://127.0.0.1:8643/static/vendor/three.module.js | grep -i content-encoding

# SSE 排除：响应头应无 content-encoding
curl -s -N -m 3 -D - -o /dev/null http://127.0.0.1:8643/api/events/stream \
    | grep -i "content-encoding"   # 期望：无输出
```

### 1.2 前端加载预算（懒加载 + 数据面节流）

四件套，全部有守卫测试（`tests/unit/test_ui_perf_loading.py`）：

| 件 | 位置 | 语义 |
|---|---|---|
| three 懒加载 | `app.js` drawBoxes / `view_fieldviz.js` drawIsoMesh 调用点 `await import("three")` | 1.27MB 大件不进首屏；index.html **modulepreload 已删**（保留预取会让首屏强制下完它）——"modulepreload 缺席为常态"是回流钉 |
| runs 页 limit=500 | `view_runs.js` `/api/runs?limit=500` + 文本筛选 120ms debounce | 裸调全量在 runs 大时拖死渲染；500 上限配服务端 total 翻页条 |
| palette TTL 60s | `palette.js` `_DYN_TTL_MS = 60000` | runs+recipes 数据源 60s 缓存命中零网络；`#` 前缀搜 run 强制刷新一次绕 TTL；失败响应不入缓存 |
| dashboard 渐进首绘 | `routes/agent.py` `api_solvers` 走 `run_in_threadpool` | 同步冷扫曾阻塞事件循环 8.3s（真机抓出）——线程池化后首绘 ~99ms，数据后补填装 |

首屏线传实测：710KB → 454KB（−36%）。

**怎么复测**：首屏线传 = 浏览器 DevTools Network 面板 reload 总传输量
（无 three 大件即懒加载生效）；守卫测试一条命令：

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_ui_perf_loading.py -q
```

### 1.3 服务端批处理面：lake index 消费（内部面）

health 批检 / monitor 巡环 / league 联赛三个批处理面的**候选枚举**从
"逐目录 scandir"升级为 lake index 主源 + 滞后护栏 + 目录扫回退
（`lake_service.index_candidate_paths`，三面同款消费契约）：

1. 目录侧计数（裸 scandir，毫秒级）vs 索引侧计数双算；
2. 计数差 `|index − dir| > 阈值`（缺省 0=任何漂移即回退）→ 判索引滞后，
   **回退原目录扫路径——宁慢勿错，行为不变**；
3. 护栏过才走索引查询取候选路径（`?` 绑定）。

护栏语义实测（2026-10-19，runs 树 2283 个一级 run 目录）：索引建成后
health/monitor 面枚举 ~30ms、league 两层面 ~150ms；把索引人为放旧后
（index=9168 vs 目录 11447）护栏当场判 `usable=False` 回退目录扫，信封
`enumeration_source` 落 `dir_scan_fallback` + 告警注记——消费方零感知。
同机当时点的批量实测：health 枚举 103→28.5ms（−72%）/
league 575→120ms（−79%）/ monitor 152→19ms（−87%）。

**怎么复测**：

```bash
# 重建索引（幂等；数千目录纯读扫描）
rfauto lake index            # → ✓ rows=11481 meta=1815 verdict=137 db=runs\.lake_index.duckdb

# 看消费面走了哪条源（信封注记键；batch 面才有——单点 runs health 无此键）
rfauto runs health --all --json --limit 3
# → {"ok": true, ..., "enumeration_source": "lake_index", "enumeration_warnings": []}
# 回退时 enumeration_source="dir_scan_fallback" + warnings 带滞后告警原文
```

## 2. 契约棘轮门：新增端点/调用时会发生什么

`scripts/check_ui_contracts.py` 是**只读静态分析**（零网络、零 import
前端代码），双向对账：

- **A 悬空调用**：前端 JS（`static/**/*.js`，vendor/ 除外）的 `/api/`
  字面调用（反引号模板串 / 引号字面量 / `+` 拼接链三形态）经归一化后
  必须 ⊆ server.py Route 表——路径改名、笔误在静态门暴露，不用等真机
  点击 404；
- **B 无消费端点**：Route 表里 `/api/*` 必须被前端调用，或登记进
  `UNCONSUMED_ALLOWLIST`（带理由）——服务端加了端点没人消费同样红。

归一化口径（两侧同款）：路由参数 `{run_id}`/`{name:path}` → `*`；
JS 模板表达式 `${...}` → `*`；拼接链非字面量段（`encodeURIComponent(x)`
等）→ `*`；查询串从首个 `?` 截断（参数名/值契约不在本门，路径段契约
先行）；字面量尾随 `/` 补 `*`。

当前基线实测：**前端调用形态 61 · 服务端路由 65 · 无消费豁免 4 →
PASS（悬空 0 · 未登记无消费 0）**。

### 新端点四步（照做即绿）

1. **服务端**：`server.py`（或 `routes/*.py` 经装配）加
   `Route("/api/xxx", handler)`；
2. **前端**：JS 里用 `/api/` 字面形态调用——`` apiFetch(`/api/xxx/${id}`)
   `` 或 `"/api/xxx"`，归一化后与路由形态一致即可；
3. **确无 UI 消费面**（服务端兼容层/edb_app 侧脚本消费等）：在
   `UNCONSUMED_ALLOWLIST` 加条目**必须带理由注释**——棘轮纪律
   **只可删不可加**（删=前端接入清偿；加=新死路由须台账背书）；
4. **自证**：

```bash
.venv/Scripts/python.exe scripts/check_ui_contracts.py
# [UI 契约] 前端调用形态 61 · 服务端路由 65 · 无消费豁免 4
# [PASS] UI 前后端契约门（双向对账零违例：悬空 0 · 未登记无消费 0）
```

`DANGLING_ALLOWLIST` 基线为空——出现"悬空调用"先当笔误查，确有理由的
豁免是例外并须台账背书，不是常规出口。

本门已常驻化进合流预检（`scripts/merge_preflight.py` 面 18）——返回前
必跑 preflight（见第 4 节）。

## 3. 改动性能面的守卫

- 新增 vendor 大件 / 改 index.html 预取：跑 `test_ui_perf_loading.py`
  （modulepreload 缺席钉、preload href 单源钉）；
- 改 server.py 中间件栈：跑 `test_w1e_ui_csp.py`（CSP 头哈希钉不破）；
- 新端点 / 改路由：跑 `check_ui_contracts.py`；
- 改批处理面枚举：护栏行为钉在
  `tests/unit/test_lake_service.py` + `test_lake_index_batch_wiring.py`
  （回退语义：库缺/计数差/查询败三路全部回退目录扫且带告警注记）。

## 4. 收官：合流预检

```bash
.venv/Scripts/python.exe scripts/merge_preflight.py
```

UI 面（契约棘轮门=面 18、CSP、注册序、信封契约）与数字链全在其中，
全绿再返回。

## 5. 高频坑位

- **契约门对参数串失明**：查询串从 `?` 截断——`?limit=500` 写错参数名
  本门不报（这是已知限制，门对此失明）。参数面契约靠服务端
  ParamError→400 信封
  （`A8-D`）+ 定向测试兜底；
- **SSE 端点别手挂 gzip 排除**：starlette 缺省 `exclude_content_types`
  已覆盖 `text/event-stream`，手工再配一遍反而漂移；
- **three 别加回 modulepreload**：消费面已全在 `await import` 链内，
  预取只会把 1.27MB 拉回首屏（`test_ui_perf_loading` 回流钉当场红）；
- **palette 失败响应要绕 TTL**：错误信封不入缓存是钉过的语义
  （`palette.js` 头注）——新数据源接入照抄该形态，别把失败缓存 60s；
- **验证用备用端口**：`rfauto ui --port 8643`（#143，常驻旧实例占
  8642 会让"新端点 404"变成假象）。
