<!-- PR-10 文档站同步副本：源=docs/tutorials/campaign-walkthrough.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 战役逐阶段推进：从 plan 到 final_verify

> 多保真优化战役的完整推进手册（SO 走查任务 C 的 C3 断点收口）。
> 五条命令 + 一键执行器，全部对 `rfauto campaign --help` 实测口径。

## 战役生命周期

```
campaign plan ──► campaign run ──► campaign status ──► 判读/repro 归档
      │                │（断点续跑内嵌）
      └── campaign event（手工推进/修正状态机）──► campaign list（总览）
```

## 1. 生成计划（确定性阶段队列）

```bash
rfauto campaign plan recipes/my_bpf.yaml --out-dir runs/campaigns/
```

配方 → typed 五阶段队列（calibrate → … → report → final_verify），
含阶段依赖（depends_on）、预算、license 门槛、premortem 与
failure_knowledge。落盘后计划是不可变契约——改配方要重新 plan。

## 2. 一键执行（含断点续跑）

```bash
rfauto campaign run runs/campaigns/<name>.json
```

按依赖拓扑序派发各阶段 entry 命令，完成即自动 `campaign event` 推
状态机；失败短路、可续跑（重跑同一命令，已完成阶段按状态机跳过）。
长跑纪律：真机重项用后台分离 + 日志轮询；每机互斥意识管进程（#261）。

## 3. 盯状态

```bash
rfauto campaign status runs/campaigns/<name>.json   # verdict/各阶段 status/n_done/n_dead
rfauto campaign list                                # 扫全部已落盘计划
```

UI 侧同源看板：SSE 进度流、campaign queue/dashboard（`rfauto ui`
后浏览器打开）。

## 4. 手工推进状态机

```bash
rfauto campaign event runs/campaigns/<name>.json <stage> <event>
```

`stage_failed` 事件会把依赖它的未完成阶段递归 aborted——这是保护性
语义，不要绕过；确要重来就修因后重新 plan。

## 5. 收尾（判读与归档）

```bash
rfauto runs compare <run_a> <run_b>       # 跨保真/跨阶段对比
rfauto explain-run runs/<final_run>       # 指纹取证
rfauto repro runs/<final_run>             # 可复现包（干净 venv 可重建）
rfauto repro-verify <包目录>              # 验证复现包
```

## 纪律速查

- 判据统计量匹配响应形态（窄带谐振别用带内 max，#195）；
- study 缓存同种子秒回——配对实验合法、新轨迹要换 study/seed（#158）；
- 服务器侧任务毕必须清理（remote_hfss_cleanup； 规则 0b）。

## 下一步

- 单次调优（非战役）：`rfauto tune` / `rfauto autotune --self-verify`
- 偏差判读串接：`docs/tutorials/measurement-alignment.md`
- 多机协同：`rfauto remote probe/status`
