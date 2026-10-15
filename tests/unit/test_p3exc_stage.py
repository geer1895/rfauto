"""3 端口 legacy 模板第二激励子进程隔离（#208 处方 a，CFIX 2026-10-13）。

背景（runs/aurora_c_oe/coupled_line 实证）：旧 legacy footer 同进程对同一
CSX 二次 FDTD.Run(cleanup=True)——首个 Run 销毁 CSX C++ 对象，第二 run 与
解释器 teardown 段原生崩（数据齐全、主 CSV 已写、done 已打印仍
rc=3221226356=0xC0000354），try/except 对原生终止不可见。

形态：主脚本=「文件头 + GEOMETRY 标记圈住的几何段 + 文末 TAIL 标记携带的
stage 尾段（env 哨兵守卫）」；运行时把三段重组为 _rfauto_p3exc_stage.py 交
subprocess（RFAUTO_P3EXC_STAGE=1）——全新进程全新 CSX，进程内首个且唯一一
个 FDTD.Run。主 CSV 在发射 stage 前先行落盘（崩溃保护钉）。

判据口径（#212/#368）：结构判据在渲染文本与 CSXCAD 实测对象上，不做裸字
符串臆断；stage 端到端在 mock 引擎（openEMS.Run/MSLPort.CalcPort 类级）
下离线跑通，CSXCAD 缺席环境 importorskip 诚实跳过（gap_midline 先例）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.oe_templates.registry import (
    _NWAY_PORT_ROTATION_TEMPLATES,
    _THREE_PORT_ROTATION_TEMPLATES,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
)
from rfauto.adapters.oe_templates.render_core import (
    P3EXC_GEOM_BEGIN,
    P3EXC_GEOM_END,
    P3EXC_TAIL_BEGIN,
    P3EXC_TAIL_END,
)
from rfauto.adapters.openems_templates import render_script

BAND_HALF_GHZ = 0.25
MESH_MM = 0.4

# legacy else 分支里 body 含 _port3 的全部模板（第二激励形态消费者）
STAGE_TEMPLATES = ("coupled_line", "gysel", "tjunc", "wilkinson")
# 无 _port3 的 legacy 模板（保留旧 no-op 块，全文 sha 字节钉模板在列）
NO_STAGE_TEMPLATES = ("cpw", "mline", "siw")


def _render(template: str) -> str:
    f0 = float(TEMPLATE_META[template]["f0_ghz"])
    return render_script(template, dict(TEMPLATE_NOMINAL[template]),
                         (f0 - BAND_HALF_GHZ, f0 + BAND_HALF_GHZ),
                         mesh_resolution_mm=MESH_MM)


@pytest.mark.parametrize("template", STAGE_TEMPLATES)
def test_stage_form_present_for_three_port_legacy(template):
    """3 端口 legacy 模板：子进程隔离形态齐备、进程内二次 Run 绝迹。"""
    text = _render(template)
    assert P3EXC_GEOM_BEGIN in text and P3EXC_GEOM_END in text
    assert P3EXC_TAIL_BEGIN in text and P3EXC_TAIL_END in text
    # 进程内第二 FDTD（#208 雷形态）必须绝迹
    assert "_FDTD3" not in text
    # launcher：重组 stage 文件 + 子进程发射 + sidecar 回读
    assert "_rfauto_p3exc_stage.py" in text
    assert "RFAUTO_P3EXC_STAGE" in text
    assert "sparams_p3exc.csv" in text
    # 尾段 kwargs 占位必须已在渲染期替换（不许占位符漏网进生成脚本）
    assert "@P3XKW@" not in text
    assert "FDTD.Run(_SIM3, verbose=0, disable_dumps=True, cleanup=True)" in text
    # gysel #211 判废修复断言不得回退（尾段保留旧激励禁用逻辑）
    assert 'not str(_pr.GetName()).startswith("e3_")' in text


@pytest.mark.parametrize("template", NO_STAGE_TEMPLATES)
def test_no_stage_form_without_port3(template):
    """无 _port3 的 legacy 模板：标记/launcher 不注入（siw 全文 sha 钉、
    EEP 轮转族 sha 钉族同口径的漂移守卫）。"""
    text = _render(template)
    assert "RFAUTO_P3EXC" not in text
    assert "_rfauto_p3exc_stage.py" not in text
    # 轮转族（EEP/nway/diplexer）同样不受扰——sha 钉模板抽查一个口径
    assert template not in (_THREE_PORT_ROTATION_TEMPLATES
                            + _NWAY_PORT_ROTATION_TEMPLATES)


def test_marker_lines_unique_and_launcher_wired():
    """标记=launcher 与离线审计的唯一接口：独立标记行各恰一条，且 launcher
    的 split 引用与标记字面量同源（防止两处字面量漂移后 stage 装配解体）。"""
    text = _render("coupled_line")
    for marker in (P3EXC_GEOM_BEGIN, P3EXC_GEOM_END,
                   P3EXC_TAIL_BEGIN, P3EXC_TAIL_END):
        assert text.count("\n" + marker + "\n") == 1
        assert text.count('"' + marker + '"') >= 1   # launcher split 引用


def test_main_csv_written_before_stage_launch():
    """顺序钉（CFIX）：主 Run → 主 CSV 先行落盘 → stage 发射 → 最终写。"""
    text = _render("coupled_line")
    i_run = text.index("FDTD.Run(SIM_PATH")
    i_prov = text.index('with open(CSV_PATH, "w", newline="") as fh:')
    i_launch = text.index("_sp.run(")
    i_final = text.index("if not _LOOP_DONE:")
    assert i_run < i_prov < i_launch < i_final
    # 崩溃保护钉注释在场（教训载体，审查可读性）
    assert "崩溃保护钉" in text
    assert "try/except 拦不住原生终止" in text


def _assemble_stage_src(text: str) -> str:
    """与渲染脚本 launcher 同源的三段装配（标记字符串=唯一接口）。

    GEOMETRY 标记行在 launcher 之前（首个出现即真标记行，split 取首）；TAIL
    标记行在文末（launcher 自身的引用字面量出现更早，必须 rsplit 取末）——
    与 render_core launcher 的切向逐字一致，切向漂移即本测试红。"""
    head = text.split(P3EXC_GEOM_BEGIN, 1)[0]
    geo = text.split(P3EXC_GEOM_BEGIN, 1)[1].split(P3EXC_GEOM_END, 1)[0]
    tail = text.rsplit(P3EXC_TAIL_BEGIN, 1)[1].rsplit(P3EXC_TAIL_END, 1)[0]
    return head + geo + tail


def test_stage_guard_noop_without_env_flag(tmp_path):
    """env 哨兵未设：stage 进程跑完几何段即静默结束（不 Run 不落产物）——
    主进程执行到文末尾段同款 no-op 的离线等价证明。"""
    pytest.importorskip("CSXCAD")
    stage_src = _assemble_stage_src(_render("coupled_line"))
    compile(stage_src, "_rfauto_p3exc_stage.py", "exec")
    stage_path = tmp_path / "_rfauto_p3exc_stage.py"
    scope: dict = {"__name__": "__main__", "__file__": str(stage_path)}
    exec(compile(stage_src, str(stage_path), "exec"), scope)
    assert not (tmp_path / "sparams_p3exc.csv").exists()
    assert not (tmp_path / "fdtd_p3exc").exists()


def test_stage_runs_end_to_end_with_mocked_engine(tmp_path, monkeypatch):
    """stage 端到端（mock 引擎）：独立进程形态的脚本能 import/构建到
    FDTD.Run 完成——Run 参数（fdtd_p3exc/cleanup/disable_dumps）、e3_ 激励
    副本+旧激励禁用手术、sidecar 401 行、launcher 口径回读装配 S23。"""
    pytest.importorskip("CSXCAD")
    import csv
    import sys
    import types

    import openEMS as oe_pkg
    from openEMS.ports import MSLPort

    stage_src = _assemble_stage_src(_render("coupled_line"))
    stage_path = tmp_path / "_rfauto_p3exc_stage.py"
    stage_path.write_text(stage_src, encoding="utf-8")

    run_calls: list[tuple[str, dict]] = []

    n_freq = 401

    def _fake_calcport(self, sim_path, freq, *args, **kw):
        self.uf_inc = np.ones(n_freq, dtype=complex)
        self.uf_ref = np.full(n_freq, 0.5, dtype=complex)
        self.beta = np.zeros(n_freq)

    # openEMS 引擎类是 cython 不可变类型，不能类级 setattr——用模块 shim +
    # 子类注入（stage 头 `from openEMS import openEMS` 拿到即 shim 类；
    # PEP 562 __getattr__ 透传其余包属性，openEMS.ports 子模块经真实
    # __path__ 照常加载）。
    class _ShimOpenEMS(oe_pkg.openEMS):
        def Run(self, sim_path, verbose=0, **kw):
            run_calls.append((str(sim_path), dict(kw)))

    shim = types.ModuleType("openEMS")
    shim.__path__ = oe_pkg.__path__
    shim.openEMS = _ShimOpenEMS
    shim.__getattr__ = lambda name: getattr(oe_pkg, name)
    monkeypatch.setitem(sys.modules, "openEMS", shim)
    monkeypatch.setattr(MSLPort, "CalcPort", _fake_calcport)
    monkeypatch.setenv("RFAUTO_P3EXC_STAGE", "1")

    scope: dict = {"__name__": "__main__", "__file__": str(stage_path)}
    exec(compile(stage_src, str(stage_path), "exec"), scope)

    # Run 恰一次：fdtd_p3exc 目录、主 Run kwargs 同款
    assert len(run_calls) == 1
    sim_path, kwargs = run_calls[0]
    assert Path(sim_path) == tmp_path / "fdtd_p3exc"
    assert kwargs.get("cleanup") is True
    assert kwargs.get("disable_dumps") is True

    # 激励手术实测（CSXCAD 对象）：e3_ 激励副本在场，主激励属性仍在但禁用
    csx = scope["CSX"]
    exc_names = []
    for _i in range(csx.GetQtyProperties()):
        pr = csx.GetProperty(_i)
        if str(pr.GetTypeString()) == "Excitation":
            exc_names.append(str(pr.GetName()))
    assert any(n.startswith("e3_") for n in exc_names)
    assert any(not n.startswith("e3_") for n in exc_names)

    # sidecar：launcher 同口径回读装配 S23
    sidecar = tmp_path / "sparams_p3exc.csv"
    assert sidecar.exists()
    with open(sidecar, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["freq_hz", "re_S23", "im_S23"]
    assert len(rows) == n_freq + 1
    re_col = [float(r[1]) for r in rows[1:]]
    im_col = [float(r[2]) for r in rows[1:]]
    s23 = np.asarray(re_col) + 1j * np.asarray(im_col)
    assert len(s23) == n_freq and np.all(np.isfinite(s23))
