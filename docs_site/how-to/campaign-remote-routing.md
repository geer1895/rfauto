<!-- PR-10 文档站同步副本：源=docs/how-to/campaign-remote-routing.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 如何把战役 stage 路由到远程机器（campaign --remote）

**场景**：战役计划里的真机 stage（HFSS 精算/openEMS 批）想发到课题组
仿真服务器跑，本机只留编排。这是 E62 席能力（2026-10-08，E-06/PR-15
拆批件）：plan 级 `--remote` 旗标 + stage 级 `remote` 键，经发射门序
路由到注册机器。多机通道全景与机器登记实操见
docs/tutorials/remote_server.md；服务器硬规则以
docs/服务器接入与仿真资源说明.md 为准（本文不重复红线表）。

## 0. 前置

- 机器已登记：`configs/remote_machines.yaml`（入库无凭据）+ 同目录
  `remote_machines.local.yaml`（凭据，gitignored）——键结构见
  docs/tutorials/remote_server.md 第 1 节；
- 可选依赖就位：`pip install rfauto[remote]`（paramiko 懒加载）；
- 版本配对红线自检：服务器 AEDT 版本必须与本机相同（PyAEDT gRPC
  客户端-服务端配对）。

## 1. 探活：先确认机器面健康

```bash
rfauto remote probe [machine]      # TCP 连通性+时延（零副作用零凭据）
rfauto remote status [machine]     # 探活+SSH 认证可达（凭据缺失如实
                                   #   missing_credentials，不猜不试）
rfauto remote queue [machine]      # 在途作业+单写锁排队+席位占用
rfauto remote resources [machine]  # 资源视图
```

机器名缺省=唯一登记机器；无登记时全部"空表如实"（本地模式零行为
变化）。

## 2. 写 remote 声明：三种形态

声明挂在 stage 上（`stage_extra.remote`），plan 级缺省键为
`campaign_remote_default`，优先级=**stage 声明 > plan 级缺省**：

```jsonc
{
  "campaign_remote_default": "sim_server",     // plan 级：全部 stage 缺省路由
  "stages": [
    {"node_id": "calibrate", "stage_extra": {
        "remote": "sim_server"}},              // stage 级：机器名
    {"node_id": "tune", "stage_extra": {
        "remote": {"machine": "sim_server",
                   "wait_mode": "poll",
                   "keep_remote": true}}},     // stage 级：dict 细控
    {"node_id": "report", "stage_extra": {
        "remote": false}}                      // 显式 False：本机执行
  ]
}
```

归一规则（`service/campaign_executor.py::stage_remote_decl`，离线单测
钉）：`None/False/""` =不路由；`true` =缺省登记机器；字符串=机器名
（去空白）；dict=机器名+细控键。**本机路径零变化契约**：plan 里没有
remote 声明、CLI 不带 `--remote`，执行路径与历史逐字节同。

## 3. 发射：dry-run → run

```bash
# 先看拓扑序+阶段预算+互斥预览，零执行
rfauto campaign run <plan 目录或 campaign.plan.json> --dry-run

# 战役级缺省路由（CLI 旗标；stage 声明在场时逐 stage 优先）
rfauto campaign run <plan> --remote sim_server --json
```

## 4. 发射门序（每个 remote stage 过一遍）

| 序 | 门 | 不过时行为 |
|---|---|---|
| 1 | 资源日历窗（维护窗判定） | blocked → **SKIP**，预检/通道不被触达 |
| 2 | license 预检（端口探活；席位 lmstat 查询登记 UNVERIFIED——端口 OPEN≠席位可用，G6 教训） | fail-closed → **SKIP**（不假射） |
| 3 | 执行通道（HFSS gRPC/ADS/openEMS 三通道单源复用 remote_service/remote_oe_service，零双实现） | 通道缺/SKIP → **SKIP**；通道 FAIL → 如实 FAIL |

SKIP 语义=无座位载荷/前置不满足的**如实声明**，不假绿也不假红
（信封三态见 docs/explanation/envelope-and-api-evolution.md）。

## 5. 产物与判读

- 每个 remote 座位目录落 `remote_stage.json`（全量信封）+ 座位级
  stage_result（瘦身记账键：`license_preflight`/`remote_exec`/
  `solve_success`/`batch`/`task_dir_remote`/`out_dir_local`…）；
- 服务器侧任务目录在注册表 `hfss.project_root` 指定的大容量数据盘
  （`<remote-workspace>\tasks\<batch>` 形态）——**服务器侧临时目录一律
  放数据盘，禁写生产云盘**；
- 断点续跑：`--resume` 重调同参（续跑语义由战役期刊承担）；
- 查询面：`rfauto remote queue` 看在途与排队，`rfauto campaign status`
  看战役视图（路由 SKIP=inconclusive→视图 pending）。

## 6. 任务毕清理（硬规则）

清理失败翻 FAIL，不许留孤儿：杀掉本次拉起的 `ansysedt`、删 schtasks
任务、清任务目录——走 `remote_hfss_cleanup`（remote_service 单源）。
发射前互斥预检（#261 每机互斥）命中他人在跑实例=候跑 SKIP，
**禁止代杀**别人的进程。

## 7. 边界与已知余项

- `recipe-loop` 远跑是拆批余件（未接线路由如实 SKIP）；
- `--detach` 后台执行 v1 如实 skipped 登记（未接线）；
- 全离线单测面：`tests/unit/test_campaign_remote_route.py`
  （#139：预检/通道/日历全 monkeypatch，零网络零真机）。
