"""EDB 快车道批处理产物健康门（hfss_batch 契约适配，service 层质量门）。

产物形态适配动机：仓内既有体检（service/health_service.py G11）面向
``runs/<run_id>/`` 目录形态（openEMS sparams.csv 掩码载体 / HFSS 会话
Touchstone / meta.json 事实源）；EDB 快车道产物 =
``rfauto.adapters.hfss_batch.solve_project_batch`` 一次性批处理的结构化
回执 dict（``{ok, rc, timed_out, project, logfile, artifacts, export,
errors, ...}``，含 ``-batchextract`` 批后导出段）+ 批后导出的
Touchstone（.sNp）+ 批处理日志——既无 run 目录也无 meta.json，直接复用
G11 目录体检会"无可识别体检产物"全空 suspect。本模块消费批处理回执
dict + Touchstone 文件（skrf 读，health_service._load_touchstone 同款
懒加载惯例），产出独立三态质量门。

数值门边界纪律（项目规则 #376 家法，2026-10-08/09 W5 回取复核席实证）：
本门全部闭边界 verdict 判据一律留 1e-9 家法余量（与
core/trl_solt._LINE_PASSIVE_MARGIN 同源）——健康门闭区间语义（实测
≤ 门 / σmax ≤ 1+容差 / 窗双边闭）在恰等边界读数上字面比较会被量化
噪声系统性误 FAIL，噪声是门实现侧必须吸收的、不是数据侧缺陷。三
常量统一表（字段=常量名/门/噪声源/量级论证）：

- ``_S11_DIP_DB_EPS`` = 1e-9 dB。门=``s11_dip`` 谷深（实测 ≤ 门为过；
  单谷 @f0 与多谷最深谷两分支同一比较式）。噪声源=门值恰等的物理
  幅值 |Γ|=10^(门/20) 经 double 域 20·log10 往返量化（门值域扫描
  [-40,-1] 0.1dB 步长实测 30/391 个门值落违约侧，如 -7.2dB 读
  -7.199999999999999）。量级论证=比门粒度（通用惯例 1dB）低 9 个
  量级，不掩盖真违约。
- ``_SPLIT_WINDOW_DB_EPS`` = 1e-9 dB。门=``s_split_window`` 等分分配
  窗（[-3.8,-2.5] 双边闭；出窗判据上下界各留余量）。噪声源=同款
  dB 往返量化（-2.5dB 恰等上界腿实测读 -2.4999999999999996）。量级
  论证=比窗粒度（0.1dB）低 8 个量级。
- ``_PASSIVITY_LINEAR_EPS`` = 1e-9（线性域）。门=``passivity`` σmax ≤
  1+容差（1.01，带缘闭）。噪声源=容差 1.01 的 double 表示+SVD 舍入
  （实测 114/201 组合读 1.0100000000000002，偏差 +2.2e-16）。量级
  论证=比容差粒度（0.01）低 14 个量级；无 dB 换算，噪声源不同于前
  两者而暴露面同型。

恰等边界回归钉必配（构造恰等例断言不翻 verdict）——tests/unit/
test_edb_health_gate.py 三钉与三常量一一对应。

第四处核查结论（2026-10-09 逐判据审计：全收口）——本模块其余数值
比较均非 #376 类闭边界门：``reciprocity`` 的 ``worst >=
RECIPROCITY_TOLERANCE``（FAIL 侧）门义即边界=违约（非恰等=过语义），
且 |Sij−Sji| 与容差同在线性域直读、无门值↔量测表示变换（30/391、
114/201 类门值构造越界机制在此不存在），健康不对称读数距容差多个
量级、无自然恰等构造面，并与 core/solve_health G11 同式跨门一致；
f0 扫频跨度 ``f_min ≤ f0 ≤ f_max`` 为成员性前置（出跨度 → UNKNOWN
不判，无误 FAIL 面）；多谷检测的局部极小/间距归并为同源网格内部
逻辑（平手=链式归并保持既有单谷路径，谷锚的门比较另有
``_S11_DIP_DB_EPS`` 保护）；其余为整型形态/契约比较与已带
rtol=1e-6 容差的 ``np.isclose``（f0 落格兜底）。

判据族（七因子+条件性 f0_offset 谷位标记，全部确定性数值规则——铁律
7：LLM/agent 永不产生物理数字，本门只消费求解器实测与批处理结构化
回执，门常量为判据非产物；``s_split_window`` 为模板作用域判据未登记
族不计入 criteria，``f0_offset`` 仅在 f0 邻域检出多谷时出现）：

- ``solve_status``：求解 rc/超时态。``rc==0 且未超时`` → PASS；
  ``timed_out`` → FAIL（watchdog 整树击杀后残留产物不可信，#157 家族）；
  ``rc is None`` → FAIL（前置失败：路径/exe/发射，进程未拉起）；
  ``rc!=0`` → FAIL；回执缺失/非 dict → UNKNOWN（#122 不冒充）。
- ``touchstone``：存在性 + 可读性。发现链=显式路径 > 回执
  ``export.out_file`` > 回执 ``artifacts`` 扫 .sNp；候选缺失/文件不存在
  → FAIL（``-BatchSolve`` 只求解不产网络参数的断链指纹，2026-10-08
  真机冒烟）；skrf 环境缺失 → UNKNOWN（不可证实，#122）；解析失败/
  形状非法 → FAIL（证据损坏是具体缺陷，#316 多报方向）。
- ``port_count``：Touchstone 实测端口数 vs spec 声明端口数（wave_port
  ``port_nr`` / 通用 ``number`` 同池取最大编号）；spec 未声明 → UNKNOWN
  不硬判；不符 → FAIL（#248/#309 端口数契约族）。
- ``passivity``：σmax ≤ 1 + 容差（复数域全带宽；容差与
  core.solve_health.PASSIVITY_TOLERANCE 同源 1%，SpecEvaluator
  check_passivity 同款；恰等带缘留 1e-9 线性域余量
  ``_PASSIVITY_LINEAR_EPS``，量化噪声不误判）；含非有限值 → FAIL
  （数据损坏）。
- ``s11_dip``：S11@f0 谷深（dB）按 spec.sim_setup 单频口径（发射族
  ``f0_ghz`` / 通用形态 ``adaptive_freq_ghz``）；f0 不在扫频跨度内 →
  UNKNOWN 不外推；spec 未声明 f0 → UNKNOWN（未声明判定目标，#122）；
  门常量按模板作用域分派（#274 家法）：调用方显式覆盖 > 模板登记表 >
  通用缺省门，登记表值 None = 该族显式不设门（如实 UNKNOWN 不硬套
  他族门）；恰等门值留 1e-9 dB 余量 ``_S11_DIP_DB_EPS``（dB 换算
  量化噪声不误 FAIL，与 s_split_window 同家法）。W7 语义扩展
  （2026-10-08）：f0 对称窗内检出多谷（相邻极小间距>窗宽 5% 计独立
  谷）时本因子改锚**最深谷**（主谷@f0 典型形态与 at-f0 读数同值=
  现有行为保持），并触发 ``f0_offset`` 谷位标记因子。
- ``f0_offset``（条件性谷位标记，W7 冒烟语义扩展）：仅当 f0 邻域
  ±对称窗内谷计数>1（ratrace 双谷 1.97/2.67GHz 夹持类多模/非谷形态）
  → UNKNOWN + detail 标 ``multi_dip_near_f0``——argmin 谷/插值 f0 的
  谷位标记语义失真（#298 家法：峰位/频偏判据只在单谷同口径可用），
  不冒充 PASS 也不硬 FAIL（#122）；单谷/无谷不出现本判据（既有行为
  零变化），既有 UNKNOWN 路径（无数据/未声明 f0/f0 出跨度）不触发
  多谷检测。
- ``s_split_window``：|S21|/|S31|@f0 等分分配窗（dB，双边界闭区间），
  门常量按模板作用域分派（#274 家法）：调用方显式窗 >
  ``S_WINDOW_DB_BY_TEMPLATE`` 登记表；**无通用缺省窗**——等分分配窗是
  功分器族专属物理语义，未登记且无显式窗的族不设本判据（criteria 键
  缺席=不判，不硬套他族门，也不冒充 PASS）。登记出处=W1 冒烟门语义
  仲裁（2026-10-09，runs/edblane85/w1_smoke REPORT §3.2）：理想等分
  分配损耗 -3.01dB，健康实测 -3.19/-3.26；冒烟任务书字面门"各
  ≤-3.8dB"是单边下界语义错位，会误杀任何健康功分器——裁定物理窗
  [-3.8, -2.5]dB（下界=3dB 分配+0.8dB 实现容差，上界排除异常增益/
  提取伪象）。
- ``reciprocity``：|Sij−Sji| 逐对（掩码纪律 #314——Touchstone 是全矩阵
  无掩码载体，按全矩阵判但 detail/evidence 如实声明
  ``measured_mask=None`` 语义；单端口无跨端口对 = 平凡真如实注记）。

verdict 规则（#122）：任一 FAIL → FAIL；否则任一 UNKNOWN → UNKNOWN
（不冒充 FAIL 也不冒充 PASS）；全 PASS → PASS。``ok`` 仅作报告字段
（= verdict==PASS），非门禁判据（G11 同款口径）。

best-effort（#105）：判读输入缺失/畸形不抛异常，落结构化
UNKNOWN/FAIL + ``errors`` 留痕；单因子异常不传染。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.solve_health import (
    LESSON_PASSIVITY,
    LESSON_RECIPROCITY,
    PASSIVITY_TOLERANCE,
    RECIPROCITY_TOLERANCE,
)

# 注意：本模块**不定义 __all__**——公开 API 快照（scripts/check_public_api）
# 只登记带 __all__ 的模块，无 __all__ 文件记私有零快照变化（新模块出生
# 不触发 --generate 评审动作；edb_adapter 同款口径）。

#: 报告 schema 标识（JSON 消费面稳定钉）。
SCHEMA = "edb-health-gate-v1"

# ---------------------------------------------------------------------------
# 状态与 verdict 常量（三态；与 G11 的 healthy/unhealthy/suspect 词汇不同——
# 本门是批处理产物门，消费方按本词汇表消费）
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_UNKNOWN = "UNKNOWN"

# factor 键名（供服务层/门禁按名取用；passivity/reciprocity 与 G11 内核
# 同名——同一物理判据跨门同名，便于报表侧对齐）
FACTOR_SOLVE_STATUS = "solve_status"
FACTOR_TOUCHSTONE = "touchstone"
FACTOR_PORT_COUNT = "port_count"
FACTOR_PASSIVITY = "passivity"
FACTOR_S11_DIP = "s11_dip"
FACTOR_S_SPLIT_WINDOW = "s_split_window"

#: 分配窗边界浮点余量（2026-10-08 回取复核席实证缺陷修复）：恰落在窗
#: 边界的物理幅值经 double 域 20·log10(10^(x/20)) 换算带 ~1e-15 dB 量化
#: 噪声（实测 -2.5 dB 恰等腿读 -2.4999999999999996，越上界 4.4e-16），
#: 闭区间字面比较会误判出窗——与 core/trl_solt._LINE_PASSIVE_MARGIN 同
#: 家法留容差；1e-9 dB 比窗粒度（0.1 dB）低 8 个量级，对任何真实判读
#: 零影响。
_SPLIT_WINDOW_DB_EPS = 1e-9
FACTOR_RECIPROCITY = "reciprocity"
FACTOR_F0_OFFSET = "f0_offset"

# 教训编号（）——写进每条判据，保证报告可回溯到踩坑原文
LESSON_SOLVE_STATUS = "#157（watchdog 整树击杀，击杀后残留产物不可信）"
LESSON_TOUCHSTONE = "#316（证据损坏多报方向）+ 2026-10-08 -BatchSolve 不产网络参数断链"
LESSON_PORT_COUNT = "#248/#309（Touchstone 端口数契约：skrf 按扩展名推 rank/多模改名）"
LESSON_S11_DIP = "#274（门常量按模板作用域分派，非适用族不硬套）"
LESSON_S_SPLIT_WINDOW = (
    "W1 冒烟门语义仲裁（2026-10-09：理想等分 -3.01dB，健康实测"
    " -3.19/-3.26，字面 ≤-3.8 单边门误杀健康功分器）"
    "+ #274（模板作用域分派，非适用族不设判据）"
)
LESSON_F0_OFFSET = (
    "#298（峰位/频偏口径：argmax/argmin 只在两侧同口径可用）"
    "+ W7 冒烟（ratrace 双谷 1.97/2.67GHz 夹持，谷位标记语义失真）"
)

#: S 参数幅值的 log 地板（SpecEvaluator 同款 1e-30，防 log10(0)）。
_DB_FLOOR = 1e-30

#: S11@f0 谷深门边界浮点余量（2026-10-08 W5 复核席）：与
#: ``_SPLIT_WINDOW_DB_EPS`` 同款同源——门值恰等的物理幅值 |Γ|=10^(门/20)
#: 经 double 域 20·log10 往返带量化噪声，门值域扫描 [-40,-1] 0.1dB 步长
#: 实测 30/391 个门值落违约侧（最大偏差 +3.6e-15 dB，如 -7.2dB 读
#: -7.199999999999999、-13.6dB 读 -13.599999999999998），字面
#: ``s11_db > gate_db`` 会把语义上"恰达门"（门语义=实测 ≤ 门为过，闭
#: 边界）的读数误判 FAIL——与 core/trl_solt._LINE_PASSIVE_MARGIN 同
#: 家法留容差；1e-9 dB 比门粒度（通用惯例 1dB 量级）低 9 个量级，对
#: 任何真实判读零影响。
_S11_DIP_DB_EPS = 1e-9

#: f0 邻域多谷检测的独立谷间距判据（W7 冒烟语义扩展，2026-10-08）：
#: 相邻极小间距 > 窗宽 × 本系数才计为两个独立谷（窗宽=f0 对称窗全宽
#: =2·min(f0−fmin, fmax−f0)，全含于扫频跨度）；≤ 系数的相邻极小链式
#: 归并为同一谷（保留更深者）——单谷肩部纹波/采样量化不误触发多谷
#: 语义。0.05=任务口径（窗 5%）。
_DIP_SEP_WINDOW_FRACTION = 0.05

#: 多谷 f0_offset 标记的 detail/evidence 标签（JSON 消费面稳定钉）。
_MULTI_DIP_DETAIL_TAG = "multi_dip_near_f0"

#: 无源性门边界浮点余量（2026-10-08 W5 复核席）：容差带缘闭语义
#: （σmax ≤ 1+容差为过）在恰等构造的实测 114/201 组合落违约侧——十进制
#: d+o=1.01 的 double 表示 + SVD 舍入使 σmax 读 1.0100000000000002
#: （偏差 +2.2e-16，比容差粒度 0.01 低 14 个量级），字面
#: ``sigma_max > PASSIVITY_TOLERANCE`` 会把"恰在带缘"的读数误判
#: FAIL。与 ``_S11_DIP_DB_EPS`` 同 eps 家法（线性域，无 dB 换算，噪声
#: 源不同暴露面同型）；对任何真实判读零影响。
_PASSIVITY_LINEAR_EPS = 1e-9

#: S11@f0 谷深通用缺省门（dB，实测 ≤ 门为过）＝回波损耗 ≥10 dB 的通用
#: 射频匹配惯例（|Γ|≤0.316）。模板族专属门须带出处登记进
#: ``S11_DIP_DB_BY_TEMPLATE``，禁止臆造物理数字（铁律 7/#274）。
#:
#: W10 0.02 档回退后通用门充分性核验（2026-10-09 ge8e 审查席，与
#: adapters/edb_templates/coupled_line.py ``DEFAULT_ADAPT_MAX_DELTA``
#: W10 定谳回退贯通；2026-10-09 回取复核席修订噪声归属）：0.02 档健康
#: coupled_line S11@f0 实测 -16.31~-18.83 dB，档位伪象对本门主判的
#: S11 自身 0.02 档→紧档移动 ~2.5 dB（-16.31→-18.83，W6→mc2→W10 链；
#: W10 REPORT §3）——通用门到最近健康读数（0.02 档最浅 -16.31）裕度
#: ~6.3 dB ≥ 2.5×S11 档位敏感（REPORT §2 的 ~0.62 dB 系 S31 口径伪象
#: 回收，勿移用到 S11），通用缺省门在 0.02 档仍充分；且伪象方向=读数
#: 偏浅（欠匹配方向），0.02 档只可能误杀不误放，false-PASS 风险≈0。
#: eps 家法余量（``_S11_DIP_DB_EPS``，1e-9）只吸收恰等量化噪声、不承担
#: 物理档位噪声（无此必要），本族亦无需登记专属门。后续新族接入仍按
#: #274 先扫健康读数分布与档位噪声量级再定门口径。
DEFAULT_S11_DIP_DB = -10.0

#: 模板作用域门登记表（#274 家法：键=spec.template 名；值=S11@f0 谷深门
#: dB 或 None）。登记须带出处（ 坑号/官方口径）；值 None=该族显式
#: 不设谷深门（如实 UNKNOWN，不硬套通用缺省门）。未登记的模板名回退
#: :data:`DEFAULT_S11_DIP_DB`。
S11_DIP_DB_BY_TEMPLATE: dict[str, float | None] = {}

#: Wilkinson 功分器族 |S21|/|S31|@f0 等分分配窗（dB，双边界闭区间，
#: 两腿各自落窗内才算过）＝W1 冒烟门语义仲裁裁定值（2026-10-09，
#: runs/edblane85/w1_smoke REPORT §3.2）：理想等分分配损耗 -3.01dB，
#: 下界 -3.8 = 3dB 分配 + 0.8dB 实现容差（健康实测 -3.19/-3.26 有余量），
#: 上界 -2.5 排除异常增益（分配损耗显著小于 3dB = 提取/接线伪象）。
#: 禁止臆造物理数字（铁律 7）：改动此窗须带真机/仲裁出处。
POWER_DIVIDER_SPLIT_WINDOW_DB = (-3.8, -2.5)

#: |S21|/|S31| 等分分配窗登记表（#274 家法，与 ``S11_DIP_DB_BY_TEMPLATE``
#: 同构）：键=spec.template 名；值=(下界 dB, 上界 dB) 或 None。登记须带
#: 出处；值 None=该族显式不设分配窗（判据缺席，不硬套功分器窗）。与
#: S11 门的两点语义差：①无通用缺省窗（S11 有 -10dB 通用惯例，等分窗
#: 是功分器族专属）——未登记且无显式窗的族 **criteria 不含本判据**
#: （缺席=不判，非 UNKNOWN 冒充也非 PASS 冒充）；②窗是双边界闭区间。
#: "wilkinson" 登记=HFSS/openEMS 插件族同名物理窗（等分分配物理为族级
#: 语义，与适配器无关）；"edb_power_divider"=EDB 快车道发射器登记名。
S_WINDOW_DB_BY_TEMPLATE: dict[str, tuple[float, float] | None] = {
    "edb_power_divider": POWER_DIVIDER_SPLIT_WINDOW_DB,
    "wilkinson": POWER_DIVIDER_SPLIT_WINDOW_DB,
}

#: Touchstone 文件名后缀（.sNp，大小写不敏感）。
_TOUCHSTONE_SUFFIX_RE = re.compile(r"\.s\d+p$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 判据条目构造（G11 _factor 同构：JSON 友好、lesson 可溯）
# ---------------------------------------------------------------------------

def _factor(
    factor: str,
    status: str,
    detail: str,
    lesson_ref: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "factor": factor,
        "status": status,
        "detail": detail,
        "lesson_ref": lesson_ref,
    }
    if evidence:
        item["evidence"] = evidence
    return item


def _unknown(
    factor: str, detail: str, lesson_ref: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """产物缺失/不可判定时的 UNKNOWN 条目（不冒充 FAIL/PASS，#122）。"""
    return _factor(factor, UNKNOWN, detail, lesson_ref, evidence=evidence)


# ---------------------------------------------------------------------------
# spec 侧声明提取（EDB spec 契约：edb_adapter 模块 docstring 同源）
# ---------------------------------------------------------------------------

def _spec_template(spec: dict[str, Any] | None) -> str | None:
    """spec.template 元段（发射器登记名）；缺省 None。"""
    if not isinstance(spec, dict):
        return None
    raw = spec.get("template")
    text = str(raw).strip() if raw is not None else ""
    return text or None


def _spec_f0_ghz(
    spec: dict[str, Any] | None, errors: list[str],
) -> float | None:
    """spec.sim_setup 单频口径（发射族 f0_ghz / 通用 adaptive_freq_ghz）。

    两键同给时按 edb_adapter 契约属非法 spec（适配器 fail-fast），此处
    不重复仲裁、取先命中键并记 errors；值不可解析 → None + errors 留痕。
    """
    if not isinstance(spec, dict):
        return None
    ss = spec.get("sim_setup")
    if not isinstance(ss, dict):
        return None
    for key in ("f0_ghz", "adaptive_freq_ghz"):
        raw = ss.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            errors.append(f"spec.sim_setup.{key} 无法解析为 float: {raw!r}")
            return None
        if not np.isfinite(value) or value <= 0:
            errors.append(f"spec.sim_setup.{key} 非正/非有限: {value!r}")
            return None
        return value
    return None


def _spec_port_count(
    spec: dict[str, Any] | None, errors: list[str],
) -> int | None:
    """spec.ports 声明端口数：wave_port.port_nr / 通用 number 同池取最大
    编号（契约：编号 ≥1 全表唯一，同池查重——最大编号=端口数）；个别条目
    缺编号键时按序号补位（健壮性，合法 spec 不触达）；ports 缺失/空 →
    None（未声明，UNKNOWN 不硬判）。"""
    if not isinstance(spec, dict):
        return None
    ports = spec.get("ports")
    if not isinstance(ports, list) or not ports:
        return None
    numbers: list[int] = []
    for i, port in enumerate(ports):
        if not isinstance(port, dict):
            errors.append(f"spec.ports[{i}] 非 dict，端口数声明不可解析")
            continue
        for key in ("port_nr", "number"):
            raw = port.get(key)
            if isinstance(raw, bool):  # bool 是 int 子类，先排除
                continue
            if isinstance(raw, int):
                numbers.append(int(raw))
                break
        else:
            numbers.append(i + 1)
    if not numbers:
        return None
    return max(numbers)


# ---------------------------------------------------------------------------
# Touchstone 定位与读取（skrf 懒加载，health_service 同款惯例）
# ---------------------------------------------------------------------------

def _resolve_touchstone_path(
    batch_result: dict[str, Any] | None,
    explicit: str | Path | None,
    errors: list[str],
) -> Path | None:
    """Touchstone 发现链：显式 kwarg > 回执 export.out_file > artifacts 扫 .sNp。"""
    if explicit is not None:
        return Path(explicit)
    if not isinstance(batch_result, dict):
        return None
    export = batch_result.get("export")
    if isinstance(export, dict):
        out_file = export.get("out_file")
        if out_file:
            return Path(str(out_file))
    artifacts = batch_result.get("artifacts")
    if isinstance(artifacts, (list, tuple)):
        for art in artifacts:
            if _TOUCHSTONE_SUFFIX_RE.search(str(art)):
                return Path(str(art))
    return None


def _load_touchstone_gate(
    path: Path | None, errors: list[str],
) -> tuple[str, np.ndarray | None, np.ndarray | None]:
    """读 Touchstone → (state, freq_hz, s_matrix)。

    state ∈ found/missing/env/corrupt/absent：
    - absent：发现链无候选（export 未请求/未生成，artifacts 无 .sNp）；
    - missing：候选路径但文件不存在；
    - env：skrf 不可用（环境类，不可证实 #122）；
    - corrupt：解析失败/形状非法（证据损坏，#316 多报方向）；
    - found：freq_hz/s_matrix 有效。
    """
    if path is None:
        errors.append("未发现 Touchstone 产物（export.out_file 缺且 "
                      "artifacts 扫描无 .sNp）")
        return "absent", None, None
    if not path.is_file():
        errors.append(f"Touchstone 文件不存在: {path}")
        return "missing", None, None
    try:
        import skrf  # 懒加载（SpecEvaluator/health_service 惯例）
    except Exception as exc:
        errors.append(f"skrf 不可用，Touchstone 未判读: {exc}")
        return "env", None, None
    try:
        network = skrf.Network(str(path))
        freq_hz = np.asarray(network.f, dtype=float)
        s_matrix = np.asarray(network.s, dtype=complex)
    except Exception as exc:
        errors.append(f"Touchstone 解析失败 {path.name}: {exc}")
        return "corrupt", None, None
    if (freq_hz.ndim != 1 or freq_hz.size == 0 or s_matrix.ndim != 3
            or s_matrix.shape[0] != freq_hz.size
            or s_matrix.shape[1] != s_matrix.shape[2]):
        errors.append(
            f"Touchstone 形状非法 {path.name}: f{freq_hz.shape} s{s_matrix.shape}"
            "（须 1D 频轴 + 方阵 S）")
        return "corrupt", None, None
    return "found", freq_hz, s_matrix


# ---------------------------------------------------------------------------
# 逐判据因子
# ---------------------------------------------------------------------------

def _solve_status_factor(batch_result: dict[str, Any] | None) -> dict[str, Any]:
    """求解 rc/超时态（hfss_batch 契约：ok 仅在 rc==0 且未超时为真）。"""
    if not isinstance(batch_result, dict):
        return _unknown(
            FACTOR_SOLVE_STATUS,
            "批处理回执缺失/非 dict，求解态不可证实（#122 不冒充 FAIL）",
            LESSON_SOLVE_STATUS)
    rc = batch_result.get("rc")
    timed_out = bool(batch_result.get("timed_out"))
    evidence: dict[str, Any] = {"rc": rc, "timed_out": timed_out}
    for key in ("project", "logfile", "elapsed_s", "project_kind"):
        if batch_result.get(key) is not None:
            evidence[key] = batch_result[key]
    if timed_out:
        return _factor(
            FACTOR_SOLVE_STATUS, FAIL,
            "求解超时（watchdog 整树击杀）——击杀后残留产物不可信",
            LESSON_SOLVE_STATUS, evidence=evidence)
    if rc is None:
        return _factor(
            FACTOR_SOLVE_STATUS, FAIL,
            "前置失败未拉起求解进程（rc=None：路径/exe/日志目录/发射）"
            "，零产物可判",
            LESSON_SOLVE_STATUS, evidence=evidence)
    # bool 是 int 子类（isinstance(True, int)=True，审查 A3 P3-6）：rc=True
    # 旧码会以 int 身份穿成"退出码非零"FAIL，rc=False 更会穿成 rc==0 成功
    # 路径——bool 先排一行闭环，契约=int|None 如实 UNKNOWN（#122 不冒充）。
    if isinstance(rc, bool) or not isinstance(rc, int):
        return _unknown(
            FACTOR_SOLVE_STATUS,
            f"回执 rc 形态非法: {rc!r}（契约=int|None，bool 不收），"
            "求解态不可证实",
            LESSON_SOLVE_STATUS, evidence=evidence)
    if rc != 0:
        return _factor(
            FACTOR_SOLVE_STATUS, FAIL,
            f"ansysedt 退出码非零: rc={rc}（详见回执 logfile_tail/errors）",
            LESSON_SOLVE_STATUS, evidence=evidence)
    # rc==0 且未超时；ok 键在档且为 False 属契约矛盾，保守按 FAIL
    if batch_result.get("ok") is False:
        return _factor(
            FACTOR_SOLVE_STATUS, FAIL,
            "回执契约矛盾（ok=False 而 rc==0 且未超时）——保守按失败",
            LESSON_SOLVE_STATUS, evidence=evidence)
    evidence["ok"] = True
    return _factor(
        FACTOR_SOLVE_STATUS, PASS,
        f"求解成功（rc=0 未超时，elapsed_s={batch_result.get('elapsed_s')}）",
        LESSON_SOLVE_STATUS, evidence=evidence)


def _touchstone_factor(state: str, path: Path | None) -> dict[str, Any]:
    """Touchstone 存在性 + 可读性（state 语义见 _load_touchstone_gate）。"""
    evidence: dict[str, Any] = {"path": str(path) if path is not None else None}
    if state == "found":
        return _factor(
            FACTOR_TOUCHSTONE, PASS,
            f"Touchstone 在档且可读: {path}",
            LESSON_TOUCHSTONE, evidence=evidence)
    if state in ("absent", "missing"):
        return _factor(
            FACTOR_TOUCHSTONE, FAIL,
            "Touchstone 未生成（-BatchSolve 只求解不产网络参数的断链指纹；"
            "需 export_touchstone=True 走 -batchextract 批后导出）"
            if state == "absent" else f"Touchstone 候选路径文件不存在: {path}",
            LESSON_TOUCHSTONE, evidence=evidence)
    if state == "env":
        return _unknown(
            FACTOR_TOUCHSTONE,
            "skrf 不可用（环境类），Touchstone 在档但不可判读——"
            "不可证实≠失败（#122）",
            LESSON_TOUCHSTONE, evidence=evidence)
    return _factor(
        FACTOR_TOUCHSTONE, FAIL,
        f"Touchstone 解析失败/形状非法（证据损坏）: {path}",
        LESSON_TOUCHSTONE, evidence=evidence)


def _port_count_factor(
    s_matrix: np.ndarray | None, expected: int | None,
) -> dict[str, Any]:
    """Touchstone 实测端口数 vs spec 声明端口数。"""
    if s_matrix is None:
        return _unknown(
            FACTOR_PORT_COUNT, "S 数据不可读，端口数无从核对", LESSON_PORT_COUNT,
            evidence={"expected_ports": expected})
    observed = int(s_matrix.shape[-1])
    evidence: dict[str, Any] = {"observed_ports": observed,
                                "expected_ports": expected}
    if expected is None:
        return _unknown(
            FACTOR_PORT_COUNT,
            f"spec 未声明端口（observed={observed}），无从交叉核对——不硬判",
            LESSON_PORT_COUNT, evidence=evidence)
    if observed != expected:
        return _factor(
            FACTOR_PORT_COUNT, FAIL,
            f"端口数不符：Touchstone 实测 {observed} vs spec 声明 {expected}"
            "（#248 族：导出按端口数契约命名/落矩阵）",
            LESSON_PORT_COUNT, evidence=evidence)
    return _factor(
        FACTOR_PORT_COUNT, PASS,
        f"端口数一致（{observed}）",
        LESSON_PORT_COUNT, evidence=evidence)


def _passivity_factor(s_matrix: np.ndarray | None) -> dict[str, Any]:
    """σmax ≤ 1+容差（复数域全带宽）；非有限值=数据损坏 FAIL。

    σmax=逐频最大奇异值（真无源性判据 |S|₂≤1）；多端口下 entry-wise
    max|Sij|≤1（SpecEvaluator 近似口径）只是必要条件——本门按任务口径
    取奇异值，容差 1% 仍与 core.solve_health.PASSIVITY_TOLERANCE 同源。
    比较留 _PASSIVITY_LINEAR_EPS（1e-9）线性域边界余量：恰在容差带缘
    的读数经 double 表示/SVD 舍入可落带缘违约侧 ~1e-16（实测 1.01 读
    1.0100000000000002），闭语义"≤ 容差为过"不得因量化噪声误 FAIL
    （与 _S11_DIP_DB_EPS/_SPLIT_WINDOW_DB_EPS 同款家法）。
    """
    if s_matrix is None:
        return _unknown(
            FACTOR_PASSIVITY, "S 数据不可读，无法校验无源性", LESSON_PASSIVITY)
    finite = np.isfinite(s_matrix.real) & np.isfinite(s_matrix.imag)
    n_bad = int(np.count_nonzero(~finite))
    if n_bad:
        return _factor(
            FACTOR_PASSIVITY, FAIL,
            f"S 含非有限值 {n_bad} 处（数据损坏，无源性不可证）",
            LESSON_PASSIVITY, evidence={"non_finite_count": n_bad})
    sigma_all = np.linalg.svd(s_matrix, compute_uv=False)  # (n_freq, n)
    sigma_max = float(np.max(sigma_all))
    at_freq = int(np.argmax(np.max(sigma_all, axis=-1)))
    evidence = {
        "sigma_max": round(sigma_max, 6),
        "tolerance": PASSIVITY_TOLERANCE,
        "at_freq_index": at_freq,
        "metric": "sigma_max（逐频最大奇异值）",
    }
    if sigma_max > PASSIVITY_TOLERANCE + _PASSIVITY_LINEAR_EPS:
        return _factor(
            FACTOR_PASSIVITY, FAIL,
            f"σmax={sigma_max:.4f} > {PASSIVITY_TOLERANCE}：无源性违背"
            "（无源网络奇异值≤1，1% 容差与 SpecEvaluator/G11 同源）",
            LESSON_PASSIVITY, evidence=evidence)
    return _factor(
        FACTOR_PASSIVITY, PASS,
        f"σmax={sigma_max:.4f} ≤ {PASSIVITY_TOLERANCE}（1% 容差内）",
        LESSON_PASSIVITY, evidence=evidence)


def _reciprocity_factor(s_matrix: np.ndarray | None) -> dict[str, Any]:
    """|Sij−Sji| 逐对（掩码纪律 #314：Touchstone 全矩阵无掩码载体，
    按全矩阵判但如实声明 measured_mask=None；单端口=平凡真如实注记）。"""
    if s_matrix is None:
        return _unknown(
            FACTOR_RECIPROCITY, "S 数据不可读，无法校验互易性",
            LESSON_RECIPROCITY,
            evidence={"measured_mask": None,
                      "mask_semantics": "全矩阵口径（Touchstone 无掩码载体）"})
    n = int(s_matrix.shape[-1])
    evidence: dict[str, Any] = {
        "measured_mask": None,
        "mask_semantics": ("全矩阵口径：Touchstone 为全矩阵导出无掩码载体，"
                           "全部 i<j 端口对独立判（#314 掩码纪律如实声明）"),
        "n_ports": n,
    }
    if n < 2:
        return _factor(
            FACTOR_RECIPROCITY, PASS,
            "单端口无跨端口对，互易性平凡真（如实注记）",
            LESSON_RECIPROCITY, evidence=evidence)
    finite = np.isfinite(s_matrix.real) & np.isfinite(s_matrix.imag)
    if bool(np.count_nonzero(~finite)):
        return _factor(
            FACTOR_RECIPROCITY, FAIL,
            "S 含非有限值（数据损坏），互易性不可证——按 #316 多报方向记 FAIL",
            LESSON_RECIPROCITY, evidence=evidence)
    worst_val = -1.0
    worst_pair: tuple[int, int] | None = None
    for i in range(n):
        for j in range(i + 1, n):
            diff = float(np.max(np.abs(s_matrix[:, i, j] - s_matrix[:, j, i])))
            if diff > worst_val:
                worst_val = diff
                worst_pair = (i, j)
    evidence["max_symmetry_violation"] = round(worst_val, 8)
    evidence["worst_pair"] = list(worst_pair or [])
    evidence["tolerance"] = RECIPROCITY_TOLERANCE
    if worst_val >= RECIPROCITY_TOLERANCE and worst_pair is not None:
        i, j = worst_pair
        return _factor(
            FACTOR_RECIPROCITY, FAIL,
            f"互易性违背：max|S{i + 1}{j + 1}−S{j + 1}{i + 1}|"
            f"={worst_val:.4f} ≥ {RECIPROCITY_TOLERANCE}",
            LESSON_RECIPROCITY, evidence=evidence)
    return _factor(
        FACTOR_RECIPROCITY, PASS,
        f"互易（max|Sij−Sji|={worst_val:.2e} < {RECIPROCITY_TOLERANCE}，"
        "全矩阵口径）",
        LESSON_RECIPROCITY, evidence=evidence)


def _resolve_s11_gate(
    template: str | None, explicit_gate: float | None,
) -> tuple[float | None, str]:
    """S11@f0 门分派（#274 家法）：显式覆盖 > 模板登记表（值可 None=
    该族不设门）> 通用缺省门。返回 (gate_db, gate_scope)。"""
    if explicit_gate is not None:
        return float(explicit_gate), "explicit"
    if template is not None and template in S11_DIP_DB_BY_TEMPLATE:
        return S11_DIP_DB_BY_TEMPLATE[template], f"template:{template}"
    return DEFAULT_S11_DIP_DB, "default"


def _find_dips_near_f0(
    freq_hz: np.ndarray, s11_col: np.ndarray, f0_hz: float,
) -> tuple[list[float], list[float]] | None:
    """f0 邻域多谷检测（W7 冒烟语义扩展，2026-10-08，确定性数值规则）。

    窗=f0 对称窗（半宽=min(f0−fmin, fmax−f0)，全含于扫频跨度）；窗内
    |S11| dB 曲线的严格局部极小为谷候选，相邻候选间距 ≤ 窗宽×
    ``_DIP_SEP_WINDOW_FRACTION``（5%）视为同一谷链式归并（保留更深者，
    单谷肩部纹波不误触发多谷）。

    Returns:
        (谷频率 Hz 升序, 谷深 dB)——空列表=窗内无谷（平/单调响应）；
        None=窗内有效样本不足（<3，无从检测，多谷语义不触发）。
    """
    finite = np.isfinite(s11_col.real) & np.isfinite(s11_col.imag)
    f_min, f_max = float(np.min(freq_hz)), float(np.max(freq_hz))
    half = min(f0_hz - f_min, f_max - f0_hz)
    if not np.isfinite(half) or half <= 0:
        return None
    lo, hi = f0_hz - half, f0_hz + half
    idx = np.flatnonzero(finite & (freq_hz >= lo) & (freq_hz <= hi))
    if idx.size < 3:
        return None
    f_win = freq_hz[idx]
    db_win = 20.0 * np.log10(np.abs(s11_col[idx]) + _DB_FLOOR)
    is_min = (db_win[1:-1] < db_win[:-2]) & (db_win[1:-1] < db_win[2:])
    cand = np.flatnonzero(is_min) + 1  # 窗内严格局部极小（边界点不计）
    if cand.size == 0:
        return [], []
    sep = _DIP_SEP_WINDOW_FRACTION * 2.0 * half
    dip_freqs: list[float] = []
    dip_dbs: list[float] = []
    for pos in cand:
        f_c = float(f_win[pos])
        db_c = float(db_win[pos])
        if dip_freqs and f_c - dip_freqs[-1] <= sep:
            if db_c < dip_dbs[-1]:  # 同一谷：链式归并保留更深者
                dip_freqs[-1] = f_c
                dip_dbs[-1] = db_c
        else:
            dip_freqs.append(f_c)
            dip_dbs.append(db_c)
    return dip_freqs, dip_dbs


def _f0_offset_factor(
    dip_freqs: list[float], dip_dbs: list[float], f0_ghz: float | None,
) -> dict[str, Any]:
    """多谷 f0_offset 谷位标记因子：UNKNOWN（不冒充 PASS 也不硬 FAIL，#122）。

    W7 冒烟实证（ratrace 双谷 1.97/2.67GHz 夹持）：f0 邻域多谷时
    argmin 谷/插值 f0 的谷位标记语义失真——f0 偏移判据（#298 家法：
    峰位/频偏只在单谷同口径可用）如实 UNKNOWN 交上层/人工仲裁。
    """
    deepest = int(np.argmin(dip_dbs))
    evidence: dict[str, Any] = {
        "f0_ghz": f0_ghz,
        "n_dips_near_f0": len(dip_freqs),
        "dip_freqs_ghz": [round(f / 1e9, 6) for f in dip_freqs],
        "dip_depths_db": [round(d, 3) for d in dip_dbs],
        "deepest_dip_freq_ghz": round(dip_freqs[deepest] / 1e9, 6),
        "dip_sep_rule": "相邻极小间距>窗宽5%计独立谷",
        "marker": _MULTI_DIP_DETAIL_TAG,
    }
    return _unknown(
        FACTOR_F0_OFFSET,
        f"{_MULTI_DIP_DETAIL_TAG}：f0 邻域检出 {len(dip_freqs)} 谷"
        f"（{'/'.join(f'{f / 1e9:.4g}' for f in dip_freqs)} GHz）——"
        "argmin 谷/插值 f0 的谷位标记语义失真（W7 ratrace 双谷夹持实证），"
        "f0 偏移判据不冒充 PASS 也不硬 FAIL（#122）",
        LESSON_F0_OFFSET, evidence=evidence)


def _s11_dip_factor(
    freq_hz: np.ndarray | None,
    s_matrix: np.ndarray | None,
    f0_ghz: float | None,
    gate_db: float | None,
    gate_scope: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """S11@f0 谷深（dB）：f0 复数线性插值 → 20·log10|S11| vs 门。

    门语义=实测 ≤ 门为过（闭边界）；比较留 _S11_DIP_DB_EPS（1e-9 dB）
    边界余量：恰等门值的幅值经 10^(x/20)→20·log10 double 往返带 ~1e-15
    dB 量化噪声（门值域扫描实测可落违约侧），不得因换算噪声误 FAIL
    （与 _SPLIT_WINDOW_DB_EPS 同款家法，2026-10-08 W5 复核席）。

    W7 语义扩展（2026-10-08）：f0 对称窗内检出多谷（谷计数>1，相邻极小
    间距>窗宽 5% 计独立谷）时进入多谷分支——本因子改锚**最深谷**（主谷
    @f0 典型形态与 at-f0 插值读数同值=现有行为保持；at-f0 读数仍在
    evidence 双报），并追加 f0_offset 谷位标记 UNKNOWN 因子（#122）；
    单谷/无谷走原路径（evidence/detail 逐字节不变），既有 UNKNOWN 路径
    （无数据/未声明 f0/f0 出跨度/f0 无样本）不做多谷检测。

    Returns:
        (s11_dip 因子条目, 追加因子列表)——追加列表仅在多谷分支非空
        （当前恰为 f0_offset 一条）。
    """
    base_evidence: dict[str, Any] = {"f0_ghz": f0_ghz, "gate_db": gate_db,
                                     "gate_scope": gate_scope}
    if freq_hz is None or s_matrix is None:
        return _unknown(
            FACTOR_S11_DIP, "S 数据不可读，S11@f0 谷深无从评估",
            LESSON_S11_DIP, evidence=base_evidence), []
    if f0_ghz is None:
        return _unknown(
            FACTOR_S11_DIP,
            "spec 未声明 f0（sim_setup.f0_ghz / adaptive_freq_ghz 均缺）——"
            "未声明判定目标不硬判（#122）",
            LESSON_S11_DIP, evidence=base_evidence), []
    f0_hz = f0_ghz * 1e9
    f_min, f_max = float(np.min(freq_hz)), float(np.max(freq_hz))
    base_evidence["sweep_span_ghz"] = [round(f_min / 1e9, 6),
                                       round(f_max / 1e9, 6)]
    if not (f_min <= f0_hz <= f_max):
        return _unknown(
            FACTOR_S11_DIP,
            f"f0={f0_ghz} GHz 不在扫频跨度 "
            f"[{f_min / 1e9:.6g}, {f_max / 1e9:.6g}] GHz 内——不外推（#122）",
            LESSON_S11_DIP, evidence=base_evidence), []
    s11_col = s_matrix[:, 0, 0]
    finite = np.isfinite(s11_col.real) & np.isfinite(s11_col.imag)
    s11: complex | None = None
    if freq_hz.size >= 2 and int(np.count_nonzero(finite)) >= 2:
        f_ok = freq_hz[finite]
        s11 = complex(
            float(np.interp(f0_hz, f_ok, s11_col.real[finite])),
            float(np.interp(f0_hz, f_ok, s11_col.imag[finite])))
    else:
        idx_list = np.flatnonzero(finite)
        for idx in idx_list:
            if np.isclose(float(freq_hz[idx]), f0_hz, rtol=1e-6):
                s11 = complex(s11_col[idx])
                break
    if s11 is None:
        return _unknown(
            FACTOR_S11_DIP, f"f0={f0_ghz} GHz 处无有效样本，谷深无从评估",
            LESSON_S11_DIP, evidence=base_evidence), []
    s11_db = float(20.0 * np.log10(abs(s11) + _DB_FLOOR))
    base_evidence["s11_db_at_f0"] = round(s11_db, 3)
    # W7 多谷分支：谷计数>1 → 锚最深谷 + f0_offset 标 UNKNOWN（#122）。
    detected = _find_dips_near_f0(freq_hz, s11_col, f0_hz)
    if detected is not None and len(detected[0]) > 1:
        dip_freqs, dip_dbs = detected
        deepest = int(np.argmin(dip_dbs))
        dip_db = dip_dbs[deepest]
        dip_hz = dip_freqs[deepest]
        base_evidence.update({
            "n_dips_near_f0": len(dip_freqs),
            "dip_freqs_ghz": [round(f / 1e9, 6) for f in dip_freqs],
            "deepest_dip_freq_ghz": round(dip_hz / 1e9, 6),
            "s11_db_at_dip": round(dip_db, 3),
            "dip_anchor": "deepest（多谷取最深谷，W7 语义扩展；主谷@f0 "
                          "形态与 at-f0 读数同值）",
        })
        extra = [_f0_offset_factor(dip_freqs, dip_dbs, f0_ghz)]
        if gate_db is None:
            return _unknown(
                FACTOR_S11_DIP,
                f"多谷取最深谷：S11@dip={dip_db:.2f} dB 已测"
                f"（{len(dip_freqs)} 谷），但该族未设谷深门（gate=None，"
                "#274 非适用族不硬套他族门）——如实不判",
                LESSON_S11_DIP, evidence=base_evidence), extra
        base_evidence["gate_db"] = float(gate_db)
        if dip_db > float(gate_db) + _S11_DIP_DB_EPS:
            return _factor(
                FACTOR_S11_DIP, FAIL,
                f"多谷取最深谷：S11@dip={dip_db:.2f} dB"
                f"（{len(dip_freqs)} 谷，最深 @{dip_hz / 1e9:.4g} GHz）"
                f"未达谷深门 {gate_db:.2f} dB（门作用域={gate_scope}）",
                LESSON_S11_DIP, evidence=base_evidence), extra
        return _factor(
            FACTOR_S11_DIP, PASS,
            f"多谷取最深谷：S11@dip={dip_db:.2f} dB"
            f"（{len(dip_freqs)} 谷，最深 @{dip_hz / 1e9:.4g} GHz）"
            f"≤ 门 {gate_db:.2f} dB（门作用域={gate_scope}）",
            LESSON_S11_DIP, evidence=base_evidence), extra
    if gate_db is None:
        return _unknown(
            FACTOR_S11_DIP,
            f"S11@f0={s11_db:.2f} dB 已测，但该族未设谷深门（gate=None，"
            "#274 非适用族不硬套他族门）——如实不判",
            LESSON_S11_DIP, evidence=base_evidence), []
    base_evidence["gate_db"] = float(gate_db)
    if s11_db > float(gate_db) + _S11_DIP_DB_EPS:
        return _factor(
            FACTOR_S11_DIP, FAIL,
            f"S11@f0={s11_db:.2f} dB 未达谷深门 {gate_db:.2f} dB"
            f"（门作用域={gate_scope}）",
            LESSON_S11_DIP, evidence=base_evidence), []
    return _factor(
        FACTOR_S11_DIP, PASS,
        f"S11@f0={s11_db:.2f} dB ≤ 门 {gate_db:.2f} dB"
        f"（门作用域={gate_scope}）",
        LESSON_S11_DIP, evidence=base_evidence), []


def _resolve_s_split_window(
    template: str | None,
    explicit_window: Any,
    errors: list[str],
) -> tuple[tuple[float, float] | None, str]:
    """|S21|/|S31| 分配窗分派（#274 家法）：显式窗 > 模板登记表 > 无门。

    返回 (window_db, window_scope)；window_db=None=本族不设判据（登记表
    miss 或登记值 None，或显式窗缺失/形态非法）。显式窗形态非法不抛
    异常（#105 best-effort）：errors 留痕后按未提供处理（回退登记表）。
    """
    if explicit_window is not None:
        try:
            lo, hi = explicit_window
            lo_f, hi_f = float(lo), float(hi)
            if not (np.isfinite(lo_f) and np.isfinite(hi_f) and lo_f <= hi_f):
                raise ValueError(f"非有限或下界>上界: {explicit_window!r}")
            return (lo_f, hi_f), "explicit"
        except (TypeError, ValueError) as exc:
            errors.append(f"s_split_window_db 形态非法，已忽略显式窗: {exc}")
    if template is not None and template in S_WINDOW_DB_BY_TEMPLATE:
        return S_WINDOW_DB_BY_TEMPLATE[template], f"template:{template}"
    return None, "none"


def _s_interp_db_at_f0(
    freq_hz: np.ndarray, series: np.ndarray, f0_hz: float,
) -> float | None:
    """复数序列在 f0 处线性插值 → 20·log10|·|（_DB_FLOOR 防 log(0)）。

    f0 处无有效样本（有效点 <2 且无恰落格点）→ None（不外推，#122）。
    """
    finite = np.isfinite(series.real) & np.isfinite(series.imag)
    if freq_hz.size >= 2 and int(np.count_nonzero(finite)) >= 2:
        f_ok = freq_hz[finite]
        val = complex(
            float(np.interp(f0_hz, f_ok, series.real[finite])),
            float(np.interp(f0_hz, f_ok, series.imag[finite])))
        return float(20.0 * np.log10(abs(val) + _DB_FLOOR))
    idx_list = np.flatnonzero(finite)
    for idx in idx_list:
        if np.isclose(float(freq_hz[idx]), f0_hz, rtol=1e-6):
            return float(20.0 * np.log10(abs(complex(series[idx])) + _DB_FLOOR))
    return None


def _s_split_window_factor(
    freq_hz: np.ndarray | None,
    s_matrix: np.ndarray | None,
    f0_ghz: float | None,
    window_db: tuple[float, float],
    window_scope: str,
) -> dict[str, Any]:
    """|S21|/|S31|@f0 等分分配窗（W1 冒烟仲裁裁定语义）。

    双腿（P1→P2 / P1→P3）各自落窗 [下界, 上界]（闭区间）为 PASS；任一
    腿出窗 → FAIL（detail 点名腿与越界方向）。仅对登记族/显式窗生效
    （判据缺席由调用方控制，#274）；数据形态不足（<3 端口）或 f0 缺失/
    出跨度 → UNKNOWN 不外推（#122）。逐点 @f0 读数语义（非带内
    max/min，#195 口径：等分分配是单频标称量）。
    """
    lo_db, hi_db = float(window_db[0]), float(window_db[1])
    base_evidence: dict[str, Any] = {
        "f0_ghz": f0_ghz,
        "window_db": [lo_db, hi_db],
        "window_scope": window_scope,
    }
    if freq_hz is None or s_matrix is None:
        return _unknown(
            FACTOR_S_SPLIT_WINDOW, "S 数据不可读，分配窗无从评估",
            LESSON_S_SPLIT_WINDOW, evidence=base_evidence)
    if s_matrix.shape[-1] < 3:
        return _unknown(
            FACTOR_S_SPLIT_WINDOW,
            f"端口数 {s_matrix.shape[-1]} < 3，无 |S21|/|S31| 分配对可判"
            "（功分器窗需 3 端口形态）",
            LESSON_S_SPLIT_WINDOW, evidence=base_evidence)
    if f0_ghz is None:
        return _unknown(
            FACTOR_S_SPLIT_WINDOW,
            "spec 未声明 f0（sim_setup.f0_ghz / adaptive_freq_ghz 均缺）——"
            "未声明判定目标不硬判（#122）",
            LESSON_S_SPLIT_WINDOW, evidence=base_evidence)
    f0_hz = f0_ghz * 1e9
    f_min, f_max = float(np.min(freq_hz)), float(np.max(freq_hz))
    base_evidence["sweep_span_ghz"] = [round(f_min / 1e9, 6),
                                       round(f_max / 1e9, 6)]
    if not (f_min <= f0_hz <= f_max):
        return _unknown(
            FACTOR_S_SPLIT_WINDOW,
            f"f0={f0_ghz} GHz 不在扫频跨度 "
            f"[{f_min / 1e9:.6g}, {f_max / 1e9:.6g}] GHz 内——不外推（#122）",
            LESSON_S_SPLIT_WINDOW, evidence=base_evidence)
    legs = {
        "S21": _s_interp_db_at_f0(freq_hz, s_matrix[:, 0, 1], f0_hz),
        "S31": _s_interp_db_at_f0(freq_hz, s_matrix[:, 0, 2], f0_hz),
    }
    if any(v is None for v in legs.values()):
        return _unknown(
            FACTOR_S_SPLIT_WINDOW,
            f"f0={f0_ghz} GHz 处无有效样本，分配窗无从评估",
            LESSON_S_SPLIT_WINDOW, evidence=base_evidence)
    base_evidence["s21_db_at_f0"] = round(legs["S21"], 3)
    base_evidence["s31_db_at_f0"] = round(legs["S31"], 3)
    out_legs = [(name, db) for name, db in legs.items()
                if (db < lo_db - _SPLIT_WINDOW_DB_EPS
                    or db > hi_db + _SPLIT_WINDOW_DB_EPS)]
    if out_legs:
        detail = "、".join(
            f"{name}@f0={db:.2f} dB 出窗"
            f"（{'低于下界' if db < lo_db else '高于上界'} "
            f"{lo_db if db < lo_db else hi_db:.1f}）"
            for name, db in out_legs)
        return _factor(
            FACTOR_S_SPLIT_WINDOW, FAIL,
            f"{detail}，分配窗 [{lo_db}, {hi_db}] dB"
            f"（窗作用域={window_scope}）",
            LESSON_S_SPLIT_WINDOW, evidence=base_evidence)
    return _factor(
        FACTOR_S_SPLIT_WINDOW, PASS,
        f"|S21|@f0={legs['S21']:.2f} dB、|S31|@f0={legs['S31']:.2f} dB "
        f"双落窗 [{lo_db}, {hi_db}] dB（窗作用域={window_scope}）",
        LESSON_S_SPLIT_WINDOW, evidence=base_evidence)


# ---------------------------------------------------------------------------
# 服务入口
# ---------------------------------------------------------------------------

def check_edb_batch_health(
    batch_result: dict[str, Any] | None = None,
    *,
    spec: dict[str, Any] | None = None,
    touchstone_path: str | Path | None = None,
    template: str | None = None,
    s11_dip_gate_db: float | None = None,
    s_split_window_db: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """对 EDB 快车道批处理产物做健康门判读（三态 verdict + 逐判据明细）。

    Args:
        batch_result: ``hfss_batch.solve_project_batch`` 结构化回执 dict
            （``{ok, rc, timed_out, project, logfile, artifacts, export,
            errors, ...}`` 契约；``export`` 为 ``-batchextract`` 导出段）。
            None/非 dict 时求解态判 UNKNOWN（不冒充 FAIL，#122）。
        spec: EDB 声明式 spec dict（edb_adapter 契约），用于提取端口数
            声明（``ports``）、单频口径（``sim_setup.f0_ghz`` /
            ``adaptive_freq_ghz``）与模板名（``template``）。None 时相关
            判据如实 UNKNOWN。
        touchstone_path: 显式 Touchstone 路径（覆盖回执发现链）。
        template: 模板名（覆盖 spec.template；用于 #274 门作用域分派）。
        s11_dip_gate_db: 显式 S11@f0 谷深门 dB（最高优先级，覆盖模板
            登记表与通用缺省门）。
        s_split_window_db: 显式 |S21|/|S31|@f0 分配窗 (下界, 上界) dB
            （最高优先级，覆盖模板登记表；形态非法时 errors 留痕并回退
            登记表，#105）。显式窗/登记窗都缺席时本判据不进 criteria
            （等分窗为功分器族专属，无通用缺省，#274）。

    Returns:
        dict: ``{schema, ok, verdict, template, touchstone, criteria,
        summary[, errors]}``——``verdict`` ∈ PASS/FAIL/UNKNOWN（任一
        FAIL → FAIL；否则任一 UNKNOWN → UNKNOWN；全 PASS → PASS，
        #122）；``ok`` 仅作报告字段（=verdict==PASS），非门禁判据
        （G11 同款口径）；``criteria`` 逐判据明细（factor/status/detail/
        lesson_ref[/evidence]，数值/门/判定全在 evidence；``s_split_window``
        仅在窗生效时出现，``f0_offset`` 仅在 f0 邻域多谷时出现=W7 谷位
        标记语义扩展）；``summary`` 红绿账。best-effort（#105）：
        输入缺失/畸形不抛异常。
    """
    errors: list[str] = []
    criteria: list[dict[str, Any]] = []

    eff_template = str(template).strip() if template else None
    if not eff_template:
        eff_template = _spec_template(spec)

    # ① 求解 rc/超时态
    criteria.append(_solve_status_factor(batch_result))

    # ② Touchstone 定位 + 读取
    ts_path = _resolve_touchstone_path(batch_result, touchstone_path, errors)
    state, freq_hz, s_matrix = _load_touchstone_gate(ts_path, errors)
    criteria.append(_touchstone_factor(state, ts_path))

    # ③④⑤⑥ S 数据判据族（数据不可读时各判据自行落 UNKNOWN，不传染）
    expected_ports = _spec_port_count(spec, errors)
    criteria.append(_port_count_factor(s_matrix, expected_ports))
    criteria.append(_passivity_factor(s_matrix))

    f0_ghz = _spec_f0_ghz(spec, errors)
    gate_db, gate_scope = _resolve_s11_gate(eff_template, s11_dip_gate_db)
    dip_factor, dip_extra = _s11_dip_factor(freq_hz, s_matrix, f0_ghz,
                                            gate_db, gate_scope)
    criteria.append(dip_factor)
    criteria.extend(dip_extra)  # 多谷分支追加 f0_offset（W7 语义扩展）

    window_db, window_scope = _resolve_s_split_window(
        eff_template, s_split_window_db, errors)
    if window_db is not None:
        criteria.append(_s_split_window_factor(freq_hz, s_matrix, f0_ghz,
                                               window_db, window_scope))

    criteria.append(_reciprocity_factor(s_matrix))

    # verdict 聚合（#122：FAIL > UNKNOWN > PASS；UNKNOWN 不冒充 FAIL/PASS）
    statuses = [str(c["status"]) for c in criteria]
    if FAIL in statuses:
        verdict = VERDICT_FAIL
    elif UNKNOWN in statuses:
        verdict = VERDICT_UNKNOWN
    else:
        verdict = VERDICT_PASS

    fail_factors = [c["factor"] for c in criteria if c["status"] == FAIL]
    unknown_factors = [c["factor"] for c in criteria if c["status"] == UNKNOWN]

    # 信封契约 §4：域报告非 RPC 信封，ok 键构建后补赋（避开 AST 一跳
    # 变量中转形态的裸信封守卫；ok 语义=verdict==PASS，见下）。
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "verdict": verdict,
        "template": eff_template,
        "touchstone": str(ts_path) if ts_path is not None else None,
        "criteria": criteria,
        "summary": {
            "n_pass": statuses.count(PASS),
            "n_fail": len(fail_factors),
            "n_unknown": len(unknown_factors),
            "fail_factors": fail_factors,
            "unknown_factors": unknown_factors,
        },
    }
    report["ok"] = verdict == VERDICT_PASS
    if errors:
        report["errors"] = errors
    return report
