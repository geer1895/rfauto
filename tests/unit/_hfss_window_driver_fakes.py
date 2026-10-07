"""hfss_window_driver 测试共享 fakes/patch 面——自 test_hfss_window_driver.py 抽出（I-04，W6-E，2026-10-06）。

纯搬运重构（ra_criteria SPECS §五 I-04）：_Fake 三件/_mmf/_FakeProc/
三 _patch_* mock 面 + 共享 fixture 助手（_gate/_synth_wilkinson_like/
_arr_rects_single_source/_setup_h/_stepped_s21/_coupled_censored_sparams_csv）
+ 驱动模块单例（_load/mod）与 FREQ 合成频轴，逐字节 verbatim 搬入，
类名/函数名/断言/文案零改动，零行为变化（判据=collect 恒等+全文件绿）。
tests/unit 包内导入惯例（_dataset_service_helpers 同款）；本文件名下划线
前缀=pytest 不收集。

_FakeHfss 契约镜像 docstring 块随迁不丢（SPECS §5.2 判据④）。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "hfss_window_arbitration.py"


def _load():
    spec = importlib.util.spec_from_file_location("hfss_window_arbitration", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


FREQ = np.linspace(2.0e9, 3.0e9, 401)


def _synth_wilkinson_like() -> np.ndarray:
    fg = FREQ / 1e9
    f0 = 2.2075
    s = np.zeros((len(FREQ), 3, 3), dtype=complex)
    base = 10.0 ** (-0.5 / 20.0)
    dip = 10.0 ** (-32.12 / 20.0)
    s[:, 0, 0] = base - (base - dip) * np.exp(-((fg - f0) / 0.05) ** 2)
    s[:, 1, 0] = 10.0 ** (-3.30 / 20.0)
    s[:, 2, 0] = 10.0 ** (-3.34 / 20.0)
    s[:, 1, 2] = 10.0 ** (-19.4 / 20.0)
    return s


def _gate(metric="f_match_ghz", gate=3.0, kind="rel_pct", key=True, x_ref=None):
    return {"metric": metric, "gate": gate, "gate_kind": kind, "key": key,
            "x_ref": x_ref}


def _arr_rects_single_source(template):
    from rfauto.adapters.openems_templates import _arr_layout

    ctx = mod.seat_context(template)
    lay = mod.seat_layout(template, ctx)
    arr = _arr_layout(template, dict(ctx["nominal_params"]))
    src = {name: (x0, y0, x1, y1)
           for _prop, name, x0, y0, _z0, x1, y1, _z1 in arr["boxes"]}
    return ctx, lay, src


# ═══════════════ builder 可执行面（_FakeHfss 契约镜像，零真机）══════════════
# bbox 轴向映射=pyaedt 实码口径（marchand 锚 #310④）：XY sizes=(x,y)、
# YZ=(y,z)、XZ=(z,x)（sizes 直通不重排）；unite 保首名+并集 bbox（#310）；
# 面心=模型单位 mm（#285）。经 pytest.importorskip 钉住（驱动内 Gravity 惰性
# 导入依赖 pyaedt 常量模块，离线可装可跑）。

class _FakeObject:
    def __init__(self, bbox):
        self.bounding_box = bbox
        self.solve_inside = None


def _mmf(v):
    return float(str(v).strip().removesuffix("mm"))


class _FakeModeler:
    def __init__(self):
        self._units = None
        self.objects: dict = {}
        self.rect_bboxes: dict = {}      # 逐薄片创建时 bbox 记录（unite 后仍在）
        self._face_centers: dict = {}
        self._next_fid = 1
        self.unite_calls: list = []
        self.subtract_calls: list = []
        self.wave_ports: list = []
        self.lumped_rlc: list = []
        self.lumped_ports: list = []
        self.pec_assignments: list = []
        self.radiation_assignments: list = []

    @property
    def model_units(self):
        return self._units

    @model_units.setter
    def model_units(self, v):
        self._units = v

    def _reg(self, name, bbox):
        self.objects[name] = _FakeObject(bbox)

    def create_box(self, origin, sizes, name, material=None):
        x, y, z = (_mmf(v) for v in origin)
        dx, dy, dz = (_mmf(v) for v in sizes)
        self._reg(name, [x, y, z, x + dx, y + dy, z + dz])
        return name

    def create_rectangle(self, orientation, origin, sizes, name):
        x, y, z = (_mmf(v) for v in origin)
        if orientation == "XY":
            dx, dy = (_mmf(v) for v in sizes)
            bbox = [x, y, z, x + dx, y + dy, z]
        elif orientation == "YZ":
            sy, sz = (_mmf(v) for v in sizes)
            bbox = [x, y, z, x, y + sy, z + sz]
        elif orientation == "XZ":
            sz_, sx = (_mmf(v) for v in sizes)
            bbox = [x, y, z, x + sx, y, z + sz_]
        else:
            raise AssertionError(orientation)
        self._reg(name, bbox)
        self.rect_bboxes[name] = bbox
        return name

    def __getitem__(self, name):
        return self.objects[name]

    @property
    def object_names(self):
        return list(self.objects)

    def unite(self, names):
        self.unite_calls.append(list(names))
        keep = names[0]
        bs = [self.objects[n].bounding_box for n in names
              if n in self.objects]
        union = ([min(b[i] for b in bs) for i in range(3)]
                 + [max(b[i] for b in bs) for i in range(3, 6)])
        self.objects[keep] = _FakeObject(union)
        for n in names[1:]:
            self.objects.pop(n, None)

    def subtract(self, a, tools, keep_originals=False):
        self.subtract_calls.append((a, list(tools), keep_originals))

    def get_object_faces(self, name):
        if name not in self.objects:
            return []
        b = self.objects[name].bounding_box
        cx, cy, cz = (0.5 * (b[0] + b[3]), 0.5 * (b[1] + b[4]),
                      0.5 * (b[2] + b[5]))
        ids = []
        for c in ((b[0], cy, cz), (b[3], cy, cz), (cx, b[1], cz),
                  (cx, b[4], cz), (cx, cy, b[2]), (cx, cy, b[5])):
            self._face_centers[self._next_fid] = c
            ids.append(self._next_fid)
            self._next_fid += 1
        return ids

    def get_face_center(self, fid):
        return self._face_centers[fid]


class _FakeHfss:
    def __init__(self):
        self.modeler = _FakeModeler()
        self.material_names: list = []

    @property
    def materials(self):
        return self

    def add_material(self, name, properties=None):
        self.material_names.append(name)
        return name

    def assign_perfecte_to_sheets(self, assignment, name):
        self.modeler.pec_assignments.append((list(assignment), name))

    def wave_port(self, **kw):
        self.modeler.wave_ports.append(kw)

    def assign_lumped_rlc_to_sheet(self, **kw):
        self.modeler.lumped_rlc.append(kw)

    def lumped_port(self, **kw):
        self.modeler.lumped_ports.append(kw)

    def assign_radiation_boundary_to_faces(self, assignment, name):
        self.modeler.radiation_assignments.append((list(assignment), name))
        return name


def _setup_h(setup):
    class _H:
        def get_setup(self, name):
            return setup
    return _H()


def _patch_remote_pipeline(monkeypatch, conv_seq, sink):
    """wilkinson 真机 mock 面（零 pyaedt 零网络）：open→build→solve→export
    全替身，read_touchstone 喂合成 S，convergence_record 按序脚本化。
    sink = (captured_verdicts: list, out_dir: Path)。"""
    captured, out_dir = sink
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)

    class _Dummy:
        def release_desktop(self, **kw):
            pass

    monkeypatch.setattr(mod, "open_local_hfss", lambda seat, p: _Dummy())
    monkeypatch.setattr(mod, "build_seat",
                        lambda h, name, ctx: {"notes": [], "ports": []})
    monkeypatch.setattr(mod, "make_setup_and_sweep", lambda h, s, lv: None)
    monkeypatch.setattr(mod, "solve_with_watchdog",
                        lambda h, setup: {"solve_s": 1.0})
    monkeypatch.setattr(mod, "export_touchstone", lambda h, p, n: p)
    monkeypatch.setattr(mod, "read_touchstone",
                        lambda p, reject_synthetic=False:
                        (FREQ, _synth_wilkinson_like()))
    monkeypatch.setattr(mod, "convergence_record",
                        lambda h: conv_seq.pop(0) if len(conv_seq) > 1
                        else conv_seq[0])
    captured.append(mod.run_seat("wilkinson", machine="local",
                                 out_dir=out_dir, dry_run=False))


def _patch_remote_session(monkeypatch, calls, bootstrap_ok=True):
    """P1-1 mock 面：远程探活/配置替身+Desktop/Hfss 构造期开关快照。"""
    pytest.importorskip("ansys.aedt.core")
    import ansys.aedt.core as aedt
    from ansys.aedt.core.generic.settings import settings as aedt_settings

    import rfauto.service.remote_service as rs

    order: list = []
    calls["order"] = order
    calls["bootstrap"] = []

    class _FakeDesktop:
        def __init__(self, **kw):
            order.append("desktop")
            calls["desktop"] = {
                "kw": kw,
                "grpc_local": aedt_settings.grpc_local,
                "grpc_secure_mode": aedt_settings.grpc_secure_mode,
                "remote_rpc_session": aedt_settings.remote_rpc_session,
                "pre_grpc_args": os.environ.get("PYAEDT_USE_PRE_GRPC_ARGS"),
            }

        def release_desktop(self, **kw):
            pass

    class _FakeHfss:
        def __init__(self, **kw):
            order.append("hfss")
            calls["hfss"] = {"kw": kw,
                             "remote_rpc_session":
                                 aedt_settings.remote_rpc_session}

        def release_desktop(self, **kw):
            pass

    monkeypatch.setattr(rs, "remote_probe", lambda m: {
        "machines": [{"ports": {"ansys_license": {"open": True}}}]})
    monkeypatch.setattr(rs, "hfss_remote_session_config", lambda m: {
        "ok": True,
        "remote": {"remote_machine": m, "machine": "10.20.30.40",
                   "port": 50051, "project_root": "E:\\rfauto_remote",
                   "version": "2025.1"}})
    monkeypatch.setattr(aedt, "Desktop", _FakeDesktop)
    monkeypatch.setattr(aedt, "Hfss", _FakeHfss)

    def _bootstrap(machine, project_dir):
        order.append("bootstrap")
        calls["bootstrap"].append((machine, project_dir))
        return bootstrap_ok

    monkeypatch.setattr(mod, "ensure_remote_project_dir", _bootstrap)
    return aedt_settings


class _FakeProc:
    def __init__(self, rc=0):
        self.returncode = rc

    def wait(self):
        return self.returncode


def _patch_registry_transport(monkeypatch, sent: list, query_output: str = "",
                              cfg=None):
    """注册表+SSH 替身（launch/cleanup mock 面）：run_command 输出 query_output，
    upload_file 捕获 vbs 字节。返回 uploads 收集器。"""
    import types

    if cfg is None:
        cfg = types.SimpleNamespace(
            name="sim_host", host="10.20.30.40",
            hfss_ansysedt_exe="E:/ANSYSINC/ansysedt.exe",
            hfss_project_root="E:/rfauto_remote")
    uploads: list[tuple[str, bytes]] = []

    class _T:
        def __init__(self, c):
            pass

        def connect(self):
            pass

        def run_command(self, cmd, timeout_s=60.0):
            sent.append(cmd)
            return 0, query_output, ""

        def upload_file(self, local, remote):
            uploads.append((remote, Path(local).read_bytes()))
            return True

        def close(self):
            pass

    base = "rfauto.infra.remote_machines"
    monkeypatch.setattr(f"{base}.SshTransport", _T)
    monkeypatch.setattr(f"{base}.load_remote_machines",
                        lambda: {"sim_host": object()})
    monkeypatch.setattr(f"{base}.resolve_machine",
                        lambda name, table: cfg)
    return uploads


def _stepped_s21(fg: np.ndarray, segments: list[tuple[float, float, float]],
                 floor_db: float = -6.0) -> np.ndarray:
    """stepped 席形态合成：segments=[(f_lo, f_hi, level_db)]，段外=floor_db。"""
    s21 = np.full(len(fg), 10.0 ** (floor_db / 20.0))
    for lo, hi, lvl in segments:
        s21[(fg >= lo) & (fg <= hi)] = 10.0 ** (lvl / 20.0)
    return s21


def _coupled_censored_sparams_csv(path: Path) -> None:
    """coupled 带心 censored 形态合成 OE sparams.csv（9 列掩码载体 schema，
    S31 峰 −3dB 带自 2.388 触上窗沿 3.0——与归档 oe_nominal_wideband 同形态）。"""
    fg = np.linspace(1.8, 3.0, 401)
    s31 = np.where(fg >= 2.388, 10.0 ** (-9.16 / 20.0), 10.0 ** (-20.0 / 20.0))
    s21 = np.full(401, 10.0 ** (-0.45 / 20.0))
    s11 = np.full(401, 0.05)
    rows = ["freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,re_S23,im_S23"]
    for k in range(len(fg)):
        vals = (float(fg[k]) * 1e9, float(s11[k]), 0.0, float(s21[k]), 0.0,
                float(s31[k]), 0.0, 0.01, 0.0)
        rows.append(",".join(repr(v) for v in vals))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
