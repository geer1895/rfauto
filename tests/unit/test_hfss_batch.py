"""HFSS 一次性批处理求解（hfss_batch，one-shot batch）单测——全 fake 零真机。

覆盖四条主路径 + 缝面：
1. 成功：rc=0、命令行钉字面、产物扫描命中；
2. 超时击杀：watchdog 触发整树回收（fake kill 记 pid）、timed_out 如实；
3. 路径缺失：.aedt/.aedb 两态都不成立 → 结构化失败，零 Popen；
4. aedb 回退：目录形态直通 -BatchSolve（Ansys 团队确认口径）。

Touchstone 批后导出（-batchextract 第二段，2026-10-08 补路）：脚本烘焙/
命令行钉字面/成功按端口数改名/文件未生成/超时击杀/脚本写失败/session
预留位/求解接线四路径（成功·失败不推翻 ok·缺省 False 零变化·求解败不导出）
——subprocess 全程 monkeypatch 假进程/假 rc（零真机）。

导出分派（2026-10-08 W5 真机实证补测）：HFSS 3D Layout 设计无任何
Analysis 模块（GetModule 四名全 FAIL），脚本须探针 Solutions 模块失败
后回退 design 级 ExportNetworkData（pyaedt analysis.py 先例）——烘焙
脚本按字面 exec + fake oDesktop 假桌面零真机钉行为（模块路径/design 级
回退/名义兜底/FATAL 早退仍 QuitApplication/sweep 透传）。

烘焙守卫与注入面（W5 审查席移交 P1/P2）：占位符守卫收紧为 token 模式
正则（值内字面 ``<<`` 不误报/真残留仍拦/非 ASCII 名守卫保留）；字符串
值烘焙前转义（特殊字符名 compile 通过 + exec 值逐位保真）；两调用点
（export/solve）烘焙守卫 ValueError 结构化落账不逃逸（edb_solve 只捕
RuntimeError/OSError，裸 ValueError 直达即信封契约违例；导出失败不推翻
求解 ok，#105）。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

import rfauto.adapters.hfss_batch as hb
from rfauto.adapters.hfss_batch import (
    build_batch_command,
    build_batch_extract_command,
    build_batch_extract_script,
    collect_solve_artifacts,
    export_touchstone_after_solve,
    find_ansysedt_exe,
    normalize_project_path,
    read_logfile_tail,
    solve_project_batch,
)

_EXE = "E:\\fake\\AnsysEM\\ansysedt.exe"


# ─── 假进程 / 假发射器 ───────────────────────────────────────────────────────

class _FakeProc:
    """subprocess.Popen 假进程：立即返回 rc 或阻塞到 kill 事件。"""

    def __init__(self, rc: int = 0, release: threading.Event | None = None,
                 pid: int = 4242) -> None:
        self.pid = pid
        self._rc = rc
        self._release = release

    def wait(self, timeout: float | None = None) -> int:
        if self._release is not None:
            # 阻塞至 fake kill 置位（watchdog 超时击杀语义的真实时序）
            assert self._release.wait(timeout=30.0), "fake proc 等待击杀超时"
        return self._rc


class _PopenRecorder:
    """Popen 替身：记录命令行/kwargs，杜绝真机进程。"""

    def __init__(self, proc: _FakeProc) -> None:
        self.proc = proc
        self.calls: list[dict] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": list(cmd), **kwargs})
        return self.proc


@pytest.fixture()
def no_real_popen(monkeypatch):
    """兜底闸：未被替换的 Popen 一律炸（保证零真机）。"""

    def _boom(*_a, **_k):
        raise AssertionError("测试路径不得触达真实 subprocess.Popen")

    monkeypatch.setattr(hb.subprocess, "Popen", _boom)


def _patch_launch(monkeypatch, recorder: _PopenRecorder) -> None:
    monkeypatch.setattr(hb.subprocess, "Popen", recorder)


def _patch_exe(monkeypatch, exe: str = _EXE) -> None:
    monkeypatch.setattr(hb, "find_ansysedt_exe", lambda explicit=None: Path(exe))


def _aedt_project(tmp_path: Path, with_results: bool = True) -> Path:
    proj = tmp_path / "demo.aedt"
    proj.write_text("fake project", encoding="utf-8")
    if with_results:
        results = tmp_path / "demo.aedtresults"
        results.mkdir()
        (results / "demo.s2p").write_text("! touchstone", encoding="utf-8")
        (results / "solved.csv").write_text("a,b\n", encoding="utf-8")
        (results / "mesh.txt").write_text("not counted", encoding="utf-8")
    return proj


# ─── 路径归一 ────────────────────────────────────────────────────────────────

def test_normalize_project_path_forms(tmp_path):
    proj = _aedt_project(tmp_path, with_results=False)
    assert normalize_project_path(proj) == (proj, "aedt")
    aedb = tmp_path / "demo2.aedb"
    aedb.mkdir()
    assert normalize_project_path(aedb) == (aedb, "aedb")
    plain_dir = tmp_path / "not_a_database"
    plain_dir.mkdir()
    assert normalize_project_path(plain_dir) is None
    assert normalize_project_path(tmp_path / "ghost.aedt") is None


# ─── 命令行构造（官方形态钉字面）──────────────────────────────────────────────

def test_build_batch_command_minimal():
    cmd = build_batch_command(_EXE, "D:\\jobs\\demo.aedt")
    assert cmd == [_EXE, "-ng", "-BatchSolve", "D:\\jobs\\demo.aedt"]


def test_build_batch_command_design_setup_logfile():
    # 参数顺序纪律（真机实证 2026-10-08）：AEDT 2025 R1 拒收 -Logfile
    # 置于工程之后（requires a filename ... last parameter，rc=1）——
    # 工程路径恒为末位。
    cmd = build_batch_command(
        _EXE, "demo.aedt", design="HFSSDesign1", setup="Setup1",
        logfile="E:\\logs\\x.log")
    assert cmd == [_EXE, "-ng", "-BatchSolve", "-designs",
                   "HFSSDesign1:Setup1", "-Logfile",
                   "E:\\logs\\x.log", "demo.aedt"]


def test_build_batch_command_design_only():
    cmd = build_batch_command(_EXE, "demo.aedt", design="D1")
    assert cmd == [_EXE, "-ng", "-BatchSolve", "-designs", "D1", "demo.aedt"]


# ─── 主路径 1：成功 ──────────────────────────────────────────────────────────

def test_solve_success_command_artifacts_logfile(tmp_path, monkeypatch,
                                                 no_real_popen):
    proj = _aedt_project(tmp_path)
    recorder = _PopenRecorder(_FakeProc(rc=0))
    _patch_launch(monkeypatch, recorder)
    _patch_exe(monkeypatch)

    res = solve_project_batch(proj, design="HFSSDesign1", setup="Setup1",
                              timeout_s=60.0)

    assert res["ok"] is True
    assert res["rc"] == 0
    assert res["timed_out"] is False
    assert res["errors"] == []
    assert res["project_kind"] == "aedt"
    assert res["ansysedt_exe"] == _EXE
    # 命令行钉字面（发射序 + design:setup 限定 + Logfile 前置，工程恒末位——
    # 真机实证 AEDT 2025 R1 拒收 -Logfile 收口形态）
    cmd = res["command"]
    assert cmd[:3] == [_EXE, "-ng", "-BatchSolve"]
    assert cmd[3:5] == ["-designs", "HFSSDesign1:Setup1"]
    assert cmd[5:7] == ["-Logfile", str(proj.parent
                                            / ("ansysedt_batch_"
                                               + proj.stem + ".log"))]
    assert cmd[-1] == str(proj)
    # 发射 kwargs：console 输出重定向进 logfile（文件句柄非管道）
    assert recorder.calls[0]["stderr"] is hb.subprocess.STDOUT
    # 产物回收：touchstone + 结果白名单，非白名单不收
    assert any(a.endswith("demo.s2p") for a in res["artifacts"])
    assert any(a.endswith("solved.csv") for a in res["artifacts"])
    assert not any(a.endswith("mesh.txt") for a in res["artifacts"])
    assert Path(res["logfile"]).is_file()
    assert res["elapsed_s"] >= 0.0


def test_solve_success_appends_launcher_output_to_logfile(
        tmp_path, monkeypatch, no_real_popen):
    """Popen 收到的 stdout 句柄即 logfile（追加形态，launch 侧输出可回读）。"""
    proj = _aedt_project(tmp_path, with_results=False)

    class _WritingProc(_FakeProc):
        def wait(self, timeout=None):
            # 模拟子进程向继承句柄写 console 输出
            self._handle.write(b"launcher stderr line\n")
            return 0

    recorded: dict = {}

    def _popen(cmd, stdout=None, **kwargs):
        recorded["stdout"] = stdout
        proc = _WritingProc(rc=0)
        proc._handle = stdout
        return proc

    monkeypatch.setattr(hb.subprocess, "Popen", _popen)
    _patch_exe(monkeypatch)

    res = solve_project_batch(proj, timeout_s=60.0)
    assert res["ok"] is True
    assert recorded["stdout"] is not None
    assert "launcher stderr line" in res["logfile_tail"]


# ─── 主路径 2：超时击杀 ──────────────────────────────────────────────────────

def test_solve_timeout_kills_process_tree(tmp_path, monkeypatch,
                                          no_real_popen):
    proj = _aedt_project(tmp_path, with_results=False)
    killed: list[int] = []
    release = threading.Event()

    def fake_kill(pid, timeout_s=10.0):
        killed.append(pid)
        release.set()
        return True

    monkeypatch.setattr(hb, "_kill_process_tree", fake_kill)

    class _BlockingProc:
        pid = 99

        @staticmethod
        def wait(timeout=None):
            assert release.wait(timeout=30.0), "watchdog 未击杀，假进程悬挂"
            return 1

    monkeypatch.setattr(hb.subprocess, "Popen",
                        lambda cmd, **kw: _BlockingProc())
    _patch_exe(monkeypatch)

    res = solve_project_batch(proj, timeout_s=0.05)

    assert res["ok"] is False
    assert res["timed_out"] is True
    assert killed == [99]  # 整树击杀按 Popen 句柄 pid，不按进程名扫杀
    assert "超时" in res["errors"][0] and "击杀" in res["errors"][0]


def test_solve_nonpositive_timeout_means_unlimited(tmp_path, monkeypatch,
                                                   no_real_popen):
    """timeout_s<=0 = 不设超时（不启动 watchdog timer，避免立即触发）。"""
    proj = _aedt_project(tmp_path, with_results=False)
    started: list[float] = []
    real_watchdog = hb.Watchdog

    class _SpyWatchdog(real_watchdog):
        def start(self, timeout_s, callback):
            started.append(float(timeout_s))
            super().start(timeout_s, callback)

    monkeypatch.setattr(hb, "Watchdog", _SpyWatchdog)
    _patch_launch(monkeypatch, _PopenRecorder(_FakeProc(rc=0)))
    _patch_exe(monkeypatch)

    res = solve_project_batch(proj, timeout_s=0)
    assert res["ok"] is True
    assert started == []  # watchdog 从未启动


# ─── 主路径 3：路径缺失 / 形态非法 ────────────────────────────────────────────

def test_solve_project_path_missing_structured_fail(tmp_path, monkeypatch,
                                                    no_real_popen):
    _patch_exe(monkeypatch)
    res = solve_project_batch(tmp_path / "ghost.aedt")
    assert res["ok"] is False
    assert res["rc"] is None
    assert res["command"] == []  # 未发射任何进程
    assert ".aedt" in res["errors"][0] and ".aedb" in res["errors"][0]


def test_solve_plain_directory_rejected(tmp_path, monkeypatch,
                                        no_real_popen):
    plain = tmp_path / "not_a_database"
    plain.mkdir()
    _patch_exe(monkeypatch)
    res = solve_project_batch(plain)
    assert res["ok"] is False and res["rc"] is None
    assert res["command"] == []


def test_solve_nonpath_project_rejected(no_real_popen):
    res = solve_project_batch(None)  # type: ignore[arg-type]
    assert res["ok"] is False
    assert res["rc"] is None
    assert res["command"] == []
    assert "形态非法" in res["errors"][0]


# ─── 主路径 4：aedb 目录回退 ─────────────────────────────────────────────────

def test_solve_aedb_directory_fallback(tmp_path, monkeypatch, no_real_popen):
    aedb = tmp_path / "demo.aedb"
    aedb.mkdir()
    (aedb / "HFSSDesign1.s4p").write_text("! touchstone", encoding="utf-8")
    recorder = _PopenRecorder(_FakeProc(rc=0))
    _patch_launch(monkeypatch, recorder)
    _patch_exe(monkeypatch)

    res = solve_project_batch(aedb, timeout_s=60.0)

    assert res["ok"] is True
    assert res["project_kind"] == "aedb"
    assert str(aedb) in res["command"]  # 目录路径直通 -BatchSolve
    assert aedb.name in Path(res["logfile"]).name  # 日志随工程名
    assert any(a.endswith(".s4p") for a in res["artifacts"])


# ─── exe 发现（复用 version_probe 链；全 fake）───────────────────────────────

def test_find_exe_explicit_file(tmp_path):
    exe = tmp_path / "ansysedt.exe"
    exe.write_bytes(b"MZ")
    assert find_ansysedt_exe(exe) == exe


def test_find_exe_explicit_install_dir(tmp_path):
    exe = tmp_path / "AnsysEM" / "ansysedt.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    assert find_ansysedt_exe(tmp_path) == exe


def test_find_exe_via_env_install(monkeypatch, tmp_path):
    exe = tmp_path / "AnsysEM" / "ansysedt.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("RFAUTO_AEDT_PATH", str(tmp_path))
    monkeypatch.setattr("rfauto.infra.version_probe.resolve_aedt_install",
                        lambda p: {"path": Path(p or tmp_path),
                                   "aedt_version": "2025.1",
                                   "source": "explicit"})
    assert find_ansysedt_exe() == exe


def test_find_exe_via_probe_auto(monkeypatch, tmp_path):
    exe = tmp_path / "Win64" / "ansysedt.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    monkeypatch.delenv("RFAUTO_AEDT_PATH", raising=False)
    monkeypatch.setattr("rfauto.infra.version_probe.resolve_aedt_install",
                        lambda p: {"path": tmp_path, "aedt_version": "2025.1",
                                   "source": "auto-probe"})
    assert find_ansysedt_exe() == exe


def test_find_exe_ansysem_root_bin_layer_fallback(monkeypatch, tmp_path):
    """ANSYSEM_ROOTxxx 直指 bin 层的安装形态（version_probe 归一失败仍可
    从原值目录兜底发现）。"""
    exe = tmp_path / "ansysedt.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.delenv("RFAUTO_AEDT_PATH", raising=False)
    for name in list(os.environ):
        if name.startswith("ANSYSEM_ROOT"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("rfauto.infra.version_probe.resolve_aedt_install",
                        lambda p: None)
    monkeypatch.setenv("ANSYSEM_ROOT999", str(tmp_path))
    assert find_ansysedt_exe() == exe


def test_find_exe_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("RFAUTO_AEDT_PATH", raising=False)
    for name in list(os.environ):
        if name.startswith("ANSYSEM_ROOT"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("rfauto.infra.version_probe.resolve_aedt_install",
                        lambda p: None)
    assert find_ansysedt_exe() is None
    assert find_ansysedt_exe(tmp_path / "ghost_dir") is None


def test_solve_exe_missing_clear_error(tmp_path, monkeypatch, no_real_popen):
    proj = _aedt_project(tmp_path, with_results=False)
    monkeypatch.setattr(hb, "find_ansysedt_exe", lambda explicit=None: None)
    res = solve_project_batch(proj)
    assert res["ok"] is False and res["rc"] is None
    assert res["command"] == []
    assert "ansysedt.exe" in res["errors"][0]
    assert "RFAUTO_AEDT_PATH" in res["errors"][0]  # 明确报错含修复路径


# ─── 产物扫描 / 日志尾部 ─────────────────────────────────────────────────────

def test_collect_artifacts_aedt_and_cap(tmp_path):
    proj = _aedt_project(tmp_path)  # demo.s2p + solved.csv 已就位
    found = collect_solve_artifacts(proj)
    assert len(found) == 2
    assert found == sorted(found)  # 排序稳定
    capped = collect_solve_artifacts(proj, limit=1)
    assert len(capped) == 1


def test_collect_artifacts_empty_project(tmp_path):
    proj = _aedt_project(tmp_path, with_results=False)
    assert collect_solve_artifacts(proj) == []


def test_collect_artifacts_parent_shallow_no_sibling_leak(tmp_path):
    """工程旁目录浅层扫描（2026-10-08 审查批 P1）：父目录常为共享工作目录，
    兄弟工程 aedtresults 里的白名单产物不得递归混入本工程清单（docstring
    契约=工程旁浅层）；工程旁直属产物（批后导出落点）仍回收。"""
    proj = _aedt_project(tmp_path, with_results=False)
    sibling_results = tmp_path / "other.aedtresults"
    sibling_results.mkdir()
    (sibling_results / "leak.s2p").write_text("! other project", encoding="utf-8")
    (tmp_path / "beside_export.s4p").write_text("! beside", encoding="utf-8")
    found = collect_solve_artifacts(proj)
    assert any(a.endswith("beside_export.s4p") for a in found)
    assert not any("leak.s2p" in a for a in found)


def test_read_logfile_tail_lines_and_missing(tmp_path):
    log = tmp_path / "x.log"
    log.write_text(
        "\n".join(f"line{i}" for i in range(100)), encoding="utf-8")
    tail = read_logfile_tail(log, max_lines=5)
    assert tail.splitlines()[-1] == "line99"
    assert len(tail.splitlines()) == 5
    assert read_logfile_tail(tmp_path / "nope.log") == ""


# ─── Touchstone 批后导出（-batchextract 第二段，全 fake 零真机）──────────────

def _fake_aedt_export(cmd: list[str]) -> Path:
    """假 AEDT 提取段：解析脚本烘焙面的 _OUT_FILE，按 4 端口形态落盘。

    行形态对齐 infer_touchstone_port_count 的 4 端口判据：每频点一块，
    首行 9 值（1+2*4）+ 3 行 8 值（块行数=4）。
    """
    script = Path(cmd[cmd.index("-batchextract") + 1])
    text = script.read_text(encoding="utf-8")
    marker = '_OUT_FILE = "'
    start = text.index(marker) + len(marker)
    out = Path(text[start:text.index('"', start)])
    rows = ["! fake ExportNetworkData", "# HZ S MA R 50"]
    for freq in ("1.0e9", "2.0e9"):
        rows.append(freq + " 1 0 1 0 1 0 1 0")  # 9 值（1+2*4）
        rows.extend(["0 1 0 1 0 1 0 1"] * 3)    # 8 值 ×3（块行数=4）
    out.write_text("\n".join(rows), encoding="utf-8")
    return out


def _patch_two_phase(monkeypatch, solve_rc: int = 0,
                     export_writes: bool = True,
                     export_rc: int = 0) -> list[dict]:
    """两段假发射：-BatchSolve 段与 -batchextract 段按命令行分派记录。"""
    calls: list[dict] = []

    def _popen(cmd, **kwargs):
        calls.append({"cmd": list(cmd), **kwargs})
        if "-batchextract" in cmd:
            if export_writes:
                _fake_aedt_export(cmd)
            return _FakeProc(rc=export_rc, pid=4243)
        return _FakeProc(rc=solve_rc, pid=4242)

    monkeypatch.setattr(hb.subprocess, "Popen", _popen)
    return calls


def test_build_batch_extract_command_literal():
    cmd = build_batch_extract_command(_EXE, "E:\\s\\x.py",
                                      "D:\\jobs\\demo.aedt")
    assert cmd == [_EXE, "-ng", "-batchextract", "E:\\s\\x.py",
                   "D:\\jobs\\demo.aedt"]
    assert cmd[-1].endswith(".aedt")  # 工程恒末位（-BatchSolve 同纪律）


def test_batch_extract_script_baked_literals():
    text = build_batch_extract_script(
        project_name="demo", design="D1", setup="S1", sweep="SW1",
        out_file="E:\\out\\demo_export.s2p", renorm=True)
    assert text.isascii()  # IronPython 2 编码面零风险
    assert "<<" not in text  # 占位符全数替换（禁带占位符上真机）
    assert 'f"' not in text and "f'" not in text  # 无 f-string（IronPython 2）
    assert '_OUT_FILE = "E:/out/demo_export.s2p"' in text  # 正斜杠烘焙
    assert '_DESIGN_NAME = "D1"' in text
    assert '_SETUP_NAME = "S1"' in text
    assert '_SWEEP_NAME = "SW1"' in text
    assert "_RENORM = True" in text
    assert "ExportNetworkData(" in text  # 14 参直连口径本体在档


def test_batch_extract_script_auto_defaults():
    text = build_batch_extract_script(out_file="x.s2p")
    assert '_DESIGN_NAME = ""' in text  # 空=脚本内自动枚举
    assert '_SETUP_NAME = ""' in text
    assert '_SWEEP_NAME = ""' in text
    assert "_RENORM = False" in text  # 缺省原生参考基（hfss_adapter 主口径）


def test_export_success_renames_by_port_count(tmp_path, monkeypatch,
                                              no_real_popen):
    proj = _aedt_project(tmp_path, with_results=False)
    calls = _patch_two_phase(monkeypatch)
    _patch_exe(monkeypatch)

    res = export_touchstone_after_solve(proj, design="HFSSDesign1",
                                        setup="Setup1")

    assert res["ok"] is True
    assert res["rc"] == 0 and res["timed_out"] is False
    assert res["errors"] == []
    assert res["n_ports"] == 4
    # 占位 .s2p 已按内容反推端口数改名 .s4p（内容不依赖扩展名，改名即可）
    exported = Path(res["out_file"])
    assert exported.name == "demo_export.s4p"
    assert exported.is_file()
    assert not (tmp_path / "demo_export.s2p").exists()
    # 命令行钉字面：官方旗标 + 脚本 + 工程恒末位
    cmd = res["command"]
    assert cmd[:3] == [_EXE, "-ng", "-batchextract"]
    assert cmd[-1] == str(proj)
    assert Path(cmd[3]).is_file()
    # 渲染字面量在档证据链：设计/setup 已烘焙进脚本字面量
    baked = Path(cmd[3]).read_text(encoding="utf-8")
    assert '_DESIGN_NAME = "HFSSDesign1"' in baked
    assert '_SETUP_NAME = "Setup1"' in baked
    assert len(calls) == 1


def test_export_failure_no_file_structured(tmp_path, monkeypatch,
                                           no_real_popen):
    proj = _aedt_project(tmp_path, with_results=False)
    _patch_two_phase(monkeypatch, export_writes=False)
    _patch_exe(monkeypatch)

    res = export_touchstone_after_solve(proj)

    assert res["ok"] is False
    assert res["rc"] == 0  # 进程本身退出 0，败因=文件未生成
    assert res["out_file"] is None and res["n_ports"] is None
    assert any("未生成" in e for e in res["errors"])


def test_export_timeout_kills_process_tree(tmp_path, monkeypatch,
                                           no_real_popen):
    proj = _aedt_project(tmp_path, with_results=False)
    killed: list[int] = []
    release = threading.Event()

    def fake_kill(pid, timeout_s=10.0):
        killed.append(pid)
        release.set()
        return True

    monkeypatch.setattr(hb, "_kill_process_tree", fake_kill)

    class _BlockingProc:
        pid = 77

        @staticmethod
        def wait(timeout=None):
            assert release.wait(timeout=30.0), "watchdog 未击杀，假进程悬挂"
            return 1

    monkeypatch.setattr(hb.subprocess, "Popen",
                        lambda cmd, **kw: _BlockingProc())
    _patch_exe(monkeypatch)

    res = export_touchstone_after_solve(proj, timeout_s=0.05)

    assert res["ok"] is False and res["timed_out"] is True
    assert res["out_file"] is None
    assert killed == [77]  # 只回收自己 Popen 的子进程树
    assert "超时" in res["errors"][0]


def test_export_script_write_failure_structured_fail(tmp_path, monkeypatch,
                                                     no_real_popen):
    proj = _aedt_project(tmp_path, with_results=False)
    _patch_exe(monkeypatch)

    def _boom(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(hb, "_write_extract_script", _boom)
    res = export_touchstone_after_solve(proj)
    assert res["ok"] is False and res["rc"] is None
    assert res["command"] == []  # 脚本未落盘绝不发射
    assert "写入失败" in res["errors"][0]


def test_export_session_mode_reserved_stub(tmp_path, monkeypatch,
                                           no_real_popen):
    """回退 B 接口位：mode=session 明确结构化报错未接线，绝不静默走错通道。"""
    proj = _aedt_project(tmp_path, with_results=False)
    _patch_exe(monkeypatch)
    res = export_touchstone_after_solve(proj, mode="session")
    assert res["ok"] is False and res["rc"] is None
    assert res["command"] == []
    assert "hfss_session" in res["errors"][0]


def test_export_project_missing_and_exe_missing(tmp_path, monkeypatch,
                                                no_real_popen):
    _patch_exe(monkeypatch)
    res = export_touchstone_after_solve(tmp_path / "ghost.aedt")
    assert res["ok"] is False and res["command"] == []
    assert ".aedt" in res["errors"][0]

    proj = _aedt_project(tmp_path, with_results=False)
    monkeypatch.setattr(hb, "find_ansysedt_exe", lambda explicit=None: None)
    res2 = export_touchstone_after_solve(proj)
    assert res2["ok"] is False and "ansysedt.exe" in res2["errors"][0]


def test_solve_export_true_full_pipeline(tmp_path, monkeypatch,
                                         no_real_popen):
    proj = _aedt_project(tmp_path)
    calls = _patch_two_phase(monkeypatch)
    _patch_exe(monkeypatch)

    res = solve_project_batch(proj, design="HFSSDesign1", setup="Setup1",
                              timeout_s=60.0, export_touchstone=True)

    assert res["ok"] is True
    assert res["errors"] == []
    assert res["export"]["ok"] is True
    assert res["export"]["n_ports"] == 4
    # 两段发射有序：先 -BatchSolve 后 -batchextract
    assert "-BatchSolve" in calls[0]["cmd"]
    assert "-batchextract" in calls[1]["cmd"]
    # 批后导出的 .s4p 随 artifacts 回收（扫描置于导出尝试之后）
    assert any(a.endswith("demo_export.s4p") for a in res["artifacts"])


def test_solve_export_default_false_zero_change(tmp_path, monkeypatch,
                                                no_real_popen):
    proj = _aedt_project(tmp_path)
    calls = _patch_two_phase(monkeypatch)
    _patch_exe(monkeypatch)

    res = solve_project_batch(proj, timeout_s=60.0)

    assert res["ok"] is True
    assert res["export"] is None  # 未请求=键面 None（零行为变化）
    assert len(calls) == 1  # 仅求解段，无第二段进程
    assert "-batchextract" not in calls[0]["cmd"]
    assert res["errors"] == []


def test_solve_export_failure_keeps_solve_ok(tmp_path, monkeypatch,
                                             no_real_popen):
    proj = _aedt_project(tmp_path)
    _patch_two_phase(monkeypatch, export_writes=False)
    _patch_exe(monkeypatch)

    res = solve_project_batch(proj, timeout_s=60.0, export_touchstone=True)

    assert res["ok"] is True  # 导出失败不推翻求解 ok（#105 best-effort）
    assert res["export"]["ok"] is False
    assert any("导出失败" in e for e in res["errors"])


def test_solve_export_skipped_when_solve_failed(tmp_path, monkeypatch,
                                                no_real_popen):
    proj = _aedt_project(tmp_path, with_results=False)
    calls = _patch_two_phase(monkeypatch, solve_rc=1)
    _patch_exe(monkeypatch)

    res = solve_project_batch(proj, timeout_s=60.0, export_touchstone=True)

    assert res["ok"] is False
    assert res["export"] is None  # 求解未成功（rc!=0）不导出
    assert len(calls) == 1  # 第二段进程未发射


# ─── 导出分派：3D Layout 回退 / FATAL finally / sweep 透传 ────────────────────
#
# W5 真机实证：HFSS 3D Layout 设计无
# 任何 Analysis 模块——GetModule("AnalysisSetup"/"Setup"/"Output"/
# "Solutions") 四名全 FAIL，ExportNetworkData 挂 design 对象（pyaedt
# analysis.py 先例：design_type "HFSS 3D Layout Design" → module=
# self.odesign）。烘焙脚本按字面 exec + fake oDesktop 零真机钉行为。

def _run_baked_script(text: str, desktop) -> None:
    """烘焙脚本字面 exec（fake oDesktop 注入 globals，main() 立即执行）。"""
    exec(compile(text, "batch_extract_script.py", "exec"),
         {"oDesktop": desktop})  # 自产模板 + 假桌面，零真机


class _FakeAedtModule:
    """design.GetModule(...) 返回的分析模块替身（HFSS 3D 建模器口径）。"""

    def __init__(self) -> None:
        self.export_calls: list[tuple] = []

    def GetSetups(self):
        return ["Setup1"]

    def GetSweeps(self, setup):
        return ["Sweep1"]

    def ExportNetworkData(self, *args):
        self.export_calls.append(args)


class _FakeDesign:

    def __init__(self, module=None, design_export_fails: bool = False) -> None:
        self._module = module
        self._design_export_fails = design_export_fails
        self.module_queries: list[str] = []
        self.export_calls: list[tuple] = []

    def GetName(self):
        return "0;D1"

    def GetModule(self, name):
        self.module_queries.append(str(name))
        if self._module is None:
            raise Exception("module not available: " + str(name))
        return self._module

    def ExportNetworkData(self, *args):
        self.export_calls.append(args)
        if self._design_export_fails:
            raise Exception("design-level export exploded")


class _FakeProject:

    def __init__(self, design) -> None:
        self._design = design
        self.pinned: list[str] = []

    def GetName(self):
        return "demo.aedt"

    def GetActiveDesign(self):
        return None

    def SetActiveDesign(self, name):
        self.pinned.append(name)
        return self._design

    def GetTopDesignList(self):
        return ["0;D1"]


class _FakeDesktop:

    def __init__(self, project) -> None:
        self._project = project
        self.quit_calls = 0

    def GetActiveProject(self):
        return self._project

    def GetProjects(self):
        return []

    def QuitApplication(self):
        self.quit_calls += 1


def test_baked_script_dispatch_structure():
    """分派探针 + design 级回退 + 名义兜底 + finally 退出结构在档。"""
    text = build_batch_extract_script(out_file="x.s2p")
    assert 'design.GetModule("Solutions")' in text  # 探针先试模块（HFSS 3D）
    assert "solutions.ExportNetworkData(*args)" in text
    assert "design.ExportNetworkData(*args)" in text  # 回退 design 级（Layout）
    assert '_NOMINAL_SETUP = "setup1"' in text
    assert '_NOMINAL_SWEEP = "sweep1"' in text
    # QuitApplication 在 finally 块内（#265：FATAL 早退不留孤儿桌面）
    assert text.index("finally:") < text.index("oDesktop.QuitApplication()")


def test_script_module_path_when_solutions_module_available():
    """HFSS 3D 建模器口径：Solutions 模块可用 → 模块路径导出，14 参逐位钉。"""
    module = _FakeAedtModule()
    design = _FakeDesign(module=module)
    desktop = _FakeDesktop(_FakeProject(design))
    _run_baked_script(
        build_batch_extract_script(project_name="demo",
                                   out_file="E:/o/x.s2p"), desktop)
    assert len(module.export_calls) == 1
    args = module.export_calls[0]
    assert len(args) == 14
    assert args[0] == ""  # DesignVariations: nominal
    assert args[1] == ["Setup1:Sweep1"]  # 自动枚举的选择
    assert args[2] == 3  # FileFormat: Touchstone
    assert args[3] == "E:/o/x.s2p"
    assert args[4] == ["all"]
    assert design.export_calls == []  # design 级回退未触达
    assert desktop.quit_calls == 1


def test_script_design_level_fallback_when_all_modules_fail():
    """3D Layout 口径：GetModule 全 FAIL（W5 四名形态）→ design 级直呼 +
    名义 setup1:sweep1 兜底，全程零旗标自动适配。"""
    design = _FakeDesign(module=None)
    desktop = _FakeDesktop(_FakeProject(design))
    _run_baked_script(
        build_batch_extract_script(project_name="demo",
                                   out_file="E:/o/x.s2p"), desktop)
    # 枚举面探过 AnalysisSetup/Setup，导出面探过 Solutions（W5 探针第四名
    # Output 属诊断面，脚本不消费）
    assert design.module_queries == ["AnalysisSetup", "Setup", "Solutions"]
    assert len(design.export_calls) == 1
    args = design.export_calls[0]
    assert len(args) == 14  # 与模块路径同参（W5 修正脚本逐字对齐口径）
    assert args[1] == ["setup1:sweep1"]  # 名义兜底（W5 实证可导出）
    assert desktop.quit_calls == 1


def test_script_design_level_pads_missing_sweep():
    """design 级口径恒发 Setup:Sweep 对（pyaedt 惯例）：sweep 缺失补名义名。"""
    design = _FakeDesign(module=None)
    desktop = _FakeDesktop(_FakeProject(design))
    _run_baked_script(
        build_batch_extract_script(project_name="demo", setup="SetupA",
                                   out_file="E:/o/x.s2p"), desktop)
    assert design.export_calls[0][1] == ["SetupA:sweep1"]


def test_script_fatal_still_quits_application():
    """#265：FATAL 早退（无工程）也必须 QuitApplication（finally 语义）。"""
    desktop = _FakeDesktop(None)
    with pytest.raises(RuntimeError, match="FATAL"):
        _run_baked_script(
            build_batch_extract_script(project_name="demo",
                                       out_file="E:/o/x.s2p"), desktop)
    assert desktop.quit_calls == 1


def test_script_both_export_paths_fail_fatal_and_quits():
    """双路径全败 → FATAL 带回退路径错误信息；QuitApplication 仍执行。"""
    design = _FakeDesign(module=None, design_export_fails=True)
    desktop = _FakeDesktop(_FakeProject(design))
    with pytest.raises(RuntimeError, match="both export paths failed"):
        _run_baked_script(
            build_batch_extract_script(project_name="demo",
                                       out_file="E:/o/x.s2p"), desktop)
    assert len(design.export_calls) == 1  # design 级回退确实尝试过
    assert desktop.quit_calls == 1


def test_solve_passes_sweep_to_export_stage(tmp_path, monkeypatch,
                                            no_real_popen):
    """solve_project_batch 的 sweep 形参透传导出段脚本字面（原缺口补齐）。"""
    proj = _aedt_project(tmp_path, with_results=False)
    calls = _patch_two_phase(monkeypatch)
    _patch_exe(monkeypatch)

    res = solve_project_batch(proj, design="HFSSDesign1", setup="Setup1",
                              sweep="SW9", timeout_s=60.0,
                              export_touchstone=True)

    assert res["ok"] is True
    assert res["export"]["ok"] is True
    baked = Path(res["export"]["script"]).read_text(encoding="utf-8")
    assert '_SWEEP_NAME = "SW9"' in baked
    assert len(calls) == 2  # 求解段 + 导出段


# ─── 烘焙守卫与注入面（W5 审查席移交 P1/P2 修复钉）────────────────────────────

def test_bake_guard_token_mode_accepts_value_angle_literals():
    """P1：占位符守卫收紧为 token 模式正则——值内非 token 形态 ``<<``
    （``D<<1``/``a << b``/``<<x>>`` 小写形）是合法名的一部分，照常烘焙
    不再误抛（裸 ``"<<" in text`` 会把这类名误判成模板漏洞）。"""
    text = build_batch_extract_script(
        project_name="demo", design="D<<1", setup="a << b", sweep="<<x>>",
        out_file="E:/o/x.s2p")
    compile(text, "baked.py", "exec")  # 语法面
    assert '_DESIGN_NAME = "D<<1"' in text  # 值内字面原样保留
    assert '_SETUP_NAME = "a << b"' in text
    assert '_SWEEP_NAME = "<<x>>"' in text


def test_bake_guard_template_residue_still_raises(monkeypatch):
    """P1：守卫语义保留——模板真残留 token 形态占位符仍 ValueError
    （绝不带占位符上真机）。"""
    monkeypatch.setattr(
        hb, "_BATCH_EXTRACT_SCRIPT_TEMPLATE",
        hb._BATCH_EXTRACT_SCRIPT_TEMPLATE + "\n_EXTRA = <<NEW_TOKEN>>\n")
    with pytest.raises(ValueError, match="占位符"):
        build_batch_extract_script(out_file="x.s2p")


def test_bake_guard_token_shaped_value_still_raises():
    """token 形态的值（大写占位符形）与模板残留不可区分，保守方向仍拦。"""
    with pytest.raises(ValueError, match="占位符"):
        build_batch_extract_script(design="A<<OUT_FILE>>B", out_file="x.s2p")


def test_bake_guard_non_ascii_name_raises():
    """非 ASCII 名守卫保留（IronPython 2 编码面零风险）——由调用点
    结构化落账（见下），烘焙纯函数本身仍抛 ValueError。"""
    with pytest.raises(ValueError, match="ASCII"):
        build_batch_extract_script(design="设计1", out_file="x.s2p")


def test_export_bake_failure_structured_no_raise(tmp_path, monkeypatch,
                                                 no_real_popen):
    """P1 调用点①：烘焙守卫 ValueError 绝不逃逸 export_touchstone_
    after_solve（"本函数不抛异常"承诺）——结构化 ok=False + 未发射进程。"""
    proj = _aedt_project(tmp_path, with_results=False)
    _patch_exe(monkeypatch)

    res = export_touchstone_after_solve(proj, design="设计1")

    assert res["ok"] is False and res["rc"] is None
    assert res["command"] == []  # 烘焙失败绝不发射
    assert res["out_file"] is None and res["n_ports"] is None
    assert "烘焙失败" in res["errors"][0]


def test_solve_export_valueerror_structured_fallback_keeps_solve_ok(
        tmp_path, monkeypatch, no_real_popen):
    """P1 调用点②：solve_project_batch 侧导出链 ValueError 结构化兜底
    （edb_solve 只捕 RuntimeError/OSError，裸 ValueError 直达即信封契约
    违例）；导出失败不推翻求解 ok（#105）。"""
    proj = _aedt_project(tmp_path, with_results=False)
    _patch_launch(monkeypatch, _PopenRecorder(_FakeProc(rc=0)))
    _patch_exe(monkeypatch)

    def _boom(*_a, **_k):
        raise ValueError("烘焙守卫 boom")

    monkeypatch.setattr(hb, "export_touchstone_after_solve", _boom)
    res = solve_project_batch(proj, timeout_s=60.0, export_touchstone=True)

    assert res["ok"] is True  # 求解 ok 不被导出链异常推翻
    assert res["export"]["ok"] is False
    assert res["export"]["rc"] is None
    assert any("boom" in e and "导出失败" in e for e in res["errors"])


# ─── 路径参数形态守卫（ge8e W7 审查批 P2 补钉）────────────────────────────────

def test_export_null_byte_out_path_structured_no_raise(tmp_path, monkeypatch,
                                                       no_real_popen):
    """out_path 嵌空字节：结构化 ok=False 零发射（mkdir/unlink 对空字节抛
    ValueError 非 OSError，裸抛即违"本函数不抛异常"承诺——空字节路径
    is_file() 吞错返回 False 探测不到，须早拦防白发射真机会话）。"""
    proj = _aedt_project(tmp_path, with_results=False)
    _patch_exe(monkeypatch)

    res = export_touchstone_after_solve(proj, out_path="bad\0path.s2p")

    assert res["ok"] is False and res["rc"] is None
    assert res["command"] == []  # 带病路径绝不发射 ansysedt
    assert any("空字节" in e for e in res["errors"])


def test_export_bad_logfile_dir_structured_no_raise(tmp_path, monkeypatch,
                                                    no_real_popen):
    """logfile_dir 嵌空字节 / 非路径形态：结构化 ok=False 零发射
    （mkdir ValueError 面 + Path() TypeError 面双盖）。"""
    proj = _aedt_project(tmp_path, with_results=False)
    _patch_exe(monkeypatch)

    res = export_touchstone_after_solve(proj, logfile_dir="bad\0dir")
    assert res["ok"] is False and res["rc"] is None
    assert res["command"] == []
    assert any("空字节" in e for e in res["errors"])  # 早拦在 mkdir 之前

    res2 = export_touchstone_after_solve(proj, logfile_dir=123)  # type: ignore[arg-type]
    assert res2["ok"] is False and res2["command"] == []
    assert any("logfile_dir 形态非法" in e for e in res2["errors"])

    res3 = export_touchstone_after_solve(proj, out_path=123)  # type: ignore[arg-type]
    assert res3["ok"] is False and res3["command"] == []
    assert any("out_path 形态非法" in e for e in res3["errors"])


def test_solve_bad_logfile_dir_structured_fail(tmp_path, monkeypatch,
                                               no_real_popen):
    """solve_project_batch 侧 logfile_dir 空字节：结构化失败零发射
    （executor _route_batch_stage 对本函数不设 try，裸异常=节点失败面）。"""
    proj = _aedt_project(tmp_path, with_results=False)
    _patch_exe(monkeypatch)

    res = solve_project_batch(proj, timeout_s=60.0,
                              logfile_dir="bad\0dir")

    assert res["ok"] is False and res["rc"] is None
    assert res["command"] == []
    assert any("不可创建" in e for e in res["errors"])

    res2 = solve_project_batch(proj, timeout_s=60.0, logfile_dir=123)  # type: ignore[arg-type]
    assert res2["ok"] is False and res2["command"] == []
    assert any("logfile_dir 形态非法" in e for e in res2["errors"])


def test_baked_script_special_chars_compile_and_value_roundtrip():
    """P2：含特殊字符的名烘焙前转义——脚本 compile() 通过、转义形态在档
    （反斜杠加倍/双引号前缀反斜杠/控制字符 \\xNN）且值经字面 exec 逐位
    保真（假桌面回读 pinned design 与导出选择）。"""
    weird_design = 'D\\1"x'   # 反斜杠 + 双引号
    weird_setup = "S\t2"      # 控制字符（制表符）
    weird_sweep = "SW\n3"     # 控制字符（换行）
    text = build_batch_extract_script(
        project_name='pro"ject.aedt', design=weird_design,
        setup=weird_setup, sweep=weird_sweep, out_file="E:/o/x.s2p")

    compile(text, "baked.py", "exec")  # 语法坏脚本当场红（注入面）
    assert text.isascii()  # 控制字符已转 \xNN，无裸控制字符进字面量
    assert '_DESIGN_NAME = "D\\\\1\\"x"' in text
    assert '_SETUP_NAME = "S\\x092"' in text
    assert '_SWEEP_NAME = "SW\\x0a3"' in text
    assert '_EXPECT_PROJECT = "pro\\"ject.aedt"' in text

    # 值保真：字面 exec + 假桌面，pinned design / 导出选择与原值逐位相等
    design = _FakeDesign(module=None)
    project = _FakeProject(design)
    desktop = _FakeDesktop(project)
    _run_baked_script(text, desktop)
    assert project.pinned == [weird_design]
    assert design.export_calls[0][1] == [weird_setup + ":" + weird_sweep]
    assert desktop.quit_calls == 1
