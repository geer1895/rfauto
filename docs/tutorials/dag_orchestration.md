# DAG 战役编排：断点续跑、互斥与失败语义

> `rfauto campaign`（docs/tutorials/campaign-walkthrough.md）回答"战役
> 推进到哪个阶段了"；本文讲它脚下的**执行基座**：`rfauto dag` 把一张
> 节点计划变成可断点续跑、跨 run 缓存、机器互斥、失败语义可声明的确定
> 性执行。多节点流水线（渲染→求解→后处理→判读）、被杀后重启不重算、
> 失败只重算下游——这些都内建在基座里，不用自己写 shell 粘合。本文全部
> 命令实测过（退出码 0/1 如实标注），演示计划零真机零网络。前置：
> docs/tutorials/campaign-walkthrough.md（战役状态机）、
> docs/tutorials/getting-started.md。
> 英文版（English version）：docs/tutorials/dag_orchestration_en.md。

## 1. 两层编排面：状态机与执行基座

```
campaign plan/run（状态机面）     docs/tutorials/campaign-walkthrough.md
        │  五阶段→节点映射（STAGE_KIND_MAP 确定性表）
        ▼
dag run（执行基座面）             pipeline/dag_runner.py（本文）
        ├─ 断点续跑：逐节点键重算，键同即跳过
        ├─ 跨 run CAS：产物内容寻址，字节级不变零重算
        ├─ #261 机器互斥：solve 节点派发前过机器锁
        └─ 失败语义：abort/continue/skip + inconclusive 三态
```

分工：campaign 管"战役语义"（阶段依赖/预算/license 门槛/verdict 状态机），
dag 管"执行语义"（每秒都在发生的事：键计算、重试阶梯、锁、期刊）。计划
schema（`rfauto-dag-v1`）的权威定义在 `core/compose/dag_schema.py`，规格
在 docs/plan_deepdive_specs_20260924.md §DP-9。

## 2. 计划形态：一张 rfauto-dag-v1 计划

节点只有四种 `kind`：`render | solve | postprocess | judge`（执行基座对
solve 类节点强制 #261 机器互斥）。最小计划=三个文件写入节点（演示用，
零真机）——存为 `runs/demo/dag_tutorial/plan.json`：

```json
{
  "nodes": [
    {
      "node_id": "render",
      "kind": "render",
      "inputs": {"params": {"w_mm": 0.987}},
      "cmd": "python -c \"open('w.txt','w',encoding='utf-8').write('0.987')\"",
      "outputs": ["w.txt"],
      "budget": {"timeout_s": 60},
      "retries": 1
    },
    {
      "node_id": "solve",
      "kind": "solve",
      "depends_on": ["render"],
      "inputs": {"params": {"mock_s11_db": -42.5}},
      "cmd": "python -c \"open('sparams.txt','w',encoding='utf-8').write('f0 S11 -42.5dB')\"",
      "outputs": ["sparams.txt"],
      "budget": {"timeout_s": 120},
      "retries": 1
    },
    {
      "node_id": "judge",
      "kind": "judge",
      "depends_on": ["solve"],
      "inputs": {"params": {"gate_db": -40.0}},
      "cmd": "python -c \"open('verdict.txt','w',encoding='utf-8').write('PASS')\"",
      "outputs": ["verdict.txt"],
      "budget": {"timeout_s": 60},
      "retries": 0
    }
  ]
}
```

字段读法：`inputs.params` 进**节点键**（改它=宣告"我要重算"）；`cmd` 是
声明性命令串（v1 内建 subprocess 执行器直接 argv 执行，不走 shell——
Windows 反斜杠路径安全，#142 家法）；`outputs` 是产物契约（相对节点工作
目录，缺失按声明判据处置，见 §5）；`budget.timeout_s` 是看门狗预算。
每个节点有独立工作目录 `<run-dir>/<node_id>/`，产物互不覆盖。数据在节点
间靠产物路径约定传递（上游写文件、下游读文件），基座不管数据搬运。

## 3. 动手：执行、期刊与断点续跑

```bash
rfauto dag run runs/demo/dag_tutorial/plan.json \
    --run-dir runs/demo/dag_tutorial/run \
    --solve-lock runs/demo/dag_tutorial/run/.solve.lock
```

实测输出：

```
✓ DAG 完成  verdict=COMPLETE  hit=0  recompute=3
  done         render
  done         solve
  done         judge
  期刊: runs\aurora_d\tut\dag_demo_run\dag.state.json
```

`--solve-lock` 显式指定互斥锁路径（缺省=runs 家族锁 `runs/.oe_collect.lock`
——真机上"同一台机器同时只跑一个求解"的语义）；演示里指到自己 run 目录，
避免与真机采集互锁。

**再跑一遍同一命令**（断点续跑就是"重跑同一命令"）：

```
✓ DAG 完成  verdict=COMPLETE  hit=3  recompute=0
```

三个节点全部 **hit**（键同+产物校验过=直接跳过）——被杀/中断后重启的
代价只是"还没跑完的节点"。期刊是唯一事实源，随时读：

```bash
rfauto dag status runs/demo/dag_tutorial/run
```

实测输出：

```
runs/demo/dag_tutorial/run  verdict=COMPLETE  hit=3  recompute=3
             DAG 节点态摘要（dag.state.json）
┌─────────┬────────┬──────────────┬─────────────┬────────┐
│ node_id │ status │ key          │ outputs     │ source │
├─────────┼────────┼──────────────┼─────────────┼────────┤
│ judge   │ done   │ 1c77b7e2090e │ verdict.txt │        │
│ render  │ done   │ c3abec0ab230 │ w.txt       │        │
│ solve   │ done   │ 280bf132213d │ sparams.txt │        │
└─────────┴────────┴──────────────┴─────────────┴────────┘
```

## 4. 键传导：改一处，只重算受影响的链

把 `render` 的 `w_mm` 改成 `1.202`（存为 `dag_demo_plan_v2.json`）再跑
（同一 `--run-dir`）：

```
✓ DAG 完成  verdict=COMPLETE  hit=0  recompute=3
```

**上游键进下游键载荷**——render 的参数变了，它的键变，solve/judge 的键
跟着变，全链递归重算。这就是"断点续跑"的精确语义：**不是从头跑，也不
是傻跑，是按键重算**。

跨 run 还有一层**零拷贝缓存（CAS）**：换一个全新的 `--run-dir` 首跑同一
计划（此前的产物一张不复制过来），实测：

```
✓ DAG 完成  verdict=COMPLETE  hit=2  recompute=1
```

期刊里 render/solve 的 `source=cache`——产物内容寻址命中，直接**引用**
上一个 run 的工作目录（零拷贝），只有 judge 重算（后处理/judge 节点的键
还折叠上游产物的落点路径与内容 digest——落点换了就重新校验重建，保守
方向：宁可重算，不误命中）。

## 5. 失败语义：abort / continue / inconclusive

节点失败（执行族）与证据不可判（判定族）是**两族，分别记录不混淆**
（#225 纪律）。用一个必失败节点演示三种下游处置——`boom` 节点
`raise SystemExit(3)`：

**缺省 `failure_policy=abort`**：下游递归标 aborted，run 判死。

```
✗ DAG 执行失败
  - DAG 执行未完成: verdict=ABORTED      （退出码 1）
```

期刊里 `boom=failed`、`after_boom=aborted`。

**`failure_policy=continue`**（加在 boom 节点上——语义是"我失败后下游
照常执行"）：下游照跑，期刊注记自动归因：

```
after_boom done | notes: ['上游 boom failed 但 failure_policy=continue（按策略继续执行；本节点失败时归因策略而非上游）']
boom failed | notes: ['attempt0: executor 失败: rc=3']
```

注意 run 级 verdict 仍是 `ABORTED`、退出码仍 1——**continue 不掩盖失败**，
只是不让失败传染下游。

**`inconclusive_when`（判定族）**：节点"跑完了但证据不可判"。声明
`"inconclusive_when": {"message_contains": "UNDECIDABLE"}`，节点执行成功
且消息命中 → `inconclusive`（不是 failed）：

```
✓ DAG 完成  verdict=PARTIAL  hit=0  recompute=1
  inconclusive gate
期刊注记: inconclusive_when.message_contains 命中（'UNDECIDABLE'）→ 节点态
inconclusive（跑完但证据不可判；产物留盘不写 manifest/不入索引）
```

读法：inconclusive 节点**产物留盘供人工检视、不入 CAS 索引（不采信为可
复用产物）、不判死下游**；续跑会给它再一次判定的机会。run 级无失败但
有 inconclusive → verdict=PARTIAL（COMPLETE 要求全部 done）。另一条声明
途径 `outputs_missing_any`：声明产物重试穷尽后仍缺且全部是声明的"软产物"
→ inconclusive 而非 failed——缺的是硬产物（未声明软）照旧 failed。

## 6. 看门狗与互斥：真机节点的两条安全带

- **看门狗**：`budget.timeout_s` 到点 → 整树终止（Windows `taskkill /T`，
  #157 家法：防引擎孙进程孤儿占锁）→ **判废重试**，按 `escalation` 阶梯
  逐级加资源（缺省 `[{budget_x:1.5}, {mesh_tier:next}]`=#145 Abort 语义）。
  竞态完成（到点后才交付）接受真结果不丢数据；超预算（wall > 1.5×timeout）
  PARTIAL 入库不删数据。
- **#261 机器互斥**：`kind=solve` 的节点派发前必须拿到机器锁——本仓
  openEMS 是 python 进程内 FDTD，`tasklist|findstr openEMS` 对它无效，
  互斥按锁文件实现（缺省 `runs/.oe_collect.lock` 家族）。同机多轨/多机
  协同时这是防"两个求解互相拖慢 3-8×"的硬闸（#246 实证）。run 实例本身
  也有单例锁（同 run-dir 二次 `dag run` 占即拒，`--lock-wait-s` 控等待）。

## 7. 上层编排：campaign run 与排队常驻

- `rfauto campaign run <plan.json>`：战役五阶段（plan 产物）自动映射成
  节点链交给本基座执行，阶段完成即推进状态机（战役面见
  docs/tutorials/campaign-walkthrough.md，本文不重复）；
- `rfauto campaign queue-daemon`：排队常驻执行体（轮询队列→日历窗→
  license 预检→逐项发射，发射后不等）——overnight 战役队列的挂法；
- 远程路由（哪台机器跑 solve）：多机通道面见
  docs/tutorials/remote_server.md（`rfauto remote probe/status`、远跑
  三通道、任务毕清理），本篇不展开；
- MCP/agent 编排：DAG 两叶刻意未加进 MCP（CLI 先行）——agent 侧编排
  走 `run_campaign` 即可，零数值面是基座铁律（数值只出确定性内核）。

## 纪律速查

- 键语义：`inputs.params` 与上游产物键进节点键——**想重算就改声明面，
  不要手删工作目录**；
- 期刊（dag.state.json）是唯一事实源，重启重放/判读都以它为准；
- 失败（执行族）≠ inconclusive（判定族）≠ skipped（策略族）：三态分别
  记录，verdict 消费面不引入新态；
- solve 节点必过 #261 互斥；同机并发求解是性能坑不是功能（#246）；
- 长跑真机节点：后台分离+日志轮询+watchdog 超时给足（AGENTS #157）。

## 下一步

- 战役状态机与五阶段推进：docs/tutorials/campaign-walkthrough.md
- 多机协同与远跑通道：docs/tutorials/remote_server.md
- 判读节点的 verdict 语义：docs/tutorials/verdict_semantics.md
