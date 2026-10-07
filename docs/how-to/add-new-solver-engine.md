# 接入一个新求解引擎（指引汇总）

> SO 走查 E3 断点收口：引擎接入的知识此前散在  坑条/适配器源码/
> 远程文档三处，本文汇成单一入口。骨架生成与契约细节见
> `docs/tutorials/extending-rfauto.md` 第 1、3 节（本文不重复）。

## 五步接入路径

1. **生成骨架**：`service/adapter_kit.scaffold_adapter("my_solver")`
   ——六方法占位（connect / is_available / build_geometry / solve /
   get_sparams / close）+ `param_semantics` 语义清单 + 注册入口，
   落盘前 compile() 自检，不覆盖既有文件。
2. **过契约门**：`check_adapter_contract(MySolverAdapter)` 单类检查；
   `check_known_adapters()` 全仓体检。非 EMSolver 契约的原生 API 通道
   （如 ADS）如实标注 `contract` 字段，不硬套六方法。
3. **同源通道注册**（战役外环）：`optimization/adapter_channels.
   register_channel("my_channel", factory)`——工厂吸收构造签名差异，
   惰性 import（工厂体内 import）防 sys.modules 钉死冲突。
4. **逐参数对语义**（#154）：同名几何参数跨适配器语义可能相反，
   接入即对照 `physics_roles`，单通道"看着对"跨保真就是两个器件家族。
5. **消费钉自证**：`docs/how-to/new-surface-checklist.md` 引擎节。

## 真机纪律（历史坑换来的，跳步必付学费）

- **版本配对**：远程/多机服务器侧版本必须=本机（PyAEDT gRPC
  客户端-服务端版本配对 + HFSS=对齐基准的数值可比性）；服务器仅需
  `ansysedt -grpcsrv` 监听。连通性冒烟：`rfauto remote probe/status`。
- **互斥**：本机 openEMS 是 python 进程内 FDTD（无独立 exe），互斥
  探测按命令行匹配而非进程名（#261）；新引擎的互斥标记必须自排除
  （含自身名会无限自等，#261 家族 G3）。
- **资源释放**：脚本 finally 必 release_desktop，否则留孤儿求解进程
  占许可/轨道（#265）；开工先查父进程已死的求解进程。
- **先离线审计再真跑**：渲染→exec 几何段→CSXCAD/HFSS 离线实测判据
  （#212）；HFSS 异常第一时间查官方文档而非调参。
- **服务器执行形态**：优先 console 可见/bat 直指，隐藏窗形态易被
  服务器杀毒静默击杀；发射后必须存活复核。
- **任务毕清理**：杀求解进程、删计划任务，中间文件只落约定目录
  。

## 注册表分工速记

| 注册表 | 值 | 层 |
|---|---|---|
| `EMSolverRegistry` | 类（六方法契约） | 适配器层 |
| `_CHANNEL_FACTORIES` | 工厂函数 | 战役层 |
| 模型插件（models/registry） | 模型插件类 | 配方模型层 |

## 参考

- 契约与骨架长版：`docs/tutorials/extending-rfauto.md`
- 远程接入与资源约束：`远程仿真资源说明`
- 官方口径集中页：`docs/rf_template_references.md`
