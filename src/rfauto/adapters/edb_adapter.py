"""PyEDB 适配器（EDB 快车道底座）——平面器件族经 EDB 建模 + hfss_batch 批处理求解。

定位（2026-10-08，Ansys 团队成员建议口径）：平面设计走 PyEDB——EDB（Ansys
Electronics Desktop 分层版图数据库）独立内存态 API 无需桌面会话；声明式版图
规格（``spec`` dict）经 :func:`spec_to_config_json` 翻成 pyedb
``configuration.load`` 兼容 dict/JSON 并落盘存证，再注入 Edb 内存库生成
``.aedb`` 工程；批处理求解经 ``rfauto.adapters.hfss_batch.solve_project_batch``
（AEDT 命令行批处理，他席通道——未落地时显式报错，不静默不臆造）。

分层纪律：本模块属 adapters 层（cli/mcp_server → service → linkage/... →
adapters → pipeline → infra → core），向下依赖合法；v1 仅依赖 stdlib
（pyedb / hfss_batch 均为函数内惰性 import），不 import service/cli
（import-linter 语义自查通过）。本模块**不注册**进 EMSolverRegistry
（独立协议通道：``workdir`` 构造、非 EMSolverAdapter 契约，同
hfss_session 工具层口径），能力声明见 em_solver_base 尾部 "edb" 字符串键条目。

单位纪律（硬规则 3，spec 内长度单位固定 **毫米**）
------------------------------------------------
进 pyedb 的换算口径（以 pyedb 0.83.0 官方文档/源码注释为准，出处逐条标注）：
- 路径/坐标数字：官方文档口径 trace path 点为**米**
  (``pyedb/configuration/cfg_modeler.py::CfgTrace.add_trace`` docstring
  "Ordered list of absolute [x, y] waypoints in metres"）→ mm×1e-3；
- 宽度/厚度/孔径：``CfgTrace.add_trace`` docstring 口径接受带单位字符串
  （``"0.1mm"``/``"100um"``）→ 数值按 ``%.10g`` 拼带单位字符串透传（2026-10-08
  契约统一：与 edb_templates.schema.assemble_config 的 _fmt_mm/_fmt_ghz
  同式同精度——同一 spec 双路径产出的 config 字符串逐位一致；10 位有效
  数字在 mm 尺度=亚纳米，远低于版图几何精度）；
- 频率：``CfgFrequencies`` start/stop 接受 ``"1GHz"`` 形字符串（官方
  docstring 示例口径）→ GHz 数值按 ``%.10g`` 拼 ``"GHz"`` 字符串透传（规避
  setup 内部频率缺省单位为 Hz 的歧义）；sweep 步进同口径带单位；
- 过孔位置/端口/平面原语坐标数字：与 trace path 同一 EDB 数据库单位口径
  按米换算（pyedb 未逐处文档化，按官方可文档化处同构标注**假设**——真机
  首跑时以 port 落点复核，若引擎口径不一致在此一处修正）。

诚实边界（#122 如实）
--------------------
- 本适配器只做"建库 + 发求解请求"两件事：S 参数回收/判读归 hfss_batch
  通道与上游管线，本模块不解析仿真输出（get_sparams 类语义不存在）；
- ``material`` 仅传引用名时依赖 pyedb 默认材料库（copper/FR4_epoxy 等
  出厂内置）；自定义 er/tanD 必须走 ``material_props`` 显式定义，或在
  ``stackup.materials`` 显式材料段定义（发射族口径，2026-10-08 契约统一）；
- v1 信号层不支持自定义材料定义（material_props 仅限介质层）——给出即
  fail-fast 报错（不虚报）；
- wave_port（发射族端口）阻抗在 pyedb ``CfgEdgePort``
  set_parameters_to_edb 里**硬编码 50Ω**（0.83 实测，docs/pyedb_distilled.md
  §3.3/§7-A2——configuration 通道无法给 wave_port 设其他阻抗）→ spec 给出
  非 50 阻抗即 fail-fast（不静默错配）；
- ``resistors`` 落地走 pyedb 0.83.0 自家纯电阻处方（SourceType.Rlc 分支，
  dotnet/database/source_excitations.py:898-908）：点端子对 + RlcBoundary，
  **不产生金属电阻体**（几何间隙保持开路，防短路）；``width_mm`` 仅作
  发射面几何声明存证，不进引擎几何（集总边界无宽度参数）；电阻若不与
  版图金属（trace/via 端点）重合，端子悬空属 spec 几何错误——由上游
  edb_templates.validate_spec 端点附着审计负责，本层不重复仲裁。

3D Layout setup 自适应档写入通道（W8 仲裁建议 2，2026-10-09；#333 族旋钮
效力；W10 定谳更名——原题「真收紧通道」的"真"字被 W10 真机证伪）
------------------------------------------------
EDB/HFSS 3D Layout 工程的自适应档（``max_delta``/``max_passes``）的
**建模期写入通道**：``spec.sim_setup.adapt`` → config
``setups[0].single_frequency_adaptive_solution`` →
``configuration.load(apply_file=True)`` 随建库一次性落 setup——发射器
改档即随建库写入**请求档**。

**W10 定谳（真机战役判读报告，2026-10-09）：EDB
3D Layout 路径 MaxDelta 写入不可达**。EDB 3D Layout schema（SimSetupID=19）
无 MaxDelta 键——四互证维持（AEDT 2025.1 SolveSetups 模块无 EditSetup/
InsertSetup 无任何 Delta 键名/configuration.load 的 AdaptiveSettings 子树
被丢弃/两代工程盘面均无 MaxDelta 键），``configuration.load`` 通道与
pyaedt props 通道同样写不进；spec 硬断言只能行使到**发射面**（config
存证带请求值，求解器永不消费）。EDB 侧唯一可达收紧通道=扁平键
``MinConvergedPasses``（类路径 InsertSetup 写入，W9 mc2=2 与 W10=4 两
真机点均被求解器实消费）；EDB 侧档位伪象实测仅 ~0.62dB（W8 §3 的 ~2dB
系 HFSS 侧阶梯分解，不按面值转移 EDB），剩余 ~1.0dB 偏置=EDB-Layout 特
有建模保真差（判读面校准项，非求解旋钮可及）。**判读纪律：本通道 EDB
S31 读数不得按 max_delta 请求档归因**（W9 勘误先声，W10 定谳坐实）。

W9 勘误存档（同日真机重查）："写入即生效"
此前只在单测面验证（请求值达 configuration.load 调用——假 pyedb 替身）；
props 建库期写入 MaxDelta=0.005（会话内读回确认）批解仍按 0.02 准则停机
（verdict=TIGHTENING_NOT_EFFECTIVE）——该形态后被 W10 定谳收编为"schema
无键"的总因（props 会话内读回属会话态，不落盘不传播）。

**求解后改档不可达（W8 真机实证）——改档须重建**：对已解 3D Layout
工程重开会话后经 pyaedt ``setup.props`` 改档**不传播**——重载 props
顶层无 ``AdaptiveSettings`` 子树（新建会话才有），子树重建写入+
``update()``+save 后批解仍**逐位回放缓存解**（S31 十位小数同值
-9.4569、批解 wall 26s vs 原档 ~52s；W8 仲裁档
§2 V3 / §5-2）。因此任何"收紧判读档"需求一律改 spec
重走 :meth:`EdbAdapter.build`（新 .aedb），禁止对已建工程做求解后改档。
（W10 定谳边界：对 **EDB 路径的 max_delta**，重建也不落库——schema 无键，
见上文定谳段；本段"改档须重建"是通用纪律——HFSS 3D 侧通道与一切求解后
修改面均适用，且是 W10 之前唯一已证通道。）

配套写入一致断言（#333 族；**断言面=存储请求档，非求解效力**）：
:meth:`EdbAdapter.verify_adapt_tightening` 在批解后重开工程读回 setup
实际 max_delta（pyedb ``edb.setups[name].adaptive_settings.
adaptive_frequency_data_list`` 只读面，0.83 源码核验：
dotnet/edb.py:3221 + dotnet/database/utilities/
hfss_simulation_setup.py:176 + dotnet/database/sim_setup_data/data/
settings.py:52 + dotnet/database/sim_setup_data/data/
adaptive_frequency_data.py:24/46），与 config 存证（请求档）逐 setup
核对——不一致/不可核对=告警字符串（best-effort，#105：断言故障不阻塞
判读主路径；不可证实如实告警，#122 不冒充）。**存储档一致≠求解按档
收敛**（W9 重查实证"写入不传播"形态存在，此时读回仍可与请求一致）——
求解效力须另做新解 vs 旧解读数/mtime 差异对比（W8 建议 2 原文口径）。
W10 定谳补注：``configuration.load`` 通道的请求可能**根本不落库**
（EDB 3D Layout schema 无 MaxDelta 键）——此形态本断言如实告警（"请求
档未落库"类）；而"已落库但求解不消费"形态（W9 props 会话内读回）本
断言**原理上不可检出**——这正是断言面=存储面的语义边界。

spec dict 完整 schema（v1 统一契约，2026-10-08 与 edb_templates 发射器实测
产出对齐——正本=emit_branchline_spec/emit_power_divider_spec 实跑样例；
两形态并存按段判别：发射族形态（wave_port 端口 / board 段 / f0_ghz·sweep·
adapt setup / stackup.materials 显式材料）与通用形态（circuit·coax 端口 /
shorthand·sweeps setup / material_props 派生材料），同 spec 可混用；
未知键一律 fail-fast——防 #154 同名参数跨通道语义漂移。契约测试
tests/unit/test_edb_adapter.py::TestEmitterSpecContract 钉「发射样例 →
本函数零错且与发射器 assemble_config 逐键一致」）
----------------------------------------------------------------
::

    {
      "name": str            可选（缺省 "edb_layout"）：产物文件名主干，
                             禁路径分隔符与 ".."
      ── 元段（发射器记账面：校验后跳过，零 config 产出）──
      "template": str        可选，非空字符串（族白名单仲裁在发射器层
                             KNOWN_TEMPLATES，本层不复制名单——防两处名单漂移）
      "schema_version": int  可选，给出时必须=1（未知版本 fail-fast 不静默
                             消费；与 edb_templates.schema.SPEC_SCHEMA_VERSION
                             对齐，不 import 防依赖环，本模块硬编码同值）
      "units": {...}         可选，给出时必须 {"length": "mm", "frequency":
                             "GHz"}（本适配器 mm→米换算硬编码，其他单位声明
                             =错配隐患，fail-fast）
      "params": {...}        可选 dict：发射器设计读数面板（综合链出处等），
                             跳过
      "stackup": {           必填
        "materials": [       可选：显式材料定义直通 config stackup.materials
          {"name": str 必填， （发射族契约：铜 conductivity + 介质
           <属性键>: 数值}... permittivity/dielectric_loss_tangent 显式成文；
                             介质层只给 material 引用名、缺省库无此名时必须
                             靠本段定义）。属性键白名单=pyedb CfgMaterial
                             标量键：conductivity/permittivity/
                             dielectric_loss_tangent/magnetic_loss_tangent/
                             permeability/mass_density/poisson_ratio/
                             specific_heat/thermal_conductivity/
                             youngs_modulus/thermal_expansion_coefficient
                             （docs/pyedb_distilled.md §2）；未知键 fail-fast；
                             与层 material_props 派生材料同名冲突 fail-fast]
        "layers": [          必填，≥1；spec 层序自底向上（index0=物理底层）；
                             config 落库翻转一次为自顶向下——pyedb 0.83
                             __create_stackup 按列表序逐层 AddLayerBottom
                             （每次插到全栈最底→列表首项落物理顶层；
                             configuration.py:863-868 + dotnet/database/
                             stackup.py:97-130 源码实证；官方示例
                             TOP,DE,BOTTOM 首项=顶层同口径；
                             docs/pyedb_distilled.md §3.1/§6-2 处方
                             「adapter 翻转一次」；真机冒烟
                             以 GND=elevation0
                             验证的物理序=信号层在上）
          {"name": str       必填，全表唯一，
           "type": str       必填，"signal" | "dielectric"，
           "thickness_mm": number 必填，>0，
           "material": str   可选；signal 缺省 "copper"（pyedb 默认库），
           "material_props": {可选；仅 dielectric 可给（与 material 互斥），
             "er": number    必填，>0，
             "tan_d": number 可选，≥0，缺省 0.0，
             "name": str     可选，缺省 f"{层名}_material"，全表唯一}}
        ]
      },
      "traces": [            可选
        {"name": str         可选（缺省 "trace_{i}"，全表唯一），
         "layer": str        必填，须为 stackup 中 signal 层名，
         "width_mm": number  必填，>0，
         "path_mm": [[x,y],...] 必填，≥2 个 [x, y] 毫米点，
         "net": str          可选（缺省 ""），
         "role" 等发射侧声明键：容忍透传忽略}
        config 面统一 cap=flat / corner=sharp（发射器契约假设 4：wave_port
        与电阻端子落走线端点，要求足迹=精确矩形、端点=矩形边缘；pyedb
        缺省 round 圆头会在端点短 r/2，docs/pyedb_distilled.md §3.2）],
      "vias": [              可选
        {"name": str         可选（缺省 "via_{i}"，全表唯一），
         "diameter_mm": number 必填，>0（同孔径共享 padstack 定义），
         "x_mm": number      必填，"y_mm": number 必填，
       "start_layer": str  必填，须在 stackup 层名内，
       "stop_layer": str   必填，同上；两层须恰为最顶+最底信号层（v1 仅
                           整叠通孔：pyedb CfgPadstackDefinition.hole_range
                           本层未透传、缺省 through 语义，盲埋孔 spec 会
                           静默错落——给出即 fail-fast 不虚报），
         "net": str          可选（缺省 ""）}
      ],
      "resistors": [         可选（集总电阻，键名与 edb_templates 功分器发射
                             契约逐字对齐）
        {"name": str         可选（缺省 "resistor_{i}"，电阻表内唯一），
         "layer": str        必填，须为 stackup 中 signal 层名，
         "net": str          必填非空（RLC 端子须挂版图既有 net），
         "r_ohm": number     必填，>0（纯电阻：L/C 恒关断），
         "width_mm": number  必填，>0（发射面几何声明存证；点端子落地不产生
                             金属体——防间隙短路，宽度不进引擎几何），
         "path_mm": [[x,y],[x,y]] 必填，≥2 点（毫米；首点=正端子、末点=参考
                             端子），
         "role": str         可选（发射侧元数据，透传忽略）}
      ],
      "ports": [             可选；两形态按 "type" 判别：
        {"type": "wave_port" ── 发射族形态（make_wave_port 契约 → CfgEdgePort）
         "name": str         必填非空，
         "port_nr": int      必填 ≥1，全表唯一（与 circuit "number" 同池查重），
         "trace": str        必填，须为 traces 表内既有走线名（CfgEdgePort
                             落库按名取图元，引用不存在走线 fail-fast），
         "point_mm": [x,y]   必填（毫米；语义=该走线端点，端点附着几何审计
                             在 edb_templates.validate_spec，本层不重复仲裁），
         "impedance": number 可选，缺省 50；给出时必须=50（pyedb CfgEdgePort
                             通道硬编码 50Ω，非 50 fail-fast 不静默错配），
         "horizontal_extent_factor": int 可选 ≥1，缺省 5（透传），
         "vertical_extent_factor": int   可选 ≥1，缺省 3（透传）}
        {"number": int       通用形态（circuit|coax，正负终端电路端口，原契约
         "start"/"end" 终端  不变）：端口号 ≥1 唯一；终端={"layer","point_mm",
         "layer"/"net"/"name" "net"} 或 [x,y] 简写（端口级 layer/net 作缺省）；
         "impedance_ohm"/    impedance_ohm >0 缺省 50；name 缺省 f"p{number}"}
         "type": "circuit"|"coax"}
      ],
      "board": {             可选（发射族版图边界）：给出时→
        "lower_left_mm": [x,y] 必填，  ① config modeler.planes 一条整版矩形
        "upper_right_mm": [x,y] 必填， 平面原语（name="GND_plane"、net="GND"、
                                       落 stackup.layers[0]=地板载体层（须
                                       signal 层）、角点坐标 mm→米）——与
                                       edb_templates assemble_config 逐键
                                       同款；② config boundaries 开放域辐
                                       射边界（use_open_region=True/radiation，
                                       wave_port·HFSS 求解的辐射条件）。
                                       角点须 x1>x0、y1>y0；未知键 fail-fast}
      "sim_setup": {         可选（缺省不生成 setup）；两形态互斥键同给 fail-fast：
        发射族形态：
          "f0_ghz": number   >0（单频自适应频点；仅 type=hfss），
          "sweep": {         发射族扫频 dict（单段 linear_count）：
            "name": str      可选（缺省 "sweep1"），
            "type": str      可选 "interpolation"|"discrete"（缺省 interpolation，
                             setup 级 sweep_type 作二级缺省），
            "start_ghz"/"stop_ghz": number 必填 >0 且 stop≥start，
            "points": int    可选 ≥2，缺省 401}，
          "adapt": {         发射族自适应 dict（仅 type=hfss）：
            "max_passes": int 可选 ≥1，缺省 20，
            "max_delta": number 可选 >0，缺省 0.02}，
        通用形态（原契约不变）：
          "name": str        可选（缺省 "hfss_setup_1"；发射器 assemble_config
                             侧字面 "setup1"——纯命名差异，pyedb 语义零影响，
                             契约测试按此单键豁免对齐），
          "type": str        可选，"hfss"|"siwave_ac"，缺省 "hfss"，
          "sweep_type": str  可选，"interpolation"|"discrete"，缺省
                             "interpolation"，
          "f_start_ghz": number 简写三件套（与 sweeps 二选一）：>0，
          "f_stop_ghz": number  >0 且 ≥ f_start_ghz，
          "points": int      ≥2，缺省 401（linear_count 单段），
          "sweeps": [        可选，显式段列表（给出时覆盖简写三件套），
            {"type": str     必填："linear_count"|"linear_step"|
                             "log_count"|"log_step"|"single"，
             "start_ghz"/"stop_ghz"/"count"/"step_ghz"/"freq_ghz"
                             按 type 组合必填（见 _SWEEP_FIELDS），
             "name": str     可选（缺省 "sweep_{i}"）}
          ],
          "adaptive_freq_ghz": number 可选（仅 hfss；缺省 5.0，pyedb 官方缺省），
          "max_passes": int  可选（仅 hfss；≥1，缺省 20），
          "max_delta_s": number 可选（仅 hfss；>0，缺省 0.02）}
    }
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 注意：本模块**不定义 __all__**——公开 API 快照（scripts/check_public_api）
# 只登记带 __all__ 的模块，无 __all__ 文件记私有零快照变化（新模块出生
# 不触发 --generate 评审动作）。

#: AEDT 版本缺省钉（版本对齐纪律：本机 HFSS/AEDT 2025 R1（v251）为对齐
#: 基准；PyAEDT/pyedb 版本串口径 2025 R1 → "2025.1"）。env 可覆盖
#: （远程/异版本机联调），换机部署须与服务器侧版本对齐纪律同步。
_DEFAULT_AEDT_VERSION = "2025.1"
_AEDT_VERSION_ENV = "RFAUTO_EDB_AEDT_VERSION"

#: pyedb DotNet 通道 Ansys OpenSSL **预载 feature-flag**（#373 回归实验，
#: 2026-10-14；处方：import pyedb 前
#: ctypes.WinDLL 绝对路径预载 AnsysEM 的 libcrypto/libssl-3-x64.dll）。
#: env ``RFAUTO_PYEDB_PRELOAD``（1/true/yes/on 大小写不敏感）或构造参数
#: ``enable_preload`` 显式开启；**缺省关闭=零行为变化**（不触预载路径）。
#: 显式参数优先于 env（三态：None=读 env）；开启后预载 fail-soft
#: （pyedb_preload 信封 ok=False 不阻断——后续 import pyedb 自会暴露真实
#: 问题，#105 观测面不阻塞主路径）。
_PYEDB_PRELOAD_ENV = "RFAUTO_PYEDB_PRELOAD"
_PYEDB_PRELOAD_TRUTHY = frozenset({"1", "true", "yes", "on"})

#: 毫米 → 米（pyedb configuration 官方文档口径：path 点单位为米，见模块
#: docstring「单位纪律」节出处标注）
_MM_TO_M = 1e-3

#: 合法层类型（CfgLayer.layer_type 词表：signal/dielectric）
_LAYER_TYPES = ("signal", "dielectric")

#: 合法端口类型（CfgPort.CFG_PORT_TYPE 词表）
_PORT_TYPES = ("circuit", "coax")

#: 合法 setup 类型（CfgSetups.create 分派词表）
_SETUP_TYPES = ("hfss", "siwave_ac")

#: 合法 sweep 形态（spec 词表；CfgFrequencies docstring 写 "linear_step/
#: log_step" 但真 literal 是 FrequencyDistribution=linear_scale/log_scale/
#: single/linear_count/log_count——docstring 与实现失真按实现口径，2026-10-08
#: 真 CfgData 校验实测抓出）
_SWEEP_TYPES = ("linear_count", "linear_step", "log_count", "log_step", "single")

#: spec sweep 形态 → pyedb distribution literal（见 _SWEEP_TYPES 注）
_SWEEP_DISTRIBUTION: dict[str, str] = {
    "linear_count": "linear_count",
    "linear_step": "linear_scale",
    "log_count": "log_count",
    "log_step": "log_scale",
    "single": "single",
}

#: sweep 形态 → 必填 spec 键（缺键/多键 fail-fast；#154 同名参数语义纪律）
_SWEEP_FIELDS: dict[str, tuple[str, ...]] = {
    "linear_count": ("start_ghz", "stop_ghz", "count"),
    "linear_step": ("start_ghz", "stop_ghz", "step_ghz"),
    "log_count": ("start_ghz", "stop_ghz", "count"),
    "log_step": ("start_ghz", "stop_ghz", "step_ghz"),
    "single": ("freq_ghz",),
}

#: spec 顶层合法键（未知键 fail-fast——防 #154 同名参数跨通道语义漂移）。
#: 2026-10-08 契约统一：template/schema_version/units/params=发射器元段
#: （校验后跳过零产出），board=发射族版图边界（→planes+boundaries）。
_SPEC_KEYS = ("name", "template", "schema_version", "units", "params",
              "stackup", "traces", "vias", "resistors", "ports", "board",
              "sim_setup")

#: 支持的 spec schema 版本（=edb_templates.schema.SPEC_SCHEMA_VERSION；不
#: import 防依赖环——发射器包与适配器是平级消费关系，版本对齐由契约测试
#: tests/unit/test_edb_adapter.py 钉住；未知版本 fail-fast 不静默消费）
_SUPPORTED_SCHEMA_VERSION = 1

#: 显式材料属性键白名单（pyedb CfgMaterial 标量键，docs/pyedb_distilled.md
#: §2 逐键核验口径；频变/列表型键不在 v1 面内——未知键 fail-fast）
_MATERIAL_KEYS = (
    "conductivity", "permittivity", "dielectric_loss_tangent",
    "magnetic_loss_tangent", "permeability", "mass_density",
    "poisson_ratio", "specific_heat", "thermal_conductivity",
    "youngs_modulus", "thermal_expansion_coefficient",
)


class EdbSpecError(ValueError):
    """spec 校验失败（fail-fast，错误消息含定位上下文与中文说明）。"""


# ─── 校验原子（fail-fast 中文定位）───────────────────────────────────────────


def _fail(ctx: str, msg: str) -> EdbSpecError:
    return EdbSpecError(f"spec 校验失败[{ctx}]: {msg}")


def _as_dict(v: Any, ctx: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise _fail(ctx, f"须为 dict，实得 {type(v).__name__}")
    return v


def _req_key(d: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in d:
        raise _fail(ctx, f"缺必填键 {key!r}")
    return d[key]


def _as_num(v: Any, ctx: str, key: str) -> float:
    """number（int/float；bool 是 int 子类必须显式排除）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _fail(ctx, f"{key!r} 须为数值，实得 {type(v).__name__}")
    return float(v)


def _as_pos_num(v: Any, ctx: str, key: str) -> float:
    n = _as_num(v, ctx, key)
    if n <= 0:
        raise _fail(ctx, f"{key!r} 须为正数，实得 {n}")
    return n


def _as_int(v: Any, ctx: str, key: str, minimum: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise _fail(ctx, f"{key!r} 须为整数，实得 {type(v).__name__}")
    if v < minimum:
        raise _fail(ctx, f"{key!r} 须 ≥{minimum}，实得 {v}")
    return v


def _as_str(v: Any, ctx: str, key: str) -> str:
    if not isinstance(v, str) or not v:
        raise _fail(ctx, f"{key!r} 须为非空字符串，实得 {v!r}")
    return v


def _as_point_mm(v: Any, ctx: str, key: str) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise _fail(ctx, f"{key!r} 须为 [x, y] 两元素序列，实得 {v!r}")
    return [_as_num(v[0], ctx, f"{key}[0]"), _as_num(v[1], ctx, f"{key}[1]")]


def _fmt_mm(v: float) -> str:
    """毫米数值 → 带单位字符串（``%.10g``，与 edb_templates.schema.assemble_config
    的 _fmt_mm 同式同精度——同一 spec 双路径 config 字符串逐位一致；10 位有效
    数字在 mm 尺度=亚纳米）。"""
    return f"{float(v):.10g}mm"


def _fmt_ghz(v: float) -> str:
    """GHz 数值 → 带单位字符串（CfgFrequencies 官方字符串口径；``%.10g``
    同 _fmt_mm 统一口径——如 0.7*2.4=1.6800000000000002 → "1.68GHz"）。"""
    return f"{float(v):.10g}GHz"


# ─── spec 分节翻译（spec_to_config_json 的私有件）───────────────────────────


def _translate_meta(spec: dict[str, Any]) -> None:
    """翻译元段（template/schema_version/units/params）——只校验零产出。

    发射器记账面（设计读数面板/族标识/单位声明）：适配器跳过不消费，但
    类型/取值非法必须 fail-fast——尤其 units（mm→米换算硬编码，其他单位
    声明=静默错配隐患）与 schema_version（未知版本不静默消费）。
    """
    template = spec.get("template")
    if template is not None:
        # 族白名单（KNOWN_TEMPLATES）仲裁在发射器层，本层不复制名单——防漂移
        _as_str(template, "spec", "template")
    sv = spec.get("schema_version")
    if sv is not None and (isinstance(sv, bool) or not isinstance(sv, int)
                           or sv != _SUPPORTED_SCHEMA_VERSION):
        raise _fail("spec.schema_version",
                    f"须为 {_SUPPORTED_SCHEMA_VERSION}（未知版本不静默消费），"
                    f"实得 {sv!r}")
    units = spec.get("units")
    if units is not None:
        units = _as_dict(units, "spec.units")
        if units.get("length") != "mm" or units.get("frequency") != "GHz":
            raise _fail("spec.units",
                        "须为 {'length': 'mm', 'frequency': 'GHz'}（本适配器 "
                        f"mm→米换算硬编码），实得 {units!r}")
    params = spec.get("params")
    if params is not None:
        _as_dict(params, "spec.params")  # 内容发射器自治，仅挡非 dict


def _translate_materials(stackup: dict[str, Any]) -> list[dict[str, Any]]:
    """翻译 stackup.materials（显式材料定义）→ config materials 列表。

    发射族契约（edb_templates build_spec_stackup）：铜以 conductivity、介质以
    permittivity/dielectric_loss_tangent 显式成文直通——介质层只给 material
    引用名而 pyedb 缺省库无此名时，必须靠本段定义（否则落库成无名材料）。
    属性键白名单见 _MATERIAL_KEYS；与层 material_props 派生材料的同名冲突在
    _translate_stackup 派生面 fail-fast。
    """
    mats = stackup.get("materials")
    if mats is None:
        return []
    if not isinstance(mats, list):
        raise _fail("stackup.materials", "须为 list")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, m in enumerate(mats):
        ctx = f"stackup.materials[{i}]"
        m = _as_dict(m, ctx)
        name = _as_str(_req_key(m, "name", ctx), ctx, "name")
        if name in seen:
            raise _fail(ctx, f"材料名 {name!r} 重复（材料名全表唯一）")
        seen.add(name)
        entry: dict[str, Any] = {"name": name}
        for k, v in m.items():
            if k == "name":
                continue
            if k not in _MATERIAL_KEYS:
                raise _fail(ctx, f"不接受材料属性键 {k!r}"
                                 f"（合法：{list(_MATERIAL_KEYS)}）")
            entry[k] = _as_num(v, ctx, k)  # 数值逐键透传（EDB 侧单位各自内置）
        out.append(entry)
    return out


def _translate_stackup(
    stackup: dict[str, Any],
    reserved_material_names: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], set[str]]:
    """翻译 stackup 节 → (派生 materials, layers, signal 层名集, 全部层名集)。

    ``reserved_material_names``：stackup.materials 显式段已占用的材料名
    （material_props 派生名与其冲突即 fail-fast——同名两定义=静默歧义）。

    层序翻转（2026-10-08 审查批 P0 修复，证据链见模块 docstring「layers」键
    注）：spec 层序自底向上（index0=物理底层），config 层列表翻转一次为
    **自顶向下**（首项=物理顶层）——pyedb 0.83 ``__create_stackup`` 按列表序
    逐层 ``AddLayerBottom``（每次插到全栈最底→列表首项落物理顶层；
    configuration.py:863-868 + dotnet/database/stackup.py:97-130 源码实证），
    不翻转则发射族 [GND, SUB, TOP] 落库成 GND 在物理顶层=叠层整体上下颠倒
    （倒置微带，综合 λ/4 几何全错且无报错）。翻转是单点修正（两处 config
    生产端：本函数 + edb_templates.schema.assemble_config），spec 契约与
    signal/全层名集（集合，无序）不受影响。
    """
    layers_spec = _req_key(_as_dict(stackup, "stackup"), "layers", "stackup")
    if not isinstance(layers_spec, list) or not layers_spec:
        raise _fail("stackup.layers", "须为非空 list（至少 1 层）")
    materials: list[dict[str, Any]] = []
    layers: list[dict[str, Any]] = []
    layer_names: set[str] = set()
    signal_layers: set[str] = set()
    material_names: set[str] = (
        set(reserved_material_names) if reserved_material_names else set())
    for i, ly in enumerate(layers_spec):
        ctx = f"stackup.layers[{i}]"
        ly = _as_dict(ly, ctx)
        name = _as_str(_req_key(ly, "name", ctx), ctx, "name")
        if name in layer_names:
            raise _fail(ctx, f"层名 {name!r} 重复（层名全表唯一）")
        layer_names.add(name)
        ltype = _as_str(_req_key(ly, "type", ctx), ctx, "type")
        if ltype not in _LAYER_TYPES:
            raise _fail(ctx, f"type 须为 {_LAYER_TYPES} 之一，实得 {ltype!r}")
        thickness = _as_pos_num(_req_key(ly, "thickness_mm", ctx), ctx, "thickness_mm")
        material = ly.get("material")
        if material is not None:
            material = _as_str(material, ctx, "material")
        props = ly.get("material_props")
        if props is not None:
            props = _as_dict(props, f"{ctx}.material_props")
        if ltype == "signal":
            if props is not None:
                # 诚实边界：v1 信号层不支持自定义材料定义（见模块 docstring）
                raise _fail(ctx, "signal 层不支持 material_props（v1 边界），"
                                 "如需自定义导体材料请先在 pyedb 材料库登记后以 material 名引用")
            material = material or "copper"  # pyedb 默认材料库内置
        else:
            if material is not None and props is not None:
                raise _fail(ctx, "material 与 material_props 二选一（不得同时给出）")
            if props is not None:
                er = _as_pos_num(_req_key(props, "er", f"{ctx}.material_props"),
                                 f"{ctx}.material_props", "er")
                tan_d = props.get("tan_d", 0.0)
                tan_d = _as_num(tan_d, f"{ctx}.material_props", "tan_d")
                if tan_d < 0:
                    raise _fail(ctx, f"material_props.tan_d 须 ≥0，实得 {tan_d}")
                mat_name = props.get("name")
                mat_name = (_as_str(mat_name, f"{ctx}.material_props", "name")
                            if mat_name is not None else f"{name}_material")
                if mat_name in material_names:
                    raise _fail(ctx, f"材料名 {mat_name!r} 重复（材料名全表唯一）")
                material_names.add(mat_name)
                materials.append({
                    "name": mat_name,
                    "permittivity": er,
                    "dielectric_loss_tangent": tan_d,
                })
                material = mat_name
            elif material is None:
                raise _fail(ctx, "dielectric 层必须给 material（引用名）或 "
                                 "material_props（er/tan_d 显式定义）")
        if ltype == "signal":
            signal_layers.add(name)
        # thickness 走带单位字符串透传（CfgLayer.thickness: float|int|str，
        # 字符串口径零精度损失，见模块 docstring 单位纪律）；层类型键出
        # layer_type（CfgLayer 原生键名、"type" 是其 validation_alias——
        # 与发射器 assemble_config 逐键一致）
        layers.append({"name": name, "layer_type": ltype, "material": material,
                       "thickness": _fmt_mm(thickness)})
    # spec 自底向上 → config 自顶向下（pyedb AddLayerBottom 首项落物理顶层，
    # 翻转证据链见本函数 docstring 与模块 docstring「layers」键注）
    layers.reverse()
    return materials, layers, signal_layers, layer_names


def _translate_traces(
    spec: dict[str, Any], signal_layers: set[str],
) -> list[dict[str, Any]]:
    """翻译 traces 节 → pyedb modeler.traces 列表（路径点 mm→米）。"""
    traces_spec = spec.get("traces") or []
    if not isinstance(traces_spec, list):
        raise _fail("traces", "须为 list")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, tr in enumerate(traces_spec):
        ctx = f"traces[{i}]"
        tr = _as_dict(tr, ctx)
        name = tr.get("name")
        name = _as_str(name, ctx, "name") if name is not None else f"trace_{i + 1}"
        if name in seen:
            raise _fail(ctx, f"trace 名 {name!r} 重复（全表唯一）")
        seen.add(name)
        layer = _as_str(_req_key(tr, "layer", ctx), ctx, "layer")
        if layer not in signal_layers:
            raise _fail(ctx, f"layer {layer!r} 不在 stackup signal 层内 "
                             f"{sorted(signal_layers)}")
        width = _as_pos_num(_req_key(tr, "width_mm", ctx), ctx, "width_mm")
        path = _req_key(tr, "path_mm", ctx)
        if not isinstance(path, list) or len(path) < 2:
            raise _fail(ctx, "path_mm 须为 ≥2 点的 list（每点 [x, y] 毫米）")
        path_m = []
        for j, pt in enumerate(path):
            x, y = _as_point_mm(pt, ctx, f"path_mm[{j}]")
            path_m.append([x * _MM_TO_M, y * _MM_TO_M])  # mm→米（官方文档口径）
        net = tr.get("net", "")
        net = _as_str(net, ctx, "net") if net else ""
        out.append({
            "name": name,
            "layer": layer,
            "path": path_m,
            "width": _fmt_mm(width),
            "net_name": net,
            # 统一契约（edb_templates.schema 假设 4）：cap=flat（足迹=精确
            # 矩形、端点=矩形边缘——wave_port/电阻端子落走线端点的前提）、
            # corner=sharp；pyedb 缺省 round 圆头会在端点短 r/2
            # （docs/pyedb_distilled.md §3.2，与发射器 assemble_config 同款）
            "start_cap_style": "flat",
            "end_cap_style": "flat",
            "corner_style": "sharp",
        })
    return out


def _translate_vias(
    spec: dict[str, Any], layer_names: set[str],
    signal_layers_topdown: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """翻译 vias 节 → (padstack definitions, instances)。

    同孔径共享一个 padstack 定义（definitions 去重）；位置 mm→米（假设口径
    见模块 docstring 单位纪律）。

    v1 边界（2026-10-08 审查批 P1，fail-fast）：只支持**整叠通孔**——
    start/stop 两层须恰为最顶+最底信号层。pyedb CfgPadstackDefinition 的
    ``hole_range`` 本层未透传（缺省 through 语义，cfg_padstacks.py:196 可选
    字段，docs/pyedb_distilled.md §3.2），盲埋孔 spec 会静默按整叠通孔落库
    （几何错且无报错）——诚实边界同 signal material_props 先例：给出即
    fail-fast 不虚报。``signal_layers_topdown``：config 层列表（已翻转自顶
    向下）中的信号层名序，[0]=物理顶层、[-1]=物理底层。
    """
    vias_spec = spec.get("vias") or []
    if not isinstance(vias_spec, list):
        raise _fail("vias", "须为 list")
    definitions: list[dict[str, Any]] = []
    def_by_diameter: dict[float, str] = {}
    instances: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, via in enumerate(vias_spec):
        ctx = f"vias[{i}]"
        via = _as_dict(via, ctx)
        diameter = _as_pos_num(_req_key(via, "diameter_mm", ctx), ctx, "diameter_mm")
        x_mm = _as_num(_req_key(via, "x_mm", ctx), ctx, "x_mm")
        y_mm = _as_num(_req_key(via, "y_mm", ctx), ctx, "y_mm")
        start = _as_str(_req_key(via, "start_layer", ctx), ctx, "start_layer")
        stop = _as_str(_req_key(via, "stop_layer", ctx), ctx, "stop_layer")
        for lname in (start, stop):
            if lname not in layer_names:
                raise _fail(ctx, f"层名 {lname!r} 不在 stackup 内 {sorted(layer_names)}")
        if signal_layers_topdown and {start, stop} != {
                signal_layers_topdown[0], signal_layers_topdown[-1]}:
            raise _fail(
                ctx,
                f"v1 仅支持整叠通孔（start/stop 两层须恰为最顶+最底信号层 "
                f"{signal_layers_topdown[0]!r}/{signal_layers_topdown[-1]!r}；"
                "pyedb CfgPadstackDefinition.hole_range 未透传、缺省 through "
                "语义，盲埋孔会静默错落整叠通孔），实得 "
                f"start={start!r} stop={stop!r}")
        name = via.get("name")
        name = _as_str(name, ctx, "name") if name is not None else f"via_{i + 1}"
        if name in seen:
            raise _fail(ctx, f"过孔名 {name!r} 重复（全表唯一）")
        seen.add(name)
        net = via.get("net", "")
        net = _as_str(net, ctx, "net") if net else ""
        if diameter not in def_by_diameter:
            def_name = f"via_{_fmt_mm(diameter)}"
            def_by_diameter[diameter] = def_name
            definitions.append({
                "name": def_name,
                "material": "copper",
                "hole_parameters": {"shape": "circle", "diameter": _fmt_mm(diameter)},
            })
        instances.append({
            "name": name,
            "definition": def_by_diameter[diameter],
            "net_name": net,
            "layer_range": [start, stop],
            # 位置 mm→米（EDB 数据库单位口径假设，见模块 docstring）
            "position": [x_mm * _MM_TO_M, y_mm * _MM_TO_M],
        })
    return definitions, instances


def _translate_resistors(
    spec: dict[str, Any], signal_layers: set[str],
) -> list[dict[str, Any]]:
    """翻译 resistors 节 → 归一电阻清单（校验 fail-fast，不进 config）。

    键名与 edb_templates/schema.py 功分器发射契约逐字对齐（name/layer/net/
    r_ohm/width_mm/path_mm[/role]）。电阻**只校验不落 config JSON**（pyedb
    0.83 configuration 无 lumped 段，schema.py 假设 5 实测口径）——落地由
    :meth:`EdbAdapter._land_resistors` 在 configuration.load 之后走 pyedb
    lumped RLC 边界（防逐字套用 config 时变金属短路间隙）。
    """
    resistors_spec = spec.get("resistors") or []
    if not isinstance(resistors_spec, list):
        raise _fail("resistors", "须为 list")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, res in enumerate(resistors_spec):
        ctx = f"resistors[{i}]"
        res = _as_dict(res, ctx)
        name = res.get("name")
        name = _as_str(name, ctx, "name") if name is not None else f"resistor_{i + 1}"
        if name in seen:
            raise _fail(ctx, f"电阻名 {name!r} 重复（电阻表内唯一）")
        seen.add(name)
        layer = _as_str(_req_key(res, "layer", ctx), ctx, "layer")
        if layer not in signal_layers:
            raise _fail(ctx, f"layer {layer!r} 不在 stackup signal 层内 "
                             f"{sorted(signal_layers)}")
        # net 必填非空：点端子经 pyedb find_net_by_name 挂网，空 net 无处可挂
        net = _as_str(_req_key(res, "net", ctx), ctx, "net")
        r_ohm = _as_pos_num(_req_key(res, "r_ohm", ctx), ctx, "r_ohm")
        width = _as_pos_num(_req_key(res, "width_mm", ctx), ctx, "width_mm")
        path = _req_key(res, "path_mm", ctx)
        if not isinstance(path, list) or len(path) < 2:
            raise _fail(ctx, "path_mm 须为 ≥2 点的 list（每点 [x, y] 毫米；"
                             "首点=正端子、末点=参考端子）")
        path_mm = []
        for j, pt in enumerate(path):
            x, y = _as_point_mm(pt, ctx, f"path_mm[{j}]")
            path_mm.append([x, y])
        role = res.get("role")
        if role is not None:
            _as_str(role, ctx, "role")  # 发射侧元数据：仅校验类型，透传忽略
        out.append({
            "name": name,
            "layer": layer,
            "net": net,
            "r_ohm": r_ohm,
            "width_mm": width,  # 声明存证：点端子 RLC 无宽度参数，不进引擎
            "path_mm": path_mm,
        })
    return out


def _translate_board(
    spec: dict[str, Any], ground_layer: str, signal_layers: set[str],
) -> list[dict[str, Any]]:
    """翻译 board 节（发射族版图边界）→ modeler.planes 整版矩形平面清单。

    口径与 edb_templates.schema.assemble_config 逐键同款（2026-10-08 契约
    统一）：board 角点矩形 → name="GND_plane"/net="GND" 的 rectangle 平面
    原语，落 spec 层序 ``stackup.layers[0]``（自底向上的物理底层信号层，须
    signal 层——发射族契约假设 2「地面=最底信号层整版矩形」；config 层列表
    已翻转自顶向下，故地板载体层由调用方传 config 层列表**末位**）；角点
    坐标 mm→米（EDB 数据库单位，同 trace path 口径）。层序翻转已按 pyedb
    0.83 源码实证落地（AddLayerBottom 首项落物理顶层，见
    _translate_stackup docstring）；真机首跑仍以 ``edb.stackup.layers`` 落位
    顺序复核存证（单位纪律"port 落点复核"同窗口，docs/pyedb_distilled.md
    §3.1/§6-2）。

    Returns:
        空列表=spec 无 board 段（通用 spec，零行为变化）；单元素列表=平面
        原语（调用方同时据此补 boundaries 开放域辐射边界——发射族口径）。
    """
    board = spec.get("board")
    if board is None:
        return []
    ctx = "board"
    board = _as_dict(board, ctx)
    for k in board:
        if k not in ("lower_left_mm", "upper_right_mm"):
            raise _fail(ctx, f"不接受键 {k!r}（合法键："
                             "('lower_left_mm', 'upper_right_mm')）")
    ll = _as_point_mm(_req_key(board, "lower_left_mm", ctx), ctx, "lower_left_mm")
    ur = _as_point_mm(_req_key(board, "upper_right_mm", ctx), ctx, "upper_right_mm")
    if ur[0] <= ll[0] or ur[1] <= ll[1]:
        raise _fail(ctx, f"角点须 upper_right 严格大于 lower_left（x/y 各向），"
                         f"实得 lower={ll} upper={ur}")
    if ground_layer not in signal_layers:
        raise _fail(ctx, f"地板载体层 stackup.layers[0]={ground_layer!r} 须为 "
                         "signal 层（发射族契约：地面=最底信号层整版矩形）")
    # 坐标 mm→米（EDB 数据库单位口径，见模块 docstring 单位纪律）
    return [{
        "name": "GND_plane",
        "layer": ground_layer,
        "net_name": "GND",
        "type": "rectangle",
        "lower_left_point": [ll[0] * _MM_TO_M, ll[1] * _MM_TO_M],
        "upper_right_point": [ur[0] * _MM_TO_M, ur[1] * _MM_TO_M],
    }]


def _translate_port_terminal(
    t: Any, ctx: str, port_level: dict[str, Any], signal_layers: set[str],
) -> dict[str, Any]:
    """翻译端口终端 → pyedb coordinates 选择器（CfgTerminalInfo 导出形态）。"""
    if isinstance(t, (list, tuple)):
        x, y = _as_point_mm(list(t), ctx, "point_mm")
        layer = port_level.get("layer")
        net = port_level.get("net", "")
    elif isinstance(t, dict):
        layer = t.get("layer")
        net = t.get("net", "")
        x, y = _as_point_mm(_req_key(t, "point_mm", ctx), ctx, "point_mm")
    else:
        raise _fail(ctx, "终端须为 [x, y] 简写或 {layer, point_mm, net} dict，"
                         f"实得 {type(t).__name__}")
    if not (isinstance(layer, str) and layer):
        raise _fail(ctx, "终端缺 layer（dict 终端须自带，[x,y] 简写须端口级 layer 提供缺省）")
    if layer not in signal_layers:
        raise _fail(ctx, f"layer {layer!r} 不在 stackup signal 层内 {sorted(signal_layers)}")
    if net is None:
        net = ""
    if not isinstance(net, str):
        raise _fail(ctx, f"net 须为字符串，实得 {type(net).__name__}")
    # coordinates 选择器 = CfgCoordinateTerminalInfo.export_properties 形态；
    # point 单位按 EDB 数据库口径（米）换算（假设标注见模块 docstring）
    return {"coordinates": {"layer": layer, "point": [x * _MM_TO_M, y * _MM_TO_M],
                            "net": net}}


def _translate_wave_port(
    p: dict[str, Any], ctx: str, trace_names: set[str],
    seen_numbers: set[int], seen_names: set[str],
) -> dict[str, Any]:
    """发射族 wave_port 端口 → CfgEdgePort dict（extent 因子透传，坐标 mm→米）。

    键白名单=make_wave_port 七键+type——未知键 fail-fast；阻抗语义见模块
    docstring 诚实边界（pyedb CfgEdgePort 通道硬编码 50Ω，非 50 拒收）；
    trace 引用存在性在此 fail-fast（CfgEdgePort.set_parameters_to_edb 按
    名取图元，晚失败定位深）；端点附着几何审计在
    edb_templates.validate_spec（本层不重复仲裁，同电阻口径）。
    """
    allowed = ("name", "port_nr", "type", "trace", "point_mm", "impedance",
               "horizontal_extent_factor", "vertical_extent_factor")
    for k in p:
        if k not in allowed:
            raise _fail(ctx, f"不接受键 {k!r}（wave_port 合法键：{list(allowed)}）")
    name = _as_str(_req_key(p, "name", ctx), ctx, "name")
    if name in seen_names:
        raise _fail(ctx, f"端口名 {name!r} 重复（全表唯一）")
    seen_names.add(name)
    port_nr = _as_int(_req_key(p, "port_nr", ctx), ctx, "port_nr", 1)
    if port_nr in seen_numbers:
        raise _fail(ctx, f"端口号 {port_nr} 重复（全表唯一）")
    seen_numbers.add(port_nr)
    trace = _as_str(_req_key(p, "trace", ctx), ctx, "trace")
    if trace not in trace_names:
        raise _fail(ctx, f"引用不存在走线 {trace!r}（已知走线："
                         f"{sorted(trace_names)}——先建 trace 后建端口）")
    x, y = _as_point_mm(_req_key(p, "point_mm", ctx), ctx, "point_mm")
    impedance = _as_num(p.get("impedance", 50.0), ctx, "impedance")
    if impedance != 50.0:
        raise _fail(ctx, f"wave_port 阻抗必须=50（pyedb CfgEdgePort 通道硬编码"
                         f" 50Ω、无法表达其他值），实得 {impedance}")
    hef = _as_int(p.get("horizontal_extent_factor", 5), ctx,
                  "horizontal_extent_factor", 1)
    vef = _as_int(p.get("vertical_extent_factor", 3), ctx,
                  "vertical_extent_factor", 1)
    # point_on_edge 单位按 EDB 数据库口径（米）换算（同 trace path 口径）
    return {
        "name": name,
        "type": "wave_port",
        "primitive_name": trace,
        "point_on_edge": [x * _MM_TO_M, y * _MM_TO_M],
        "horizontal_extent_factor": hef,
        "vertical_extent_factor": vef,
        "pec_launch_width": "0.01mm",  # CfgEdgePort 官方缺省（显式写出便于存证）
    }


def _translate_ports(
    spec: dict[str, Any], signal_layers: set[str], trace_names: set[str],
) -> list[dict[str, Any]]:
    """翻译 ports 节 → pyedb ports 列表。

    两形态按条目 "type" 判别：wave_port（发射族，:func:`_translate_wave_port`）
    与 circuit|coax（通用，端口号/起止 → 正负终端电路端口，原契约不变）。
    """
    ports_spec = spec.get("ports") or []
    if not isinstance(ports_spec, list):
        raise _fail("ports", "须为 list")
    out: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    seen_names: set[str] = set()
    for i, p in enumerate(ports_spec):
        ctx = f"ports[{i}]"
        p = _as_dict(p, ctx)
        ptype = p.get("type", "circuit")
        if ptype == "wave_port":
            out.append(_translate_wave_port(p, ctx, trace_names,
                                            seen_numbers, seen_names))
            continue
        if ptype not in _PORT_TYPES:
            raise _fail(ctx, f"type 须为 {(*_PORT_TYPES, 'wave_port')} 之一，"
                             f"实得 {ptype!r}")
        number = _as_int(_req_key(p, "number", ctx), ctx, "number", 1)
        if number in seen_numbers:
            raise _fail(ctx, f"端口号 {number} 重复（全表唯一）")
        seen_numbers.add(number)
        for key in ("layer", "net", "name"):
            v = p.get(key)
            if v is not None and (not isinstance(v, str) or (key != "net" and not v)):
                raise _fail(ctx, f"{key!r} 须为非空字符串，实得 {v!r}")
        start = _translate_port_terminal(
            _req_key(p, "start", ctx), f"{ctx}.start", p, signal_layers)
        end = _translate_port_terminal(
            _req_key(p, "end", ctx), f"{ctx}.end", p, signal_layers)
        impedance = p.get("impedance_ohm", 50.0)
        impedance = _as_pos_num(impedance, ctx, "impedance_ohm")
        ptype = p.get("type", "circuit")
        if ptype not in _PORT_TYPES:
            raise _fail(ctx, f"type 须为 {_PORT_TYPES} 之一，实得 {ptype!r}")
        name = p.get("name") or f"p{number}"
        if name in seen_names:
            raise _fail(ctx, f"端口名 {name!r} 重复（全表唯一）")
        seen_names.add(name)
        out.append({
            "name": name,
            "type": ptype,
            "impedance": impedance,
            "positive_terminal": start,
            "negative_terminal": end,
        })
    return out


def _translate_sweep_entry(sw: Any, i: int, sweep_type: str) -> dict[str, Any]:
    """翻译 sweeps[i] → CfgFrequencySweep dict（GHz→带单位字符串透传）。

    sweep_type 落在 sweep 条目级 "type" 键（CfgFrequencySweep 的
    validation_alias=AliasChoices("type", "sweep_type") 口径；CfgBaseModel
    extra="forbid"——setup 级塞该键会被 CfgHFSSSetup.model_validate 拒收）。
    """
    ctx = f"sim_setup.sweeps[{i}]"
    sw = _as_dict(sw, ctx)
    stype = sw.get("type")
    if stype not in _SWEEP_TYPES:
        raise _fail(ctx, f"type 须为 {_SWEEP_TYPES} 之一，实得 {stype!r}")
    required = _SWEEP_FIELDS[stype]
    for key in required:
        if key not in sw:
            raise _fail(ctx, f"type={stype!r} 缺必填键 {key!r}")
    for key in sw:
        if key not in ("type", "name", *required):
            raise _fail(ctx, f"type={stype!r} 不接受键 {key!r}"
                             f"（合法：type/name/{required}）")
    start = _as_pos_num(sw["start_ghz"], ctx, "start_ghz") if "start_ghz" in sw else None
    stop = _as_pos_num(sw["stop_ghz"], ctx, "stop_ghz") if "stop_ghz" in sw else None
    if start is not None and stop is not None and stop < start:
        raise _fail(ctx, f"stop_ghz({stop}) 不得小于 start_ghz({start})")
    freq: dict[str, Any]
    if stype == "linear_count":
        count = _as_int(sw["count"], ctx, "count", 2)
        freq = {"start": _fmt_ghz(start), "stop": _fmt_ghz(stop),
                "increment": count, "distribution": _SWEEP_DISTRIBUTION[stype]}
    elif stype == "linear_step":
        step = _as_pos_num(sw["step_ghz"], ctx, "step_ghz")
        freq = {"start": _fmt_ghz(start), "stop": _fmt_ghz(stop),
                "increment": _fmt_ghz(step), "distribution": _SWEEP_DISTRIBUTION[stype]}
    elif stype == "log_count":
        count = _as_int(sw["count"], ctx, "count", 2)
        freq = {"start": _fmt_ghz(start), "stop": _fmt_ghz(stop),
                "increment": count, "distribution": _SWEEP_DISTRIBUTION[stype]}
    elif stype == "log_step":
        step = _as_pos_num(sw["step_ghz"], ctx, "step_ghz")
        freq = {"start": _fmt_ghz(start), "stop": _fmt_ghz(stop),
                "increment": step, "distribution": _SWEEP_DISTRIBUTION[stype]}
    else:  # single
        f0 = _as_pos_num(sw["freq_ghz"], ctx, "freq_ghz")
        freq = {"start": _fmt_ghz(f0), "stop": _fmt_ghz(f0),
                "increment": 1, "distribution": _SWEEP_DISTRIBUTION[stype]}
    name = sw.get("name")
    name = _as_str(name, ctx, "name") if name is not None else f"sweep_{i + 1}"
    return {"name": name, "type": sweep_type, "frequencies": [freq]}


def _translate_emitter_sweep(sw: Any, default_type: str) -> dict[str, Any]:
    """发射族 sweep dict → CfgFrequencySweep（单段 linear_count）。

    键面与 edb_templates 发射器 sim_setup.sweep 契约逐字对齐（name/type/
    start_ghz/stop_ghz/points，schema.py 假设 8 缺省口径）；产出与
    assemble_config 同式同键。
    """
    ctx = "sim_setup.sweep"
    sw = _as_dict(sw, ctx)
    allowed = ("name", "type", "start_ghz", "stop_ghz", "points")
    for k in sw:
        if k not in allowed:
            raise _fail(ctx, f"不接受键 {k!r}（合法：{list(allowed)}）")
    start = _as_pos_num(_req_key(sw, "start_ghz", ctx), ctx, "start_ghz")
    stop = _as_pos_num(_req_key(sw, "stop_ghz", ctx), ctx, "stop_ghz")
    if stop < start:
        raise _fail(ctx, f"stop_ghz({stop}) 不得小于 start_ghz({start})")
    points = _as_int(sw.get("points", 401), ctx, "points", 2)
    stype = sw.get("type", default_type)
    if stype not in ("interpolation", "discrete"):
        raise _fail(ctx, f"type 须为 ('interpolation', 'discrete') 之一，"
                         f"实得 {stype!r}")
    name = sw.get("name")
    name = _as_str(name, ctx, "name") if name is not None else "sweep1"
    return {"name": name, "type": stype, "frequencies": [{
        "start": _fmt_ghz(start),
        "stop": _fmt_ghz(stop),
        "increment": points,
        "distribution": "linear_count",
    }]}


def _translate_emitter_adapt(adapt: Any) -> tuple[int, float]:
    """发射族 adapt dict → (max_passes, max_delta)（缺省 20/0.02，假设 8）。"""
    ctx = "sim_setup.adapt"
    adapt = _as_dict(adapt, ctx)
    for k in adapt:
        if k not in ("max_passes", "max_delta"):
            raise _fail(ctx, f"不接受键 {k!r}"
                             "（合法：('max_passes', 'max_delta')）")
    max_passes = _as_int(adapt.get("max_passes", 20), ctx, "max_passes", 1)
    max_delta = _as_num(adapt.get("max_delta", 0.02), ctx, "max_delta")
    if max_delta <= 0:
        raise _fail(ctx, f"max_delta 须 >0，实得 {max_delta}")
    return max_passes, max_delta


def _translate_sim_setup(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """翻译 sim_setup 节 → pyedb setups 列表（缺省不生成）。

    两形态并存（2026-10-08 契约统一）：发射族形态 f0_ghz/sweep(dict)/
    adapt(dict)（edb_templates 发射器产出）与通用形态 shorthand/sweeps
    （原契约）；互斥键同给 fail-fast（不猜优先级——#154 同名键语义纪律）。
    """
    ss = spec.get("sim_setup")
    if ss is None:
        return []
    ctx = "sim_setup"
    ss = _as_dict(ss, ctx)
    name = ss.get("name")
    name = _as_str(name, ctx, "name") if name is not None else "hfss_setup_1"
    stype = ss.get("type", "hfss")
    if stype not in _SETUP_TYPES:
        raise _fail(ctx, f"type 须为 {_SETUP_TYPES} 之一，实得 {stype!r}")
    sweep_type = ss.get("sweep_type", "interpolation")
    if sweep_type not in ("interpolation", "discrete"):
        raise _fail(ctx, f"sweep_type 须为 ('interpolation', 'discrete') 之一，"
                         f"实得 {sweep_type!r}")
    # ── 形态判别与互斥键守卫（发射族 vs 通用，混给=歧义 fail-fast）─────────
    f0_ghz = ss.get("f0_ghz")
    adapt_dict = ss.get("adapt")
    sweep_dict = ss.get("sweep")
    if sweep_dict is not None:
        if "sweeps" in ss:
            raise _fail(ctx, "'sweep'（发射族 dict 形态）与 'sweeps'（显式列表"
                             "形态）不得同给（歧义）")
        for k in ("f_start_ghz", "f_stop_ghz", "points"):
            if k in ss:
                raise _fail(ctx, f"'sweep' 与通用形态简写键 {k!r} 不得同给（歧义）")
    if adapt_dict is not None and any(k in ss for k in ("max_passes", "max_delta_s")):
        raise _fail(ctx, "'adapt' 与通用形态键 max_passes/max_delta_s 不得同给"
                         "（歧义）")
    if f0_ghz is not None and "adaptive_freq_ghz" in ss:
        raise _fail(ctx, "'f0_ghz' 与 'adaptive_freq_ghz' 不得同给（歧义）")
    if stype != "hfss" and (f0_ghz is not None or adapt_dict is not None):
        raise _fail(ctx, "f0_ghz/adapt 仅 type=hfss 可给"
                         "（siwave_ac 无单频自适应语义）")
    sweeps = ss.get("sweeps")
    if sweep_dict is not None:
        freq_sweeps = [_translate_emitter_sweep(sweep_dict, sweep_type)]
    elif sweeps is not None:
        if not isinstance(sweeps, list) or not sweeps:
            raise _fail(ctx, "sweeps 须为非空 list（或缺省走 f_start/f_stop/points 简写）")
        freq_sweeps = [_translate_sweep_entry(sw, i, sweep_type)
                       for i, sw in enumerate(sweeps)]
    else:
        if f0_ghz is not None or adapt_dict is not None:
            raise _fail(ctx, "发射族形态 f0_ghz/adapt 需配合扫频形态之一"
                             "（'sweep' dict / 'sweeps' 列表 / f_start_ghz 简写）")
        f_start = _as_pos_num(_req_key(ss, "f_start_ghz", ctx), ctx, "f_start_ghz")
        f_stop = _as_pos_num(_req_key(ss, "f_stop_ghz", ctx), ctx, "f_stop_ghz")
        if f_stop < f_start:
            raise _fail(ctx, f"f_stop_ghz({f_stop}) 不得小于 f_start_ghz({f_start})")
        points = ss.get("points", 401)
        points = _as_int(points, ctx, "points", 2)
        freq_sweeps = [{
            "name": "sweep_1",
            "type": sweep_type,
            "frequencies": [{
                "start": _fmt_ghz(f_start),
                "stop": _fmt_ghz(f_stop),
                "increment": points,
                "distribution": _SWEEP_DISTRIBUTION["linear_count"],
            }],
        }]
    setup: dict[str, Any] = {"name": name, "type": stype, "freq_sweep": freq_sweeps}
    if stype == "hfss":
        # 自适应缺省 = pyedb CfgSingleFrequencyAdaptiveSolution 官方缺省
        # （"5GHz"/20/0.02）——显式写出便于存证与复现；发射族 f0_ghz 作
        # 自适应频点（f0 单频口径，edb_templates sim_setup 契约）
        if f0_ghz is not None:
            adapt_freq = _as_pos_num(f0_ghz, ctx, "f0_ghz")
        else:
            adapt_freq = _as_pos_num(ss.get("adaptive_freq_ghz", 5.0), ctx,
                                     "adaptive_freq_ghz")
        if adapt_dict is not None:
            max_passes, max_delta = _translate_emitter_adapt(adapt_dict)
        else:
            max_passes = _as_int(ss.get("max_passes", 20), ctx, "max_passes", 1)
            max_delta = _as_num(ss.get("max_delta_s", 0.02), ctx, "max_delta_s")
            if max_delta <= 0:
                raise _fail(ctx, f"max_delta_s 须 >0，实得 {max_delta}")
        setup["adapt_type"] = "single"
        setup["single_frequency_adaptive_solution"] = {
            "adaptive_frequency": _fmt_ghz(adapt_freq),
            "max_passes": max_passes,
            "max_delta": max_delta,
        }
    elif any(k in ss for k in ("adaptive_freq_ghz", "max_passes", "max_delta_s")):
        raise _fail(ctx, "adaptive_freq_ghz/max_passes/max_delta_s 仅 type=hfss 可给"
                         "（siwave_ac 无单频自适应语义）")
    return [setup]


# ─── 收紧生效断言（W8 仲裁建议 2：#333 族旋钮效力断言，纯函数件）─────────────


def _load_requested_adapt(
    config_json_path: Path,
) -> dict[str, dict[str, Any]] | None:
    """config 存证 JSON → 请求档登记表（setup 名 → 单频自适应三元组）。

    请求正本=建库时落盘的 configuration JSON（``build()`` 注入 pyedb 的
    同一 dict）——其中 ``setups[*].single_frequency_adaptive_solution`` 即
    建模期写入 setup 的目标档。

    Returns:
        dict：{setup 名: {"adaptive_frequency": str, "max_delta": float,
        "max_passes": int}}，仅收 type=hfss 且带
        single_frequency_adaptive_solution 的条目；空 dict=存证良构但无
        此类请求（无可核对项，vacuous 真）；None=存证不可读（缺失/损坏/
        非 dict/setups 段畸形——可疑态，调用方告警不冒充核对通过）。
    """
    try:
        raw = json.loads(Path(config_json_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    setups = raw.get("setups")
    if setups is None:
        return {}
    if not isinstance(setups, list):
        return None
    requested: dict[str, dict[str, Any]] = {}
    for entry in setups:
        if not isinstance(entry, dict) or entry.get("type") != "hfss":
            continue
        sol = entry.get("single_frequency_adaptive_solution")
        if not isinstance(sol, dict):
            continue
        name = entry.get("name")
        freq = sol.get("adaptive_frequency")
        max_delta = sol.get("max_delta")
        max_passes = sol.get("max_passes")
        # 逐键类型守卫（bool 是 int 子类显式排除；#364④ 数值位不用 or 惯语）
        if not (isinstance(name, str) and name and isinstance(freq, str)):
            continue
        if isinstance(max_delta, bool) or not isinstance(max_delta, (int, float)):
            continue
        if isinstance(max_passes, bool) or not isinstance(max_passes, int):
            continue
        requested[name] = {
            "adaptive_frequency": freq,
            "max_delta": float(max_delta),
            "max_passes": int(max_passes),
        }
    return requested


def _verify_one_setup_adapt(
    name: str,
    requested: dict[str, Any],
    setups: dict[str, Any],
) -> list[str]:
    """单个 setup 的请求档 vs 工程读回核对（告警清单，空=一致）。

    读回面（pyedb 0.83 只读集合，源码核验见模块 docstring「自适应档写入
    通道」节）：``setups[name].adaptive_settings.adaptive_frequency_data_list``
    → 条目 ``adaptive_frequency``/``max_delta``。单频点条目直接对档（频点
    字符串随附存证）；多频点按 adaptive_frequency 忽略大小写匹配，无命中
    不猜（#122 如实告警）。max_delta 比较留 rel_tol=1e-9（与
    edb_health_gate 边界 eps 家法同源：double 往返量化噪声不误报）。
    """
    setup = setups.get(name)
    if setup is None:
        return [
            f"收紧生效断言[{name}]：工程内无同名 setup（读回="
            f"{sorted(str(k) for k in setups)}）——请求档未落库？"
        ]
    try:
        entries = list(setup.adaptive_settings.adaptive_frequency_data_list)
    except Exception as exc:
        return [
            f"收紧生效断言[{name}]：adaptive_settings 读回失败"
            f"（{type(exc).__name__}: {exc}）——不可核对如实告警（#122）"
        ]
    if not entries:
        return [
            f"收紧生效断言[{name}]：setup 无自适应频点数据——请求档未落库？"
        ]
    chosen: Any = None
    if len(entries) == 1:
        chosen = entries[0]
    else:
        req_freq = str(requested["adaptive_frequency"]).strip().lower()
        for entry in entries:
            try:
                obs_freq = str(entry.adaptive_frequency).strip().lower()
            except Exception:
                continue
            if obs_freq == req_freq:
                chosen = entry
                break
    if chosen is None:
        observed_freqs: list[str] = []
        for entry in entries:
            try:
                observed_freqs.append(str(entry.adaptive_frequency))
            except Exception:
                observed_freqs.append("<不可读>")
        return [
            f"收紧生效断言[{name}]：请求频点 "
            f"{requested['adaptive_frequency']!r} 未在读回频点表 "
            f"{observed_freqs} 中——不猜对档（#122），人工核对 setup"
        ]
    try:
        observed_delta = float(chosen.max_delta)
    except Exception as exc:
        return [
            f"收紧生效断言[{name}]：max_delta 读回失败"
            f"（{type(exc).__name__}: {exc}）——不可核对如实告警（#122）"
        ]
    if not math.isclose(observed_delta, requested["max_delta"], rel_tol=1e-9):
        try:
            obs_freq = str(chosen.adaptive_frequency)
        except Exception:
            obs_freq = requested["adaptive_frequency"]
        return [
            f"收紧生效断言[{name}]：max_delta 不一致——请求 "
            f"{requested['max_delta']:.6g} vs 工程实测 {observed_delta:.6g}"
            f"（@{obs_freq}）。W8 实证 3D Layout 求解后改档不传播（回放"
            "缓存解）——改档须重建工程；W10 定谳：EDB 3D Layout schema "
            "无 MaxDelta 键（写入"
            "不可达），EDB 路径重建亦不落库——收紧判读走判读面校准或 "
            "HFSS 仲裁（见模块 docstring「自适应档写入通道」节）"
        ]
    return []


# ─── 公开入口 ───────────────────────────────────────────────────────────────


def spec_to_config_json(spec: dict) -> dict:
    """声明式版图规格 → pyedb ``configuration.load`` 兼容 dict。

    纯函数（零 pyedb 依赖、零副作用）；校验 fail-fast（缺键/类型错/越界
    给中文定位错误 :class:`EdbSpecError`）。schema 全文见模块 docstring
    （v1 统一契约：发射族形态+通用形态，正本=edb_templates 发射器样例）。

    产出分节（按需生成，空节省略）：
    - ``stackup``: materials（stackup.materials 显式段 + 层 material_props
      派生，同名冲突 fail-fast）/layers（er/tanD → permittivity/
      dielectric_loss_tangent）
    - ``modeler``: traces（路径点 mm→米，cap=flat/corner=sharp）+ planes
      （board 段 → "GND_plane" 整版矩形，与发射器 assemble_config 逐键同款）
    - ``padstacks``: definitions/instances（过孔，位置 mm→米）
    - ``ports``: wave_port（发射族，extent 因子透传）与 circuit/coax
      （coordinates 正负终端）按条目 type 分派
    - ``setups``: hfss/siwave_ac setup + 频率 sweep（发射族 f0_ghz/sweep/
      adapt 与通用 shorthand/sweeps 两形态）
    - ``boundaries``: 开放域辐射边界（仅 board 段给出时——发射族口径，
      wave_port/HFSS 求解的辐射条件；通用 spec 不注入，行为零变化）

    ``resistors`` 节**只校验不产出**（pyedb 0.83 configuration 无 lumped 段，
    schema.py 假设 5）：结构非法在此 fail-fast；归一清单由 build() 重取并
    走 pyedb lumped RLC 落地（见 :meth:`EdbAdapter._land_resistors`）。
    元段（template/schema_version/units/params）校验后跳过，零 config 产出。
    """
    spec = _as_dict(spec, "spec")
    unknown = [k for k in spec if k not in _SPEC_KEYS]
    if unknown:
        raise _fail("spec", f"未知顶层键 {sorted(unknown)}（合法键：{list(_SPEC_KEYS)}）")
    name = spec.get("name")
    if name is not None:
        name = _as_str(name, "spec", "name")
        if any(sep in name for sep in ("/", "\\", "..")) or Path(name).name != name:
            raise _fail("spec.name", f"须为纯文件名主干（禁路径分隔符与 '..'），实得 {name!r}")
    _translate_meta(spec)  # 元段 fail-fast 校验（template/版本/单位/params）
    stackup_spec = _as_dict(_req_key(spec, "stackup", "spec"), "stackup")
    materials = _translate_materials(stackup_spec)
    derived, layers, signal_layers, layer_names = _translate_stackup(
        stackup_spec, reserved_material_names={m["name"] for m in materials})
    config: dict[str, Any] = {
        "stackup": {"materials": materials + derived, "layers": layers}}
    modeler: dict[str, Any] = {}
    traces = _translate_traces(spec, signal_layers)
    if traces:
        modeler["traces"] = traces
    # board → 整版矩形平面（发射族）；非空在函数尾同时触发 boundaries。
    # 地板载体层取 config 层列表**末位**（层列表已翻转为自顶向下，末位=
    # spec 首层=物理底层信号层=发射族契约的地板载体）
    board_planes = _translate_board(spec, layers[-1]["name"], signal_layers)
    if board_planes:
        modeler["planes"] = board_planes
    if modeler:
        config["modeler"] = modeler
    definitions, instances = _translate_vias(
        spec, layer_names,
        [ly["name"] for ly in layers if ly["layer_type"] == "signal"])
    if instances:
        config["padstacks"] = {"definitions": definitions, "instances": instances}
    # 电阻只校验不进 config（防金属短路间隙；落地在 build() 走 pyedb RLC）
    _translate_resistors(spec, signal_layers)
    ports = _translate_ports(spec, signal_layers, {t["name"] for t in traces})
    if ports:
        config["ports"] = ports
    setups = _translate_sim_setup(spec)
    if setups:
        config["setups"] = setups
    if board_planes:
        config["boundaries"] = {"use_open_region": True,
                                "open_region_type": "radiation"}
    return config


@dataclass
class EdbBuildResult:
    """build() 产物：aedb 工程路径 + 配置 JSON 存证路径 + 非致命告警。"""
    aedb_path: Path
    config_json_path: Path
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchSolveResult:
    """solve_batch() 归一结果（hfss_batch 结构化 dict 的 BatchSolveResult 视图）。

    字段语义对齐 ``hfss_batch.solve_project_batch`` 返回 dict（他席契约，
    2026-10-08 实测）：``ok`` 仅在 rc==0 且未超时为真；``rc=None`` 表示
    前置失败未拉起进程。
    """
    success: bool
    message: str = ""
    log_path: Path | None = None
    artifacts: list[Path] = field(default_factory=list)
    rc: int | None = None
    timed_out: bool = False
    elapsed_s: float = 0.0


class EdbAdapter:
    """EDB 快车道适配器：声明式 spec → EDB 建库 → 批处理求解请求。

    用法::

        adapter = EdbAdapter(Path("runs/edb_demo"))
        result = adapter.build(spec)        # → EdbBuildResult
        solved = adapter.solve_batch(result.aedb_path)

    pyedb 全程惰性导入（import 在函数内）：未安装时 RuntimeError 指明
    ``pip install rfauto[edb]``；AEDT 版本缺省钉 2025 R1（对齐基准，
    env ``RFAUTO_EDB_AEDT_VERSION`` 可覆盖）。

    预载 feature-flag（#373 回归实验，缺省关闭=零行为变化）：构造参数
    ``enable_preload=True`` 或 env ``RFAUTO_PYEDB_PRELOAD``（truthy：
    1/true/yes/on）开启后，import pyedb 前先经
    ``rfauto.adapters.pyedb_preload.preload_ansys_openssl`` 预载 AnsysEM
    的 OpenSSL 副本（python-build-standalone venv 上 DotNet 后端同名
    DLL 对撞硬崩的最小可用配方，R5 实证）；参数 None=读 env，显式
    False 优先于 env。root 解析/fail-soft/幂等语义见 pyedb_preload 模块。
    """

    def __init__(self, workdir: Path, enable_preload: bool | None = None):
        self._workdir = Path(workdir)  # #140：入参一律先 Path() 收敛
        self._aedt_version = os.environ.get(_AEDT_VERSION_ENV, _DEFAULT_AEDT_VERSION)
        self._enable_preload = enable_preload  # None=读 env（缺省关）

    # ── 惰性依赖装载 ──────────────────────────────────────────────────────

    @staticmethod
    def _load_pyedb_cls(enable_preload: bool | None = None) -> type:
        """惰性导入 pyedb 并返回 Edb 类（缺装显式报错指路 extra）。

        ``enable_preload`` 三态：None=读 env ``RFAUTO_PYEDB_PRELOAD``
        （缺省关）；True/False=显式覆盖 env。开启时 import 前先预载
        （#373 R5 配方；fail-soft 信封，失败不阻断——#105）。
        """
        if enable_preload is None:
            raw = os.environ.get(_PYEDB_PRELOAD_ENV, "")
            enable_preload = raw.strip().lower() in _PYEDB_PRELOAD_TRUTHY
        if enable_preload:
            from rfauto.adapters.pyedb_preload import preload_ansys_openssl

            preload_ansys_openssl()  # fail-soft 信封；失败不阻断（#105）
        try:
            import pyedb
        except ImportError as exc:  # pragma: no cover - 分支由假包注入测试覆盖
            raise RuntimeError(
                "pyedb 未安装（EDB 快车道通道依赖）：请安装可选依赖 "
                "`pip install rfauto[edb]`（pyaedt 环境已随装时可直接复用）"
            ) from exc
        edb_cls = getattr(pyedb, "Edb", None)
        if edb_cls is None:
            raise RuntimeError("pyedb 包异常：无 Edb 入口类（版本不兼容？）——"
                               "请核对 pyedb>=0.83")
        return edb_cls

    # ── 建库 ─────────────────────────────────────────────────────────────

    def _alloc_aedb_path(self, stem: str) -> tuple[Path, list[str]]:
        """分配 .aedb 路径：占用时数字后缀顺移（不覆盖既有工程）。"""
        warnings: list[str] = []
        candidate = self._workdir / f"{stem}.aedb"
        n = 0
        while candidate.exists():
            n += 1
            candidate = self._workdir / f"{stem}_{n}.aedb"
        if n:
            warnings.append(f"{stem}.aedb 已存在，改用新工程 {candidate.name}"
                            "（不覆盖既有产物）")
        return candidate, warnings

    def build(self, spec: dict) -> EdbBuildResult:
        """声明式 spec → 配置 JSON 落盘 + pyedb 建库（.aedb）。

        步骤：spec_to_config_json（fail-fast 校验+翻译）→ config JSON 落盘
        存证 → 惰性导入 pyedb → 新建 .aedb → ``configuration.load(config,
        apply_file=True)`` 注入 → resistors 逐条 pyedb lumped RLC 落地
        （无 resistors 键/空列表=零额外调用，行为零变化）→ save/close
        （release 纪律：close 必须 finally，#265 同族）。同名工程占用时
        数字后缀顺移不覆盖。

        自适应档（sim_setup.adapt.max_delta/max_passes）随 configuration.load
        **建模期写入请求档**——3D Layout setup 的建模期写入通道（求解后改档
        不传播，W8 实证改档须重建，见模块 docstring「3D Layout setup 自适应
        档写入通道」节及其 W10 定谳：EDB 3D Layout schema 无 MaxDelta 键，
        请求档在 EDB 路径写入不可达、重建亦不落库）；批解后可用
        :meth:`verify_adapt_tightening` 核对存储请求档一致（写入面）。
        """
        config = spec_to_config_json(spec)  # fail-fast：先校验后落盘
        # 电阻归一清单（纯函数幂等重取；结构合法性已由上面校验保证）
        signal_layers = {ly["name"] for ly in config["stackup"]["layers"]
                         if ly["layer_type"] == "signal"}
        resistors = _translate_resistors(spec, signal_layers)
        self._workdir.mkdir(parents=True, exist_ok=True)
        stem = str(spec.get("name") or "edb_layout")
        aedb_path, warnings = self._alloc_aedb_path(stem)
        # 配置 JSON 与 aedb 工程同名配对（后缀顺移后各场 build 的存证互不覆盖）
        config_json_path = self._workdir / f"{aedb_path.stem}_config.json"
        # JSON 存证（ensure_ascii=False 保持中文可读；下游可用
        # edb.configuration.load 该文件复现，export() 侧互证）
        config_json_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        edb_cls = self._load_pyedb_cls(self._enable_preload)
        edb = edb_cls(edbpath=str(aedb_path), isreadonly=False,
                      version=self._aedt_version)
        try:
            configuration = getattr(edb, "configuration", None)
            if configuration is None or not hasattr(configuration, "load"):
                raise RuntimeError("pyedb Edb 实例无 configuration.load 接口"
                                   "（版本不兼容？）——请核对 pyedb>=0.83")
            configuration.load(config, append=True, apply_file=True)
            if resistors:
                self._land_resistors(edb, resistors)
            edb.save_edb()
        finally:
            edb.close_edb()  # #265 同族：不 release 会留孤儿会话/文件锁
        return EdbBuildResult(aedb_path=aedb_path,
                              config_json_path=config_json_path,
                              warnings=warnings)

    def _land_resistors(self, edb: Any, resistors: list[dict[str, Any]]) -> int:
        """逐条把 spec 电阻落成 pyedb lumped RLC 边界（点端子对，间隙保持
        开路无金属体）。

        口径逐字对齐 pyedb 0.83.0 自家实现（出处按行）：
        - 端子创建：``excitation_manager.create_point_terminal(x, y, layer,
          net, name)``（dotnet/database/source_excitations.py:951-962）——
          坐标 EDB 数据库单位=米（同 trace path 口径，mm×1e-3）；
        - 边界类型：双端子 ``boundary_type = "RlcBoundary"``（cell/terminal/
          terminal.py:35-46 字符串映射 + :174-178 setter，= 裸 API
          ``Cell.Terminal.BoundaryType.RlcBoundary``）；
        - RLC 参数：``core.Utility.Rlc()``（edb.py:719 ``core`` = 裸
          ``Ansoft.Edb`` 命名空间，= pyedb 内部 ``self._edb.Utility.Rlc()``
          同一入口）；**纯电阻处方逐字取自 SourceType.Rlc 分支**
          （source_excitations.py:898-908）：CEnabled=False/LEnabled=False/
          REnabled=True/R=edb_value(r_ohm)（裸数值透传，官方同款——
          :1757 create_rlc_boundary_on_pins；Utility.Value 缺省单位欧姆）；
        - 参数挂接：正端子 ``_edb_object.SetRlcBoundaryParameters(rlc)``
          （:1760 同款；wrapper 无此属性故走裸对象）+ 参考端子接线
          ``pos.reference_terminal = ref``（terminal.py:218-221）；
        - 参考端子命名 ``{name}_ref``（:1765 同款）；端子名创建时已传入
          （PointTerminal.Create name 参数），不再补 SetName。

        pin 版 ``create_rlc_boundary_on_pins``（:1724）需 PadstackInstance
        引脚——本 spec 电阻是走线间隙（无引脚）故走点端子对；端子创建失败
        （net 不存在/点位非法）经 pyedb RuntimeError 包装电阻名上下文后
        重抛（fail-fast 不静默）。
        """
        excitation = getattr(edb, "excitation_manager", None)
        if excitation is None or not hasattr(excitation, "create_point_terminal"):
            raise RuntimeError("pyedb Edb 实例无 excitation_manager."
                               "create_point_terminal 接口（版本不兼容？）"
                               "——请核对 pyedb>=0.83")
        core = getattr(edb, "core", None)
        if core is None or not hasattr(core, "Utility"):
            raise RuntimeError("pyedb Edb 实例无 core.Utility 裸 API 入口"
                               "（版本不兼容？）——请核对 pyedb>=0.83")
        for res in resistors:
            (x0, y0), (x1, y1) = res["path_mm"][0], res["path_mm"][-1]
            try:
                pos = excitation.create_point_terminal(
                    x0 * _MM_TO_M, y0 * _MM_TO_M, res["layer"], res["net"],
                    name=f"{res['name']}_p")
                ref = excitation.create_point_terminal(
                    x1 * _MM_TO_M, y1 * _MM_TO_M, res["layer"], res["net"],
                    name=f"{res['name']}_ref")
            except RuntimeError as exc:
                raise RuntimeError(
                    f"电阻 {res['name']!r} 端子创建失败（layer={res['layer']!r}"
                    f" net={res['net']!r}——net 须为版图既有 net，点位须落"
                    f"金属）：{exc}") from exc
            pos.boundary_type = "RlcBoundary"
            ref.boundary_type = "RlcBoundary"
            rlc = core.Utility.Rlc()
            # 纯电阻处方（source_excitations.py:898-908 逐字）：L/C 关断
            rlc.CEnabled = False
            rlc.LEnabled = False
            rlc.REnabled = True
            rlc.R = edb.edb_value(res["r_ohm"])
            pos._edb_object.SetRlcBoundaryParameters(rlc)
            pos.reference_terminal = ref
        return len(resistors)

    # ── 批处理求解（转调他席 hfss_batch 通道）─────────────────────────────

    @staticmethod
    def _normalize_batch_result(raw: Any) -> BatchSolveResult:
        """hfss_batch 返回值 → BatchSolveResult（dict 归一/透传双形态）。"""
        if isinstance(raw, BatchSolveResult):
            return raw
        if isinstance(raw, dict):
            # hfss_batch.solve_project_batch 结构化 dict 契约（他席 docstring
            # 口径）：{ok, rc, timed_out, logfile, logfile_tail, artifacts,
            # elapsed_s, errors}。判缺一律显式 is None/isinstance（#364④
            # falsy 陷阱纪律：数值可达 0 的位禁 or 缺省惯语）。
            errors = raw.get("errors")
            if isinstance(errors, (list, tuple)):
                messages = [str(e) for e in errors if e]
            elif errors:
                messages = [str(errors)]
            else:
                messages = []
            timed_out = bool(raw.get("timed_out", False))
            ok = raw.get("ok")
            rc = raw.get("rc")
            logfile = raw.get("logfile")
            artifacts_raw = raw.get("artifacts")
            artifacts = ([Path(a) for a in artifacts_raw]
                         if isinstance(artifacts_raw, (list, tuple)) else [])
            elapsed = raw.get("elapsed_s")
            return BatchSolveResult(
                success=bool(ok) if ok is not None else False,
                message="; ".join(messages)
                        or ("watchdog 超时" if timed_out else ""),
                log_path=Path(logfile) if logfile else None,
                artifacts=artifacts,
                rc=rc if rc is None or isinstance(rc, int) else None,
                timed_out=timed_out,
                elapsed_s=float(elapsed) if isinstance(elapsed, (int, float)) else 0.0,
            )
        # 其他形态不臆造：如实记失败与形态名（不静默当成功）
        return BatchSolveResult(
            success=False,
            message=f"hfss_batch 返回形态不可识别: {type(raw).__name__}")

    def solve_batch(self, aedb_path: Path, timeout_s: float = 3600.0) -> BatchSolveResult:
        """向 hfss_batch 批处理通道发求解请求（只发请求，不解析 S 参数输出）。

        内部转调 ``rfauto.adapters.hfss_batch.solve_project_batch``（他席
        实现；未落地时 RuntimeError 明确报错——hasattr 惰性导入纪律）。
        返回值按其结构化 dict 契约归一为 :class:`BatchSolveResult`（已是
        BatchSolveResult 则原样透传，双形态兼容）。``timeout_s`` 直通其
        watchdog 超时语义。
        """
        import importlib

        try:
            mod = importlib.import_module("rfauto.adapters.hfss_batch")
        except ImportError as exc:
            raise RuntimeError(
                "hfss_batch 批处理求解通道未落地（他席交付中）：solve_batch "
                "暂不可用；建库面 build() 不受影响"
            ) from exc
        fn = getattr(mod, "solve_project_batch", None)
        if not callable(fn):
            raise RuntimeError(
                "rfauto.adapters.hfss_batch 缺 solve_project_batch 可调用入口"
                "（契约不完整）——solve_batch 暂不可用")
        aedb_path = Path(aedb_path)  # #140 口径
        if not aedb_path.exists():
            raise FileNotFoundError(f"aedb 工程不存在: {aedb_path}")
        return self._normalize_batch_result(fn(aedb_path, timeout_s=timeout_s))

    # ── 收紧生效断言（W8 仲裁建议 2）──────────────────────────────────────

    def verify_adapt_tightening(self, build_result: EdbBuildResult) -> list[str]:
        """核对工程内 setup 实际自适应档与请求档一致（不一致/不可核对=告警）。

        W8 仲裁建议 2（#333 族）：EDB 3D Layout 的建模期写入通道
        =configuration.load 随建库写入；求解后改档不传播（重载走缓存解，
        W8 真机实证）。本断言在**批解后**调用：重开建库工程（只读）读回
        setup 实际 max_delta，与 config 存证（``build_result.
        config_json_path``，即建模期注入的请求正本）逐 setup 核对——任一
        setup 的 max_delta 与请求不一致，或读回链路不可用，都以告警字符
        串返回（best-effort，#105：断言不抛异常、不阻塞判读主路径；不可
        证实如实告警不冒充通过，#122）。

        断言语义边界（W9 勘误落口径，W10 定谳补全，真机复验档）：
        本断言核的是**存储请求档=读回档**
        （写入面一致），**不是**"求解按新档收敛"的行为效力——W9 重查实证
        props 建库期写入读回一致后批解仍按 0.02 准则停机
        （TIGHTENING_NOT_EFFECTIVE）；W10 进一步定谳 configuration.load 通道
        的请求可能根本不落库（EDB 3D Layout schema 无 MaxDelta 键）——该
        "未落库"形态由本断言告警暴露，"已落库但不消费"形态本断言原理上
        不可检出；求解效力须另做读数/mtime 差异对比。

        Args:
            build_result: :meth:`build` 产物（aedb 路径 + config 存证路径
                配对——存证即建模期注入的请求记录）。

        Returns:
            告警清单（空=存证无 hfss 单频自适应请求（无可核对项，vacuous
            真）或全部 setup 逐项一致）。

        用法（solve_batch 之后）::

            result = adapter.build(spec)
            solved = adapter.solve_batch(result.aedb_path)
            for warning in adapter.verify_adapt_tightening(result):
                ...  # 记账/上报：请求档未在工程内生效
        """
        aedb_path = Path(build_result.aedb_path)  # #140 口径
        config_json_path = Path(build_result.config_json_path)
        requested = _load_requested_adapt(config_json_path)
        if requested is None:
            return [
                f"收紧生效断言不可核对：config 存证缺失/损坏/畸形 "
                f"{config_json_path}（请求档无从读取，#122 不冒充通过）"
            ]
        if not requested:
            return []  # 存证无 hfss 单频自适应请求——无可核对项
        try:
            edb_cls = self._load_pyedb_cls(self._enable_preload)
        except RuntimeError as exc:
            return [
                f"收紧生效断言不可核对：pyedb 不可用（{exc}）——"
                "工程内 setup 档未核实（#122）"
            ]
        try:
            edb = edb_cls(edbpath=str(aedb_path), isreadonly=True,
                          version=self._aedt_version)
        except Exception as exc:
            return [
                f"收紧生效断言不可核对：重开工程失败 {aedb_path.name}"
                f"（{type(exc).__name__}: {exc}）——#122 不冒充通过"
            ]
        warnings_out: list[str] = []
        try:
            try:
                setups = getattr(edb, "setups", None)
                if not isinstance(setups, dict):
                    raise RuntimeError(
                        "edb.setups 不可读（属性缺失或非 dict——版本兼容？）")
            except Exception as exc:
                warnings_out.append(
                    f"收紧生效断言不可核对（best-effort #105）：edb.setups "
                    f"读回失败（{type(exc).__name__}: {exc}）——#122 不冒充通过")
            else:
                for name, req in requested.items():
                    warnings_out.extend(_verify_one_setup_adapt(name, req, setups))
        finally:
            edb.close_edb()  # #265 同族：只读回一会话也必须释放
        return warnings_out
