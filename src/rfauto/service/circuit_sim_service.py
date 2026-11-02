"""ADS 前仿链回路 service（aurora_o T-O4）：出图 / 三态合参 / 编排 / 反标注。

用户旅程（runs/aurora_o/design_specs/T-O4_ADS_UX_SPEC.md §1.1 五步）：
J1 出图 → J2 draw.io Edit Data 改值 → J3 run（读图→合参→渲染网表→
hpeesofsim→解析→系统指标→对拍）→ J4 反标注 → J5 迭代。用户核心需求=
"人工参与并调整前仿"——本模块是回路的编排薄层，**零内核新建**：

- 渲染/求解/解析/对拍全复用 service/ads_template_service（render_ads_template
  / run_ads_template；``runner`` 注入 = 离线验收通道，#139 单测纪律）；
- 系统指标复用 linkage/ads_circuit.compute_system_metrics（带内均值单源）；
- 网表数值只出自确定性渲染器（铁律 7）：图上参数是**文本**，经
  core/circuit_diagram.parse_effective_params 解析后直喂渲染器，本模块
  零物理公式零数字手抄；指标卡数值经 report_render.fmt_value（.6g 单源）。

三态优先级（spec §3.1 钉死）：``params_override``（--params JSON）显式键 >
图 UserObject ``p_*`` 值 > 族缺省（渲染器缺省/BRANCHLINE_CASCADE_DEFAULTS/
sweep 缺项随 SnP 频带）。合并后逐键带来源（input-json/diagram/default）
回显进信封（审计可读）。

反标注（spec §4）：指标 → ``annot_sim`` 层追加回图（core.
build_annotated_diagram_xml 幂等替换旧层）；每数值卡必带
source+sim_ref+unit（provenance 图版）；sim_ref=数据集文件路径**非时间戳**
（byte-identical 纪律，同图同结果两次反标注逐字节同文件）。

环境红线（转抄，本模块禁绕行）：求解只走 ads_netlist.run_hpeesofsim 正规
入口（#272 裸调 exe 静默无输出）；真机执行仓根或显式 RFAUTO_HPEESOF_DIR
（#295 相对 cwd 读 settings）；真机 solo 单飞（#246 并发拖慢 2.7-8×）。

M3 增补（aurora_p A2 席，spec §八 遗留 1 实施位；设计定稿
runs/aurora_p/a2/M3_DESIGN.md）：active_chain_sparam / loadpull_hb 两族
接入同一回路——渲染步分派到 linkage.ads_active_chain 既有渲染器
（#293 HB 语法真机实证单源，本模块零网表语法零数字手抄）；PARAM_KEYS/
METRIC_NAMES 保持 MVP 两族不动（既有自证钉零改动），新族注册表
ACTIVE_PARAM_KEYS/ACTIVE_METRIC_NAMES 并行，内部查表走并集。active 族
对拍容差语义=linkage 对拍函数单源缺省（链 0.1 dB / loadpull 0.05 dB），
``gate`` 显式给则透传为 tol_db。

B4 增补（aurora_p B4 席，反标注曲线嵌入；opt-in 缺省零变化）：``curves``
（run）/ ``with_curves``（annotate）开启后，circuit_result 的 ``circuit
["curves"]`` 节（曲线序列节点——core.diagram_curve_image 从 parse payload
单源逐点提取）反标注为 ``sim_g`` 曲线卡（drawio image cell，data URI
无 ``;base64`` 红线先例同款）；payload 无 S 参数（HB 单点族）如实跳过
不炸（warnings 注记）；缺省参数路径行为逐字节同现状（既有幂等/键集钉
零改动）。
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.core import diagram_curve_image as dci
from rfauto.core.active_chain import DEFAULT_Z0
from rfauto.core.circuit_diagram import (
    ANNOT_LAYER_ID,
    CircuitDiagramError,
    build_annotated_diagram_xml,
    build_circuit_diagram_xml,
    family_param_keys,
    family_param_owner,
    parse_effective_params,
    read_circuit_params,
    write_circuit_xml,
)
from rfauto.linkage import ads_template_family as atf
from rfauto.service import ads_template_service as ads_svc
from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.report_render import fmt_value

logger = logging.getLogger(__name__)

__all__ = [
    "ACTIVE_METRIC_NAMES",
    "ACTIVE_PARAM_KEYS",
    "METRIC_NAMES",
    "PARAM_KEYS",
    "annotate_circuit_diagram",
    "circuit_sim_run",
    "generate_circuit_diagram",
]

#: param_key 白名单（spec §2.3 单源；自证钉见 tests/unit/
#: test_circuit_sim_service.py——inspect.signature 断言本表==渲染器关键字
#: 参数集（含 sweep 子键展开），白名单忘更即红；另钉==core.circuit_diagram
#: 布局表键集（#231 注册表消费者家法参数版））。
PARAM_KEYS: dict[str, frozenset[str]] = {
    "wilkinson_snp": frozenset({
        "sweep.fstart", "sweep.fstop", "sweep.npoints", "sweep.unit", "z0", "n_ports",
    }),
    "branchline_cascade": frozenset({
        "sweep.fstart", "sweep.fstop", "sweep.npoints", "sweep.unit", "z0",
        "f0_hz", "theta_in_deg", "theta_out_deg", "z_line",
    }),
}

#: M3 增补两族参数白名单（aurora_p A2；设计定稿 runs/aurora_p/a2/
#: M3_DESIGN.md §1/§4）。active_chain_sparam 的 match_snp=数据文件位参
#: 上图（device 走 run --snp——同 MVP snp_path 排除语义的显式例外）；
#: loadpull_hb 的 z_load_re/z_load_im 成对 ↔ 渲染器 z_load: complex
#: （service 组装）。自证钉=tests/unit/test_circuit_diagram_active.py
#: （渲染器签名键集集合差恰=例外键，#231 家法参数版）。
ACTIVE_PARAM_KEYS: dict[str, frozenset[str]] = {
    "active_chain_sparam": frozenset({
        "frequency_unit", "npoints", "z0", "match_snp",
    }),
    "loadpull_hb": frozenset({
        "f0_hz", "power_dbm", "harmonic_order", "frequency_unit", "z0",
        "z_load_re", "z_load_im",
    }),
}

#: 全族查表（PARAM_KEYS 保持 MVP-only 零改动的组合视图；run/generate/
#: 三态合并一律经此取已知族与白名单）。
_ALL_PARAM_KEYS: dict[str, frozenset[str]] = {**PARAM_KEYS, **ACTIVE_PARAM_KEYS}

#: per-family 系统指标清单（spec §3.2 单源：wilkinson 3 端口=AdsCircuitRecipe
#: 缺省四指标；branchline 合成 2 端口无平衡指标）。
METRIC_NAMES: dict[str, tuple[str, ...]] = {
    "wilkinson_snp": (
        "system_gain_db", "input_vswr", "amplitude_balance_db", "output_phase_balance",
    ),
    "branchline_cascade": ("system_gain_db", "input_vswr"),
}

#: M3 增补两族指标清单（loadpull=HB 单点 Pout/增益，aac.hb_payload_to_point
#: 单源；active_chain=2 端口链路增益/驻波，同 compute_system_metrics）。
ACTIVE_METRIC_NAMES: dict[str, tuple[str, ...]] = {
    "active_chain_sparam": ("system_gain_db", "input_vswr"),
    "loadpull_hb": ("pout_dbm", "gain_db"),
}

_ALL_METRIC_NAMES: dict[str, tuple[str, ...]] = {**METRIC_NAMES, **ACTIVE_METRIC_NAMES}

#: 指标单位表（annot 卡 unit 属性；无量纲="1"，ISO 80000 口径）
_METRIC_UNITS: dict[str, str] = {
    "system_gain_db": "dB", "input_vswr": "1",
    "amplitude_balance_db": "dB", "output_phase_balance": "deg",
    "pout_dbm": "dBm", "gain_db": "dB",
}

#: 反标注右栏卡几何与样式（常量——spec §八.5 实现席定夺项；x=1060 与
#: core 布局表预留的反标注列同位；绿系=ok / 红系=fail——不凑绿语义的颜色化）
_ANNOT_X = 1060
_ANNOT_W = 340
_ANNOT_Y0 = 40
_ANNOT_GAP = 16
_HEAD_H = 104
_METRIC_H = 40
_COMPARE_H = 40
_METRIC_STYLE = ("rounded=1;whiteSpace=wrap;html=1;"
                 "fillColor=#d5e8d4;strokeColor=#82b366;align=left;")
_METRIC_BAD_STYLE = ("rounded=1;whiteSpace=wrap;html=1;"
                     "fillColor=#f8cecc;strokeColor=#b85450;align=left;")

#: 指标数值文本格式化单源（spec §4.2：.6g 家法——复用 report_render.fmt_value
#: 同函数，禁 .4f 手搓；import 在文件头）

#: 频率单位换算（active_chain sweep 快照回显专用；与 atf._UNIT_SCALE 同表
#: 语义——网表数字单源仍在渲染器，本表只服务信封/头卡回显）
_FREQ_SCALE: dict[str, float] = {"GHz": 1e9, "MHz": 1e6, "kHz": 1e3, "Hz": 1.0}

#: 指标单源函数名（annot 卡 source 属性；loadpull=HB 点结果提取函数，
#: 其余族（含 active_chain）S 参数指标同出 compute_system_metrics）
_METRIC_SOURCE_SPARAM = "rfauto.linkage.ads_circuit.compute_system_metrics"
_METRIC_SOURCE_HB = "rfauto.linkage.ads_active_chain.hb_payload_to_point"

#: 曲线卡几何（B4；640×400 px PNG 的 1.6 整数等比——core.diagram_curve_image
#: CURVE_CANVAS 同比；x=反标注列同位、y=sim_c 之后续排）
_CURVE_W = 480
_CURVE_H = 300
#: 曲线卡 label（图例键名动态段由 _annotation_cards 注入；ASCII 键名+中文
#: 卡面文案——图内（PNG 内部）文本 ASCII 纪律由 core 渲染面单源承担）
_CURVE_LABEL_FMT = "S 参数曲线（dB）：{labels}——数据=parse payload 单源"


# --------------------------------------------------------------------------- #
# 入参归一（#140：PathLike 第一行收敛；params JSON 形态归一）
# --------------------------------------------------------------------------- #

def _normalize_override(params_override: Any) -> dict[str, Any]:
    """--params JSON → flat dotted 覆盖表（嵌套 ``{"sweep": {...}}`` 展开）。

    值保持 JSON 原生类型（渲染器直接消费，不走文本往返）；bool 显式拒绝
    （bool 是 int 子类，float(True)=1.0 静默手误）。
    """
    if params_override is None:
        return {}
    if not isinstance(params_override, dict):
        raise CircuitDiagramError(
            f"params 覆盖必须是 JSON 对象，收到 {type(params_override)!r}")
    flat: dict[str, Any] = {}
    for key, val in params_override.items():
        if isinstance(val, bool):
            raise CircuitDiagramError(f"参数 {key!r} 值不能是 bool（{val!r}）")
        if key == "sweep" and isinstance(val, dict):
            for leaf, leaf_val in val.items():
                if isinstance(leaf_val, bool):
                    raise CircuitDiagramError(
                        f"参数 sweep.{leaf} 值不能是 bool（{leaf_val!r}）")
                flat[f"sweep.{leaf}"] = leaf_val
        else:
            flat[str(key)] = val
    return flat


def _fmt_param_text(key: str, value: Any) -> str:
    """参数值 → 图面文本（int 键整数、float %g、str 原样；bool 拒）。

    %g 形态与渲染器网表 %g 同族（"2.4e+09"/"50"），float 往返无损——
    读回-渲染等价钉（不改值时网表=渲染器直调逐字节）依赖此无损性。
    """
    if isinstance(value, bool):
        raise CircuitDiagramError(f"参数 {key!r} 值不能是 bool（{value!r}）")
    if key in ("n_ports", "sweep.npoints", "npoints", "harmonic_order"):
        return str(int(value))
    if isinstance(value, (int, float)):
        return f"{float(value):g}"
    return str(value)


def _family_defaults(family: str) -> dict[str, Any]:
    """族缺省表（flat dotted；sweep 缺项=None=随 SnP 频带，unit=渲染器缺省）。

    数值单源：branchline 数值全部抄 linkage.BRANCHLINE_CASCADE_DEFAULTS
    （逐键引用不重造）；wilkinson z0=渲染器签名缺省 50.0（白名单自证钉
    同步钉住该缺省，签名漂移即红）。M3 两族（设计定稿 §1）：z0 缺省=
    core.active_chain.DEFAULT_Z0（渲染器同源单值）；harmonic_order=渲染器
    签名缺省 5（自证钉同步钉住）；npoints J1 出图时以 meta 解析为具体值
    （min 两文件）；必给键（match_snp/f0_hz/power_dbm/z_load_re/
    z_load_im）缺省 None=文件路径与 HB 工作点不臆造（铁律 7），J1 需
    --params 显式给。
    """
    if family == "wilkinson_snp":
        return {
            "sweep.fstart": None, "sweep.fstop": None, "sweep.npoints": None,
            "sweep.unit": "GHz", "z0": 50.0, "n_ports": None,
        }
    if family == "active_chain_sparam":
        return {
            "frequency_unit": "GHz", "npoints": None,
            "z0": float(DEFAULT_Z0), "match_snp": None,
        }
    if family == "loadpull_hb":
        return {
            "f0_hz": None, "power_dbm": None, "harmonic_order": 5,
            "frequency_unit": "GHz", "z0": float(DEFAULT_Z0),
            "z_load_re": None, "z_load_im": None,
        }
    defaults: dict[str, Any] = {
        "sweep.fstart": None, "sweep.fstop": None, "sweep.npoints": None,
        "sweep.unit": "GHz", "z0": float(atf.BRANCHLINE_CASCADE_DEFAULTS["z0"]),
    }
    for key in ("f0_hz", "theta_in_deg", "theta_out_deg", "z_line"):
        defaults[key] = float(atf.BRANCHLINE_CASCADE_DEFAULTS[key])
    return defaults


def _resolve_active_generation_defaults(
    family: str,
    snp: Path,
    override: dict[str, Any],
    ads_netlist: Any,
) -> dict[str, Any]:
    """M3 两族 J1 出图缺省解析与必给键核对（fail fast——渲染器终审前的 J1 面）。

    active_chain_sparam：match_snp 必给（文件存在+2 端口核对）；npoints
    缺省解析为具体值=min(两文件 npoints)（渲染器语义回显——非 sweep 键
    不上图空串语义，出图永远全键具体值）。loadpull_hb：f0_hz/power_dbm/
    z_load_re/z_load_im 必给（HB 工作点/负载阻抗不臆造，铁律 7）。
    """
    defaults = _family_defaults(family)
    if family == "active_chain_sparam":
        match_raw = override.get("match_snp")
        if match_raw is None:
            raise CircuitDiagramError(
                "active_chain_sparam 出图需 --params 提供 match_snp"
                "（匹配网络 Touchstone 路径——器件走 --snp）")
        match = Path(str(match_raw))
        if not match.exists():
            raise FileNotFoundError(f"匹配网络 Touchstone 不存在: {match}")
        m_meta = ads_netlist.snp_meta_for_netlist(match)
        if int(m_meta["n_ports"]) != 2:
            raise CircuitDiagramError(
                f"匹配网络 Touchstone 须 2 端口，实读 {m_meta['n_ports']}: {match}")
        d_meta = ads_netlist.snp_meta_for_netlist(snp)
        defaults["npoints"] = min(int(m_meta["npoints"]), int(d_meta["npoints"]))
    else:  # loadpull_hb
        missing = sorted(k for k in ("f0_hz", "power_dbm", "z_load_re", "z_load_im")
                         if k not in override)
        if missing:
            raise CircuitDiagramError(
                f"loadpull_hb 出图缺必给参数 {missing}（--params 显式给——"
                "HB 工作点/负载阻抗不臆造，铁律 7）")
    return defaults


def _flatten_params(params: dict[str, Any]) -> dict[str, Any]:
    """渲染器 params dict（嵌套 sweep）→ flat dotted。"""
    flat: dict[str, Any] = {}
    for key, val in params.items():
        if key == "sweep" and isinstance(val, dict):
            for leaf, leaf_val in val.items():
                flat[f"sweep.{leaf}"] = leaf_val
        else:
            flat[key] = val
    return flat


def _nest_params(flat: dict[str, Any]) -> dict[str, Any]:
    """flat dotted → 渲染器 params dict（sweep 子 dict 组装）。"""
    out: dict[str, Any] = {}
    sweep: dict[str, Any] = {}
    for key, val in flat.items():
        if val is None:
            continue
        if key.startswith("sweep."):
            sweep[key[len("sweep."):]] = val
        else:
            out[key] = val
    if sweep:
        out["sweep"] = sweep
    return out


def _three_state_merge(
    family: str,
    diagram_raw: dict[str, str],
    params_override: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[str]]:
    """三态合成（spec §3.1/§6 钉 3）：--params > 图值 > 族缺省。

    Returns:
        (params_for_render, effective_view, notes)
        effective_view = {key: {"value": v|None, "source": input-json/diagram/
        default}}（sorted 键序——信封确定性）。

    Raises:
        CircuitDiagramError: 非 sweep 键图值空串/图缺键且覆盖亦缺
            （spec §2.4：空串=缺项仅限 sweep；缺键=J2 误删，fail loud——
            sweep 四键除外，其缺项语义=Touchstone 兜底，spec §2.2）。
    """
    override = _normalize_override(params_override)
    known = _ALL_PARAM_KEYS[family]
    notes: list[str] = []
    unknown = sorted(set(diagram_raw) - known)
    if unknown:
        notes.append(
            "忽略白名单外参数键（读回 warnings 计数并忽略，spec §2.3）: "
            + ", ".join(unknown))
    whitelist_raw = {k: v for k, v in diagram_raw.items() if k in known}
    diagram_params = parse_effective_params(whitelist_raw)
    diagram_flat = _flatten_params(diagram_params)
    defaults = _family_defaults(family)
    effective: dict[str, dict[str, Any]] = {}
    merged_flat: dict[str, Any] = {}
    for key in sorted(known):
        if key in override:
            value: Any = override[key]
            source = "input-json"
        elif key in diagram_flat:
            value = diagram_flat[key]
            source = "diagram"
        elif key.startswith("sweep."):
            # sweep 缺项=合法三态（缺项语义→Touchstone 兜底，spec §2.2/§6 钉 3）
            value = defaults.get(key)
            source = "default"
            notes.append(f"{key} 缺项→随 SnP 频带（resolve_sweep 兜底）")
        else:
            # 非 sweep 键图缺且覆盖亦缺=J2 误删，fail loud（spec §2.4 空串/
            # 缺键语义仅限 sweep；静默兜缺省会把用户改过的值无声丢掉）
            raise CircuitDiagramError(
                f"图缺必带参数键 {key!r}（预期承载卡 {family_param_owner(family, key)}"
                "；J2 编辑误删请恢复属性或重新出图）")
        merged_flat[key] = value
        effective[key] = {"value": value, "source": source}
    return _nest_params(merged_flat), effective, notes


# --------------------------------------------------------------------------- #
# J1 出图
# --------------------------------------------------------------------------- #

def generate_circuit_diagram(
    family: str,
    snp_path: Any,
    out_path: Any,
    *,
    params: dict[str, Any] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """生成参数化电路图 .drawio（J1；不触 ADS）。

    缺省值取族缺省（图上 sweep fstart/fstop/npoints 留空=随 SnP 频带的
    缺项语义显式上图，spec §2.2）；``params``（同 --params 形态，flat 或
    嵌套）可覆盖缺省。SnP 端口数实读（snp_meta_for_netlist，#248 钉：
    图上端口卡数==实读 N）。

    Returns: ok 信封 {out_path, family, n_ports, values:{key:{value,source}}}；
    失败 ok=False errors=[...]（信封契约，不静默不凑绿）。
    """
    try:
        family = str(family)
        if family not in _ALL_PARAM_KEYS:
            raise CircuitDiagramError(
                f"未知模板族 {family!r}（可选 {sorted(_ALL_PARAM_KEYS)}）")
        snp = Path(snp_path)  # PathLike 入参第一行收敛（#140）
        if not snp.exists():
            raise FileNotFoundError(f"Touchstone 不存在: {snp}")
        from rfauto.adapters import ads_netlist

        meta = ads_netlist.snp_meta_for_netlist(snp)
        n_ports = int(meta["n_ports"])
        override = _normalize_override(params)
        if family in ACTIVE_PARAM_KEYS:
            # M3（设计定稿 §1）：器件=--snp（DUT 主数据），2 端口契约
            # （渲染器同款核对，J1 fail fast）；n_ports 拓扑固定 2。
            if n_ports != 2:
                raise CircuitDiagramError(
                    f"{family} 器件 Touchstone 须 2 端口，实读 {n_ports}: {snp}")
            n_ports = 2
            defaults = _resolve_active_generation_defaults(family, snp, override, ads_netlist)
        else:
            if "n_ports" in override:
                n_ports = int(override["n_ports"])
            if family == "branchline_cascade" and n_ports != 4:
                raise CircuitDiagramError(
                    f"branchline_cascade 期望 4 端口 Touchstone，实读 {n_ports}: {snp}")
            defaults = _family_defaults(family)
        values: dict[str, str] = {}
        view: dict[str, dict[str, Any]] = {}
        for key in family_param_keys(family):
            if key in override:
                value: Any = override[key]
                # 来源名与 run 三态同词表（spec §3.1 单源：--params JSON 显式键
                # =input-json；J1 出图与 J3 run 同名，消费端零分叉——aurora_o
                # o_ads 件2 统一，原 J1 侧 "params-json" 并入）
                source = "input-json"
            else:
                value = defaults.get(key)
                source = "default"
            if key == "n_ports" and value is None:
                value = n_ports
                source = "default"
            if value is None:
                if family in ACTIVE_PARAM_KEYS:
                    # M3：active 族必给键（match_snp/f0_hz/power_dbm/z_load_*）
                    # 缺失=J1 显式报错——文件路径与 HB 工作点不臆造（铁律 7），
                    # 无 sweep 缺项语义（两族均无 sweep.* 键）
                    raise CircuitDiagramError(
                        f"{family} 出图缺必给参数 {key!r}（--params 显式给——"
                        "文件路径/HB 工作点不臆造，铁律 7）")
                values[key] = ""  # sweep 缺项语义上图显式化（spec §2.2）
                view[key] = {"value": None, "source": source}
            else:
                values[key] = _fmt_param_text(key, value)
                view[key] = {"value": value, "source": source}
        xml_text = build_circuit_diagram_xml(
            family, values, n_ports=n_ports, snp_name=snp.name, title=title)
        out = write_circuit_xml(xml_text, out_path)
    except (ValueError, TypeError, OSError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")
    return ok_envelope(
        out_path=str(out), family=family, n_ports=n_ports, values=view,
        n_params=len(values))


# --------------------------------------------------------------------------- #
# J3+J4 run：读图→三态合参→渲染→求解→解析→指标→反标注
# --------------------------------------------------------------------------- #

def circuit_sim_run(
    diagram_path: Any,
    *,
    snp_path: Any,
    out_dir: Any,
    params_override: dict[str, Any] | None = None,
    runner: Callable[[Path], dict[str, Any]] | None = None,
    ads_dir: Any = None,
    compare: bool = True,
    gate: float | None = None,
    family: str | None = None,
    reference_snp_path: Any = None,
    curves: bool = False,
) -> dict[str, Any]:
    """读图 → 三态合参 → 渲染 → 求解/解析 → 指标 → 反标注（J3+J4 一条龙）。

    Args:
        diagram_path: .drawio 图（**只读**——反标注产物落 out_dir，原稿不动）。
        snp_path: Touchstone 路径（网表 File 来源；图上 SnP 卡仅示名）。
        out_dir: 工作目录（必填语义=缺省拒跑防 cwd 落湖，#144 家法）。
        params_override: 三态最高优先（--params JSON，flat 或嵌套 sweep）。
        runner: ``runner(netlist_path) -> payload`` 注入位（离线验收通道，
            #139；None=真 hpeesofsim 链，env 红线 #272/#295 由既有入口处理）。
        ads_dir: ADS 安装根（缺省 env RFAUTO_HPEESOF_DIR → settings）。
        compare: 是否对拍（真机缺省 True）。
        gate: 对拍门（MVP 族 None=DEFAULT_MAX_ABS_DELTA_S_GATE，max|ΔS| 口径；
            active 族=对拍容差 dB 透传，None=linkage 对拍函数单源缺省）。
        family: 显式族名核对（与图内 family 不一致=error，#154 防张冠李戴）。
        reference_snp_path: 对拍参考（透传 run_ads_template，缺省 snp 自身）。
        curves: opt-in 曲线卡（B4）：True 时 payload S 参数单源提取为
            circuit["curves"] 节并反标注 sim_g 曲线卡；payload 无 S 参数
            （HB 单点族）如实 warnings 跳过不炸；False（缺省）行为逐字节
            同现状（零新键零新卡）。

    Returns:
        ok 信封（family/effective/sweep/metrics/compare/ads/netlist_path/
        result_path/annotated_diagram_path/notes；curves=True 时另带
        curves_card）；ADS 段失败如实 ok=False
        并降级反标注（只装 error 头卡，#105/#122 不虚构指标）。
    """
    try:
        diagram_file = Path(diagram_path)  # PathLike 入参第一行收敛（#140）
        snp = Path(snp_path)
        work = Path(out_dir)
        if not diagram_file.exists():
            raise FileNotFoundError(f"电路图不存在: {diagram_file}")
        if not snp.exists():
            raise FileNotFoundError(f"Touchstone 不存在: {snp}")
        original_xml = diagram_file.read_text(encoding="utf-8")
        info = read_circuit_params(original_xml)
        fam = info["family"]
        if fam is None:
            raise CircuitDiagramError(
                "图缺 family 属性（非 rfauto 出图或被改坏——请用 "
                "ads-circuit diagram 重新出图）")
        if family is not None and str(family) != fam:
            raise CircuitDiagramError(
                f"图内 family={fam!r} 与显式 --family={family!r} 不一致"
                "（防张冠李戴，#154 家法）")
        if fam not in _ALL_PARAM_KEYS:
            raise CircuitDiagramError(
                f"未知模板族 {fam!r}（可选 {sorted(_ALL_PARAM_KEYS)}）")
        params_for_render, effective, notes = _three_state_merge(
            fam, info["raw"], params_override)
        is_active = fam in ACTIVE_PARAM_KEYS
        if gate is None and not is_active:
            gate = ads_svc.DEFAULT_MAX_ABS_DELTA_S_GATE

        # runner 捕获包装：payload 旁路给指标层（注入通道旁路捕获；真机链
        # 由 _run_active_netlist 解析后同样入 box——active 族解析×1，
        # MVP 既有回路解析×2 的编排成本不复制到新面）
        box: dict[str, Any] = {}

        def _capture_runner(netlist: Path) -> dict[str, Any]:
            if runner is None:
                raise RuntimeError("capture runner 只应在注入模式被调用")
            payload = runner(netlist)
            box["payload"] = payload
            return payload

        if is_active:
            # M3：渲染分派 aac 渲染器单源（#293 HB 语法域），求解/解析
            # 镜像 run_ads_template 口径（#272 正规入口、失败如实降级）
            run_result = _run_active_netlist(
                fam, snp, work, params_for_render, ads_dir=ads_dir,
                runner=_capture_runner if runner is not None else None, box=box)
        else:
            request: dict[str, Any] = {
                "family": fam, "snp_path": snp, "out_dir": work,
                "params": params_for_render, "compare": bool(compare),
                "max_abs_delta_s_gate": float(gate),
            }
            if ads_dir is not None:
                request["ads_dir"] = ads_dir
            if reference_snp_path is not None:
                request["reference_snp_path"] = Path(reference_snp_path)
            run_result = ads_svc.run_ads_template(
                request, ads_runner=_capture_runner if runner is not None else None)

        payload = box.get("payload")
        metrics: dict[str, float] | None = None
        extras: dict[str, Any] = {}
        if payload is None and run_result.get("ads", {}).get("status") == "ok":
            # 防御位复解析（box 单次取数已覆盖常规路径；禁绕过正规入口，#272）
            from rfauto.adapters import ads_netlist

            dataset = Path(run_result["ads"]["dataset_path"])
            payload = (ads_netlist.parse_hb_dataset(dataset, ads_dir=ads_dir)
                       if fam == "loadpull_hb"
                       else ads_netlist.parse_dataset(dataset, ads_dir=ads_dir))
        if payload is not None:
            if is_active:
                from rfauto.linkage import ads_active_chain as aac

                metrics, extras = _finish_active_family(
                    run_result, fam, snp, params_for_render, payload,
                    compare=bool(compare), gate=gate, aac=aac)
            elif fam == "wilkinson_snp":
                net = atf.payload_to_network(payload)
                from rfauto.linkage import ads_circuit as ads_circuit_kernel

                metrics = ads_circuit_kernel.compute_system_metrics(
                    net, list(METRIC_NAMES[fam]))
            else:
                from rfauto.linkage import field_circuit_anchor as fca

                net = fca.composite_network_from_payload(payload)
                from rfauto.linkage import ads_circuit as ads_circuit_kernel

                metrics = ads_circuit_kernel.compute_system_metrics(
                    net, list(METRIC_NAMES[fam]))

        # B4 曲线序列节点（opt-in）：payload（box 单次取数/防御复解析同一份）
        # 单源提取——零重解析；payload 无 S 参数（HB 单点族）如实 warnings
        # 跳过，不炸主链（#122 如实不凑）
        curves_node: dict[str, Any] | None = None
        if curves and payload is not None:
            if dci.payload_has_sparams(payload):
                curves_node = dci.curve_series_from_payload(payload)
            else:
                notes.append(
                    "curves 开启但 payload 无 S 参数（如实跳过曲线卡——"
                    "HB 单点族无频扫 S 参数）")

        circuit_result = _enrich_result(run_result, fam, effective, notes,
                                        metrics, extras, curves=curves_node)
        result_path = work / f"{fam}_circuit_result.json"
        work.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(circuit_result, ensure_ascii=False, indent=2), encoding="utf-8")
        annotated_xml = build_annotated_diagram_xml(
            original_xml, _annotation_cards(circuit_result, result_ref=str(result_path),
                                            with_curves=bool(curves)),
            layer_title=f"前仿指标（{fam}）")
        annotated_path = work / f"{fam}_circuit.drawio"
        annotated_path.write_text(annotated_xml, encoding="utf-8")

        fields = {
            "family": fam,
            "diagram_source": str(diagram_file),
            "netlist_path": str(run_result["netlist_path"]),
            "result_path": str(result_path),
            "annotated_diagram_path": str(annotated_path),
            "annot_layer": ANNOT_LAYER_ID,
            "effective": effective,
            "sweep": run_result.get("sweep"),
            "metrics": metrics,
            "compare": run_result.get("compare"),
            "ads": run_result.get("ads"),
            "warnings": notes,
            "annotated": True,
        }
        if curves:
            fields["curves_card"] = curves_node is not None
        if run_result.get("ok"):
            return ok_envelope(**fields)
        # aurora_p H1 P2-2（B1 F-6 清偿）：对拍门红≠求解败——gate 未过而
        # 仿真本身 rc=0 时按"对拍门未过"分派文案，ADS 真失败才报"ADS 段
        # 失败"（两态对工程用户语义不同，#122 不共用误导文案）。
        ads_ok = (run_result.get("ads") or {}).get("status") == "ok"
        if ads_ok:
            reason = "对拍门未过（仿真本身成功，详见 gate/ads 节；反标注已降级装 error 头卡，#105 不掩盖）"
        else:
            reason = "ADS 段失败（详见 ads 节；反标注已降级装 error 头卡，#105 不掩盖）"
        return error_envelope(reason, **fields)
    except (ValueError, TypeError, OSError, KeyError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")


def _run_active_netlist(
    family: str,
    snp: Path,
    out_dir: Path,
    params: dict[str, Any],
    *,
    ads_dir: Any = None,
    runner: Callable[[Path], dict[str, Any]] | None = None,
    box: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """active 族 渲染+求解+解析（run_ads_template 的 M3 对应段，信封同构）。

    渲染=linkage.ads_active_chain 渲染器单源（本模块零网表语法零数字手抄，
    铁律 7）；求解只走 ads_netlist 正规入口（#272 禁裸调 exe）；解析经 box
    单次取数（注入与真机同路径）。ADS 段失败如实降级 status=error
    （#105/#122 不掩盖——上层照常反标注装 error 头卡）。
    """
    from rfauto.linkage import ads_active_chain as aac

    result: dict[str, Any] = {"family": family, "snp_path": str(snp), "params": params}
    netlist = out_dir / f"{family}_netlist.txt"
    result["netlist_path"] = str(netlist)  # 意图路径先行（渲染失败时信封仍有落点）
    ok = False
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        if family == "active_chain_sparam":
            match = Path(str(params["match_snp"]))
            if not match.exists():
                raise FileNotFoundError(f"匹配网络 Touchstone 不存在: {match}")
            aac.render_chain_netlist(
                match, snp, netlist,
                frequency_unit=str(params.get("frequency_unit") or "GHz"),
                npoints=params.get("npoints"),
                z0=float(params.get("z0", DEFAULT_Z0)),
            )
            result["sweep"] = _chain_sweep_snapshot(match, snp, params)
        else:  # loadpull_hb（HB 单点无频扫，sweep=None）
            z_load = complex(float(params["z_load_re"]), float(params["z_load_im"]))
            aac.render_loadpull_netlist(
                snp, netlist,
                f0_hz=float(params["f0_hz"]), power_dbm=float(params["power_dbm"]),
                z_load=z_load,
                harmonic_order=int(params.get("harmonic_order", 5)),
                z0=float(params.get("z0", DEFAULT_Z0)),
                frequency_unit=str(params.get("frequency_unit") or "GHz"),
            )
            result["sweep"] = None
        t0 = time.time()
        if runner is not None:
            payload = runner(netlist)
            if box is not None:
                box["payload"] = payload
            result["ads"] = {"status": "ok", "runner": "injected"}
        else:
            from rfauto.adapters import ads_netlist

            proc = ads_netlist.run_hpeesofsim(netlist, ads_dir=ads_dir)
            (out_dir / f"{family}_hpeesofsim_stdout.txt").write_text(
                proc.stdout[-6000:] + "\n--- stderr ---\n" + proc.stderr[-2000:],
                encoding="utf-8")
            dataset = Path(f"{netlist}.ds")
            parse = (ads_netlist.parse_hb_dataset if family == "loadpull_hb"
                     else ads_netlist.parse_dataset)
            payload = parse(dataset, ads_dir=ads_dir)
            if box is not None:
                box["payload"] = payload
            result["ads"] = {
                "status": "ok", "runner": "hpeesofsim", "returncode": proc.returncode,
                "sim_time_s": round(time.time() - t0, 3), "dataset_path": str(dataset),
            }
        result["ads"].update(_ads_payload_view(family, payload))
        ok = True
    except Exception as exc:  # 观测性 best-effort（run_ads_template 同款口径）
        det = getattr(exc, "details", None)
        tail = ""
        if isinstance(det, dict):
            tail = str(det.get("stdout") or det.get("stderr") or "")[-600:]
        result["ads"] = {"status": "error",
                         "error": f"{type(exc).__name__}: {exc} {tail}".strip()}
    result["ok"] = bool(ok)
    return result


def _chain_sweep_snapshot(match: Path, snp: Path, params: dict[str, Any]) -> dict[str, Any]:
    """active_chain 频扫快照（信封/头卡回显；网表数字单源仍在渲染器）。

    与渲染器同式（max/min 频段交集 + npoints 显式或 min；缺频段交集
    ValueError 由渲染器先行抛出）——source=touchstone（频段来自两数据
    文件，非用户显式三项）。
    """
    from rfauto.adapters import ads_netlist

    unit = str(params.get("frequency_unit") or "GHz")
    scale = _FREQ_SCALE[unit]
    m = ads_netlist.snp_meta_for_netlist(match)
    d = ads_netlist.snp_meta_for_netlist(snp)
    f_lo = max(float(m["fstart_hz"]), float(d["fstart_hz"]))
    f_hi = min(float(m["fstop_hz"]), float(d["fstop_hz"]))
    npoints = params.get("npoints")
    if npoints is None:
        npoints = min(int(m["npoints"]), int(d["npoints"]))
    return {
        "fstart": f_lo / scale, "fstop": f_hi / scale,
        "npoints": int(npoints), "unit": unit,
        "fstart_hz": f_lo, "fstop_hz": f_hi, "source": "touchstone",
    }


def _ads_payload_view(family: str, payload: dict[str, Any]) -> dict[str, Any]:
    """payload → ads 节回显键（n_points/port_names——annot 头卡消费）。

    loadpull_hb 的 HB 数据集行=谐波行（mix 0=DC、1=基波..），n_points
    语义=谐波数；port_names 数据集不携带（头卡 ports=0 如实）。
    """
    if family == "loadpull_hb":
        return {"n_points": len(payload.get("harmonics") or [])}
    return {
        "n_points": len(payload.get("frequency_hz") or []),
        "port_names": payload.get("port_names"),
        "port_z": payload.get("port_z"),
    }


def _finish_active_family(
    run_result: dict[str, Any],
    family: str,
    snp: Path,
    params_for_render: dict[str, Any],
    payload: dict[str, Any],
    *,
    compare: bool,
    gate: float | None,
    aac: Any,
) -> tuple[dict[str, float], dict[str, Any]]:
    """active 族 指标+对拍（payload→metrics；run_result 就地补 compare/ok）。

    - active_chain_sparam：aac.payload_to_network → compute_system_metrics；
      对拍=compare_chain_with_manual vs skrf 级联（手工口径同源参考）；
    - loadpull_hb：aac.hb_payload_to_point 单源取点；对拍=
      compare_loadpull_point vs loadpull_point_closed_form（确定性参考）。

    对拍容差语义：``gate`` 显式给=tol_db 透传；None=linkage 对拍函数单源
    缺省（链 0.1 dB / loadpull 0.05 dB）。对拍失败/提取失败如实 ok=False
    不凑绿（#122）。
    """
    from rfauto.linkage import ads_circuit as ads_circuit_kernel

    ads_ok = run_result.get("ads", {}).get("status") == "ok"
    # 容差透传：gate=None = linkage 对拍函数单源缺省（链 0.1 dB / lp 0.05 dB），
    # 显式给=tol_db 覆写——不传 None 顶掉函数缺省
    tol_kw: dict[str, Any] = {} if gate is None else {"tol_db": float(gate)}
    extras: dict[str, Any] = {}
    if family == "active_chain_sparam":
        net = aac.payload_to_network(payload)
        metrics: dict[str, float] = ads_circuit_kernel.compute_system_metrics(
            net, list(ACTIVE_METRIC_NAMES[family]))
        if compare and ads_ok:
            try:
                match = Path(str(params_for_render["match_snp"]))
                _, _, cascade = aac.chain_manual_reference(match, snp)
                cmp = aac.compare_chain_with_manual(net, cascade, **tol_kw)
                cmp["gate_ok"] = bool(cmp["consistent"])
                run_result["compare"] = cmp
            except Exception as exc:
                run_result["compare"] = {
                    "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    else:  # loadpull_hb
        z_load = complex(float(params_for_render["z_load_re"]),
                         float(params_for_render["z_load_im"]))
        power_dbm = float(params_for_render["power_dbm"])
        point = aac.hb_payload_to_point(payload, z_load=z_load, power_dbm=power_dbm)
        metrics = {name: float(point[name]) for name in ACTIVE_METRIC_NAMES[family]}
        extras = {"point": point}
        if compare and ads_ok:
            try:
                ref = aac.loadpull_point_closed_form(
                    snp, f0_hz=float(params_for_render["f0_hz"]),
                    power_dbm=power_dbm, z_load=z_load)
                cmp = aac.compare_loadpull_point(point, ref, **tol_kw)
                cmp["gate_ok"] = bool(cmp["consistent"])
                run_result["compare"] = cmp
                extras["reference"] = ref
            except Exception as exc:
                run_result["compare"] = {
                    "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    if not compare:
        run_result.setdefault("compare", {"status": "skipped"})
    cmp_node = run_result.get("compare")
    if isinstance(cmp_node, dict) and "gate_ok" in cmp_node:
        run_result["ok"] = bool(run_result.get("ok") and cmp_node["gate_ok"])
    return metrics, extras


def _enrich_result(
    run_result: dict[str, Any],
    family: str,
    effective: dict[str, dict[str, Any]],
    notes: list[str],
    metrics: dict[str, float] | None,
    extras: dict[str, Any] | None = None,
    curves: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """run 结果 + 回路面 → circuit_result（annotate 叶的离线源）。

    extras=M3 族特有节（loadpull 的 point/reference）并入 circuit 节；
    metric_source=指标单源函数名（annot 卡 source 属性，provenance 图版）；
    curves=B4 曲线序列节点（payload 单源提取，None=未开启/无 S 参数）。
    """
    sim_ref = None
    ads_node = run_result.get("ads") or {}
    if ads_node.get("dataset_path"):
        sim_ref = str(ads_node["dataset_path"])
    elif run_result.get("netlist_path"):
        sim_ref = str(run_result["netlist_path"])
    circuit: dict[str, Any] = {
        "family": family,
        "effective": effective,
        "notes": notes,
        "metrics": metrics,
        "sim_ref": sim_ref,
        "metric_names": list(_ALL_METRIC_NAMES[family]),
        "metric_source": (_METRIC_SOURCE_HB if family == "loadpull_hb"
                          else _METRIC_SOURCE_SPARAM),
    }
    if extras:
        circuit.update(extras)
    if curves:
        circuit["curves"] = curves
    return {**run_result, "circuit": circuit}


# --------------------------------------------------------------------------- #
# 指标卡装配（run 与 annotate 两路共用的唯一卡源——spec §4.2 形态）
# --------------------------------------------------------------------------- #

def _annotation_cards(circuit_result: dict[str, Any], *, result_ref: str,
                      with_curves: bool = False) -> list[dict[str, Any]]:
    """circuit_result → annot_sim 指标卡表（数值文本 .6g 单源 fmt_value）。

    - 头卡 sim_h：family/频扫快照/状态/点数/端口名（n_points 是数值 → 必带
      source+sim_ref+unit，provenance 图版钉 6）；
    - 每指标一张卡：非有限值 → status="n/a" 不出数字（NaN 不上图，钉 6）；
    - 对拍卡 sim_c：max|ΔS|/门/gate_ok 三值；gate_ok=false → 红色样式
      （不凑绿语义的颜色化）；compare skipped/error 如实降级文案；
    - 曲线卡 sim_g（B4 opt-in）：with_curves=True 且 circuit["curves"] 节
      存在时追加——PNG 确定性渲染 + 无分号 data URI 内嵌 image cell
      （幂等随整层替换）；with_curves=False 或节点缺失=零新卡（缺省零
      变化）。
    """
    circuit = circuit_result.get("circuit") or {}
    family = str(circuit.get("family") or circuit_result.get("family") or "")
    sim_ref = str(circuit.get("sim_ref") or "")
    ads_node = circuit_result.get("ads") or {}
    status = str(ads_node.get("status") or "unknown")
    cards: list[dict[str, Any]] = []
    y = _ANNOT_Y0
    sweep = circuit_result.get("sweep") or {}
    n_points = ads_node.get("n_points")
    port_names = ads_node.get("port_names") or []
    head_label = (
        f"前仿指标（{family}）\n"
        f"sweep: {_sweep_text(sweep)}\n"
        f"status={status}  n_points={fmt_value(n_points)}  "
        f"ports={len(port_names)}")
    head_attrs: dict[str, Any] = {
        "family": family, "status": status,
        "n_points": fmt_value(n_points), "unit": "1",
        "source": "rfauto.service.circuit_sim_service.circuit_sim_run",
        "sim_ref": sim_ref, "sim_result": result_ref,
    }
    if port_names:
        head_attrs["port_names"] = ",".join(str(p) for p in port_names)
    head_style_ok = status == "ok"
    cards.append({
        "id": "sim_h", "label": head_label,
        "style": ("rounded=1;whiteSpace=wrap;html=1;align=left;"
                  + ("fillColor=#d5e8d4;strokeColor=#82b366;" if head_style_ok
                     else "fillColor=#f8cecc;strokeColor=#b85450;")),
        "x": _ANNOT_X, "y": y, "width": _ANNOT_W, "height": _HEAD_H,
        "attrs": head_attrs})
    y += _HEAD_H + _ANNOT_GAP

    if status != "ok":
        # ADS 段失败降级：只装 error 头卡+stderr 尾巴引注（spec §4.3，#105）
        err_text = str(ads_node.get("error") or "")[-220:]
        cards.append({
            "id": "sim_err", "label": f"ADS 段失败（如实不虚构指标）\n{err_text}",
            "style": _METRIC_BAD_STYLE,
            "x": _ANNOT_X, "y": y, "width": _ANNOT_W, "height": _METRIC_H,
            "attrs": {"status": "error", "sim_ref": sim_ref,
                      "sim_result": result_ref, "unit": "1",
                      "source": "rfauto.service.circuit_sim_service"}})
        return cards

    metrics = circuit.get("metrics") or {}
    sim_source = str(circuit.get("metric_source") or _METRIC_SOURCE_SPARAM)
    for i, name in enumerate(circuit.get("metric_names") or []):
        value = metrics.get(name)
        unit = _METRIC_UNITS.get(name, "1")
        attrs: dict[str, Any] = {
            "metric": name, "unit": unit, "source": sim_source,
            "sim_ref": sim_ref, "sim_result": result_ref,
        }
        if value is not None and math.isfinite(float(value)):
            text = fmt_value(float(value))
            attrs["value"] = text
            attrs["status"] = "ok"
            label = f"{name} = {text} {unit}".strip()
            style = _METRIC_STYLE
        else:
            # NaN 不上图（spec §3.2：非有限 → status="n/a" 如实标注）
            attrs["status"] = "n/a"
            label = f"{name} = n/a（非有限，如实不出数字）"
            style = _METRIC_STYLE
        cards.append({
            "id": f"sim_m{i}", "label": label, "style": style,
            "x": _ANNOT_X, "y": y, "width": _ANNOT_W, "height": _METRIC_H,
            "attrs": attrs})
        y += _METRIC_H + _ANNOT_GAP

    cmp = circuit_result.get("compare") or {}
    if cmp.get("status") == "skipped":
        cards.append({
            "id": "sim_c", "label": "对拍：skipped（--no-compare）",
            "style": _METRIC_STYLE, "x": _ANNOT_X, "y": y,
            "width": _ANNOT_W, "height": _COMPARE_H,
            "attrs": {"status": "skipped", "unit": "1", "source": sim_source,
                      "sim_ref": sim_ref, "sim_result": result_ref}})
    elif "max_abs_delta_s" in cmp:
        gate_ok = bool(cmp.get("gate_ok"))
        cards.append({
            "id": "sim_c",
            "label": (
                f"对拍 max|ΔS| = {fmt_value(float(cmp['max_abs_delta_s']))}\n"
                f"门 {fmt_value(float(cmp.get('gate_max_abs_delta_s', 0)))} "
                f"gate_ok={'true' if gate_ok else 'false'}"),
            "style": _METRIC_STYLE if gate_ok else _METRIC_BAD_STYLE,
            "x": _ANNOT_X, "y": y, "width": _ANNOT_W, "height": _COMPARE_H,
            "attrs": {
                "compare_max_abs_delta_s": fmt_value(float(cmp["max_abs_delta_s"])),
                "gate_max_abs_delta_s": fmt_value(float(cmp.get("gate_max_abs_delta_s", 0))),
                "gate_ok": "true" if gate_ok else "false",
                "unit": "1", "source": "rfauto.linkage.ads_template_family.compare_family_result",
                "sim_ref": sim_ref, "sim_result": result_ref}})
    elif "max_abs_db" in cmp:
        # active_chain_sparam（dB 幅度对拍——compare_chain_with_manual 形态）
        gate_ok = bool(cmp.get("gate_ok"))
        cards.append({
            "id": "sim_c",
            "label": (
                f"对拍 max|ΔdB| = {fmt_value(float(cmp['max_abs_db']))} dB\n"
                f"容差 {fmt_value(float(cmp.get('tol_db', 0)))} dB  "
                f"gate_ok={'true' if gate_ok else 'false'}"),
            "style": _METRIC_STYLE if gate_ok else _METRIC_BAD_STYLE,
            "x": _ANNOT_X, "y": y, "width": _ANNOT_W, "height": _COMPARE_H,
            "attrs": {
                "compare_max_abs_delta_db": fmt_value(float(cmp["max_abs_db"])),
                "tol_db": fmt_value(float(cmp.get("tol_db", 0))),
                "gate_ok": "true" if gate_ok else "false",
                "unit": "dB",
                "source": "rfauto.linkage.ads_active_chain.compare_chain_with_manual",
                "sim_ref": sim_ref, "sim_result": result_ref}})
    elif "abs_delta_db" in cmp:
        # loadpull_hb（Pout dB 单点对拍——compare_loadpull_point 形态）
        gate_ok = bool(cmp.get("gate_ok"))
        cards.append({
            "id": "sim_c",
            "label": (
                f"对拍 |ΔPout| = {fmt_value(float(cmp['abs_delta_db']))} dB\n"
                f"（Δ={fmt_value(float(cmp.get('delta_db', 0)))} dB）  "
                f"容差 {fmt_value(float(cmp.get('tol_db', 0)))} dB  "
                f"gate_ok={'true' if gate_ok else 'false'}"),
            "style": _METRIC_STYLE if gate_ok else _METRIC_BAD_STYLE,
            "x": _ANNOT_X, "y": y, "width": _ANNOT_W, "height": _COMPARE_H,
            "attrs": {
                "compare_abs_delta_db": fmt_value(float(cmp["abs_delta_db"])),
                "delta_db": fmt_value(float(cmp.get("delta_db", 0))),
                "tol_db": fmt_value(float(cmp.get("tol_db", 0))),
                "gate_ok": "true" if gate_ok else "false",
                "unit": "dB",
                "source": "rfauto.linkage.ads_active_chain.compare_loadpull_point",
                "sim_ref": sim_ref, "sim_result": result_ref}})
    elif cmp.get("status") == "error":
        cards.append({
            "id": "sim_c", "label": f"对拍失败（如实）\n{str(cmp.get('error') or '')[-160:]}",
            "style": _METRIC_BAD_STYLE, "x": _ANNOT_X, "y": y,
            "width": _ANNOT_W, "height": _COMPARE_H,
            "attrs": {"status": "error", "unit": "1", "source": sim_source,
                      "sim_ref": sim_ref, "sim_result": result_ref}})

    # B4 曲线卡（opt-in；ok 状态路径——ADS 段失败降级路径无 payload 无
    # curves 节，早退不达此）：PNG 确定性渲染 + 无分号 data URI 内嵌。
    curves = circuit.get("curves") if with_curves else None
    if curves:
        plan = dci.build_curve_plan(curves)
        style = dci.curve_image_style(dci.curve_image_data_uri(
            dci.render_curves_png(plan)))
        labels = ", ".join(str(s["label"]) for s in plan["series"])
        cards.append({
            "id": "sim_g", "label": _CURVE_LABEL_FMT.format(labels=labels),
            "style": style,
            "x": _ANNOT_X, "y": y, "width": _CURVE_W, "height": _CURVE_H,
            "attrs": {
                "curves": labels, "n_points": fmt_value(plan["n_points"]),
                "unit": "dB",
                "source": "rfauto.core.diagram_curve_image.render_curves_png",
                "sim_ref": sim_ref, "sim_result": result_ref}})
    return cards


def _sweep_text(sweep: dict[str, Any]) -> str:
    """频扫快照 → 头卡一行文本（缺项如实示 "随 SnP 频带"）。"""
    if not sweep:
        return "n/a"
    source = sweep.get("source")
    return (
        f"{fmt_value(sweep.get('fstart'))}–{fmt_value(sweep.get('fstop'))} "
        f"{sweep.get('unit', '')} × {fmt_value(sweep.get('npoints'))} 点"
        f"（source={source}）")


# --------------------------------------------------------------------------- #
# annotate 叶：只反标注不重跑（离线复核/重放，spec §3.1）
# --------------------------------------------------------------------------- #

def annotate_circuit_diagram(
    diagram_path: Any,
    result_path: Any,
    out_path: Any,
    *,
    with_curves: bool = False,
) -> dict[str, Any]:
    """原图 + circuit_result.json → 反标注图（离线；不触 ADS）。

    result 须为 circuit_sim_run 产物 ``<family>_circuit_result.json``（含
    circuit 节=指标离线源；裸 run_ads_template 的 <family>_result.json 无
    指标，显式报错指引）。同图同 result 两次反标注逐字节同文件（byte-
    identical 钉：sim_ref=文件路径非时间戳）。

    ``with_curves=True``（B4 opt-in）：result 携带 ``circuit["curves"]``
    节时追加 sim_g 曲线卡（数据 URI 内嵌单文件可携）；节点缺失=warnings
    如实注记+不出卡（幂等不炸——run 侧未开 curves 或 payload 无 S 参数
    的 result 走本路径）。缺省 False 行为逐字节同现状（信封零新键）。
    """
    try:
        diagram_file = Path(diagram_path)  # PathLike 入参第一行收敛（#140）
        result_file = Path(result_path)
        if not diagram_file.exists():
            raise FileNotFoundError(f"电路图不存在: {diagram_file}")
        if not result_file.exists():
            raise FileNotFoundError(f"结果文件不存在: {result_file}")
        result = json.loads(result_file.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or "circuit" not in result:
            raise CircuitDiagramError(
                f"结果文件缺 circuit 节（annotate 消费 ads-circuit run 产物 "
                f"{result_file.name}；裸 <family>_result.json 无指标不消费）")
        original_xml = diagram_file.read_text(encoding="utf-8")
        cards = _annotation_cards(result, result_ref=str(result_file),
                                  with_curves=bool(with_curves))
        annotated_xml = build_annotated_diagram_xml(
            original_xml, cards,
            layer_title=f"前仿指标（{result.get('family')}）")
        out = write_circuit_xml(annotated_xml, out_path)
    except (ValueError, TypeError, OSError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")
    extra: dict[str, Any] = {}
    if with_curves:
        has_curve = any(str(c.get("id")) == "sim_g" for c in cards)
        extra["curves_card"] = has_curve
        extra["warnings"] = (
            [] if has_curve
            else ["result 无 circuit.curves 节（run 未开 curves 或 payload "
                  "无 S 参数）——曲线卡如实跳过"])
    return ok_envelope(
        out_path=str(out), n_cards=len(cards),
        annot_layer=ANNOT_LAYER_ID, **extra)
