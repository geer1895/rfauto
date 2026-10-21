"""错误提示规则表叶（T1 解环；架构批 W6-S1）。

从 error_hints_service 叶化：_HINT_RULES/_SOURCE/list_hint_rules 是
纯确定性数据+读面。systemone_service 的 hint_question_for_message
改读本叶，静态图上不再出现 systemone→error_hints 边
（error_hints↔systemone 2-环断；ask_systemone 方向保留单向）。
测试缝不变：test_w1_a_wiring 的 ``setattr(error_hints_service,
"list_hint_rules", ...)`` 钉的是 error_hints 模块属性（其内部
bare 调用经再导出照常命中）；_SOURCE 字符串保持原值逐位不变。
"""
from __future__ import annotations

from typing import Any

from rfauto.service.envelope import ok_envelope

_SOURCE = "rfauto.service.error_hints_service"


_HINT_RULES: tuple[dict[str, str], ...] = (
    {"pattern": "网格欠分辨", "match": "substring",
     "hint": "收紧 mesh_resolution_mm：渲染守卫要求特征尺寸 ≥4·NEAR"
             "（NEAR=BASE/4），按报错里给出的上限收紧网格档或加大特征尺寸",
     "refs": "#311/#266（缝与过孔网格守卫）", "severity": "error"},
    {"pattern": "孔间缝", "match": "substring",
     "hint": "过孔缝隙 s−d ≤ NEAR 时缝内零内部网格线（SmoothMesh 只细分"
             " >NEAR 区间）——收紧 mesh ≤ 4·(s−d) 或加大缝距",
     "refs": "#311（round6 B-LOW#4）", "severity": "error"},
    {"pattern": "Excitation inside", "match": "substring",
     "hint": "openEMS 激励盒跨满吸收边界截面会激起零模 DC 漂移——激励盒"
             "内缩 ≥2·BASE（网格单位）",
     "refs": "#253", "severity": "error"},
    {"pattern": "Mur-ABC", "match": "substring",
     "hint": "柱坐标（CoordSystem=1）不支持 MUR 吸收边界（静默退化 PEC）"
             "——柱坐标一律用 PML_8",
     "refs": "#232", "severity": "error"},
    {"pattern": "|S11|", "match": "substring",
     "hint": "max|S11|>1 先查 NrTS/FC 窗截断（窄窗长脉冲被截断出非物理"
             "反射），再怀疑物理——FC 窗要覆盖脉冲全程",
     "refs": "#262/#84", "severity": "warn"},
    {"pattern": "P1 位置共点失败", "match": "substring",
     "hint": "compose 两 pin 未共点（容差 1e-9 m）——检查实例 params 与"
             "连接声明；组合器按连接吸附摆位，勿手摆 frame",
     "refs": "DP-8 P1 守卫（core/compose/layout_netlist）", "severity": "error"},
    {"pattern": "P3 阻抗失配", "match": "substring",
     "hint": "两 pin z_ref 相对差超 1e-6——确认截面/端口设计一致；确需"
             "组合在该 connection 显式 allow_mismatch: true（豁免留痕）",
     "refs": "DP-8 P3 守卫", "severity": "error"},
    {"pattern": "P5 截面不兼容", "match": "substring",
     "hint": "基板 h/εr 必须逐位一致（同 kind 特征尺寸一致）——统一链上"
             "实例 substrate 声明",
     "refs": "DP-8 P5 守卫", "severity": "error"},
    {"pattern": "精度档案无 kernel", "match": "substring",
     "hint": "XC-P 精度档案键未注册——用报错里列出的可用 kernel 清单改名，"
             "或在 knowledge/precision_profiles.yaml 登记新档案",
     "refs": "XC-P（core/precision_profiles）", "severity": "error"},
    {"pattern": "确认域外", "match": "substring",
     "hint": "精度档案 REFUSE：使用点在内核声明有效域外——按档案"
             " valid_domain 收缩使用域或换域内内核（不外推）",
     "refs": "XC-P/铁律 5", "severity": "error"},
    {"pattern": "cannot reshape array of size", "match": "substring",
     "hint": "skrf 只按 .sNp 扩展名推断端口数——检查 Touchstone 文件名"
             " n_ports 与数据块结构（1 端口数据写成 .s2p 即此错）",
     "refs": "#248", "severity": "error"},
    {"pattern": "GrpcApi\\w*", "match": "regex",
     "hint": "HFSS gRPC：① Hfss 相对 -outdir 会挂起——outdir 一律绝对"
             "路径；② 检查孤儿 ansysedt（父进程死未 release_desktop）按"
             " PID 核对命令行后清理",
     "refs": "#243/#265/#308", "severity": "error"},
    {"pattern": "license", "match": "substring",
     "hint": "求解器 license 席位问题——先跑 rfauto remote probe 的 "
             "license_preflight 预检（发射前一级门）",
     "refs": "remote_service.license_preflight", "severity": "warn"},
    {"pattern": "ModuleNotFoundError", "match": "substring",
     "hint": "缺依赖：可选依赖必须声明进 extras——pip install -e "
             "'.[<extra>]' 后复跑；'恰好装过'会掩盖缺声明",
     "refs": "开源批③/pyproject extras", "severity": "error"},
    {"pattern": "unsupported format character", "match": "substring",
     "hint": "argparse/typer help 字符串里的 % 要写 %%——literal 百分号"
             "触发 _expand_help 格式化错",
     "refs": "#305", "severity": "error"},
    {"pattern": "coefficient estimates", "match": "substring",
     "hint": "vector_fit 定阶断言禁用 n_poles_total（skrf 存储极点数，共轭"
             "对只存一个）——比较 order.used 或有效阶 n_real+2·n_cmplx",
     "refs": "#286", "severity": "warn"},
    {"pattern": "Excitation inside Mur", "match": "substring",
     "hint": "同 Excitation inside——激励盒内缩 ≥2·BASE",
     "refs": "#253", "severity": "error"},
)


def list_hint_rules() -> dict[str, Any]:
    """规则表清单（确定性序；诊断/文档消费面）。"""
    return ok_envelope(rules=[dict(r) for r in _HINT_RULES], n_rules=len(_HINT_RULES), source=_SOURCE)
