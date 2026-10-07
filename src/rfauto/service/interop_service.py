"""Touchstone 互操作 service 接线（ME-10' 尾巴：JSON 进出，CLI/MCP 壳共享）。

数值/格式内核在 adapters/touchstone_interop.py（TS 2.1 写出 + HFSS 注释块
解析）；本模块只做文件路径校验、skrf 读入与异常到 JSON 信封的翻译
（铁律 4：服务层 JSON 进出，CLI/MCP 薄壳）。

信封契约（与 calculator_service/slotline_service 同族）：ok=False + error
字符串，绝不抛出（文件不存在/解析失败/注释块结构损坏都进信封）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.service.envelope import ok_envelope

#: 数值内核/IO 期可预期的异常族（进信封）。
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError,
                OSError)


def ts21_write(
    input_path: str,
    output_path: str,
    *,
    run_id: str | None = None,
    comments: list[str] | None = None,
    form: str = "ri",
    write_z0: bool = True,
) -> dict[str, Any]:
    """Touchstone 2.1 写出（读入既有 .sNp → TS2.1 + provenance 注释块）。

    Args:
        input_path: 输入 Touchstone（1.0/2.0/2.1 均可，skrf 读入口径）。
        output_path: 输出文件路径（扩展名建议按端口数 .sNp，本函数不改正名）。
        run_id: 关联 run 标识（写入 provenance 行；含换行显式拒绝）。
        comments: 追加自定义注释行（每行强制 ``!`` 前缀，数据区零注入）。
        form: 数据档 "ri"（缺省，无损）/ "ma" / "db"（后两者有重构造舍入）。
        write_z0: 是否写出参考阻抗（[Reference] + 逐频点 Port Impedance 注释）。

    Returns:
        JSON 原生信封：ok=True 时 data 含 path/n_ports/n_freqs/form/
        roundtrip_max_abs_err（读回对拍；ri 档逐位、ma/db 档 <<1e-12）与
        version_key（首关键字 [Version] 2.1 断言值）。
    """
    import numpy as np
    import skrf

    from rfauto.adapters.touchstone_interop import (
        TOUCHSTONE_VERSION_V2,
        write_touchstone_v2,
    )

    src = Path(input_path)
    if not src.is_file():
        return {"ok": False, "error": f"输入 Touchstone 不存在: {src}"}
    try:
        network = skrf.Network(str(src))
        out = write_touchstone_v2(
            network, output_path, comments=comments, run_id=run_id,
            write_z0=write_z0, form=form)
        readback = skrf.Network(str(out))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    if readback.s.shape != network.s.shape:
        return {"ok": False,
                "error": f"读回形状不一致: {readback.s.shape} vs "
                         f"{network.s.shape}（写出损坏，#316 方向显式报）"}
    max_err = float(np.max(np.abs(readback.s - network.s)))
    first_keyword = ""
    for line in out.read_text(encoding="ISO-8859-1").splitlines():
        text = line.strip()
        if text and not text.startswith("!"):
            first_keyword = text
            break
    return ok_envelope(
        data={
            "path": str(out),
            "n_ports": int(network.nports),
            "n_freqs": int(network.s.shape[0]),
            "form": form,
            "version_key": first_keyword,
            "version_declared": TOUCHSTONE_VERSION_V2,
            "roundtrip_max_abs_err": max_err,
            "run_id": run_id,
        },
    )


def hfss_touchstone_comments(path: str) -> dict[str, Any]:
    """HFSS Touchstone ``!`` 注释块读取（Gamma 传播常数 + Zpi 端口阻抗直读）。

    零逻辑转发 adapters.touchstone_interop.read_hfss_touchstone_comments，
    仅把 numpy 复数矩阵转 JSON 原生（[[re, im], ...] 逐频点）；注释块数值
    结构矛盾（端口数/频点数不一致/奇数 token）如实 ok=False 不静默放行
    （#316 方向）。

    Returns:
        JSON 原生信封：ok=True 时 data 含 n_ports/n_freqs/port_zpi/gamma
        （复数数组 JSON 化）、renormalized/renormalize_ohm/port_names/
        header/raw。
    """
    import numpy as np

    from rfauto.adapters.touchstone_interop import read_hfss_touchstone_comments

    try:
        parsed = read_hfss_touchstone_comments(path)
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}

    def _cx_to_json(arr) -> list | None:
        """复数矩阵 → JSON 原生（1D: [[re,im],...]；2D: 逐频点行嵌套）。"""
        if arr is None:
            return None
        array = np.asarray(arr)
        if array.ndim == 1:
            return [[float(v.real), float(v.imag)] for v in array]
        return [[[float(v.real), float(v.imag)] for v in row]
                for row in array]

    return ok_envelope(
        data={
            "path": str(path),
            "n_ports": parsed.get("n_ports"),
            "n_freqs": parsed.get("n_freqs"),
            "port_zpi": _cx_to_json(parsed.get("port_zpi")),
            "gamma": _cx_to_json(parsed.get("gamma")),
            "renormalized": parsed.get("renormalized"),
            "renormalize_ohm": parsed.get("renormalize_ohm"),
            "port_names": parsed.get("port_names"),
            "header": parsed.get("header"),
            "raw": parsed.get("raw"),
        },
    )
