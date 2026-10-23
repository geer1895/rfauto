<!-- PR-10 文档站同步副本：源=docs/how-to/campaign-queue-and-notify.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 远程调度与通知：queue-daemon 队列、对冲监测、选机推荐、digest 摘要

**场景**：多战役过夜排队。`campaign queue-daemon` 常驻轮询 runs/ 下的
战役计划，逐项过依赖与资源检查后启动子进程；跑完用 `campaign digest`
把终态聚合成一条摘要，可推送到 webhook。本文写四项配置：计划间依赖
（depends_on）、停滞对冲（两个 env 键）、选机推荐（recommend）、摘要
推送（三个 env 键）。stage 级远程路由见
docs/how-to/campaign-remote-routing.md；机器登记见
docs/tutorials/remote_server.md。

## 1. 队列常驻：campaign queue-daemon

```bash
rfauto campaign queue-daemon --once    # 单步：跑一个 tick 就退出（cron 拉起）
rfauto campaign queue-daemon           # 常驻：默认 60 秒一个 tick
```

队列 = `--root`（默认 runs/）直属子目录里的 campaign.plan.json，与
`campaign list` 相同。每项记一个 item_id（计划绝对路径的指纹前 12 位，
跨重启稳定）；状态文件写入 `runs/campaign_queue/queue_state.json`，崩溃
重启后再跑一次命令即可续跑（按 item_id 幂等记账）。

UI 队列页逐战役显示两类信息：`queue_block` 是排队原因（单飞占用/
日历窗/license 预检/等依赖），`queue_hedge` 是停滞告警（第 3 节开启
后才有此字段）。

## 2. 计划间依赖：depends_on

campaign.plan.json 顶层可写 `depends_on`（数组，元素=前置战役的
item_id）：

```jsonc
{
  "model": "wilkinson",
  "stages": ["..."],
  "depends_on": ["1a2b3c4d5e6f"]
}
```

语义：

- 前置**全部到达终态**（COMPLETE/PARTIAL/ABORTED 任一）后，本计划才
  参与启动检查；
- **前置失败不拦下游**：前置 PARTIAL/ABORTED 也是终态，依赖方照常启动
  ——要不要跑由人决定，队列不替你跳过；
- **引用必须在本队列里**（同一个 `--root` 扫到的计划）。引用了不存在的
  id，该项的人读原因形如 `等依赖：<id>（不在当前队列）（已等 N 分钟）`，
  一直不启动；
- **等依赖不堵队**：依赖未满足的项让出队位，就绪的项照常启动；
- **环检测**：计划写入前可调 `validate_depends_on`（service 层纯函数）
  先行校验，报错形如 `depends_on 校验失败（…：依赖环 a → b → a（永不满足）…）`
  ；带环计划混进常驻队列时按阻塞处置，不拖垮其他项。

item_id 从哪来：

1. 队列跑过一次后查状态文件 `runs/campaign_queue/queue_state.json`，
   `items` 里 `item_id` 与 `plan_path` 成对出现；
2. 或按指纹规则现算——计划**绝对路径**经 normcase（Windows 大小写与
   分隔符归一）后取 sha1 前 12 位。现算命令的工作目录会影响 `abspath`
   结果，请在计划所在盘符路径下执行：

```bash
python -c "import hashlib, os; p=os.path.abspath('runs/tune_b/campaign.plan.json'); print(hashlib.sha1(os.path.normcase(p).encode('utf-8')).hexdigest()[:12])"
```

## 3. 停滞对冲（缺省关）

在途战役的进展证据 = campaign.plan.json 与 queue_daemon_launch.log 的
修改时间取较新者。两个都陈旧超过阈值即判停滞疑似：tick 日志记
`hedge_alert`，UI 队列页出现 `queue_hedge` 字段。配置走两个 env 键，
**都不设=完全不启用**（不探测、不告警）：

```bash
export RFAUTO_QUEUE_HEDGE_STALL_S=3600   # 告警阈值（秒）；未设/非法/<=0 都视为关
export RFAUTO_QUEUE_HEDGE_RELAUNCH=1     # 自动重发开关；1/true/yes/on 都算开
```

- 缺省只告警不重发。开启重发后每个战役至多重发一次，原进程**不被
  杀死**；若原进程仍持 run 锁，新实例会被拒（宁可拒绝新实例也不双跑，
  日志记 `hedge_relaunch_failed`）；
- 同因告警只记一次（不刷屏）；进展恢复自动清除告警（`hedge_recovered`）；
- 重发尝试即消耗名额（每项终身一次）：重发失败也算，再停滞只告警。

## 4. 选机推荐：remote resources 的 recommend 块

```bash
rfauto remote resources --json
```

JSON 输出里的 `recommend` 块给登记机器打一个可用性参考分（纯只读，不改变
任务去向）：

```jsonc
{
  "recommend": {
    "machine": "sim-host",
    "eligible": true,
    "score": 1.5,
    "max_parallel": 1,
    "n_tasks": 0,
    "reasons": ["+磁盘余量 350.0GB（+3.50）", "-HFSS 在跑进程 1（-2.0）"],
    "excluded_by": []
  }
}
```

排除条件（任一命中即 `eligible=false`，且不打分）：未登记机器、探活
不通、SSH 认证不通过、在跑任务数未知、在跑任务数已达 1（每机同时一个
任务）、磁盘余量已知且低于 20GB。打分公式：磁盘余量（GB）除以 100，
减去 openEMS 在跑进程数的 2 倍，再减去 HFSS 在跑进程数的 2 倍——分数
只用于同一批登记机器之间比较。

## 5. digest 摘要与 webhook 推送

```bash
rfauto campaign digest --since-h 24   # 只统计计划文件近 24 小时内有更新的战役
rfauto campaign digest --no-write     # 只打印不写入文件
```

产物写入 `runs/campaign_digest/digest_<时间戳>.json` 与同名 .txt。推送
走 env 配置，**两键都不设=不发起任何请求**：

```bash
export RFAUTO_NOTIFY_WEBHOOK_URL="https://example.com/hook/your-token"
# 通用通道：POST {"text": 摘要}
export RFAUTO_NOTIFY_FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
# 飞书自定义机器人：POST {"msg_type":"text","content":{"text":摘要}}
export RFAUTO_NOTIFY_TIMEOUT_S=10   # 可选，默认 10 秒；非法或 <=0 回默认
```

`--notify/--no-notify` 三态：不带开关=读 env 配置决定；`--notify`=
配置了就推；`--no-notify`=这一次不推。推送正文只含白名单聚合字段
（战役名/模型/终态/阶段进度），计划路径与失败原因原文不进 payload；
推送失败不影响本地摘要产物，结果看返回 JSON 的 `notify` 字段。

## 6. 排障速查

| 现象 | 先看哪里 |
|---|---|
| 战役一直排队 | UI 队列页 `queue_block`；或状态文件 `items.<id>.blocked` |
| 疑似卡死 | `queue_hedge` 字段（第 3 节开启后才有） |
| 没收到推送 | 返回 JSON 的 `notify` 字段；两个 env 键是否都未设（都未设=不推） |
| 依赖的 item_id 对不上 | 计划被移动或改名会换指纹（item_id 含绝对路径） |
