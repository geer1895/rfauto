"""firmware 子应用——PT-6 固件工件三出口薄壳（规格书 §B-6，2026-10-02）。

零逻辑转发 core/firmware_export（规则 4 薄壳；数值只在确定性内核，铁律 7；
stats.py 先例：纯计算命令域内惰性 import core 直连，模块级 add_typer 自注册
——main.py 只 re-export，二次 add_typer 会双注册打红 zero-shadow 钉）：
  rfauto firmware beam      波束码字表（CSV+C 头双出+回代判据审计）
  rfauto firmware varactor  变容管 DAC 偏置表（f→C→V→码+单调/饱和审计）
  rfauto firmware dpd       DPD 系数定点表（Q 定标+回代 NMSE 门+溢出告警）

JSON 信封直出（ok=false → 退出码 1）；表格输入走 --file JSON（复数按
dpd_static.to_dict 的 {"re","im"} 对约定）；--csv/--ch 落盘（显式 UTF-8，
#89）。
"""

from __future__ import annotations

import json

import typer

from rfauto.cli.domains._core import app as app

firmware_app = typer.Typer(help="固件工件三出口（波束码字/变容管 DAC/DPD 定点，§B-6）")
app.add_typer(firmware_app, name="firmware")


def _emit_firmware(result: dict) -> None:
    """JSON 信封直出；ok=False → 退出码 1（stats._emit_stats 同款口径）。"""
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise typer.Exit(code=1)


def _write_text(path: str, text: str, what: str) -> str | None:
    """落盘 helper（显式 UTF-8，#89）；失败转 ok=False 信封语义。"""
    if not path:
        return None
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    except OSError as exc:
        _emit_firmware({"ok": False, "error": f"{what}写入失败: {exc}"})
        raise typer.Exit(code=1) from None
    return path


def _load_payload(path: str, what: str) -> dict:
    """--file JSON 读取（_core._load_json_file 薄转发，独立错误信封）。"""
    from rfauto.cli.domains._core import _load_json_file

    try:
        return _load_json_file(path, what)
    except typer.Exit:
        raise


@firmware_app.command("beam")
def firmware_beam_cmd(
    bits: int = typer.Option(..., "--bits", min=1, max=16,
                             help="相位量化位宽（1..16）"),
    file: str = typer.Option(..., "--file", help=(
        '单元表 JSON：{"element_ids":[...], "x_mm":[...], "y_mm":[...], '
        '"phase_target_deg":[...], "u0":[...]可选, "temp_comp_channels":N可选}')),
    csv_out: str = typer.Option("", "--csv", help="CSV 输出路径（可选）"),
    ch_out: str = typer.Option("", "--ch", help="C 头输出路径（可选）"),
    show_rows: bool = typer.Option(False, "--rows/--no-rows",
                                   help="信封含逐单元行（大表慎开）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """波束码字表：目标相位→b-bit 码字，CSV+C 头双出+回代判据审计."""
    from rfauto.core.firmware_export import beam_backsub_audit, beam_codeword_table, beam_table_c_header, beam_table_csv

    data = _load_payload(file, "单元表 JSON")
    try:
        table = beam_codeword_table(
            data["element_ids"], data["x_mm"], data["y_mm"],
            data["phase_target_deg"], bits=int(bits),
            u0=data.get("u0"),
            temp_comp_channels=int(data.get("temp_comp_channels", 4)),
        )
        audit = beam_backsub_audit(table)
    except (ValueError, KeyError) as exc:
        _emit_firmware({"ok": False,
                        "error": f"波束码字表失败: {exc}（KeyError=缺键）"})
        return
    envelope: dict = {
        "ok": True,
        "bits": table["bits"],
        "n_elements": table["n_elements"],
        "quant_step_deg": table["quant_step_deg"],
        "quant_loss_db": table["quant_loss_db"],
        "audit": audit,
        "csv_path": _write_text(csv_out, beam_table_csv(table), "CSV"),
        "ch_path": _write_text(ch_out, beam_table_c_header(table), "C 头"),
    }
    if show_rows:
        envelope["rows"] = table["rows"]
    _emit_firmware(envelope)


@firmware_app.command("varactor")
def firmware_varactor_cmd(
    file: str = typer.Option(..., "--file", help=(
        '载荷 JSON：{"f_targets_ghz":[...], "line_len_mm":, "z0_ohm":, '
        '"ereff":, "cj0_pf":, "phi_v":, "v_ref_v":, "bit_width":}')),
    csv_out: str = typer.Option("", "--csv", help="CSV 输出路径（可选）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """变容管 DAC 偏置表：f→C→V→码，单调性审计+饱和计数."""
    from rfauto.core.firmware_export import varactor_dac_table, varactor_table_csv

    data = _load_payload(file, "varactor 载荷 JSON")
    try:
        table = varactor_dac_table(
            data["f_targets_ghz"],
            line_len_mm=data["line_len_mm"], z0_ohm=data["z0_ohm"],
            ereff=data["ereff"], cj0_pf=data["cj0_pf"], phi_v=data["phi_v"],
            v_ref_v=data["v_ref_v"], bit_width=int(data["bit_width"]),
        )
    except (ValueError, KeyError) as exc:
        _emit_firmware({"ok": False,
                        "error": f"varactor DAC 表失败: {exc}（KeyError=缺键）"})
        return
    _emit_firmware({
        "ok": True,
        "bit_width": table["bit_width"],
        "v_ref_v": table["v_ref_v"],
        "lsb_v": table["lsb_v"],
        "full_scale_v": table["full_scale_v"],
        "audit": table["audit"],
        "rows": table["rows"],
        "csv_path": _write_text(csv_out, varactor_table_csv(table), "CSV"),
    })


def _complex_from_json(value) -> complex:
    """JSON 复数收敛：{"re","im"} 对或 [re, im] 对（dpd_static 约定）。"""
    if isinstance(value, dict):
        return complex(float(value["re"]), float(value["im"]))
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return complex(float(value[0]), float(value[1]))
    raise ValueError(f"复数须为 {{\"re\",\"im\"}} 对或 [re, im]，得 {value!r}")


def _complex_list(value, name: str) -> list:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} 须为非空列表")
    return [_complex_from_json(v) for v in value]


def _complex_matrix(value, name: str) -> list:
    """(K, M+1) 复系数收敛：嵌套行列表；1-D 扁平按 (K,1)（内核同约定）。"""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} 须为非空列表")
    if all(isinstance(row, (list, tuple)) for row in value):
        return [_complex_list(row, name) for row in value]
    return [[_complex_from_json(v)] for v in value]


@firmware_app.command("dpd")
def firmware_dpd_cmd(
    file: str = typer.Option(..., "--file", help=(
        '载荷 JSON：{"coeffs":[[{"re","im"}...]], "x":[{"re","im"}...] 或 '
        '[re,im] 列表, "pa_coeffs":可选, "word_bits":16, "frac_bits":12, '
        '"nmse_gate_db":0.5}')),
    csv_out: str = typer.Option("", "--csv", help="CSV 输出路径（可选）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """DPD 定点表：Q 格式定标+舍入回代预检（NMSE ≤0.5dB 劣化门）+溢出告警."""
    from rfauto.core.firmware_export import dpd_fixed_point_table, dpd_table_csv

    data = _load_payload(file, "dpd 载荷 JSON")
    try:
        coeffs = _complex_matrix(data["coeffs"], "coeffs")
        x = _complex_list(data["x"], "x")
        pa = (_complex_list(data["pa_coeffs"], "pa_coeffs")
              if data.get("pa_coeffs") is not None else None)
        table = dpd_fixed_point_table(
            coeffs, x,
            word_bits=int(data.get("word_bits", 16)),
            frac_bits=int(data.get("frac_bits", 12)),
            pa_coeffs=pa,
            nmse_gate_db=float(data.get("nmse_gate_db", 0.5)),
        )
    except (ValueError, KeyError, TypeError) as exc:
        _emit_firmware({"ok": False,
                        "error": f"DPD 定点表失败: {exc}（KeyError=缺键）"})
        return
    _emit_firmware({
        "ok": True,
        "word_bits": table["word_bits"],
        "frac_bits": table["frac_bits"],
        "q_format": table["q_format"],
        "warnings_count": table["warnings_count"],
        "overflow": table["overflow"],
        "nmse_db": table["nmse_db"],
        "gain_delta_db": table["gain_delta_db"],
        "cascade": table["cascade"],
        "nmse_gate_db": table["nmse_gate_db"],
        "verdict": table["verdict"],
        "notes": table["notes"],
        "coeffs_int": table["coeffs_int"],
        "csv_path": _write_text(csv_out, dpd_table_csv(table), "CSV"),
    })
