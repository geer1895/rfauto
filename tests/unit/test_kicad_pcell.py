"""kicad_pcell KiCad Python 解析（AU-8 同款 env 化）单测。

三钉：env 覆盖 / env 空串回退本模块常量 / 显式参压过 env。全离线：
env 指向不存在路径走 ``Path(python_exe).exists()`` 确定性失败分支，
不启动子进程；空串回退钉用 subprocess.run 打桩捕获 argv。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import rfauto.adapters.kicad_pcell as kp
from rfauto.adapters.kicad_pcell import PCBDesign, generate_pcb

_ENV = "RFAUTO_KICAD_PYTHON"


def _design() -> PCBDesign:
    return PCBDesign(board_size=[20.0, 10.0])


def test_env_override_points_to_missing_python(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out.kicad_pcb"
    monkeypatch.setenv(_ENV, str(tmp_path / "no_kicad" / "python_env.exe"))
    result = generate_pcb(out, _design())
    assert result.success is False
    assert "不存在" in result.message
    assert "python_env.exe" in result.message
    assert not out.exists()


def test_explicit_beats_env(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out.kicad_pcb"
    monkeypatch.setenv(_ENV, str(tmp_path / "no_kicad" / "python_env.exe"))
    result = generate_pcb(
        out, _design(),
        kicad_python=str(tmp_path / "no_kicad" / "python_explicit.exe"),
    )
    assert result.success is False
    assert "python_explicit.exe" in result.message
    assert "python_env.exe" not in result.message


def test_env_empty_string_falls_back_to_module_constant(
    tmp_path: Path, monkeypatch,
) -> None:
    """env 空串视同未设 → 回退本模块 KICAD_PYTHON 常量（可被测试打桩）。

    常量打桩为不存在路径（test_kicad_cli 同款隔离）→ 走「不存在」确定性
    失败分支，CI 无 KiCad 亦成立；argv 捕获版另以 subprocess.run 打桩
    验证解析结果真的进了子进程命令行。
    """
    out = tmp_path / "out.kicad_pcb"
    monkeypatch.delenv(_ENV, raising=False)
    monkeypatch.setattr(kp, "KICAD_PYTHON",
                        str(tmp_path / "no_kicad" / "python.exe"))
    result = generate_pcb(out, _design())
    assert result.success is False
    assert "python.exe" in result.message and "不存在" in result.message


def test_fallback_reaches_subprocess_argv(tmp_path: Path, monkeypatch) -> None:
    """缺省解析结果真实进入子进程命令行（subprocess.run 打桩捕获）。"""
    out = tmp_path / "out.kicad_pcb"
    argv_box: list[list[str]] = []

    fake = SimpleNamespace(args=[], returncode=1, stdout="", stderr="boom")

    def _fake_run(argv, **kwargs):
        argv_box.append(list(argv))
        return fake

    monkeypatch.delenv(_ENV, raising=False)
    monkeypatch.setattr(kp, "KICAD_PYTHON", r"E:\fake\python_stub.exe")
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(kp.subprocess, "run", _fake_run)
    result = generate_pcb(out, _design())
    assert argv_box, "子进程未被调用"
    assert argv_box[0][0] == r"E:\fake\python_stub.exe"
    assert result.success is False
    assert "KiCad 执行失败" in result.message


@pytest.mark.parametrize("env_val", [None, "", "x"])
def test_resolve_default_kwarg_single_source(env_val: str | None,
                                             monkeypatch) -> None:
    """共享解析器 default kwarg：显式 > env（空串视同未设）> default。"""
    from rfauto.adapters.kicad_extract import resolve_kicad_python

    if env_val is None:
        monkeypatch.delenv(_ENV, raising=False)
    else:
        monkeypatch.setenv(_ENV, env_val)
    assert resolve_kicad_python(None, default="D:/fb/py.exe") == (
        "x" if env_val == "x" else "D:/fb/py.exe")
    assert resolve_kicad_python("E:/ex/py.exe", default="D:/fb/py.exe") \
        == "E:/ex/py.exe"


def test_generated_kicad_script_parses_and_lazy_boundary() -> None:
    """生成脚本 compile 验证回归钉（ge5 审查 P2-3；1fc6585 修复随钉）.

    1fc6585 根因：外层 f-string 模板内嵌 `print(f"Traces: {len(pcb_data
    .get(...))}")` 的 `{len(...)}` 在父进程模板求值期即 NameError，被
    generate_pcb 尾部宽 except 折成失败——happy path 恒坏。钉两件事：
    ① 产物整体 ast.parse 可编译（急切求值/转义坏即红，全离线无需
    KiCad）；② 急切/惰性边界：三处计数 print 的 pcb_data 引用保持
    子脚本惰性原文、路径占位符不残留（output_pcb 父侧落字面）。
    """
    import ast

    script = kp._generate_kicad_script("in.json", "out.kicad_pcb")
    ast.parse(script)
    # 子进程侧惰性求值：pcb_data 引用原文进入子脚本（若模板误用单花括号，
    # 父进程求值期即 NameError——ast.parse 亦抓不到完整产物，双断言互备）
    assert "f\"Traces: {len(pcb_data.get('traces', []))}\"" in script
    assert "f\"Vias: {len(pcb_data.get('vias', []))}\"" in script
    assert "f\"Pads: {len(pcb_data.get('pads', []))}\"" in script
    # 路径占位符父侧急切求值：子脚本不残留模板占位符
    assert "{output_pcb}" not in script and "{input_json}" not in script
