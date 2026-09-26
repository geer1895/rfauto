# 如何读 verdict 门结果

**场景**：一次 run（或优化战役）结束后，你要回答"这份数据可信吗、
能不能采信/入库"。rfauto 的回答不靠肉眼看曲线，靠**预声明判据的
verdict 门**。本文讲怎么读、哪里找、UNKNOWN 怎么处理。

## 1. 单次 run：健康度体检（G11）

```bash
rfauto runs health <run_id>            # 表格 + verdict 行
rfauto runs health <run_id> --json     # 脚本/门禁消费原始 JSON
```

- **退出码即判据**：healthy=0；suspect/unhealthy/目录不存在=1——CI 和
  门禁脚本只看退出码；
- 每个检查项（factor）四列：检查项 / 状态（PASS·WARN·FAIL·UNKNOWN）/
  依据（判据出处，带历史教训编号如 #152 CFL 塌缩、#195 cost 退化、
  #174 激励体积死）/ 说明（实测数字对照阈值）；
- `verdict` 是 rollup：任一 FAIL → unhealthy；有 WARN → suspect；否则
  healthy。

**UNKNOWN 的语义**：证据不足、如实不判（fake run 没有场 dump 就不评
功率守恒）。它不是通过也不是失败——把 UNKNOWN 当 PASS 消费是错误用法；
判据面只在"两向独立已测"的数据上下结论，无对就 UNKNOWN，不凑绿也不
冒充 FAIL。

## 2. verdict 产物在 run 目录里长什么样

`service.league_service.read_verdict_artifacts(run_dir)`（CLI/
`rfauto runs compare --provenance` 同源）扫描 run 目录里的 verdict 类
产物并归一。判 run 真伪看 `meta.json` 的 `adapter`/`study` 字段：在跑
的 run 是"有 trials / 无 meta"（meta 结束才落盘）——别把半截目录当
废数据删了。

## 3. 对比两次 run

```bash
rfauto runs compare <run_id_a> <run_id_b>
```

逐指标 A/B/Δ 表 + 双方 cost。`--provenance` 输出可引用的复现块（环境
指纹）——对外报告引用实验时用这个，保证别人能对回同一环境。

## 4. 门的三条消费纪律

1. **预声明**：判据（阈值/口径/适用族）在真跑前写进判据书或 meta，跑完
   不改门——判 FAIL 是有效产出（它拦住了坏数据入库），事后改门才是
   事故；
2. **对齐响应形态**：窄带谐振器件的"带内 max"是常数陷阱，谷深语义用
   显式指标名（`s11_db_min`）；深谐振谷（−50dB 级）的 dB 域阈值本身就是
   误定口径，用线性域 |Γ| 或 εeff 锚；
3. **掩码先行**：单激励 Touchstone 是零填充部分矩阵，对称/互易补齐的
   元素必须随掩码流转；互易性判据只对两向独立已测的对下结论——5 列
   2 端口 csv 的"全 PASS"不构成互易证据。

## 5. 自己写门时

- 服务层 JSON 进出（`service/health_service.py` 是权威实现，薄壳只
  渲染）；
- 形状不符/非法掩码的兜底方向选"多报"不选"放过"——最多多一条 FAIL
  让人看，不要静默放进数据集；
- 数值合法为 0 的字段判缺失用 `is not None`，不要 `or 缺省`（0.0 是
  达标不是缺失）。
