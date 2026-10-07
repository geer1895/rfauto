"""LC-1 Gerber X2 + Excellon 导出封装（E 流版图四件之首）。

KiCad ``.kicad_pcb`` → Gerber X2（铜层/阻焊/丝印/板框 + ``.gbrjob`` 作业
文件）+ Excellon 钻孔。规格出处
``研究扩充 round15`` LC-1（gerbonara 路线，
X2 属性→层角色映射；本模块落地其导出向，读回向的往返裁判是后续件）。

与 fab-export（T43 机加交付包，ezdxf/QIF3/gcode/STEP/glTF）的关系：
fab-export 面向机械加工交付（CNC/QIF 三坐标），本模块面向 PCB 制造
交付（fab house 认 Gerber X2 + 钻孔），二者互补不重复。

导出主链走 KiCad 自带 python 子进程（铁律 2——项目 venv 禁 import
pcbnew），复用 adapters/kicad_extract 的"生成脚本 → 子进程 → stdout
JSON 标记"惯例（KICAD_PYTHON/RFAUTO_KICAD_PYTHON 同口径；因分层
约束 core 不得 import adapters，解析器此处刻意本地副本）。

gerbonara（Apache-2.0，PyPI METADATA License-Expression 实证）为可选
X2 元数据增强层：可用时读回导出目录逐文件核对 ``file_attrs`` 与本
模块自带 TF 行解析器的一致性；不可用时导出主链不受影响，契约如实
上报 ``gerbonara.available=False``。安装到隔离目录后经环境变量
``RFAUTO_GERBONARA_PATH``（目录，加入 sys.path 头部）启用，默认不改
项目 venv 依赖面。
"""
from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any

#: KiCad 自带 Python 缺省安装位（AU-8：env ``RFAUTO_KICAD_PYTHON`` 优先；
#: 与 adapters/kicad_extract.KICAD_PYTHON 同值，分层原因本地副本）。
KICAD_PYTHON = r"E:\KiCad\bin\python.exe"

#: KiCad 自带 Python 的 env 覆盖名（注册表 infra/env_vars.py 同名项）
KICAD_PYTHON_ENV = "RFAUTO_KICAD_PYTHON"

#: KiCad 自带 python 的 pcbnew site-packages（探针 10.0.6 实测）
KICAD_SITE_PACKAGES = r"E:\KiCad\bin\Lib\site-packages"

#: gerbonara 隔离安装目录的 env 覆盖名（值=含 ``gerbonara/`` 包的目录）
GERBONARA_PATH_ENV = "RFAUTO_GERBONARA_PATH"

_JSON_START = "GERBER_EXPORT_JSON_START"
_JSON_END = "GERBER_EXPORT_JSON_END"

_SUBPROCESS_TIMEOUT_S = 240
_RETRY_ATTEMPTS = 2  # LoadBoard 原生崩溃兜底（#191 哲学；绘图非 SaveBoard 无已知段错误史）

_X2_LINE_RE = re.compile(r"%TF\.([A-Za-z0-9_.]+)([^\r\n*]*)\*%")


@dataclasses.dataclass(frozen=True)
class GerberLayerSpec:
    """单层导出规格（逻辑角色 ↔ pcbnew 常量 ↔ 预期 X2 FileFunction）。"""

    role: str  # 逻辑层名（KiCad 口径，契约键，如 "F.Cu"）
    pcbnew_const: str  # pcbnew 模块层常量名（KiCad 10.0.6 探针实测存在）
    suffix: str  # 输出文件名后缀（KiCad 10 GUI 命名口径，``-<suffix>.gbr``）
    file_function: tuple[str, ...]  # 预期 %TF.FileFunction 首关键字与侧面


#: 缺省导出层计划（双层/多层板通用的 7 层制造交付面）。
#: pcbnew 常量与预期 FileFunction 均按 KiCad 10.0.6 真机导出实测回填。
DEFAULT_GERBER_LAYERS: tuple[GerberLayerSpec, ...] = (
    GerberLayerSpec("F.Cu", "F_Cu", "F_Cu", ("Copper", "Top")),
    GerberLayerSpec("B.Cu", "B_Cu", "B_Cu", ("Copper", "Bot")),
    GerberLayerSpec("F.Mask", "F_Mask", "F_Mask", ("Soldermask", "Top")),
    GerberLayerSpec("B.Mask", "B_Mask", "B_Mask", ("Soldermask", "Bot")),
    GerberLayerSpec("F.SilkS", "F_SilkS", "F_Silkscreen", ("Legend", "Top")),
    GerberLayerSpec("B.SilkS", "B_SilkS", "B_Silkscreen", ("Legend", "Bot")),
    GerberLayerSpec("Edge.Cuts", "Edge_Cuts", "Edge_Cuts", ("Profile",)),
)


def resolve_kicad_python(explicit: str | None = None) -> str:
    """KiCad 自带 Python 解析：显式参 > env ``RFAUTO_KICAD_PYTHON`` > 缺省位。"""
    if explicit:
        return explicit
    env_val = os.environ.get(KICAD_PYTHON_ENV, "")
    if env_val:
        return env_val
    return KICAD_PYTHON


def parse_x2_file_attributes(text: str) -> dict[str, tuple[str, ...]]:
    """解析 Gerber 文本中的 X2 文件属性（``%TF.xxx,field,...*%``）行。

    键去前导点（与 gerbonara ``file_attrs`` 的 ``.FileFunction`` 口径对齐
    后可比），值为逗号字段元组。非 X2 行（G04/D01/M02/%FSLA 等）忽略。
    """
    attrs: dict[str, tuple[str, ...]] = {}
    for m in _X2_LINE_RE.finditer(text):
        name, fields = m.group(1), m.group(2)
        vals = tuple(f.strip() for f in fields.split(",") if f.strip())
        attrs[name.lstrip(".")] = vals
    return attrs


def gerbonara_available() -> bool:
    """gerbonara 可导入性（惰性；先按 env 注入隔离安装目录再试探）。"""
    return _load_gerbonara_cls() is not None


def _load_gerbonara_cls() -> type | None:
    path = os.environ.get(GERBONARA_PATH_ENV, "")
    if path and path not in sys.path:
        sys.path.insert(0, path)
    try:
        from gerbonara.layers import GerberFile
    except Exception:  # 可选增强层，任何导入失败一律降级
        return None
    return GerberFile


def read_back_x2_attributes(path: str | Path) -> dict[str, Any]:
    """gerbonara 读回单文件 X2 属性（best-effort，#105——不阻塞主链）。

    返回 {键去点: 字段元组}；gerbonara 不可用时 ``{"available": False}``，
    解析失败时 ``{"available": True, "error": repr}``。
    """
    cls = _load_gerbonara_cls()
    if cls is None:
        return {"available": False}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # gerbonara 对非标语句发 Warning
            gf = cls.open(str(path))
        raw = dict(gf.file_attrs)
    except Exception as exc:
        return {"available": True, "error": repr(exc)}
    out: dict[str, Any] = {"available": True}
    for key, vals in raw.items():
        if isinstance(vals, (list, tuple)):
            out[str(key).lstrip(".")] = tuple(str(v) for v in vals)
        else:
            out[str(key).lstrip(".")] = (str(vals),)
    return out


_EXPORT_SCRIPT_TEMPLATE = r'''
import sys
sys.path.insert(0, r"{site_packages}")
import glob
import json
import os

errors = []
result = {{"ok": False, "errors": errors, "files": {{}}, "job_file": None,
          "drill_files": []}}
try:
    import pcbnew

    board = pcbnew.LoadBoard(r"{pcb_path}")
    out_dir = r"{out_dir}"
    ctl = pcbnew.PLOT_CONTROLLER(board)
    popt = ctl.GetPlotOptions()
    popt.SetOutputDirectory(out_dir)
    popt.SetFormat(pcbnew.PLOT_FORMAT_GERBER)
    popt.SetUseGerberX2format(True)
    popt.SetUseGerberAttributes(True)
    popt.SetGerberPrecision(6)
    popt.SetCreateGerberJobFile({gerber_job})
    popt.SetIncludeGerberNetlistInfo(True)
    popt.SetUseGerberProtelExtensions(False)
    popt.SetSubtractMaskFromSilk(False)
    popt.SetUseAuxOrigin(False)
    popt.SetMirror(False)
    popt.SetNegative(False)
    popt.SetScale(1)
    popt.SetAutoScale(False)
    popt.SetPlotFrameRef(False)

    layer_consts = {layer_consts}
    suffixes = {suffixes}
    roles = {roles}
    for const_name, suffix, role in zip(layer_consts, suffixes, roles):
        layer = getattr(pcbnew, const_name, None)
        if layer is None:
            errors.append("layer const missing: " + const_name)
            continue
        ctl.SetLayer(layer)
        if not ctl.OpenPlotfile(suffix, pcbnew.PLOT_FORMAT_GERBER, suffix):
            errors.append("OpenPlotfile failed: " + const_name)
            continue
        if not ctl.PlotLayer():
            errors.append("PlotLayer failed: " + const_name)
            continue
        result["files"][role] = ctl.GetPlotFileName()

    ctl.ClosePlot()

    if {gerber_job}:
        # PLOT_CONTROLLER 的 SetCreateGerberJobFile 在 SWIG 直驱路径是惰性
        # 选项（仅 GUI/kicad-cli 消费）——job 文件必须显式走
        # GERBER_JOBFILE_WRITER（KiCad 10.0.6 绑定实测存在）。
        jw = pcbnew.GERBER_JOBFILE_WRITER(board)
        for const_name, role in zip(layer_consts, roles):
            layer = getattr(pcbnew, const_name, None)
            fn = result["files"].get(role)
            if layer is None or not fn:
                continue
            jw.AddGbrFile(layer, os.path.basename(fn))
        stem = os.path.basename(r"{pcb_path}").rsplit(".", 1)[0]
        job_path = os.path.join(out_dir, stem + ".gbrjob")
        if not jw.CreateJobFile(job_path):
            errors.append("gerber job file export failed")
        elif os.path.exists(job_path):
            result["job_file"] = job_path
        else:
            jobs = sorted(glob.glob(os.path.join(out_dir, "*.gbrjob")))
            result["job_file"] = jobs[0] if jobs else None
            if not result["job_file"]:
                errors.append("gerber job file not found after CreateJobFile")

    xw = pcbnew.EXCELLON_WRITER(board)
    xw.SetOptions(False, False, pcbnew.VECTOR2I(0, 0), {merge_drill})
    xw.SetFormat(True, pcbnew.EXCELLON_WRITER.DECIMAL_FORMAT)
    if not xw.CreateDrillandMapFilesSet(out_dir, True, {drill_map}):
        errors.append("drill file export failed")
    result["drill_files"] = sorted(glob.glob(os.path.join(out_dir, "*.drl")))
    jobs = sorted(glob.glob(os.path.join(out_dir, "*.gbrjob")))
    result["job_file"] = jobs[0] if jobs else None
except Exception as exc:  # subprocess boundary: all exceptions become contract
    errors.append("KiCad export exception: %r" % (exc,))
result["ok"] = len(errors) == 0
print("{json_start}")
print(json.dumps(result, ensure_ascii=False))
print("{json_end}")
'''.replace("{{", "{").replace("}}", "}")


def _run_kicad_export(script: str, python_exe: str,
                      timeout_s: float) -> tuple[subprocess.CompletedProcess | None,
                                                 list[str], str | None]:
    """KiCad 子进程跑导出脚本；返回 (result, 逐次错误, 致命类别)。

    致命类别 "spawn"/"timeout" 时 result=None（同 kicad_extract 契约）。
    """
    result: subprocess.CompletedProcess | None = None
    errors: list[str] = []
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            result = subprocess.run(
                [python_exe, "-X", "faulthandler", "-c", script],
                capture_output=True, text=True, timeout=timeout_s,
                encoding="utf-8", errors="replace",
            )
        except FileNotFoundError:
            return None, [f"KiCad Python 不存在: {python_exe}"], "spawn"
        except subprocess.TimeoutExpired:
            return None, [f"KiCad Gerber 导出超时（>{timeout_s:.0f}s）"], "timeout"
        if result.returncode == 0:
            break
        errors.append(
            f"KiCad 退出码 {result.returncode}（第 {attempt + 1} 次尝试）: "
            f"{(result.stderr or '')[-800:]}")
        time.sleep(0.5)  # 进程间冷却：KiCad 配置/锁文件残留避让（#210）
    return result, errors, None


def _parse_export_stdout(stdout: str) -> dict[str, Any] | None:
    if _JSON_START not in stdout or _JSON_END not in stdout:
        return None
    body = stdout.split(_JSON_START, 1)[1].split(_JSON_END, 1)[0]
    try:
        import json
        return dict(json.loads(body))
    except ValueError:
        return None


def export_gerber_x2(
    pcb_path: str | Path,
    out_dir: str | Path,
    layers: tuple[GerberLayerSpec, ...] | None = None,
    *,
    kicad_python: str | None = None,
    gerber_job: bool = True,
    drill_map: bool = False,
    merge_drill: bool = True,
    timeout_s: float = _SUBPROCESS_TIMEOUT_S,
) -> dict[str, Any]:
    """KiCad 板 → Gerber X2 + Excellon 导出（LC-1 制造交付面入口）。

    契约（service 口径 JSON 进出，CLI/MCP 薄壳后续件）::

        {"ok": bool, "pcb": str, "out_dir": str,
         "files": {role: 绝对路径}, "job_file": str|None,
         "drill_files": [str],
         "x2_attributes": {role: {TF 键: 字段元组}},
         "missing_x2": [role],          # FileFunction 缺失或关键字不符
         "gerbonara": {"available": bool, "consistent": bool|None,
                        "read_back": {role: {...}}|None, "errors": [...]},
         "errors": [...]}

    ok=False 时 errors 带逐条原因（板/KiCad Python 不存在、子进程超时、
    退出码、X2 属性缺失均显式报错）。
    """
    # 相对路径禁入 KiCad（#243 同族实证：PLOT_CONTROLLER 把相对 out_dir
    # 相对板文件目录解析、EXCELLON_WRITER 相对 CWD——两套基准必须入口
    # 统一绝对化收敛）。
    pcb = Path(pcb_path).resolve()
    outd = Path(out_dir).resolve()
    result: dict[str, Any] = {
        "ok": False, "pcb": str(pcb), "out_dir": str(outd), "files": {},
        "job_file": None, "drill_files": [], "x2_attributes": {},
        "missing_x2": [], "gerbonara": {}, "errors": [],
    }
    errors: list[str] = result["errors"]
    if not pcb.exists():
        errors.append(f"板文件不存在: {pcb}")
        result["gerbonara"] = _gerbonara_idle_block()
        return result
    python_exe = resolve_kicad_python(kicad_python)
    if not Path(python_exe).exists():
        errors.append(f"KiCad Python 不存在: {python_exe}")
        result["gerbonara"] = _gerbonara_idle_block()
        return result
    outd.mkdir(parents=True, exist_ok=True)

    specs = layers if layers is not None else DEFAULT_GERBER_LAYERS
    script = (
        _EXPORT_SCRIPT_TEMPLATE
        .replace("{site_packages}", KICAD_SITE_PACKAGES)
        .replace("{pcb_path}", str(pcb))
        .replace("{out_dir}", str(outd))
        .replace("{json_start}", _JSON_START)
        .replace("{json_end}", _JSON_END)
        .replace("{gerber_job}", repr(bool(gerber_job)))
        .replace("{drill_map}", repr(bool(drill_map)))
        .replace("{merge_drill}", repr(bool(merge_drill)))
        .replace("{layer_consts}", repr([s.pcbnew_const for s in specs]))
        .replace("{suffixes}", repr([s.suffix for s in specs]))
        .replace("{roles}", repr([s.role for s in specs]))
    )
    raw, sub_errors, fatal = _run_kicad_export(script, python_exe, timeout_s)
    if fatal in ("spawn", "timeout"):
        errors.extend(sub_errors)
        result["gerbonara"] = _gerbonara_idle_block()
        return result
    payload = _parse_export_stdout(raw.stdout) if raw is not None else None
    if payload is None:
        tail = (raw.stderr or "")[-800:] if raw is not None else ""
        errors.append("KiCad 导出产物无 JSON 标记（子进程未及产出即失败）"
                      f"，stderr 尾部: {tail}")
        errors.extend(sub_errors)
        result["gerbonara"] = _gerbonara_idle_block()
        return result
    errors.extend(payload.get("errors") or [])
    errors.extend(sub_errors)
    result["files"] = {str(k): str(v) for k, v in payload.get("files", {}).items()}
    result["drill_files"] = [str(p) for p in payload.get("drill_files", [])]
    result["job_file"] = (
        str(payload["job_file"]) if payload.get("job_file") else None)

    _verify_x2_attributes(result, specs)
    result["gerbonara"] = _gerbonara_crosscheck(result["files"])
    result["ok"] = (len(errors) == 0 and len(result["files"]) == len(specs)
                    and not result["missing_x2"])
    return result


def _gerbonara_idle_block() -> dict[str, Any]:
    return {"available": gerbonara_available(), "consistent": None,
            "read_back": None, "errors": []}


def _verify_x2_attributes(result: dict[str, Any],
                          specs: tuple[GerberLayerSpec, ...]) -> None:
    """逐角色读回文件文本 → TF 属性解析 → FileFunction 存在性/关键字核验。

    缺失/不符的角色进 ``missing_x2``（X2 属性存在性是本导出的交付物，
    属主链判据而非增强层）。
    """
    x2: dict[str, dict[str, tuple[str, ...]]] = {}
    missing: list[str] = []
    for spec in specs:
        path = result["files"].get(spec.role)
        if not path or not Path(path).exists():
            missing.append(spec.role)
            continue
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        attrs = parse_x2_file_attributes(text)
        x2[spec.role] = attrs
        ff = attrs.get("FileFunction")
        if not ff:
            missing.append(spec.role)
            continue
        if not all(kw in ff for kw in spec.file_function):
            missing.append(spec.role)
    result["x2_attributes"] = x2
    result["missing_x2"] = missing


def _gerbonara_crosscheck(
    files: dict[str, str],
) -> dict[str, Any]:
    """gerbonara 读回交叉核对（仅 .gbr；Excellon 非 X2 载体跳过）。"""
    block = _gerbonara_idle_block()
    cls = _load_gerbonara_cls()
    if cls is None:
        return block
    read_back: dict[str, Any] = {}
    consistent: bool | None = True
    for role, path in files.items():
        attrs = read_back_x2_attributes(path)
        read_back[role] = attrs
        if attrs.get("error"):
            block["errors"].append(f"{role}: {attrs['error']}")
            consistent = None
            continue
        if not attrs.get("available"):
            continue
        gb_ff = attrs.get("FileFunction")
        own = parse_x2_file_attributes(
            Path(path).read_text(encoding="utf-8", errors="replace"))
        if gb_ff != own.get("FileFunction"):
            consistent = False
    block["read_back"] = read_back
    block["consistent"] = consistent
    return block
