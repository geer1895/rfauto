"""ME-5 MMT 销钉/谐振窗 HFSS 仲裁锚（T14）——sim_host 远程发射驱动。

判据预声明：runs/mmt_anchor_20260930/criteria.md（先写后跑，#122）。
三设计（WR-90，Driven Modal，模态基 renormalize=False）：ma_straight
（直段 40mm 互洽锚）/ ma_post（居中感性销钉 r=1.0mm@10GHz）/ ma_window
（零厚谐振窗孔 13.916189×3.0mm，f_res_est=10.000GHz）。

链路（docs/audit/server_invocation_playbook.md 全条适用）：探活 →
50050-50060 全闭预检（G12 绑定回退盲区防御，fail-closed）→ 服务器侧
工作目录清理（#368 同源）→ schtasks 拉起 ansysedt -ng -grpcsrv
:host:50051:InsecureMode -Logfile（G7/G8/G10）→ 本机 pyaedt 四开关
attach + remote_rpc_session=None（G9）→ 三设计串行建模/ΔS 阶梯/
离散扫频/Touchstone 导出（服务器侧路径，DoRenorm=False 模态基，直调
osolution 绕过 export_touchstone 本地存在性检查的远程假阴性）→
sftp 回拉 → finally release + remote_hfss_cleanup（:50051: 指纹精确杀
+删 schtasks，不代杀）→ hfss_run.json 落档。

真机 opt-in：RFAUTO_REMOTE_SMOKE=1（unit 门内一律拒绝）。
运行（分离进程 #157/#242）：见 runs/mmt_anchor_20260930/launch.ps1。
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "runs" / "mmt_anchor_20260930"
HFSS_OUT = WORK / "hfss"
LOGS = WORK / "logs"
OUT_JSON = WORK / "hfss_run.json"

MACHINE = "sim_host"
# gRPC 端口可经 env 覆盖（共享机并发批挪口——playbook §3.3 per-port 定案；
# 2026-09-30 02:47 实测：floquet_j4c 批占 50051 期间本批挪 50065，零互扰）
GRPC_PORT = int(os.environ.get("MMT_ANCHOR_GRPC_PORT", "50051"))
SERVER_DIR_WIN = "E:\\rfauto_remote\\mmt_anchor"
SERVER_DIR_SFTP = "E:/rfauto_remote/mmt_anchor"
VERSION = "2025.1"

A_MM, B_MM = 22.86, 10.16
L_HALF_MM = 20.0
WALL_MM = 0.5
POST_R_MM = 1.0
WIN_W_MM = 13.916189
WIN_H_MM = 3.0

F_LO, F_HI, N_PTS = 8.0, 12.0, 201
F_SOL = 10.0
LEVELS = ((0.02, 12), (0.01, 18), (0.005, 24))  # (MaxDeltaS, MaximumPasses)
DESIGNS = ("ma_straight", "ma_post", "ma_window")
SOLVE_TIMEOUT_S = float(os.environ.get("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "1800"))


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── 几何（dp1p3 纪律：Wall pec 壳+Air vacuum 零边界赋值；#310 bbox 自审）────

def _ensure_pec_material(h) -> str:
    """项目内建 PEC 等效导体材料并返回名（服务器会话系统材质库未加载，
    实测 material_keys 仅 vacuum 1 键——material="pec" 会被 pyaedt
    _check_material 静默回退 vacuum（2026-09-30 01:52 mat_diag 实证）。
    add_material 项目库路径=L2 冒烟同款（ro4350b 实证可用）。铜 σ=5.8e7
    S/m 在 X 帶 40mm 段壁损耗 ~0.001dB，对本判据门（0.5dB/7%/3%）物理
    等效 PEC。"""
    have = {k.lower() for k in h.materials.material_keys}
    if "rfauto_pec" not in have:
        # pyaedt 1.4 add_material 无 conductivity kwarg——L2 同款：建后属性赋值
        m = h.materials.add_material("rfauto_pec")
        m.conductivity = 5.8e7
    return "rfauto_pec"


def _build_geometry(h, kind: str) -> dict:
    mat = _ensure_pec_material(h)
    m = h.modeler
    m.model_units = "mm"
    frame_sheet: str | None = None
    m.create_box(
        origin=[-WALL_MM, -WALL_MM, -L_HALF_MM - WALL_MM],
        sizes=[A_MM + 2 * WALL_MM, B_MM + 2 * WALL_MM,
               2 * L_HALF_MM + 2 * WALL_MM],
        name="Wall", material=mat)
    m.create_box(origin=[0.0, 0.0, -L_HALF_MM],
                 sizes=[A_MM, B_MM, 2 * L_HALF_MM],
                 name="Air", material="vacuum")
    m.subtract("Wall", ["Air"])
    h.modeler["Air"].solve_inside = True
    if kind == "ma_post":
        m.create_cylinder(orientation="Y",
                          origin=[A_MM / 2.0, 0.0, 0.0],
                          radius=POST_R_MM, height=B_MM,
                          name="post", material=mat)
        m.subtract("Air", ["post"])
    elif kind == "ma_window":
        m.create_rectangle(orientation="XY",
                           origin=[0.0, 0.0, 0.0],
                           sizes=[A_MM, B_MM], name="win_frame")
        m.create_rectangle(
            orientation="XY",
            origin=[(A_MM - WIN_W_MM) / 2.0, (B_MM - WIN_H_MM) / 2.0, 0.0],
            sizes=[WIN_W_MM, WIN_H_MM], name="win_ap")
        m.subtract("win_frame", ["win_ap"])
        # pyaedt subtract 后对象缓存可能失名（2026-09-30 02:23 实测
        # KeyError，而 AEDT 侧名字仍在——PerfectE 已按 win_frame 建成）
        with contextlib.suppress(Exception):
            m.refresh_all_ids()
        frame = next((n for n in m.object_names
                      if n.startswith("win_frame")), None)
        if frame is None:
            raise RuntimeError("win_frame 减孔后不可寻（refresh 后仍缺）")
        h.assign_perfecte_to_sheets([frame], name="WindowPEC")
        frame_sheet = frame
    # 端口：Air 端面全截面（#285 面心模型单位过滤+非空守卫）。ma_post 的
    # Air 被销钉减出圆柱孔面——非平面面 get_face_center 返回 False（02:23
    # 实测 'bool' object is not iterable），必须跳过非平面面。
    faces = m.get_object_faces("Air")
    port_faces: dict[float, int] = {}
    for f in faces:
        c = m.get_face_center(f)
        if not c or not isinstance(c, (list, tuple)):
            continue  # 非平面面（圆柱孔）无面心——非端口面
        _cx, _cy, cz = (float(v) for v in c)
        if abs(cz + L_HALF_MM) < 1e-6:
            port_faces[-L_HALF_MM] = f
        elif abs(cz - L_HALF_MM) < 1e-6:
            port_faces[L_HALF_MM] = f
    if set(port_faces) != {-L_HALF_MM, L_HALF_MM}:
        raise RuntimeError(f"端面过滤为空/不全（#285 非空守卫）: {port_faces}")
    for name, z_mm in (("P1", -L_HALF_MM), ("P2", L_HALF_MM)):
        h.wave_port(
            assignment=port_faces[z_mm], name=name, modes=1,
            renormalize=False,
            integration_line=[[A_MM / 2.0, 0.0, z_mm],
                              [A_MM / 2.0, B_MM, z_mm]])
    h.create_setup(name="Setup")
    setup = h.get_setup("Setup")
    setup.props["Frequency"] = f"{F_SOL}GHz"
    setup.props["MaxDeltaS"] = LEVELS[0][0]
    setup.props["MaximumPasses"] = LEVELS[0][1]
    setup.update()
    return {"conductor_material": mat, "frame_sheet": frame_sheet}


def _bbox_audit(h, kind: str, mat: str, frame_sheet: str | None = None) -> dict:
    names = ["Wall", "Air"]
    if kind == "ma_post":
        names.append("post")
    if kind == "ma_window":
        names.append(frame_sheet or "win_frame")
    audit = {nm: [float(v) for v in h.modeler[nm].bounding_box]
             for nm in names}
    # 材质回读审计（服务器材质库未加载→vacuum 回退事故的回归守卫）
    audit["material_audit"] = {nm: h.modeler[nm].material_name
                               for nm in names}
    expect_mat = {"Wall": mat, "Air": "vacuum"}
    if kind == "ma_post":
        expect_mat["post"] = mat
    audit["material_expect"] = expect_mat
    # 薄片（win_frame）无体材质（导电性来自 PerfectE 边界）——只对
    # expect_mat 内的实体强制材质回读（02:40 实测 KeyError 根因）
    bad = {k: v for k, v in audit["material_audit"].items()
           if k in expect_mat
           and (v or "").lower() != expect_mat[k].lower()}
    if bad:
        raise RuntimeError(f"材质回读失配（vacuum 回退守卫）: {bad}")
    audit["expect"] = {"Air": [0.0, 0.0, -L_HALF_MM, A_MM, B_MM, L_HALF_MM]}
    if kind == "ma_post":
        audit["expect"]["post"] = [A_MM / 2.0 - POST_R_MM, 0.0, -POST_R_MM,
                                   A_MM / 2.0 + POST_R_MM, B_MM, POST_R_MM]
    if kind == "ma_window":
        fs = frame_sheet or "win_frame"
        audit["expect"][fs] = [0.0, 0.0, 0.0, A_MM, B_MM, 0.0]
        audit["aperture_origin_mm"] = [(A_MM - WIN_W_MM) / 2.0,
                                       (B_MM - WIN_H_MM) / 2.0]
    audit["objects"] = sorted(h.modeler.object_names)
    return audit


def _solve_ladder(h, kind: str) -> list[dict]:
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.desktop_guard import run_with_watchdog

    levels: list[dict] = []
    for ds, mp in LEVELS:
        setup = h.get_setup("Setup")
        setup.props["Frequency"] = f"{F_SOL}GHz"
        setup.props["MaxDeltaS"] = ds
        setup.props["MaximumPasses"] = mp
        setup.update()
        run_with_watchdog(lambda: h.analyze(setup="Setup"),
                          timeout_s=SOLVE_TIMEOUT_S,
                          what=f"{kind} dS={ds}")
        passes, delta_s = HfssAdapter._extract_convergence(setup)
        # passes==0 = profile 解析失败回退 (0, 0.0)——按未收敛处理（不凑
        # trusted；2026-09-30 首跑实测 ERROR 行+passes=0 形态的教训）
        levels.append({"max_delta_s": ds, "max_passes": mp, "passes": passes,
                       "delta_s_final": (float(delta_s)
                                         if delta_s is not None else None),
                       "converged": bool(delta_s is not None and delta_s <= ds
                                         and (passes or 0) > 0),
                       "hit_max_passes": bool(passes and mp
                                              and passes >= mp)})
        log(f"{kind} dS={ds}: passes={passes} delta_s={delta_s}")
    return levels


def _sweep_and_export(h, kind: str, s2p_server_win: str) -> dict:
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.desktop_guard import run_with_watchdog

    h.create_linear_count_sweep(
        setup="Setup", unit="GHz", start_frequency=F_LO,
        stop_frequency=F_HI, num_of_freq_points=N_PTS, name="Sweep",
        sweep_type="Discrete", save_fields=False)
    run_with_watchdog(lambda: h.analyze(setup="Setup"),
                      timeout_s=SOLVE_TIMEOUT_S,
                      what=f"{kind} sweep 8-12/{N_PTS}")
    adapter = HfssAdapter()
    adapter.session.hfss = h
    # 断言+导出重试（03:33 实测：sweep 3m8s solved correctly 后 profile
    # 读取瞬时失败——重试容取数延迟，不放松断言本体；profile 报引擎
    # 错误/未完成仍拒绝）
    last_exc: Exception | None = None
    for wait_s in (0.0, 30.0, 60.0):
        if wait_s:
            time.sleep(wait_s)
            log(f"{kind} profile 重取（第 {wait_s:.0f}s 后）")
        try:
            adapter.assert_sweep_completed("Setup", "Sweep")
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            log(f"{kind} assert 失败: {type(exc).__name__}: "
                f"{str(exc)[:120]}")
    if last_exc is not None:
        raise last_exc
    # 模态基导出（DoRenorm=False；服务器侧 osolution 的 OutFile 路径按
    # 服务器文件系统解释——dp1p3/L2 双先例；直调绕过 export_touchstone
    # 的本地 path.exists() 检查，远程下该检查恒假阴性）。
    osolution = h.osolution
    if osolution is None:
        raise RuntimeError("hfss.osolution 不可用")
    osolution.ExportNetworkData(
        "", ["Setup:Sweep"], 3, s2p_server_win.replace("\\", "/"),
        ["all"], False, 50, "S", -1, 0, 15, False, False, False)
    h.save_project()  # 扫频解落盘（harvest/复判依赖，dp1p3 §4.4）
    log(f"{kind} touchstone 导出（服务器侧）: {s2p_server_win}")
    return {"touchstone_server": s2p_server_win, "sweep_type": "Discrete",
            "n_points": N_PTS, "basis": "modal (renormalize=False)",
            "assert_sweep_completed": True}


def _build_design(cfg, kind: str, s2p_local: Path, transport,
                  t0: float) -> dict:
    """单设计（**单次尝试，无设计内重试**——2026-09-30 02:07 实测：设计内
    重试的异常路径会释放共享 Desktop，下一次 Hfss() 走 new-desktop 分支
    在**本机**拉起新 ansysedt（端口漂移 50070/58210）。失败如实落档，
    判读侧按缺设计 UNKNOWN 处理；整批重跑=重挂 launch.ps1。
    machine/port 显式传参=L2 冒烟同款（Desktop attach 后同 gRPC 会话建
    项目，remote_service 实证形态）。
    """
    from ansys.aedt.core import Hfss

    proj = f"{SERVER_DIR_WIN}\\{kind}.aedt"
    s2p_server = f"{SERVER_DIR_WIN}\\{kind}.s2p"
    result: dict = {"design": kind}
    try:
        log(f"{kind} 构建")
        hfss = Hfss(project=proj, design=kind,
                    solution_type="DrivenModal", version=VERSION,
                    non_graphical=True, machine=cfg.host,
                    port=cfg.hfss_grpc_port)
        result["geometry"] = _build_geometry(hfss, kind)
        result["bbox_audit"] = _bbox_audit(
            hfss, kind, "rfauto_pec",
            result["geometry"].get("frame_sheet"))
        result["levels"] = _solve_ladder(hfss, kind)
        result["sweep"] = _sweep_and_export(hfss, kind, s2p_server)
        last = result["levels"][-1]
        result["trusted"] = bool(last["converged"]
                                 and not last["hit_max_passes"])
        result["wall_clock_min"] = round((time.time() - t0) / 60.0, 1)
        with contextlib.suppress(Exception):
            hfss.save_project()
        transport.download_file(f"{SERVER_DIR_SFTP}/{kind}.s2p", s2p_local)
        result["touchstone_local"] = str(s2p_local)
        result["touchstone_local_bytes"] = s2p_local.stat().st_size
        log(f"{kind} 完成 wall={result['wall_clock_min']}min，"
            f"回拉 {s2p_local.stat().st_size}B")
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        result["wall_clock_min"] = round((time.time() - t0) / 60.0, 1)
        log(f"{kind} 失败: {result['error']}")
        return result


def _local_ansysedt_count() -> int:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process ansysedt -ErrorAction SilentlyContinue "
             "| Measure-Object).Count"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        return int(out or "0")
    except Exception:
        return -1


def main() -> int:
    if os.environ.get("RFAUTO_REMOTE_SMOKE") != "1":
        print("FAIL: 真机发射需 RFAUTO_REMOTE_SMOKE=1", flush=True)
        return 2
    from rfauto.infra.remote_machines import (
        SshTransport,
        probe_machine,
        probe_port,
        resolve_machine,
    )
    from rfauto.service.remote_service import (
        REMOTE_SMOKE_ENV,
        _launch_grpcsrv,
        remote_hfss_cleanup,
    )

    assert REMOTE_SMOKE_ENV == "RFAUTO_REMOTE_SMOKE"
    HFSS_OUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    # 信封保全：被跳过设计的阶梯记录在旧信封里——覆盖前落 prev（03:17
    # 实测：HALT/FAIL 多轮覆写致 ma_post 阶梯记录丢失的根治）
    if OUT_JSON.exists():
        with contextlib.suppress(Exception):
            OUT_JSON.rename(
                WORK / f"hfss_run_prev_{time.strftime('%H%M%S')}.json")

    envelope: dict = {"machine": MACHINE, "version": VERSION,
                      "criteria": "runs/mmt_anchor_20260930/criteria.md",
                      "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    cfg = resolve_machine(MACHINE)
    if GRPC_PORT != 50051:
        cfg.hfss_grpc_port = GRPC_PORT  # 挪口（仅本进程 cfg 副本语义）
    envelope["local_ansysedt_count_pre"] = _local_ansysedt_count()
    transport = SshTransport(cfg)
    transport.connect()  # L2 同款：显式连接（run_command 前置条件）
    steps: dict = {}
    envelope["steps"] = steps
    desktop = None
    task_name: str | None = None
    try:
        steps["probe"] = probe_machine(cfg)
        # 端口扫描（G12 感知）：本批端口被占=HALT；他批占用的其他端口只
        # 记录不阻断（per-port 挪口模式，50051 被占与本批 50065 无涉——
        # 02:53 实测 floquet_j4c 占 50051 时误 HALT 的修正）
        occupied = []
        for p in range(50050, max(50061, GRPC_PORT + 2)):
            ok, _lat = probe_port(cfg.host, p, timeout_s=1.5)
            if ok:
                occupied.append(p)
        mine_blocked = GRPC_PORT in occupied
        steps["port_scan_50050_50060"] = {
            "occupied": occupied, "scan_hi": max(50060, GRPC_PORT + 1),
            "my_port": GRPC_PORT, "my_port_blocked": mine_blocked}
        if mine_blocked:
            envelope.update(ok=False, verdict="HALT",
                            reason=(f"本批 gRPC 端口 {GRPC_PORT} 已被占用"
                                    f"（在占端口 {occupied}）——他人实例"
                                    "不 attach 不代杀（G12 fail-closed），"
                                    "人工核对后重试"))
            return 3
        # 服务器侧工作目录：建（必须成功）+清陈旧（best-effort——活进程
        # 锁住的 console log 不阻断；03:05 实测 Remove-Item rc 非零假因）
        rc, _out, err = transport.run_command(
            f"New-Item -ItemType Directory -Force -Path '{SERVER_DIR_WIN}' "
            f"| Out-Null",
            timeout_s=20.0)
        transport.run_command(
            f"Remove-Item '{SERVER_DIR_WIN}\\*' -Force -Recurse "
            f"-ErrorAction SilentlyContinue",
            timeout_s=30.0)
        if rc != 0:
            envelope.update(ok=False, verdict="FAIL",
                            reason=f"服务器侧工作目录创建失败: {err[:120]}")
            return 3
        console_log = f"{SERVER_DIR_WIN}\\aedt_console.log"
        failure = _launch_grpcsrv(
            cfg, transport, steps, 120.0,
            extra_cli_args=f'-ng -Logfile "{console_log}"')
        if failure is not None:
            # G12 挪口发现（2026-09-30 02:57 实测定案）：ansysedt 未必绑
            # 请求口（50065 请求→实听 50052，console log 公告实际口）——
            # 实际口以 aedt_console.log 的 "GRPC server running on port:"
            # 为准，探活通过即以实际口继续（fail-closed 不放松：探不过
            # 才 FAIL）。
            _rc, tail, _e = transport.run_command(
                "powershell -NoProfile -Command \"Get-Content "
                f"'{console_log}' -Tail 25\"", timeout_s=30.0)
            m = re.search(r"GRPC server running on port:\s*(\d+)", tail)
            actual = int(m.group(1)) if m else None
            if actual and actual != GRPC_PORT:
                ok, _lat = probe_port(cfg.host, actual, timeout_s=2.0)
                if ok:
                    cfg.hfss_grpc_port = actual
                    steps["g12_port_discovery"] = {
                        "requested": GRPC_PORT, "actual": actual}
                    envelope["grpc_port_actual"] = actual
                    failure = None
                    log(f"G12 挪口发现: 请求 {GRPC_PORT} → 实听 {actual}")
        if failure is not None:
            envelope.update(ok=False, verdict="FAIL",
                            reason=failure.get("reason", "launch 失败"))
            return 3
        task_name = steps["schtasks"]["task_name"]
        envelope["grpc_task"] = task_name

        # attach（四开关共享单源；attach 后 remote_rpc_session=None，G9）
        from ansys.aedt.core import Desktop
        from ansys.aedt.core.generic.settings import settings

        from rfauto.adapters.hfss_session import remote_session_switches

        t_start = time.time()
        designs: dict[str, dict] = {}
        with remote_session_switches():
            desktop = Desktop(version=cfg.hfss_version, non_graphical=True,
                              new_desktop=False, machine=cfg.host,
                              port=cfg.hfss_grpc_port)
            steps["attach"] = {"version": str(desktop.current_version)}
            settings.remote_rpc_session = None
            for kind in DESIGNS:
                s2p_local = HFSS_OUT / f"{kind}.s2p"
                if s2p_local.exists() and s2p_local.stat().st_size > 10240:
                    # 断点续跑：已完成设计（s2p 已回拉且 >10KB）跳过重建
                    log(f"{kind} 已有产物（{s2p_local.stat().st_size}B），"
                        "跳过")
                    designs[kind] = {
                        "design": kind, "skipped_done": True,
                        "touchstone_local": str(s2p_local),
                        "touchstone_local_bytes": s2p_local.stat().st_size}
                    continue
                designs[kind] = _build_design(
                    cfg, kind, s2p_local, transport, time.time())
        envelope["designs"] = designs
        envelope["wall_total_min"] = round((time.time() - t_start) / 60.0, 1)
        got = [k for k, v in designs.items() if v.get("touchstone_local")]
        envelope["ok"] = bool(got)
        envelope["verdict"] = ("LAUNCHED" if len(got) == len(DESIGNS)
                               else ("PARTIAL" if got else "SOLVE_FAILED"))
        return 0
    except Exception as exc:
        envelope["ok"] = False
        envelope["verdict"] = "FAIL"
        envelope["reason"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return 3
    finally:
        if desktop is not None:
            with contextlib.suppress(Exception):
                desktop.release_desktop(close_on_exit=True,
                                        close_projects=False)
        # 服务器侧清理：指纹精确杀（:50051:）+ 删 schtasks 任务（不代杀）
        with contextlib.suppress(Exception):
            envelope["cleanup"] = remote_hfss_cleanup(
                machine=MACHINE, task_name=task_name,
                grpc_match=f":{GRPC_PORT}:")
        # 复扫 50051 应闭合
        with contextlib.suppress(Exception):
            from rfauto.infra.remote_machines import probe_port
            ok, _lat = probe_port(cfg.host, GRPC_PORT, timeout_s=2.0)
            envelope["port_50051_after_cleanup"] = {"open": bool(ok)}
        # 本机 ansysedt 计数核验（远程批应恒 0；>0 如实上报不代杀）
        envelope["local_ansysedt_count_post"] = _local_ansysedt_count()
        envelope["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        OUT_JSON.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2),
            encoding="utf-8")
        log(f"hfss_run.json 落档 verdict={envelope.get('verdict')} "
            f"wall_total={envelope.get('wall_total_min')}min")


if __name__ == "__main__":
    raise SystemExit(main())
