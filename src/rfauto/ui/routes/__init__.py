"""rfauto UI 路由分域包（aurora_d UI-R1 席，自 ui/server.py 机械拆分）。

拆分纪律（家法 #98 era：AST 逐函数搬家）：函数体逐字节不变地搬家，业务
仍在 service 层（内核立规注记 #4/#90/#92）；本包内模块只做参数守卫（params.py
单源）+ service 调用 + 信封构造。域划分与端点清单见各模块 docstring：

- runs.py        run 清单/详情/双 run 对比/SSE 事件流/run 执行/报告图片
- recipes.py     配方视图/保存/清单、模型 3D 预览、文件浏览
- tune.py        调参（后台线程启动/状态/trials）
- agent.py       LLM 对话（会话单例）、沙箱草稿、审批收件箱、求解器注册表
- importer.py    HFSS 工程导入（.aedt → 设计规格 + 配方草稿）
- measurement.py 校准工作台/跨保真/S 参数/Smith 圆图/报告中心
- insight.py     优化洞察（Pareto/可行性）/执行看板/成本时间线
- fieldviz.py    远场极坐标页/场可视化页（nf2ff + DumpHDF5）
- data.py        数据集页/标定锚页/UQ 页
- tools.py       微波工具箱计算器/模板画廊/代理 Playground/剖析

装配面（route 表/CSP 中间件/Mount/启动）仍在 ui/server.py——本包不持有
Starlette 应用对象。
"""
