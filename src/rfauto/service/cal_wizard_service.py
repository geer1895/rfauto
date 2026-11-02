"""cal_wizard_service —— TRL 校准件设计向导编排（aurora_p G1，2026-11-02）。

RF 工程师视角的缺口闭合：TRL 校准此前只有内核（core/trl_solt 提取）+
CLI（vna calibrate 独立校准），缺"给定频带与介质→照着做"的**设计向导
面**。本服务编排：

- 设计数学 = core/trl_design（λg/4 Line、8:1 覆盖核算、多 Line 分带、
  Reflect 短路/开路建议——教科书锚+εeff 单源在内核，本层零数值逻辑）；
- 校准测试连接图 = core/testsetup_diagram 场景构造（VNA/DUT 两卡+
  校准面标记，scene kind 走既有枚举查表）+ 既有
  :func:`rfauto.service.diagram_testsetup_service.generate_testsetup_diagram`
  出 .drawio（装配内核复用，不另写装配器）；
- 校准件定义文件 = knowledge/calkits catalog 同构 YAML 骨架（method=trl，
  标准件文件名占位——设计单只产几何，标准件 S 参数须实测后落文件，
  不伪造测量数据；消费面 measurement.calibration.load_calkit）。

规则 4：JSON 进出（信封走 ok_envelope/error_envelope 单源构造器），
CLI/MCP 薄壳。确定性：同输入两次调用（同 out_dir 两次落盘）逐字节同
（设计 dict 纯函数 + 文件名固定 + 零时间戳零 uuid）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from rfauto.core.trl_design import MAX_LINES_DEFAULT, design_trl_standards
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["trl_wizard"]

#: payload 严格键（缺省键可选）
_PAYLOAD_KEYS = {"f_start_ghz", "f_stop_ghz", "medium", "max_lines",
                 "kit_id", "connector", "title"}
_PAYLOAD_REQUIRED = ("f_start_ghz", "f_stop_ghz", "medium")

#: 落盘文件名（固定，确定性面——无时间戳）
_DESIGN_SHEET_NAME = "trl_design_sheet.json"
_CALKIT_DEF_NAME = "calkit_def.yaml"
_DIAGRAM_NAME = "trl_testsetup.drawio"


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


def _str_nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串，收到 {value!r}")
    return value


def _build_testsetup_scene(design: dict[str, Any], connector: str,
                           title: str | None = None) -> dict[str, Any]:
    """校准测试连接场景（core/testsetup_diagram 严格 schema：顶层五键/
    仪器六键/连接五键/注记两键；kind 走既有枚举查表 vna/dut）。

    校准面标记（cal_plane=true）落 VNA↔DUT 两条边——TRL 校准面=DUT
    端口平面（Thru 直连/Reflect 与 Line 同面接续，设计单 reflect 约束
    第 3 条同口径）；线缆标注零换算（connector 标签原值，无损耗/长度
    数值——铁律 7 另一面：不产数字就不标数字）。"""
    band = design.get("band_ghz") or []
    band_txt = f"{band[0]}–{band[1]} GHz" if len(band) == 2 else "频带见设计单"
    return {
        "title": title or f"TRL 校准测试连接（{band_txt}）",
        "instruments": [
            {"id": "vna", "kind": "vna", "label": "VNA",
             "ports": ["RF1", "RF2"]},
            {"id": "dut", "kind": "dut", "label": "DUT（被测件）",
             "ports": ["p1", "p2"]},
        ],
        "connections": [
            {"from": "vna.RF1", "to": "dut.p1",
             "cable": {"label": connector, "loss_db": None,
                       "length_m": None},
             "cal_plane": True, "label": None},
            {"from": "dut.p2", "to": "vna.RF2",
             "cable": {"label": connector, "loss_db": None,
                       "length_m": None},
             "cal_plane": True, "label": None},
        ],
        "notes": [
            {"text": "TRL 校准面=DUT 端口平面：Thru=两校准面直连；"
                     "Reflect=校准面接短路/开路（|Γ|≥0.3，相位 ±90° 内）；"
                     "Line=λg/4 校准线（逐条按设计单换线）", "anchor": None},
        ],
    }


def _calkit_def_yaml(design: dict[str, Any], kit_id: str) -> dict[str, Any]:
    """calkit catalog 同构骨架（load_calkit 可直接消费的占位 kit）。

    method/standards 键与消费面校准方法契约对齐（measurement.calibration）：
    单 Line=``method: trl``（_TRL_ORDER 固定序 through/reflect/line，键
    用 ``line``）；多 Line=``method: nist_multiline_trl``（严格序，键
    ``line1..lineN`` 走 _multiline_line_keys 序号排序）。标准件文件名=
    固定占位——按设计单加工实测后以 Touchstone 落同名文件即接入
    ``vna calibrate`` 消费链；零测量数据伪造（铁律 7/#122：设计产物≠
    标准件实测）。"""
    n_lines = int(design.get("n_lines") or 0)
    line_files: dict[str, str] = {}
    for j in range(1, n_lines + 1):
        key = "line" if n_lines == 1 else f"line{j}"
        line_files[key] = f"line{j}.s2p"
    entry = {
        "description": "TRL 校准套件（cal-wizard trl 设计单产物；标准件"
                       "按设计单加工实测后替换占位文件名）",
        "method": "trl" if n_lines <= 1 else "nist_multiline_trl",
        "schema_version": 1,
        "standards": {"thru": "thru.s2p", "reflect": "reflect.s1p",
                      **line_files},
    }
    return {"calkits": {kit_id: entry}}


def trl_wizard(payload: Any, out_dir: Any = None) -> dict[str, Any]:
    """TRL 设计向导编排：频带+介质 → 设计单+覆盖核算+可选三件落盘。

    Args:
        payload: 严格键 dict——必填 ``f_start_ghz``/``f_stop_ghz``/
            ``medium``（口径见 core/trl_design.resolve_medium）；可选
            ``max_lines``（Line 数上限，缺省内核单源
            MAX_LINES_DEFAULT）/``kit_id``（校准套件 ID，缺省
            "trl_wizard"）/``connector``（连接图线缆标签，缺省
            "SMA"）/``title``（测试连接图标题覆盖，缺省按频带自动）。
        out_dir: 落盘目录（None=只出信封零落盘；给定时写固定名产物：
            trl_design_sheet.json（恒写）/ calkit_def.yaml（n_lines≥1 时
            写；uncovered 无 Line 不产 kit 骨架，#122 不硬凑）/
            trl_testsetup.drawio；目录不存在自动创建）。

    Returns:
        成功信封 ``{"ok": True, **design, "written": {...}|{}}``（design
        字段逐键平铺——verdict/covered/standards/warnings 等，见
        core/trl_design.design_trl_standards；覆盖三态在 verdict 键，
        uncovered 时 standards=[] + warnings 如实）。失败信封
        ``{"ok": False, "errors": [str...]}``（入参违约/落盘 IO/连接图
        装配拒绝——不静默不凑绿）。
    """
    try:
        if not isinstance(payload, dict):
            raise ValueError(f"payload 须为 dict，收到 {type(payload)!r}")
        extra = set(payload) - _PAYLOAD_KEYS
        if extra:
            raise ValueError(
                f"payload 存在未支持键 {sorted(extra)}；严格键 "
                f"{sorted(_PAYLOAD_KEYS)}")
        for key in _PAYLOAD_REQUIRED:
            if key not in payload or payload[key] is None:
                raise ValueError(f"payload 缺必填键 {key!r}")
        f_start = _finite(payload["f_start_ghz"], "f_start_ghz")
        f_stop = _finite(payload["f_stop_ghz"], "f_stop_ghz")
        max_lines = payload.get("max_lines")
        if max_lines is not None and (
                not isinstance(max_lines, int) or isinstance(max_lines, bool)
                or max_lines < 1):
            raise ValueError(
                f"max_lines 必须是正整数，收到 {max_lines!r}")
        kit_id = "trl_wizard" if payload.get("kit_id") is None else \
            _str_nonempty(payload["kit_id"], "kit_id")
        connector = "SMA" if payload.get("connector") is None else \
            _str_nonempty(payload["connector"], "connector")

        design = design_trl_standards(
            f_start, f_stop, payload["medium"],
            max_lines=MAX_LINES_DEFAULT if max_lines is None else max_lines)

        written: dict[str, str] = {}
        if out_dir is not None:
            from rfauto.service.diagram_testsetup_service import generate_testsetup_diagram

            root = Path(out_dir)
            root.mkdir(parents=True, exist_ok=True)
            sheet_path = root / _DESIGN_SHEET_NAME
            sheet_path.write_text(
                json.dumps(design, ensure_ascii=False, indent=2),
                encoding="utf-8")
            written["design_sheet"] = str(sheet_path)

            import yaml

            n_lines = int(design.get("n_lines") or 0)
            if n_lines >= 1:
                # uncovered（n_lines=0）不出 calkit 骨架——无 Line 的 kit
                # 过不了校准消费面，如实不产（#122 不硬凑）
                calkit_path = root / _CALKIT_DEF_NAME
                calkit_path.write_text(
                    yaml.safe_dump(_calkit_def_yaml(design, kit_id),
                                   allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
                written["calkit_def"] = str(calkit_path)

            scene = _build_testsetup_scene(
                design, connector, title=payload.get("title"))
            diag = generate_testsetup_diagram(scene, root / _DIAGRAM_NAME,
                                              title=None)
            if not diag.get("ok"):
                raise ValueError(
                    "测试连接图装配被拒（core/testsetup_diagram 严格 "
                    f"schema）：{diag.get('errors')}")
            written["testsetup_diagram"] = str(root / _DIAGRAM_NAME)
    except (ValueError, TypeError, OSError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")
    return ok_envelope(**design, written=written)
