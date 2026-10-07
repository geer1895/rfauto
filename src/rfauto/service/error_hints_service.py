"""error_hints_service：错误消息 → 可行动提示映射层（XC 错误信息工程）。

**纯映射层**（硬规则 7 的对偶：映射表也是确定性数据，LLM/人不改判据）：
仓库高频错误指纹（本仓内核/引擎/环境真实错误串的子串或正则）→
{hint（可行动修复建议）, refs（坑号/docs 指针，#NNN 按 D1 裁决保留）,
severity}。映射表模块内自持（LINT_REGISTRY 惯例），新增条目=加一行
_HINT_RULES（pattern/match/hint/refs/severity 五字段）。

设计约束：
- 匹配永远基于**异常类型名 + 消息原文子串**，不做模糊语义推断；
- 一条消息可命中多条规则（全部返回，按 severity 排序 error>warn>info）；
- 未命中 → 空表如实返回（不编造提示）；
- 零 I/O、零物理数字（提示里的阈值都指回内核守卫原文）。
"""

from __future__ import annotations

import re
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

_SOURCE = "rfauto.service.error_hints_service"

#: 规则表：pattern 子串或正则；refs=坑号/文档指针；severity: error|warn|info
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

_SEV_ORDER = {"error": 0, "warn": 1, "info": 2}


def _compiled_rules() -> list[tuple[re.Pattern[str] | str, dict[str, str]]]:
    out: list[tuple[re.Pattern[str] | str, dict[str, str]]] = []
    for rule in _HINT_RULES:
        if rule.get("match") == "regex":
            out.append((re.compile(rule["pattern"]), rule))
        else:
            out.append((rule["pattern"], rule))
    return out


def hint_for_message(text: str) -> dict[str, Any]:
    """错误消息文本 → 命中提示表（全部命中随行；未命中 hits=[]）。"""
    if not isinstance(text, str):
        return error_envelope(["text 必须是字符串"])
    hits: list[dict[str, str]] = []
    for pattern, rule in _compiled_rules():
        matched = (pattern in text if isinstance(pattern, str)
                   else pattern.search(text) is not None)
        if matched:
            hits.append({"pattern": rule["pattern"],
                         "match": str(rule.get("match", "substring")),
                         "hint": rule["hint"], "refs": rule["refs"],
                         "severity": rule["severity"]})
    hits.sort(key=lambda h: _SEV_ORDER.get(h["severity"], 3))
    return ok_envelope(hits=hits, n_hits=len(hits), source=_SOURCE)


def hint_for_exception(exc: BaseException) -> dict[str, Any]:
    """异常对象 → 提示表（类型名+消息原文一并入匹配）。"""
    text = f"{type(exc).__name__}: {exc}"
    out = hint_for_message(text)
    out["exception_type"] = type(exc).__name__
    return out


def list_hint_rules() -> dict[str, Any]:
    """规则表清单（确定性序；诊断/文档消费面）。"""
    return ok_envelope(rules=[dict(r) for r in _HINT_RULES], n_rules=len(_HINT_RULES), source=_SOURCE)


def hint_for_message_enhanced(
    message: str, *, use_systemone: bool = False, provider: str | None = None
) -> dict[str, Any]:
    """第二档增强：确定性映射优先照旧，零命中时可选 System One 选规则。

    - ``hint_for_message`` 命中（或 ``use_systemone=False``，或缺省）→
      **原样返回确定性结果，System One 通道零触碰**；
    - 仅当零命中且 ``use_systemone=True``：构造 choice 问题（options=规则
      pattern 清单）走 ``ask_systemone`` 选规则出单条 hint（信封附
      ``enhanced=True``+``systemone_provider``）；
    - 任何失败（provider 不可用/降级/选索引越界/通道异常）→ 回退确定性
      结果（零命中=空表如实，不编造提示；#105：增强档永不遮蔽主路径）。
    本函数只读不写：不改既有 hint_for_message/_emit 任何行为。
    """
    base = hint_for_message(message)
    if not isinstance(message, str) or base.get("n_hits") or not use_systemone:
        return base
    try:
        from rfauto.service.systemone_service import ask_systemone

        rules = list_hint_rules().get("rules") or []
        options = [str(r.get("pattern", "")) for r in rules]
        if not options:
            return base
        question = {
            "kind": "choice",
            "question": "为下述错误消息选择最可能的修复提示规则（只返回选项）：\n"
                        + message,
            "options": options,
            "context": {"task": "hint_rule_select", "n_options": len(options)},
        }
        out = ask_systemone(question, provider=provider)
        if not out.get("ok") or out.get("degraded"):
            return base
        selected = (out.get("answer") or {}).get("selected")
        if isinstance(selected, int) and not isinstance(selected, bool):
            idx = selected
        else:
            idx = options.index(str(selected)) if str(selected) in options else -1
        if not (0 <= idx < len(rules)):
            return base
        rule = rules[idx]
        hit = {"pattern": rule["pattern"],
               "match": str(rule.get("match", "substring")),
               "hint": rule["hint"], "refs": rule["refs"],
               "severity": rule["severity"]}
        return ok_envelope(hits=[hit], n_hits=1, source=_SOURCE,
                           enhanced=True,
                           systemone_provider=out.get("provider"))
    except Exception:  # #105：增强档任何失败回退确定性结果
        return base
