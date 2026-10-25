# 如何在离线回路里开发 rfauto UI

**场景**：你要改前端样式/布局/i18n/视图逻辑，但不想（或不能）起真后端——
机器上没有 runs 数据、HFSS/求解器不可用、或者只想 5 秒内刷新看效果。
本文讲 rfauto 的 UI 离线开发回路（采纳 #4 提案，hfssq-ui-kit 思想）：
一个极简静态服务把前端与 mock 数据信封拼成无后端可跑的页面。

本文所有命令与路径均实测（2026-10-19 交付验证）。

## 1. 三十秒起一个离线页面

```bash
# 仓根执行；venv 换成你的 python 也行（脚本只用 stdlib）
.venv/Scripts/python.exe scripts/ui_dev_loop.py
```

输出：

```text
[dev-loop] UI 本体   http://127.0.0.1:8643/  (static=src\rfauto\ui\static)
[dev-loop] mock 通道 http://127.0.0.1:8643/api/<端点>  (镜像 /mock/api/<端点>)
[dev-loop] 已收录 5 端点: /api/calibration, /api/metric-glossary, ...
```

浏览器开 `http://127.0.0.1:8643/`——runs 检视、标定、词典 tooltip 等
已收录端点的视图全部有数据可渲染。改完 `static/` 下任何文件，**浏览器
刷新即见**（服务对所有响应发 `Cache-Control: no-store`，无强刷烦恼）。

## 2. mock 数据从哪来、怎么换

mock 信封在 `runs/ui_dev_loop/ui_mock_data.json`（gitignored 证据区），
结构三层：

```json
{
  "_meta": {"purpose": "...", "sanitize": "..."},
  "endpoints": {
    "/api/runs": {...完整真实信封...},
    "/api/solvers": {...}
  }
}
```

三种维护方式：

- **从真 UI 重采（推荐）**：先起真后端，再采样脱敏——

  ```bash
  rfauto ui --port 8699                                # 终端 A
  .venv/Scripts/python.exe scripts/ui_dev_loop.py \
      --capture http://127.0.0.1:8699                  # 终端 B，采完即退
  ```

  `--capture` 拉取 5 个首屏端点（runs/solvers/recipes/calibration/
  metric-glossary），把 `run_id`/`timestamp` 合成化后并入 mock 文件；
  其余端点保留不动（增量并入）。
- **手工编辑**：直接改 `endpoints` 键下的信封。键=路径（**不带查询串**
  ——查询串在匹配时被剥掉，`/api/runs` 同时伺服 `/api/runs?limit=500`）；
  值=该端点的完整响应信封（与真服务 JSON 逐键同形，前端零改造）。
- **从零开始**：删掉 mock 文件再起服务，脚本自动落一份内置合成样例
  （clean checkout 也能跑，不依赖 runs/ 历史）。

查看已收录端点：`scripts/ui_dev_loop.py --list`。未收录端点返回
`ok:false` 错误信封（`X-RFAUTO-Mock: miss`）——对应视图走既有错误
呈现，不白屏；缺哪补哪即可。

换端口/换 mock 文件/换静态目录：`--port` / `--mock` / `--static`。

## 3. 前端 apiFetch 的 mock 开关（同源/跨源两用）

`static/pages/api.js` 的 `apiFetch` 支持 **mock 基址改写**（新增
开关，opt-in，缺省零行为变化）：

- **本回路的同源用法**：`http://127.0.0.1:8643/?mock=1` ——页面内全部
  `apiFetch("/api/...")` 改写到 `/mock/api/...`（与服务端直挂 `/api` 等
  效，用于验证开关本身）；
- **跨源用法**：用任意静态伺服（`python -m http.server`、live-reload
  工具）伺服 `static/`，apiFetch 指向 dev loop 的 mock 通道：

  ```bash
  python -m http.server 8700 --directory src/rfauto/ui/static   # 静态面
  .venv/Scripts/python.exe scripts/ui_dev_loop.py --port 8643    # mock 面
  # 浏览器开 http://127.0.0.1:8700/?mock=http://127.0.0.1:8643/api
  ```

  mock 响应带 `Access-Control-Allow-Origin: *`，跨源直接可用；基址若
  已以 `/api` 结尾则不重复拼接（`/mock` 基址拼出 `/mock/api/...`）。

行为细则：

- 只改写**相对 `/api/` 路径**；绝对 URL、静态资源、SSE 不经开关；
- 超时/Bearer token/错误信封/取消逻辑逐字节不变（只换 URL）；
- 开关是**会话级**（URL 查询参数触发，不落 localStorage）——刷新去掉
  `?mock=...` 即回真通道，防止 mock 读数被误当真值；
- 编程面：`setApiMockBase(base)` / `apiMockBase()`（node 桩 fetch 可测，
  同 `setApiToken` 惯例）。

## 4. 覆盖面与限制

- **只覆盖 `apiFetch`**：视图层 27 个文件已全走
  apiFetch，离线回路覆盖全部视图数据面；`app.js` 的全局 `api`（chat 等
  少量直连面）不经本开关——起真后端调试这些面。
- **只伺服 GET**：写端点（POST /api/run、/api/tune/start 等）在 mock
  通道返回 405 信封——离线回路不伪造写副作用。
- SSE（`/api/events/stream` 等）不在 mock 面——需要事件流的视图先看
  错误呈现，属预期。

## 5. 纪律（mock 数据不进 git 的哪些面）

- mock 信封文件一律落 `runs/`（gitignored 证据区）：`runs/ui_dev_loop/
  ui_mock_data.json` 是**样例与个人调试数据**，`git status` 不应出现它；
  禁止把 mock 数据搬进 `src/`、`docs/`、`tests/` 任何提交面（测试要用
  合成信封就在测试内联构造，如 test_ui_r12_deepening 的桩 fetch）；
- **mock 读数不是物理真值**：mock runs/calibration 信封里的 verdict/
  指标是结构样例——判读、文档数字、回归对照一律以真引擎/真服务产出
  为准（#122 同族：不凑数）；
- 脱敏红线：`--capture` 已把 `run_id`/`timestamp` 合成化；手工补采
  其它端点时同样**不得携带绝对路径、凭据、主机名**进 mock 文件；
- 席位/会话收尾：dev loop 是前台进程 Ctrl-C 即走；用过的采样脚本落
  `runs/` 用毕即删（工作区摆放纪律 §9）。
