"""ADS 参数化模板族 service（JSON 进出）：渲染 / 真机运行 / 对拍。

两个入口（CLI/MCP 薄壳归 WP3.3，本轮只落 service）：
- render_ads_template：request → 渲染族网表写盘，返回路径与频扫/参数快照；
- run_ads_template：渲染 → hpeesofsim（B 档，adapters/ads_netlist 正规 env 入口）
  → .ds 解析 → 与确定性参考逐点对拍（linkage.ads_template_family.
  compare_family_result）；``ads_runner(netlist_path) -> payload`` 可注入
  （单测离线只验管线，不充当裁判）。

request 字段
------------
``family``      : "wilkinson_snp" | "branchline_cascade"（必填）
``snp_path``    : Touchstone 路径（必填；wilkinson_snp 任意 N 端口，cascade 须 4）
``output_path`` : render 入口的网表写盘路径（必填）
``out_dir``     : run 入口的工作目录（必填；网表 = <out_dir>/<family>_netlist.txt，
                  .ds 与求解器日志同目录落盘）
``params``      : 渲染器关键字参数（sweep{fstart,fstop,npoints,unit} / z0 /
                  n_ports / f0_hz / theta_in_deg / theta_out_deg / z_line）
``ads_dir``     : 可选，ADS 安装根（缺省 env RFAUTO_HPEESOF_DIR → settings）
``compare``     : 可选 bool（缺省 True），run 入口是否做对拍
``reference_snp_path`` : 可选，对拍参考 Touchstone（缺省 = snp_path 自身）。D13 宏模型
                  桥用法：snp_path 传宏模型重建 .sNp 进 ADS 电路，参考传原始
                  EM 数据 .sNp——"宏模型替身进 ADS vs 原始数据参考"对拍
``max_abs_delta_s_gate`` : 可选 float，对拍门（缺省 1e-3）；返回 ``gate_ok``

数值只在确定性内核（skrf / linkage 闭式参考）；LLM 不产生物理数字。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.linkage import ads_template_family as atf

logger = logging.getLogger(__name__)

#: 对拍门缺省值：SnP 直通/级联对拍的 max|ΔS| 上限（Touchstone dB 写出精度量级
#: 为 1e-6，留三个量级余量；真机实测数字如实回写，不因门宽而改门）。
DEFAULT_MAX_ABS_DELTA_S_GATE = 1e-3


def _jsonable(obj: Any) -> Any:
    """dict/ndarray/复数 → 严格 JSON 结构（bool 先于 int 判定）。"""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, (complex, np.complexfloating)):
        return {"re": float(obj.real), "im": float(obj.imag)}
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if not np.isfinite(f) else f
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _require(request: dict[str, Any], key: str) -> Any:
    if key not in request or request[key] in (None, ""):
        raise ValueError(f"request 缺少必填字段 {key!r}")
    return request[key]


def render_ads_template(request: dict[str, Any]) -> dict[str, Any]:
    """渲染族网表并写盘（JSON 进出）。"""
    family = str(_require(request, "family"))
    snp_path = Path(_require(request, "snp_path"))
    output_path = Path(_require(request, "output_path"))
    params = dict(request.get("params") or {})
    if family not in atf.FAMILIES:
        raise ValueError(f"未知模板族 {family!r}（可选 {list(atf.FAMILIES)}）")
    if not snp_path.exists():
        raise FileNotFoundError(f"Touchstone 不存在: {snp_path}")
    text = atf.render_family(family, snp_path, params)
    out = atf.write_netlist(text, output_path)
    sweep = atf.resolve_sweep(snp_path, params.get("sweep"))
    return _jsonable({
        "ok": True,
        "family": family,
        "snp_path": snp_path,
        "netlist_path": out,
        "n_lines": text.count("\n"),
        "sweep": sweep,
        "params": params,
    })


def run_ads_template(
    request: dict[str, Any],
    ads_runner: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """渲染 → hpeesofsim → .ds 解析 → 对拍；结果写 <out_dir>/<family>_result.json。

    ADS 段失败如实降级记录（status=error + 求解器 stdout 尾巴），不抛出、
    不掩盖；``ok`` = ADS 段成功 且（对拍开启时）gate_ok。
    """
    family = str(_require(request, "family"))
    snp_path = Path(_require(request, "snp_path"))
    out_dir = Path(_require(request, "out_dir"))
    out_dir.mkdir(parents=True, exist_ok=True)
    params = dict(request.get("params") or {})
    compare = bool(request.get("compare", True))
    gate = float(request.get("max_abs_delta_s_gate", DEFAULT_MAX_ABS_DELTA_S_GATE))
    ads_dir = request.get("ads_dir")
    reference_snp = Path(request.get("reference_snp_path") or snp_path)

    result: dict[str, Any] = {
        "family": family, "snp_path": snp_path, "reference_snp_path": reference_snp, "params": params,
    }
    rendered = render_ads_template({
        "family": family, "snp_path": snp_path,
        "output_path": out_dir / f"{family}_netlist.txt", "params": params,
    })
    netlist = Path(rendered["netlist_path"])
    result["netlist_path"] = netlist
    result["sweep"] = rendered["sweep"]

    ok = False
    payload: dict[str, Any] | None = None
    try:
        if ads_runner is not None:
            payload = ads_runner(netlist)
            result["ads"] = {"status": "ok", "runner": "injected"}
        else:
            from rfauto.adapters import ads_netlist

            t0 = time.time()
            proc = ads_netlist.run_hpeesofsim(netlist, ads_dir=ads_dir)
            sim_s = time.time() - t0
            (out_dir / f"{family}_hpeesofsim_stdout.txt").write_text(
                proc.stdout[-6000:] + "\n--- stderr ---\n" + proc.stderr[-2000:], encoding="utf-8",
            )
            t1 = time.time()
            payload = ads_netlist.parse_dataset(Path(f"{netlist}.ds"), ads_dir=ads_dir)
            result["ads"] = {
                "status": "ok", "runner": "hpeesofsim", "returncode": proc.returncode,
                "sim_time_s": sim_s, "parse_time_s": time.time() - t1,
                "dataset_path": Path(f"{netlist}.ds"),
            }
        result["ads"].update({
            "n_points": len(payload["frequency_hz"]),
            "port_names": payload.get("port_names"),
            "port_z": payload.get("port_z"),
        })
        ok = True
    except Exception as exc:  # 观测性 best-effort：许可/语法失败的正文可溯源
        det = getattr(exc, "details", None)
        tail = ""
        if isinstance(det, dict):
            tail = str(det.get("stdout") or det.get("stderr") or "")[-600:]
        result["ads"] = {"status": "error", "error": f"{type(exc).__name__}: {exc} {tail}".strip()}

    if ok and compare and payload is not None:
        try:
            cmp = atf.compare_family_result(family, reference_snp, payload, params)
            cmp["gate_max_abs_delta_s"] = gate
            cmp["gate_ok"] = bool(cmp["max_abs_delta_s"] <= gate)
            result["compare"] = cmp
            ok = ok and cmp["gate_ok"]
        except Exception as exc:
            result["compare"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            ok = False
    elif ok and not compare:
        result["compare"] = {"status": "skipped"}

    result["ok"] = bool(ok)
    out = _jsonable(result)
    (out_dir / f"{family}_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("ADS 模板族 %s 运行完成: ok=%s", family, ok)
    return out
