"""DP-4 J4c HFSS Floquet 对拍锚驱动（wf:goal-t15，半登记件落地）。

语境（#222）：runs/df6_dp4p3/criteria.md §J4c 预声明「Γ_act,n(侧射)=Σ_m S_nm，
报逐端口 |Γ_act| 与 |ΔΓ| vs HFSS Floquet」。
本驱动=缺位的发射面（research_expansion "E3 脚本缺"）+判读一体：
sim_host per-port grpcsrv（不碰他人实例 #261）→ 远程 attach（四开关
remote_session_switches，§1.3）→ 单元胞 Floquet 模型（Region+lattice pair×2
+Floquet port+50Ω 集总馈口）→ Driven Modal 自适应+Discrete 扫频 → S 参数
落 JSON 回拉 → 离线判读（对照归档 judge_2x2.json 的 gamma_act_f0，#340
回收钉互证）。判据数字带预声明在 runs/dp4_j4c_floquet/criteria.md
（发射前落盘）。

物理口径（criteria.md §主判量）：主判 |S(FEED,FEED)|@5.8GHz（馈口自反射，
50Ω 基）≡ 无限阵等幅同相激励 Γ_act(broadside)——与 openEMS Γ_act,n 同参考
阻抗同物理量；Floquet port 自反射只作副判报告。

用法（工作区根目录）::

    .venv/Scripts/python.exe scripts/hfss_floquet_anchor.py --dry-run   # 离线全链钉
    .venv/Scripts/python.exe scripts/hfss_floquet_anchor.py             # sim_host 真跑
    .venv/Scripts/python.exe scripts/hfss_floquet_anchor.py --judge-only  # 只判读

退出码：0=执行完成且 verdict 落盘（verdict 是裁决数据，DISAGREE 不算执行
失败，#225 口径）；1=执行 FAIL（fail-closed）；2=SKIP（守卫拦截）。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

# #1c 单源：EEP 毫米数全部来自模板注册表，禁抄（私有常量同模块内消费，
# 与渲染脚本/离线审计同制度）。
from rfauto.adapters.openems_templates import (  # noqa: E402
    _ARR_NOTCH_CLEAR_MM,
    _DEFAULT_SUB,
    _EEP_PROBE_HALF_X_MM,
    EEP_NOMINAL,
)


def _json_default(o: Any) -> Any:
    """complex → [re, im]（judge JSON 落档同口径）。"""
    if isinstance(o, complex):
        return [o.real, o.imag]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


OUT_DIR = REPO / "runs" / "dp4_j4c_floquet"
SERVER_SUBDIR = "floquet_j4c"
OE_JUDGE_JSON = REPO / "runs" / "df6_dp4p3" / "judge_2x2.json"
OE_S4P = REPO / "runs" / "df6_dp4p3" / "eep_2x2" / "patch_eep_2x2.s4p"

DEFAULT_MACHINE = "sim_host"
DEFAULT_PORT = 50053          # 50051=T14 残留实例不碰；50052 留 T14 波段
PORT_SCAN = range(50050, 50061)  # §3.4：attach 前扫实际监听面
F0_GHZ = 5.8
SWEEP_START_GHZ, SWEEP_STOP_GHZ, SWEEP_POINTS = 5.5, 6.1, 201
BAND_GHZ = (5.55, 6.05)
MAX_PASSES = 30
MAX_DELTA_S = 0.02
AIR_TOP_MM = 30.0
GATE_AGREE = 0.08
GATE_TREND = 0.15
GATE_PASSIVE = 1.005
CONSISTENCY_TOL = 1e-6


def unit_cell_geom() -> dict[str, Any]:
    """单元胞几何（mm，EEP_NOMINAL 单源 #1c）。"""
    nom = EEP_NOMINAL["patch_eep_2x2"]
    w = float(nom["elem_w_mm"])
    length = float(nom["elem_len_mm"])
    fw = float(nom["feed_w_mm"])
    d_in = float(nom["elem_feed_mm"])
    dx = float(nom["spacing_x_mm"])
    dy = float(nom["spacing_y_mm"])
    nw = fw + 2.0 * _ARR_NOTCH_CLEAR_MM
    yf = -length / 2.0 + d_in
    return {
        "er": float(_DEFAULT_SUB["er"]),
        "tan_d": float(_DEFAULT_SUB["tan_d"]),
        "h": float(_DEFAULT_SUB["h_mm"]),
        "w": w, "l": length, "fw": fw, "d_in": d_in,
        "nw": nw, "dx": dx, "dy": dy, "yf": yf,
        "probe_x": 2.0 * _EEP_PROBE_HALF_X_MM,
        "air_top": AIR_TOP_MM,
    }


# ── 服务器面（复用 8 席窗生产 helper，本脚本零复制）─────────────────────

def scan_server_ports(machine: str, my_port: int) -> dict[str, Any]:
    """占用面扫描 + fail-closed 守卫（§3.4：绑定回退盲区，attach 前实扫）。"""
    from rfauto.infra.remote_machines import (
        load_remote_machines,
        probe_port,
        resolve_machine,
    )

    cfg = resolve_machine(machine, load_remote_machines())
    open_ports: list[int] = []
    for p in PORT_SCAN:
        op, _ms = probe_port(cfg.host, int(p), timeout_s=1.0)
        if op:
            open_ports.append(int(p))
    info: dict[str, Any] = {"open_ports": open_ports, "my_port": int(my_port)}
    if int(my_port) in open_ports:
        info["blocked"] = f"端口 {my_port} 已有监听（不代杀，换段或人工核对）"
    lic, _ms = probe_port(cfg.host, 1055, timeout_s=2.0)
    info["ansys_license_open"] = bool(lic)
    if not lic:
        info["blocked"] = "许可端口 1055 不可达"
    return info


def ensure_server_dir(machine: str, server_dir: str) -> bool:
    """服务器目录预建（G13：cmd /c mkdir 已存在 rc=1 → PowerShell New-Item -Force）。"""
    from rfauto.infra.remote_machines import (
        SshTransport,
        load_remote_machines,
        resolve_machine,
    )

    cfg = resolve_machine(machine, load_remote_machines())
    t = SshTransport(cfg)
    t.connect()
    try:
        rc, _out, err = t.run_command(
            f"New-Item -ItemType Directory -Force -Path '{server_dir}' | Out-Null",
            timeout_s=30.0,
        )
        if rc != 0:
            print(f"[dir] New-Item rc={rc} err={err[:120]}", flush=True)
        return rc == 0
    finally:
        with contextlib.suppress(Exception):
            t.close()


def fetch_remote_file(machine: str, remote_path: str, local_path: Path) -> bool:
    """SFTP 回拉（与 8 席窗同款 best-effort）。"""
    from rfauto.infra.remote_machines import (
        SshTransport,
        load_remote_machines,
        resolve_machine,
    )

    cfg = resolve_machine(machine, load_remote_machines())
    t = SshTransport(cfg)
    t.connect()
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        t.download_file(remote_path, str(local_path))
        return local_path.exists()
    finally:
        with contextlib.suppress(Exception):
            t.close()


# ── HFSS 建模/求解（pyaedt 惰性 import，dry-run 零依赖）────────────────

def _rect_with_bbox_audit(h: Any, orientation: str, origin: list[float],
                          sizes: list[float], expect: list[float],
                          name: str) -> Any:
    """建矩形片 + bbox 自审（#310：sizes 直通不重排，映射不符换序重试）。"""
    tol = 1e-6

    def _ok(obj: Any) -> bool:
        bb = [float(v) for v in obj.bounding_box]
        return all(abs(a - b) <= tol for a, b in zip(bb, expect, strict=False))

    obj = h.modeler.create_rectangle(orientation, origin, sizes, name=name)
    if _ok(obj):
        return obj
    obj.delete()
    obj = h.modeler.create_rectangle(orientation, origin,
                                     [sizes[1], sizes[0]], name=name)
    if _ok(obj):
        return obj
    raise RuntimeError(
        f"{name}: 矩形片 bbox 自审双序均不符（orientation={orientation} "
        f"origin={origin} sizes={sizes} expect={expect}）")


def build_unit_cell(h: Any) -> dict[str, Any]:
    """单元胞建模（Region+lattice pair×2+Floquet port+集总馈口）。

    返回 build manifest（几何字面量+边界名单+校验结果，随 hfss_results.json 落档）。
    """
    g = unit_cell_geom()
    dx, dy, hh = g["dx"], g["dy"], g["h"]
    yf, nw, w, length = g["yf"], g["nw"], g["w"], g["l"]
    fw, d_in, probe_x = g["fw"], g["d_in"], g["probe_x"]
    ztop = g["air_top"]
    info: dict[str, Any] = {"geom_mm": g}

    h.modeler.model_units = "mm"
    mat = h.materials.add_material("eep_ro4350b_j4c")
    mat.permittivity = g["er"]
    mat.loss_tangent = g["tan_d"]

    # 几何次序（diag2_steps 定案）：**Region 是活对象，跟随当前模型 bbox**——
    # 先建全部实体（SUB z∈[0,h] + AIRBOX z∈[h,ztop] 真空、堆叠不重叠），Region
    # 零绝对偏移建在其后即抱住整胞（任何对象删除都会让 Region 塌缩，故此后
    # 零删除）。侧面=Region 整高单片 → lattice pair 单面对无多面拼接问题。
    # 验证用 oeditor.GetModelBoundingBox（Region 的 .bounding_box 是占位语义）。
    h.modeler.create_box([-dx / 2, -dy / 2, 0.0], [dx, dy, hh],
                         name="SUB", material="eep_ro4350b_j4c")
    h.modeler.create_box([-dx / 2, -dy / 2, hh], [dx, dy, ztop - hh],
                         name="AIRBOX", material="vacuum")
    region = h.modeler.create_region(0, pad_type="Absolute Offset")
    expect = [-dx / 2, -dy / 2, 0.0, dx / 2, dy / 2, ztop]
    rbb = [float(v) for v in
           h.modeler.oeditor.GetModelBoundingBox()]
    if not all(abs(a - b) <= 0.01 for a, b in zip(rbb, expect, strict=False)):
        raise RuntimeError(
            f"Region 生成自审不符（GetModelBoundingBox={rbb} != {expect}）"
            "——Region 未按零偏移包住模型")
    info["region_bbox"] = rbb

    sheets: list[str] = ["GND"]
    _rect_with_bbox_audit(h, "XY", [-dx / 2, -dy / 2, 0.0], [dx, dy],
                          [-dx / 2, -dy / 2, 0.0, dx / 2, dy / 2, 0.0],
                          "GND")
    # 贴片三盒 + 缺口内馈段（z=h 薄片，与 _eep_layout 单源同构）
    for nm, pos, sz, exp in (
        ("PL", [-w / 2, -length / 2, hh],
         [(w - nw) / 2, length],
         [-w / 2, -length / 2, hh, -nw / 2, length / 2, hh]),
        ("PR", [nw / 2, -length / 2, hh],
         [(w - nw) / 2, length],
         [nw / 2, -length / 2, hh, w / 2, length / 2, hh]),
        ("PC", [-nw / 2, -length / 2 + d_in, hh],
         [nw, length - d_in],
         [-nw / 2, -length / 2 + d_in, hh, nw / 2, length / 2, hh]),
        ("STUB", [-fw / 2, -length / 2, hh], [fw, d_in],
         [-fw / 2, -length / 2, hh, fw / 2, -length / 2 + d_in, hh]),
    ):
        _rect_with_bbox_audit(h, "XY", pos, sz, exp, nm)
        sheets.append(nm)
    # 馈电竖直片（x∈[−probe_x/2, +probe_x/2] × z∈[0,h] @ y=yf；
    # 映射不确定面交给 bbox 自审双序）
    _rect_with_bbox_audit(
        h, "ZX", [-probe_x / 2, yf, 0.0], [probe_x, hh],
        [-probe_x / 2, yf, 0.0, probe_x / 2, yf, hh], "FEEDSHEET")
    info["sheets_perfecte"] = sheets
    h.assign_perfecte_to_sheets(sheets, name="PEC_METALS")

    port = h.lumped_port(
        assignment="FEEDSHEET",
        integration_line=[[0.0, yf, 0.0], [0.0, yf, hh]],
        impedance=50.0, name="FEED", renormalize=True)
    info["lumped_port"] = str(port.name)

    pairs = h.auto_assign_lattice_pairs(region, "Global", "XY")
    info["lattice_pairs"] = [str(p) for p in pairs]
    if len(pairs) != 2:
        raise RuntimeError(f"lattice pair 数 {len(pairs)} != 2")
    pair_props: dict[str, Any] = {}
    for pname in pairs:
        bound = next((b for b in h.boundaries if str(b.name) == str(pname)),
                     None)
        if bound is None:
            raise RuntimeError(f"lattice pair {pname!r} 未在 boundaries 找到")
        with contextlib.suppress(Exception):
            bound.props["PhaseDelay"] = "UseScanAngle"
            bound.props["Phi"] = "0deg"
            bound.props["Theta"] = "0deg"
            bound.update()
        # 读回实值落 manifest（AutoIdentify 缺省即侧射 0°，此为证据面）
        with contextlib.suppress(Exception):
            pair_props[str(pname)] = {
                k: str(v) for k, v in dict(bound.props).items()
                if k in ("PhaseDelay", "Phi", "Theta", "ReverseV")}
    info["lattice_pair_props"] = pair_props

    top = None
    for f in region.faces:
        n = [float(v) for v in f.normal]
        if abs(n[2] - 1.0) < 1e-6:
            top = f
            break
    if top is None:
        raise RuntimeError("Region 顶面（+z 法向）未找到")
    fp = h.create_floquet_port(
        top,
        lattice_origin=[-dx / 2, -dy / 2, ztop],
        lattice_a_end=[dx / 2, -dy / 2, ztop],
        lattice_b_end=[-dx / 2, dy / 2, ztop],
        modes=2, name="FP1", renormalize=True, deembed_distance=0)
    info["floquet_port"] = str(fp.name)
    return info


def _resolve_expr(h: Any, setup_sweep: str, want: str, stem: str) -> str:
    """S 表达式解析：先精确名，失败则枚举可用量按端口名前缀匹配。"""
    try:
        qty = h.post.available_report_quantities(
            report_category="Modal Solution Data", setup=setup_sweep) or []
        if want in qty:
            return want
        for q in qty:
            if isinstance(q, str) and q.startswith(f"S({stem}!"):
                return q
    except Exception as exc:  # — 枚举失败回退精确名，如实记
        print(f"[expr] 枚举失败（{exc}），回退精确名 {want}", flush=True)
    return want


def solve_and_extract(h: Any, out_dir: Path, server_dir: str) -> dict[str, Any]:
    """setup+扫频+求解+提取（S_ff 主判 / S_fp 副判 + profile 收敛证据）。

    profile 落**服务器目录**（远程 desktop 的 ExportProfile 按服务器文件系统
    解释路径），由调用方 sftp 回拉后 parse_profile 判收敛。"""
    setup = h.create_setup(name="J4cSetup", setup_type="HFSSDriven",
                           Frequency=f"{F0_GHZ}GHz",
                           MaximumPasses=MAX_PASSES,
                           MaxDeltaS=MAX_DELTA_S)
    setup.create_frequency_sweep(unit="GHz", start_frequency=SWEEP_START_GHZ,
                                 stop_frequency=SWEEP_STOP_GHZ,
                                 num_of_freq_points=SWEEP_POINTS,
                                 name="Sweep", sweep_type="Discrete",
                                 save_fields=False)
    # **禁调 validate_full_design**（v3-v5 三连实证定案）：该 gRPC 调用在含
    # Region 设计上崩（"failed to compute face center" 宏错误）且**崩后毒化
    # 整个 gRPC 会话**——其后一切 Save 必失败（diag4/diag5 定案：同一实例
    # 不调 validate 时全 build 12 步 Save 全 OK；v3/v4/v5 调 validate 崩后
    # Save 必死）。真校验由 analyze 的求解前置验证承担，模型真坏会在
    # analyze 如实失败；几何面由 build 端 bbox 自审承担（#310）。
    errs = "validate skipped（会话毒化坑，见上注）"
    t0 = time.monotonic()
    # **单次裸 analyze**（v6 实证定案）：cores/tasks 路径写 ACF registry 文件
    # 失败（pyaedt_config.acf）且失败即毒化会话（其后 Save 必死）——禁用
    # cores/tasks/回退链，用桌面缺省核数。
    ok = h.analyze(setup="J4cSetup", blocking=True)
    solve_s = time.monotonic() - t0
    if not ok:
        raise RuntimeError("analyze 返回 False（求解未完成）")
    h.save_project()

    profile_server = f"{server_dir}\\profile.txt"
    with contextlib.suppress(Exception):
        h.export_profile("J4cSetup", output_file=profile_server)
    (out_dir / "profile.remote_path.txt").write_text(profile_server + "\n",
                                                     encoding="utf-8")

    res: dict[str, Any] = {"solve_s": solve_s, "validate": str(errs)[:400]}
    # 提取走 setup.get_solution_data（v8 实证定案）：post.reports_by_category
    # .modal_solution 的 nominal_variation→GetVariables 链在本设计上必炸
    # （v7/v8 两轮实证），且表达式名为 S(FEED,FEED) 冒号 mode 语法；
    # get_expression_data 返回 (X, Y)——X=主扫频，须 real/imag 两次调用。
    setup_obj = h.setups[0]
    data = setup_obj.get_solution_data()
    if data is None or not data.expressions:
        raise RuntimeError("setup.get_solution_data 空（解未生成？）")
    freqs = np.asarray([float(v) for v in data.primary_sweep_values])
    exprs = list(data.expressions)

    def _pick(cands: list[str]) -> str:
        for c in cands:
            if c in exprs:
                return c
        raise KeyError(f"无匹配表达式: {cands} vs {exprs}")

    for key, cands in (("s_ff", ["S(FEED,FEED)", "S(FEED!1,FEED!1)"]),
                       ("s_fp", ["S(FP1:1,FP1:1)", "S(FP1!1,FP1!1)"])):
        expr = _pick(cands)
        _x, y_re = data.get_expression_data(expr, formula="real")
        _x2, y_im = data.get_expression_data(expr, formula="imag")
        res[key] = {
            "expr": expr,
            "freq_ghz": freqs.tolist(),
            "re": np.asarray(y_re, dtype=float).tolist(),
            "im": np.asarray(y_im, dtype=float).tolist(),
        }
    return res


def convergence_from_messages(h: Any, project: str, design: str) -> dict[str, Any]:
    """收敛证据（v8 实证定案的口径）：design 域 GetMessages(sev=3) 计数。

    AEDT 自适应触 MaxPasses 未达 ΔS 时必产 "[warning] Adaptive Passes did
    not converge"（v7 同款配置实证警告在场）；零 warning=收敛达标。
    ExportConvergenceDataFile 本服务器不可用（v8 实证），profile 导出亦空
    （"no profile data"）——消息面是唯一可靠收敛证据通道。"""
    try:
        msgs = list(h.odesktop.GetMessages(project, design, 3))
    except Exception as exc:  # 消息面失败=收敛未证（如实）
        return {"ok": False, "warn_count": None,
                "note": f"GetMessages 失败：{type(exc).__name__}: "
                        f"{str(exc)[:120]}"}
    return {"ok": len(msgs) == 0, "warn_count": len(msgs),
            "note": ("零 warning（未收敛必产 'Adaptive Passes did not "
                     "converge' [warning]，v7 实证在场）" if not msgs
                     else f"warning/error {len(msgs)} 条："
                     + "; ".join(str(m)[:80] for m in msgs[:3]))}


def parse_profile(path: Path) -> dict[str, Any]:
    """从 profile 文本提自适应收敛证据（ΔS 逐 pass；容多版本措辞）。"""
    if not path.exists():
        return {"ok": False, "note": "profile 缺（导出/回拉失败）"}
    text = path.read_text(encoding="utf-8", errors="replace")
    deltas = [float(m.group(1)) for m in re.finditer(
        r"(?i)delta\s*s[^0-9\n-]*([0-9]*\.?[0-9]+(?:[eE][+-]?\d+)?)", text)]
    passes = len(re.findall(r"(?i)adaptive\s*pass", text))
    if not deltas:
        return {"ok": False, "note": "profile 未解析出 Delta S（措辞版本差，"
                                     f"passes 标记 {passes}）", "passes": passes}
    final = min(deltas)
    ok = final <= MAX_DELTA_S
    return {"ok": bool(ok), "deltas": deltas, "passes": passes,
            "final_delta": final,
            "note": ("达标停机" if ok else
                     "触 MaxPasses 未达 ΔS 目标（UNKNOWN 如实，#335）")}


def open_session(machine: str, port: int) -> tuple[Any, Any, dict[str, Any]]:
    """远程 attach（四开关单源 + remote_rpc_session=None，§1.3/G9 同款）。"""
    from ansys.aedt.core import Desktop, Hfss
    from ansys.aedt.core.generic.settings import settings

    from rfauto.adapters.hfss_session import remote_session_switches
    from rfauto.service.remote_service import hfss_remote_session_config

    remote = hfss_remote_session_config(machine).get("remote")
    if not remote:
        raise RuntimeError(f"机器 {machine!r} 未登记远程会话配置")
    remote = {**remote, "port": int(port)}
    server_dir = f"{remote['project_root']}\\{SERVER_SUBDIR}"
    server_project = f"{server_dir}\\j4c_floquet.aedt"
    if not ensure_server_dir(machine, server_dir):
        raise RuntimeError(f"服务器目录预建失败：{server_dir}（fail-closed）")
    with remote_session_switches():
        desktop = Desktop(version=remote["version"], non_graphical=True,
                          new_desktop=False, machine=remote["machine"],
                          port=remote["port"])
        settings.remote_rpc_session = None
        h = Hfss(project=server_project, design="j4c_floquet_unitcell",
                 solution_type="Modal", version=remote["version"],
                 non_graphical=True, machine=remote["machine"],
                 port=remote["port"])
    info = {"remote_port": int(port), "server_project": server_project}
    return desktop, h, info


# ── 判读（纯离线，#122 门全在 criteria.md）────────────────────────────

def load_oe_reference() -> dict[str, Any]:
    """OE 参考值：judge JSON + s4p 独立重算互证（#340 回收钉）。"""
    import skrf

    judge = json.loads(OE_JUDGE_JSON.read_text(encoding="utf-8"))
    res = judge["result"]
    # judge JSON 存 [re, im] 对（core.array_scan 落档口径），收敛为 complex
    gamma_json = [complex(float(v[0]), float(v[1]))
                  for v in res["gamma_act_f0"]]
    net = skrf.Network(str(OE_S4P))
    f0_hz = F0_GHZ * 1e9
    idx = int(np.argmin(np.abs(net.f - f0_hz)))
    s0 = net.s[idx]                      # 4×4 @5.8GHz
    gamma_s4p = [complex(sum(s0[n, m] for m in range(4))) for n in range(4)]
    dev = max(abs(a - b) for a, b in zip(
        gamma_json, gamma_s4p, strict=False))
    rows = net.f.shape[0]
    fg = net.f / 1e9
    band = (fg >= BAND_GHZ[0]) & (fg <= BAND_GHZ[1])
    band_curve = np.array([
        np.mean([abs(complex(sum(net.s[i, n, m] for m in range(4))))
                 for n in range(4)]) for i in np.where(band)[0]])
    return {
        "gamma_act_f0": gamma_json,
        "abs_mean": float(np.mean(np.abs(gamma_json))),
        "abs_spread": float(np.max(np.abs(gamma_json))
                            - np.min(np.abs(gamma_json))),
        "s4p_rows": int(rows),
        "s4p_band_points": int(band.sum()),
        "band_freq_ghz": fg[band].tolist(),
        "band_abs_mean": band_curve.tolist(),
        "consistency_dev": float(dev),
        "consistency_ok": bool(dev <= CONSISTENCY_TOL),
    }


def judge(hfss: dict[str, Any], oe: dict[str, Any]) -> dict[str, Any]:
    """预声明门判读（criteria.md §门）。纯函数：输入两 dict 输出 verdict。"""
    fg = np.asarray(hfss["s_ff"]["freq_ghz"], dtype=float)
    sff = np.asarray(hfss["s_ff"]["re"]) + 1j * np.asarray(hfss["s_ff"]["im"])
    i0 = int(np.argmin(np.abs(fg - F0_GHZ)))
    abs_f0 = float(abs(sff[i0]))
    band = (fg >= BAND_GHZ[0]) & (fg <= BAND_GHZ[1])
    passive_max = float(np.max(np.abs(sff[band]))) if band.any() else float("nan")
    checks: list[str] = []
    if not oe["consistency_ok"]:
        checks.append(
            f"OE 回收钉超 tol：|Δγ|={oe['consistency_dev']:.3e}")
    if not (passive_max <= GATE_PASSIVE):
        checks.append(f"无源性破：band max|S_ff|={passive_max:.4f}")
    conv = hfss.get("convergence") or {}
    if not conv.get("ok", False):
        checks.append(
            "HFSS 收敛未证：" + str(conv.get("note", "profile 缺/未解析")))
    dgamma = abs(abs_f0 - oe["abs_mean"])
    if checks:
        verdict = "UNKNOWN"
    elif dgamma <= GATE_AGREE:
        verdict = "AGREE"
    elif dgamma <= GATE_TREND:
        verdict = "TREND_ALIGN"
    else:
        verdict = "DISAGREE"
    trend_r = None
    try:
        sfp = np.asarray(hfss["s_fp"]["re"]) + 1j * np.asarray(
            hfss["s_fp"]["im"])
        common = band & (np.asarray(
            hfss["s_fp"]["freq_ghz"], dtype=float) >= BAND_GHZ[0])
        a = np.abs(sff[common])
        b = np.abs(sfp[common])
        if len(a) > 2 and np.std(a) > 0 and np.std(b) > 0:
            trend_r = float(np.corrcoef(a, b)[0, 1])
    except Exception:  # — 副判缺数据不阻塞主判
        pass
    return {
        "verdict": verdict,
        "d_gamma": dgamma,
        "gate": {"agree": GATE_AGREE, "trend": GATE_TREND,
                 "passive": GATE_PASSIVE},
        "hfss_abs_f0": abs_f0,
        "hfss_f0_ghz": float(fg[i0]),
        "oe_abs_mean": oe["abs_mean"],
        "oe_abs_spread": oe["abs_spread"],
        "hfss_band_passive_max": passive_max,
        "oe_gamma_act_f0_abs": [abs(v) for v in oe["gamma_act_f0"]],
        "trend_pearson_sff_vs_sfp": trend_r,
        "checks": checks,
    }


def synthetic_hfss_results() -> dict[str, Any]:
    """dry-run 合成 HFSS 曲线（谐振型 |S_ff| 过 OE 均值附近，全链判读钉）。"""
    oe = load_oe_reference()
    fg = np.linspace(SWEEP_START_GHZ, SWEEP_STOP_GHZ, SWEEP_POINTS)
    base = oe["abs_mean"] * (1.0 + 0.15 * (fg - F0_GHZ))
    phase = 1.7 + 0.9 * (fg - F0_GHZ)
    sff = base * np.exp(1j * phase)
    return {
        "dry_run": True,
        "s_ff": {"expr": "S(FEED!1,FEED!1)", "freq_ghz": fg.tolist(),
                 "re": sff.real.tolist(), "im": sff.imag.tolist()},
        "s_fp": {"expr": "S(FP1!1,FP1!1)", "freq_ghz": fg.tolist(),
                 "re": (0.3 * sff.real).tolist(),
                 "im": (0.3 * sff.imag).tolist()},
        "convergence": {"ok": True, "note": "dry-run 合成"},
        "solve_s": 0.0,
    }


# ── 主流程 ────────────────────────────────────────────────────────────

def write_verdict_md(v: dict[str, Any], path: Path) -> None:
    lines = [
        "# DP-4 J4c HFSS Floquet 对拍 verdict", "",
        f"- **verdict: {v['verdict']}**（判据 runs/dp4_j4c_floquet/criteria.md 预声明）",
        f"- |S_ff|@{v['hfss_f0_ghz']:.4f}GHz(HFSS) = {v['hfss_abs_f0']:.4f}",
        f"- mean|Γ_act|(OE 2x2 归档) = {v['oe_abs_mean']:.4f}"
        f"（端口散布 {v['oe_abs_spread']:.4f}）",
        f"- Δ|Γ| = {v['d_gamma']:.4f}（门 AGREE≤{v['gate']['agree']}"
        f" / TREND≤{v['gate']['trend']}）",
        f"- 带内 max|S_ff| = {v['hfss_band_passive_max']:.4f}"
        f"（无源性门 ≤{v['gate']['passive']}）",
        f"- 副判 Pearson r(|S_ff|,|S_fp|) = {v['trend_pearson_sff_vs_sfp']}",
        "- 逐端口 OE |Γ_act| = "
        + ", ".join(f"{x:.4f}" for x in v["oe_gamma_act_f0_abs"]),
        f"- checks: {v['checks'] or '无'}",
        "",
        "置信标注（criteria 原文）：2×2 有限阵 vs 无限阵=仅趋势对齐，"
        "盲点位置/深度以 HFSS 为准；相位不门（参考面几何不同，如实）。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DP-4 J4c HFSS Floquet 对拍锚")
    ap.add_argument("--machine", default=DEFAULT_MACHINE)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help="本席指纹端口（launch 目标+cleanup 指纹 :<port>:）")
    ap.add_argument("--attach-existing", type=int, default=None, metavar="PORT",
                    help="不 launch：直接 attach 到已有实例（§3.4 实证：本服务器 "
                         "ansysedt 忽略非缺省 grpcsrv 口恒落 50051——launch 后 "
                         "按实际监听口接管的接力路径）；清理仍按 --port 指纹")
    ap.add_argument("--launch-only", action="store_true",
                    help="只拉起本席 grpcsrv 实例（等端口开或超时），不建模；"
                         "实例驻留供 --attach-existing 接管")
    ap.add_argument("--dry-run", action="store_true",
                    help="零网络零 pyaedt：合成 HFSS 数据走全链判读")
    ap.add_argument("--judge-only", action="store_true",
                    help="只读已回拉的 hfss_results.json 判读")
    ap.add_argument("--keep-server", action="store_true",
                    help="调试用：跳过 per-port 清理（缺省必清）")
    args = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        # dry-run 产物一律 .dryrun 后缀（§4.4 stale 隔离：不得覆盖真跑产物
        # ——本批实证 dry-run 曾把真跑 hfss_results.json 覆盖丢失）
        hfss = synthetic_hfss_results()
        (OUT_DIR / "hfss_results.dryrun.json").write_text(
            json.dumps(hfss, default=_json_default, ensure_ascii=False, indent=1), encoding="utf-8")
        sfx = ".dryrun"
    elif args.judge_only:
        sfx = ""
        p = OUT_DIR / "hfss_results.json"
        if not p.exists():
            print("[judge] hfss_results.json 缺（先真跑或 dry-run）", flush=True)
            return 1
        hfss = json.loads(p.read_text(encoding="utf-8"))
    else:
        if getattr(args, "launch_only", False):
            launched = launch_remote_grpcsrv_isolated(args.machine, args.port)
            print(f"[launch-only] {launched}", flush=True)
            return 0 if launched.get("ok") else 1
        if args.attach_existing is not None:
            guard = scan_server_ports(args.machine, args.port)
            guard["attach_existing"] = int(args.attach_existing)
            # 接管路径不要求指纹口空闲（实例命令行=:port: 但实听 50051），
            # 只要求 attach 口在监听（fail-closed）
            from rfauto.infra.remote_machines import (
                load_remote_machines,
                probe_port,
                resolve_machine,
            )

            cfg_a = resolve_machine(args.machine, load_remote_machines())
            open_a, _ms = probe_port(cfg_a.host, int(args.attach_existing),
                                     timeout_s=2.0)
            guard["attach_port_open"] = bool(open_a)
            if not open_a:
                guard["blocked"] = (
                    f"attach 口 {args.attach_existing} 无监听（实例已死？"
                    "走缺省 launch 路径重拉）")
            print(f"[guard] {guard}", flush=True)
            if guard.get("blocked"):
                (OUT_DIR / "verdict.json").write_text(json.dumps(
                    {"ok": False, "skip": True, "reason": guard["blocked"],
                     "dry_run": False}, default=_json_default,
                    ensure_ascii=False, indent=1), encoding="utf-8")
                return 2
            return run_real(args, guard)
        guard = scan_server_ports(args.machine, args.port)
        print(f"[guard] {guard}", flush=True)
        if guard.get("blocked"):
            (OUT_DIR / "verdict.json").write_text(json.dumps({"ok": False, "skip": True, "reason": guard["blocked"],
                 "dry_run": False}, default=_json_default, ensure_ascii=False, indent=1),
                encoding="utf-8")
            return 2
        return run_real(args, guard)

    oe = load_oe_reference()
    v = judge(hfss, oe)
    envelope = {"ok": True, "dry_run": bool(hfss.get("dry_run", False)),
                "judge": v, "oe": {k: w for k, w in oe.items()
                                   if k not in ("band_freq_ghz",
                                                "band_abs_mean")}}
    (OUT_DIR / f"verdict{sfx}.json").write_text(
        json.dumps(envelope, default=_json_default, ensure_ascii=False, indent=1),
        encoding="utf-8")
    write_verdict_md(v, OUT_DIR / f"verdict{sfx}.md")
    print(f"[verdict] {v['verdict']}  Δ|Γ|={v['d_gamma']:.4f} "
          f"checks={v['checks'] or '无'}", flush=True)
    return 0


def launch_remote_grpcsrv_isolated(machine: str, port: int, *,
                                   grpc_wait_s: float = 600.0) -> dict[str, Any]:
    """本席隔离 bat 流（remote_service._launch_grpcsrv 同款流程，三处差异）。

    实证沿革（本批三连败定案）：①vbs 流（hfss_window_arbitration 版）
    /tr='wscript.exe "..."' 双引号经 SSH→PowerShell 逐层剥（§1.5）+无
    -Logfile 实例起机 stall（cpu≈6s/ws≈131MB 恒置、端口永不开，两轮）；
    ②共享根 bat/vbs 会被并发席 glob 清理删（首跑 vbs 消失实证）。
    本变体=**bat+schtasks /tr 直指**（mmt_anchor 50051 实证活实例同款）
    +bat/-Logfile/任务名全落本席子目录（隔离并发清理）+等待窗 300s
    （负载下冷启动余量）。杀/清仍走 win.cleanup_remote_grpcsrv（指纹不变）。"""
    import tempfile
    import uuid as _uuid

    from rfauto.infra.remote_machines import (
        SshTransport,
        load_remote_machines,
        probe_port,
        resolve_machine,
    )

    port = int(port)
    transport = None
    steps: dict[str, Any] = {}
    try:
        cfg = resolve_machine(machine, load_remote_machines())
        transport = SshTransport(cfg)
        transport.connect()
        if not cfg.hfss_ansysedt_exe:
            return {"ok": False, "port": port,
                    "reason": "机器未登记 hfss.ansysedt_exe", "steps": steps}
        open_pre, _ms = probe_port(cfg.host, port, timeout_s=2.0)
        if open_pre:
            return {"ok": False, "port": port,
                    "reason": f"端口 {port} 已有监听（不代杀）", "steps": steps}
        work_dir = cfg.hfss_project_root + "\\" + SERVER_SUBDIR
        rc, _out, err = transport.run_command(
            f"New-Item -ItemType Directory -Force -Path '{work_dir}' | Out-Null",
            timeout_s=20.0)
        if rc != 0:
            return {"ok": False, "port": port,
                    "reason": f"服务器工作目录创建失败: {err[:120]}",
                    "steps": steps}
        exe = cfg.hfss_ansysedt_exe.replace("/", "\\")
        logline = work_dir + "\\aedt_console.log"
        bat_remote = work_dir + "\\launch_grpcsrv_" + str(port) + ".bat"
        bat_lines = ("@echo off\r\n"
                     f'"{exe}" -ng -Logfile "{logline}" '
                     f"-grpcsrv {cfg.host}:{port}:InsecureMode\r\n")
        with tempfile.TemporaryDirectory() as td:
            bat_local = Path(td) / f"launch_grpcsrv_{port}.bat"
            bat_local.write_bytes(bat_lines.encode("ascii"))
            transport.upload_file(bat_local, bat_remote)
        steps["bat_upload"] = {"remote": bat_remote}
        task_name = ("RFAuto\\hfss_window_" + str(port) + "_"
                     + _uuid.uuid4().hex[:8])
        steps["schtasks"] = {"task_name": task_name}
        bat_win = work_dir + "\\launch_grpcsrv_" + str(port) + ".bat"
        for cmd, label in (
            (f"schtasks /create /f /tn \"{task_name}\" "
             f"/tr \"{bat_win}\" /sc once /st 23:59", "create"),
            (f"schtasks /run /tn \"{task_name}\"", "run"),
        ):
            rc, _out, err = transport.run_command(cmd, timeout_s=30.0)
            steps["schtasks"][label] = rc
            if rc != 0:
                steps["schtasks"]["stderr_head"] = err[:200]
                return {"ok": False, "port": port,
                        "reason": f"schtasks {label} 非零退出（rc={rc}）",
                        "steps": steps}
        deadline = time.monotonic() + grpc_wait_s
        opened = False
        while time.monotonic() < deadline:
            opened, _ms = probe_port(cfg.host, port, timeout_s=2.0)
            if opened:
                break
            time.sleep(3.0)
        if not opened:
            return {"ok": False, "port": port,
                    "reason": f"grpcsrv 端口 {port} 等待超时（>{grpc_wait_s:.0f}s）",
                    "steps": steps}
        steps["grpc_port_open"] = True
        return {"ok": True, "port": port, "task_name": task_name,
                "bat": bat_remote, "steps": steps}
    except Exception as exc:
        return {"ok": False, "port": port,
                "reason": f"{type(exc).__name__}: {str(exc)[:160]}",
                "steps": steps}
    finally:
        if transport is not None:
            with contextlib.suppress(Exception):
                transport.close()


def _load_win():
    """复用 8 席窗生产 helper（scripts/ 非包：脚本目录入 path 后按名导入）。"""
    import importlib

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        return importlib.import_module("hfss_window_arbitration")
    except ImportError as exc:
        raise RuntimeError(
            "hfss_window_arbitration 导入失败（launch/cleanup helper 复用面）"
        ) from exc


def run_real(args: argparse.Namespace, guard: dict[str, Any]) -> int:
    """真跑链：launch→attach→build→solve→extract→回拉→判读→清理。"""
    win = _load_win()

    launched: dict[str, Any] = {}
    desktop = None
    h = None
    session_info: dict[str, Any] = {}
    try:
        if getattr(args, "attach_existing", None):
            launched = {"ok": True, "attach_existing": True,
                        "port": int(args.attach_existing)}
            print(f"[launch] attach-existing 接管：{launched}", flush=True)
        else:
            launched = launch_remote_grpcsrv_isolated(args.machine, args.port)
            print(f"[launch] {launched}", flush=True)
            if not launched.get("ok"):
                raise RuntimeError(f"grpcsrv 拉起失败：{launched.get('reason')}")
        attach_port = (int(args.attach_existing)
                       if getattr(args, "attach_existing", None)
                       else int(args.port))
        desktop, h, session_info = open_session(args.machine, attach_port)
        print(f"[attach] {session_info}", flush=True)
        build_info = build_unit_cell(h)
        print(f"[build] pairs={build_info['lattice_pairs']} "
              f"floquet={build_info['floquet_port']}", flush=True)
        server_dir = session_info["server_project"].rsplit("\\", 1)[0]
        res = solve_and_extract(h, OUT_DIR, server_dir)
        hfss = {"dry_run": False, "build": build_info,
                "session": session_info, "guard": guard, **res}
        (OUT_DIR / "hfss_results.json").write_text(
            json.dumps(hfss, default=_json_default, ensure_ascii=False, indent=1),
            encoding="utf-8")
        remote_profile = f"{server_dir}\\profile.txt"
        with contextlib.suppress(Exception):
            fetch_remote_file(args.machine, remote_profile,
                              OUT_DIR / "profile.txt")
        hfss["convergence"] = convergence_from_messages(
            h, "j4c_floquet", "j4c_floquet_unitcell")
        (OUT_DIR / "hfss_results.json").write_text(
            json.dumps(hfss, default=_json_default, ensure_ascii=False, indent=1),
            encoding="utf-8")
        _export_s1p(OUT_DIR / "s_ff.s1p", hfss["s_ff"])
        oe = load_oe_reference()
        v = judge(hfss, oe)
        envelope = {"ok": True, "dry_run": False, "judge": v,
                    "oe": {k: w for k, w in oe.items()
                           if k not in ("band_freq_ghz", "band_abs_mean")}}
        (OUT_DIR / "verdict.json").write_text(
            json.dumps(envelope, default=_json_default, ensure_ascii=False, indent=1),
            encoding="utf-8")
        write_verdict_md(v, OUT_DIR / "verdict.md")
        print(f"[verdict] {v['verdict']}  Δ|Γ|={v['d_gamma']:.4f} "
              f"checks={v['checks'] or '无'}", flush=True)
        return 0
    except Exception as exc:  # — 执行失败如实落 verdict envelope
        (OUT_DIR / "verdict.json").write_text(json.dumps({"ok": False, "dry_run": False, "error": f"{type(exc).__name__}: "
             f"{exc}", "guard": guard, "session": session_info},
            default=_json_default, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[FAIL] {type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        if desktop is not None:
            # 迭代期不关实例（失败重跑省 3-4min 冷启动）；收口由下方指纹
            # 清理承担（:50053: 精确杀 + 任务删 + 席目录清空）
            with contextlib.suppress(Exception):
                desktop.release_desktop(close_projects=False,
                                        close_on_exit=False)
        task_name = (launched.get("task_name")
                     or (launched.get("steps") or {}).get("schtasks", {})
                     .get("task_name"))
        if not args.keep_server:
            cl = win.cleanup_remote_grpcsrv(args.machine, args.port,
                                            task_name=task_name)
            print(f"[cleanup] killed={cl.get('killed_pids')} "
                  f"ok={cl.get('ok')}", flush=True)
            # --launch-only 的任务名随该进程丢失：按本席端口段前缀补删
            # （RFAuto\hfss_window_<port>_*，只碰本席段，§1.4 G20 同源）
            if getattr(args, "attach_existing", None):
                with contextlib.suppress(Exception):
                    sweep = _sweep_leftover_tasks(args.machine, args.port)
                    print(f"[cleanup] task_sweep={sweep}", flush=True)


def _sweep_leftover_tasks(machine: str, port: int) -> dict[str, Any]:
    """按本席端口段前缀补删残留 schtasks（RFAuto 命名空间 hfss_window_<port>_ 前缀）。"""
    from rfauto.infra.remote_machines import (
        SshTransport,
        load_remote_machines,
        resolve_machine,
    )

    cfg = resolve_machine(machine, load_remote_machines())
    t = SshTransport(cfg)
    t.connect()
    deleted: list[str] = []
    try:
        prefix = f"RFAuto\\hfss_window_{port}_"
        _rc, out, _err = t.run_command(
            "schtasks /query /fo csv /nh 2>$null | "
            "Select-String -SimpleMatch 'hfss_window_" + str(port) + "_' | "
            "ForEach-Object { $_.Line }", timeout_s=30.0)
        for line in (out or "").splitlines():
            name = line.strip().strip('"').split('","')[0].lstrip('"')
            if name.startswith(prefix.replace("\\", "\\")):
                with contextlib.suppress(Exception):
                    t.run_command(f'schtasks /delete /f /tn "{name}"',
                                  timeout_s=20.0)
                    deleted.append(name)
        return {"deleted": deleted}
    except Exception as exc:  # 运维面 best-effort
        return {"deleted": deleted, "error": str(exc)[:120]}
    finally:
        with contextlib.suppress(Exception):
            t.close()


def _export_s1p(path: Path, srec: dict[str, Any]) -> None:
    """主判 S_ff 落 .s1p（50Ω 基，dB/deg，RFIX=50）。"""
    fg = np.asarray(srec["freq_ghz"], dtype=float)
    s = np.asarray(srec["re"]) + 1j * np.asarray(srec["im"])
    mag_db = 20.0 * np.log10(np.maximum(np.abs(s), 1e-300))
    ang = np.degrees(np.angle(s))
    lines = ["! DP-4 J4c HFSS Floquet unit cell, S(FEED!1,FEED!1), 50 ohm",
             "# HZ S RI R 50"]
    for f, re_v, im_v, db, ph in zip(fg, s.real, s.imag, mag_db, ang,
                 strict=False):
        lines.append(f"{f * 1e9:.6e} {re_v:.10e} {im_v:.10e} "
                     f"! {db:.4f}dB {ph:.3f}deg")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
