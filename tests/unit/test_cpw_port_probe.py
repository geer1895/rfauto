"""CPW-PROBE 推广批（2026-10-13）：CPWPort exc_dir 两代自适应探针单源单测。

单源=src/rfauto/adapters/oe_templates/cpw_port_probe.py——cpw/msl_cpw/fgcpw
三发射点共用注入（与 render_core footer extra_ports_import 名单一致），防三
处复制漂移（#116）。语义口径（aurora_c cpw 席服务器实测）：旧代绑定
（≤v0.37.0-rc1-11-gd3d2a49）把 exc_dir 当面法向/高度方向（'z'），新代当缝
间横向（'x'）——同一渲染字面量跨代部署必有一侧构造即炸，探针在**脚本执行
期**按部署侧绑定源码指纹自适应。单测以"指纹 dummy 类"双支钉两分支（纯
Python、不依赖真绑定），另加真绑定现状钉与本机新代行为一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.adapters.oe_templates.cpw_port_probe import (
    NEW_GEN_FINGERPRINT,
    exc_dir_probe_lines,
)


def _exec_probe(cpw_port_cls: type) -> str:
    """对任意"CPWPort 类"执行探针文本，返回 _CPW_EXC_DIR（getsource 只读
    类的 __init__ 源码、从不调用它——dummy 类的未定义名不触碰）。"""
    scope: dict = {"CPWPort": cpw_port_cls}
    exec(compile(exc_dir_probe_lines(), "cpw_probe", "exec"), scope)
    return scope["_CPW_EXC_DIR"]


class _NewGenCPWPort:
    """新代指纹 dummy（与 openEMS ports.py CPWPort.__init__ 同构一行）。"""

    def __init__(self):
        self.width_ny = CheckNyDir(exc_dir)  # noqa: F821


class _OldGenCPWPort:
    """旧代（≤d3d2a49）指纹 dummy：同位置是 exc_vec/argmax 高度口径。"""

    def __init__(self):
        self.height_ny = int(np.argmax(np.abs(exc_vec)))  # noqa: F821


def test_probe_text_shape():
    """探针文本形态钉：指纹行进 if 条件、两分支齐备、换行结尾（f-string
    直插模板体后 _portN 行仍顶格）。"""
    text = exc_dir_probe_lines()
    assert NEW_GEN_FINGERPRINT == "self.width_ny = CheckNyDir(exc_dir)"
    assert f'if "{NEW_GEN_FINGERPRINT}" in _cpw_src:' in text
    # 指纹出现 3 处：注释头 / getsource 不可得的缺省占位 / if 条件
    assert text.count(NEW_GEN_FINGERPRINT) == 3
    assert '_CPW_EXC_DIR = "x"' in text and '_CPW_EXC_DIR = "z"' in text
    assert "import inspect as _insp" in text
    assert text.endswith("\n")
    # exec 后变量名面：仅 _CPW_EXC_DIR 对外（_insp/_cpw_src 是探针内部名）
    scope: dict = {"CPWPort": _NewGenCPWPort}
    exec(compile(text, "cpw_probe", "exec"), scope)
    assert "_CPW_EXC_DIR" in scope


def test_probe_selects_x_on_new_gen_fingerprint():
    assert _exec_probe(_NewGenCPWPort) == "x"


def test_probe_selects_z_on_old_gen_fingerprint():
    assert _exec_probe(_OldGenCPWPort) == "z"


def test_probe_defaults_to_x_when_getsource_unavailable(monkeypatch):
    """冻结环境（getsource 抛 OSError/TypeError）缺省按新代 'x'（与本仓
    2026-10-02 口径一致——旧代部署必须能 getsource，缺省语义取本仓现状）。"""
    import inspect

    def _boom(_obj: object) -> str:
        raise OSError("source not available")

    monkeypatch.setattr(inspect, "getsource", _boom)
    assert _exec_probe(_NewGenCPWPort) == "x"


def test_probe_real_binding_local_is_x():
    """真绑定现状钉（本机 .venv=新代）：探针对真实 openEMS.ports.CPWPort
    选 'x'（与 render_tl CFIX 版 render 钉同语义，钉在 helper 层）。"""
    pytest.importorskip("CSXCAD")
    pytest.importorskip("openEMS")
    from openEMS.ports import CPWPort

    assert _exec_probe(CPWPort) == "x"


# ── 三发射点单源消费钉（防复制漂移 #116）────────────────────────────────────

def test_all_cpwport_emission_sites_consume_single_source():
    """cpw/msl_cpw/fgcpw 全部 CPWPort 发射点的渲染文本必须逐字节含单源探针
    文本，且零硬编码 exc_dir="x"（跨代炸弹面清零）。名单与 render_core
    footer extra_ports_import 的 CPWPort 模板集一致。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script

    probe = exc_dir_probe_lines()
    for tpl in ("cpw", "msl_cpw", "fgcpw"):
        text = render_script(tpl, dict(TEMPLATE_NOMINAL[tpl]), (2.25, 2.75))
        assert probe in text, f"{tpl}: 探针未按单源注入（复制漂移或遗漏）"
        assert 'exc_dir="x"' not in text, f"{tpl}: 硬编码 exc_dir='x' 跨代炸弹"
        assert "exc_dir=_CPW_EXC_DIR" in text, \
            f"{tpl}: CPWPort 构造未消费 _CPW_EXC_DIR"
