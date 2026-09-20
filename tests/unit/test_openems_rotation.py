"""openems_rotation 逐轮断点缓存单测。

口径：进程隔离激励轮转的每轮 sparams.csv 即断点——重入时「simulation.py
与本次渲染逐字节一致 + 产物可解析」齐备才复用该轮，否则重跑。全部子进程
与 render_script 用桩替换（零 openEMS 依赖），钉住：全跑装配、断点续跑
（只补缺失轮）、陈旧脚本守卫、损坏产物守卫、resume 开关、频率轴一致性、
全结果缓存短路。P2⑬ 增补：n_cols 通用列解析（>4 端口 N=6 装配/.s6p/
五守卫复测/槽位守卫）+ 150 端口实档锚（skipif，机器本地资产）。
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from rfauto.adapters import openems_rotation as rot

FREQ_HZ = (1e9, 2e9)


def _write_round_csv(work_k: Path, k: int,
                     freq_hz: tuple[float, ...] = FREQ_HZ,
                     n_cols: int = 4) -> None:
    """写第 k 轮 n_cols 槽位 CSV（re 列编码轮号 k，可断言数据来源轮次）。

    n_cols=4 时与旧 4 槽固定表头/取值逐字节一致（re=k*10+c+m/10）。
    """
    header = "freq_hz" + "".join(f",re_S{c + 1}1,im_S{c + 1}1"
                                 for c in range(n_cols))
    rows = [header]
    for m, f in enumerate(freq_hz):
        vals: list[float] = [f]
        for c in range(n_cols):
            vals += [k * 10 + c + m / 10.0, float(k)]
        rows.append(",".join(repr(v) for v in vals))
    (work_k / "sparams.csv").write_text("\n".join(rows) + "\n",
                                        encoding="utf-8")


def _make_fake_run(fail_rounds: set[int], calls: list[int],
                   freq_by_round: dict[int, tuple[float, ...]] | None = None,
                   n_cols: int = 4):
    """桩 subprocess.run：按轮号写产物或失败；记录实际执行轮号。"""

    def fake_run(cmd, capture_output, text, timeout, cwd):
        work_k = Path(cwd)
        k = int(work_k.name[1:])
        calls.append(k)
        if k in fail_rounds:
            return types.SimpleNamespace(returncode=1, stderr="boom")
        freq = (freq_by_round or {}).get(k, FREQ_HZ)
        _write_round_csv(work_k, k, freq, n_cols=n_cols)
        return types.SimpleNamespace(returncode=0, stderr="")

    return fake_run


@pytest.fixture()
def fake_render(monkeypatch):
    """桩 render_script：脚本内容编码轮号+代次（换参即变，喂陈旧守卫）。"""
    gen = {"n": 0}

    def _render(template, params, freq_range_ghz, mesh_resolution_mm=0.0,
                excite_port=1):
        return f"SCRIPT-{template}-{excite_port}-gen{gen['n']}"

    monkeypatch.setattr("rfauto.adapters.openems_templates.render_script",
                        _render)
    return gen


def _run(tmp_path, monkeypatch, fake_run, **kwargs) -> dict[str, Any]:
    monkeypatch.setattr("rfauto.adapters.openems_rotation.subprocess.run",
                        fake_run)
    kwargs.setdefault("template", "ratrace")
    kwargs.setdefault("params", {"gen": 0})
    kwargs.setdefault("freq_range_ghz", (1.0, 2.0))
    kwargs.setdefault("n_ports", 4)
    return rot.solve_smatrix_openems(tmp_path, **kwargs)


def test_full_run_assembles_smatrix(tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    result = _run(tmp_path, monkeypatch, _make_fake_run(set(), calls))
    assert calls == [1, 2, 3, 4]
    assert result["ok"] is True
    assert result["resumed_rounds"] == []
    assert result["n_reused"] == 0
    # 列 k = 激励 k 的列；re 编码 k*10+c（第 1 频点 m=0）
    s = result["s_params"]
    assert s.shape == (2, 4, 4)
    assert s[0, 1, 1] == complex(21.0, 2.0)  # S21@激励2
    assert s[1, 3, 3] == complex(43.1, 4.0)  # S41@激励4，第2频点
    assert Path(result["s4p_path"]).exists()
    assert result["freq_ghz"][0] == pytest.approx(1.0)


def test_resume_only_runs_missing_rounds(tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    first = _run(tmp_path, monkeypatch, _make_fake_run({2}, calls),
                 cache=False)
    assert first["ok"] is False and calls == [1, 2]
    # 重入：p1 断点复用，只补跑 p2
    second = _run(tmp_path, monkeypatch, _make_fake_run(set(), calls),
                  cache=False)
    assert calls == [1, 2, 2, 3, 4]  # p1 未重跑；p2 补跑 + p3/p4 首跑
    assert second["ok"] is True
    assert second["resumed_rounds"] == [1]
    assert second["n_reused"] == 1
    assert "断点复用 p1" in second["message"]
    # 复用列与补跑列数据来源正确
    assert second["s_params"][0, 1, 1] == complex(21.0, 2.0)  # p2 补跑
    assert second["s_params"][0, 0, 0] == complex(10.0, 1.0)  # p1 复用


def test_stale_script_forces_round_rerun(tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    assert _run(tmp_path, monkeypatch, _make_fake_run(set(), calls),
                cache=False)["ok"] is True
    # 陈旧守卫：p2 脚本被改动（如换参后残留）→ 该轮必须重跑
    (tmp_path / "p2" / "simulation.py").write_text("SCRIPT-tampered\n",
                                                   encoding="utf-8")
    result = _run(tmp_path, monkeypatch, _make_fake_run(set(), calls),
                  cache=False)
    assert result["ok"] is True
    assert result["resumed_rounds"] == [1, 3, 4]
    assert calls == [1, 2, 3, 4, 2]


def test_corrupt_csv_forces_round_rerun(tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    assert _run(tmp_path, monkeypatch, _make_fake_run(set(), calls),
                cache=False)["ok"] is True
    (tmp_path / "p3" / "sparams.csv").write_text("garbage\n", encoding="utf-8")
    result = _run(tmp_path, monkeypatch, _make_fake_run(set(), calls),
                  cache=False)
    assert result["ok"] is True
    assert result["resumed_rounds"] == [1, 2, 4]
    assert calls == [1, 2, 3, 4, 3]


def test_resume_disabled_reruns_all(tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    assert _run(tmp_path, monkeypatch, _make_fake_run(set(), calls),
                cache=False)["ok"] is True
    result = _run(tmp_path, monkeypatch, _make_fake_run(set(), calls),
                  cache=False, resume=False)
    assert calls == [1, 2, 3, 4, 1, 2, 3, 4]
    assert result["resumed_rounds"] == []


def test_freq_axis_mismatch_detected(tmp_path, monkeypatch, fake_render):
    # 偶数轮频率轴不同 → 首个偶数轮装配时显式报错（不静默混装）
    calls: list[int] = []
    result = _run(tmp_path, monkeypatch,
                  _make_fake_run(set(), calls,
                                 freq_by_round={2: (3e9, 4e9)}),
                  cache=False)
    assert result["ok"] is False
    assert any("频率轴" in e for e in result["errors"])


def test_full_result_cache_short_circuits(tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    assert _run(tmp_path, monkeypatch, _make_fake_run(set(), calls))["ok"]
    assert len(calls) == 4
    cached = _run(tmp_path, monkeypatch, _make_fake_run(set(), calls))
    assert cached["ok"] is True
    assert "缓存复用" in cached["message"]
    assert len(calls) == 4  # 子进程零重跑
    assert cached["elapsed_s"] == 0.0


# ---------------------------------------------------------------------------
# P2⑬ >4 端口通用列解析：n_cols 泛化 + .s{N}p + 槽位守卫（N=6 复测五守卫）
# ---------------------------------------------------------------------------

MAPES_P1_CSV = Path("runs") / "mapes_s2" / "rounds" / "p1" / "sparams.csv"


def test_load_round_csv_generic_width_guard(tmp_path):
    # 13 列 = 1+2×6：n_cols=6 精确解析；n_cols=7 需 15 列 → 拒绝（不再
    # 静默截断，P2⑬ 核心）；n_cols=4 取前 4 槽（保持 >= 超宽容忍语义）。
    p = tmp_path / "sparams.csv"
    header = "freq_hz" + "".join(f",re_S{c + 1}1,im_S{c + 1}1"
                                 for c in range(6))
    rows = [header]
    for m, f in enumerate(FREQ_HZ):
        vals: list[float] = [f]
        for c in range(6):
            vals += [10 + c + m / 10.0, 1.0]
        rows.append(",".join(repr(v) for v in vals))
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    r6 = rot._load_round_csv(p, 6)
    assert r6 is not None and len(r6[1]) == 6
    assert r6[1][5][0] == complex(15.0, 1.0)  # 槽 5 = 第 6 槽位复数组
    assert r6[1][5][1] == complex(15.1, 1.0)
    assert r6[0][0] == pytest.approx(1.0)
    assert rot._load_round_csv(p, 7) is None
    r4 = rot._load_round_csv(p, 4)
    assert r4 is not None and len(r4[1]) == 4


def test_six_port_generic_assembly(tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    result = _run(tmp_path, monkeypatch,
                  _make_fake_run(set(), calls, n_cols=6), n_ports=6)
    assert calls == [1, 2, 3, 4, 5, 6]
    assert result["ok"] is True
    s = result["s_params"]
    assert s.shape == (2, 6, 6)
    # 槽位恒等：轮 k 的槽 i → S(i+1, k)，re=k*10+i+m/10 编码逐值核对
    for k in range(1, 7):
        for i in range(6):
            assert s[0, i, k - 1] == complex(k * 10 + i, float(k))
            assert s[1, i, k - 1] == complex(k * 10 + i + 0.1, float(k))
    # .s{N}p 落盘（缓存命中/装配两处口径）
    assert Path(result["s4p_path"]).name == "ratrace.s6p"
    assert Path(result["s4p_path"]).exists()


def test_six_port_touchstone_roundtrip(tmp_path, monkeypatch, fake_render):
    # 判据③：skrf 回读 .s6p 往返 max|ΔS|=0
    import numpy as np
    import skrf

    result = _run(tmp_path, monkeypatch,
                  _make_fake_run(set(), [], n_cols=6), n_ports=6)
    assert result["ok"] is True
    net = skrf.Network(result["s4p_path"])
    assert net.s.shape == (2, 6, 6)
    assert float(np.abs(net.s - result["s_params"]).max()) == 0.0


def test_six_port_resume_only_runs_missing_rounds(
        tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    first = _run(tmp_path, monkeypatch,
                 _make_fake_run({2}, calls, n_cols=6), n_ports=6, cache=False)
    assert first["ok"] is False and calls == [1, 2]
    second = _run(tmp_path, monkeypatch,
                  _make_fake_run(set(), calls, n_cols=6), n_ports=6,
                  cache=False)
    assert calls == [1, 2, 2, 3, 4, 5, 6]
    assert second["ok"] is True
    assert second["resumed_rounds"] == [1]
    assert second["n_reused"] == 1
    # 复用列（p1）与补跑列（p6）数据来源正确
    assert second["s_params"][0, 0, 0] == complex(10.0, 1.0)
    assert second["s_params"][0, 5, 5] == complex(65.0, 6.0)


def test_six_port_stale_script_forces_round_rerun(
        tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    assert _run(tmp_path, monkeypatch, _make_fake_run(set(), calls, n_cols=6),
                n_ports=6, cache=False)["ok"] is True
    (tmp_path / "p4" / "simulation.py").write_text("SCRIPT-tampered\n",
                                                   encoding="utf-8")
    result = _run(tmp_path, monkeypatch, _make_fake_run(set(), calls, n_cols=6),
                  n_ports=6, cache=False)
    assert result["ok"] is True
    assert result["resumed_rounds"] == [1, 2, 3, 5, 6]
    assert calls == [1, 2, 3, 4, 5, 6, 4]


def test_six_port_corrupt_csv_forces_round_rerun(
        tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    assert _run(tmp_path, monkeypatch, _make_fake_run(set(), calls, n_cols=6),
                n_ports=6, cache=False)["ok"] is True
    (tmp_path / "p5" / "sparams.csv").write_text("garbage\n", encoding="utf-8")
    result = _run(tmp_path, monkeypatch, _make_fake_run(set(), calls, n_cols=6),
                  n_ports=6, cache=False)
    assert result["ok"] is True
    assert result["resumed_rounds"] == [1, 2, 3, 4, 6]
    assert calls == [1, 2, 3, 4, 5, 6, 5]


def test_six_port_freq_axis_mismatch_detected(
        tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    result = _run(tmp_path, monkeypatch,
                  _make_fake_run(set(), calls, n_cols=6,
                                 freq_by_round={3: (3e9, 4e9)}),
                  n_ports=6, cache=False)
    assert result["ok"] is False
    assert any("频率轴" in e for e in result["errors"])


def test_six_port_full_result_cache_short_circuits(
        tmp_path, monkeypatch, fake_render):
    calls: list[int] = []
    assert _run(tmp_path, monkeypatch, _make_fake_run(set(), calls, n_cols=6),
                n_ports=6)["ok"]
    assert len(calls) == 6
    cached = _run(tmp_path, monkeypatch, _make_fake_run(set(), calls, n_cols=6),
                  n_ports=6)
    assert cached["ok"] is True
    assert "缓存复用" in cached["message"]
    assert len(calls) == 6  # 子进程零重跑
    # 缓存命中路径产物名同为 .s{N}p
    assert Path(cached["s4p_path"]).name == "ratrace.s6p"


def test_slot_guard_reruns_round(tmp_path, monkeypatch, fake_render):
    # _absorb_round 槽位守卫：断点轮解析返回槽位数≠n_ports → 按损坏产物
    # 重跑该轮（不装配残缺矩阵、不整体失败）。
    calls: list[int] = []
    assert _run(tmp_path, monkeypatch, _make_fake_run(set(), calls),
                cache=False)["ok"] is True
    real_load = rot._load_round_csv
    poison = {"on": True}

    def bad_load(csv_path, n_cols):
        r = real_load(csv_path, n_cols)
        if poison["on"] and r is not None and "p3" in str(csv_path):
            poison["on"] = False
            return r[0], r[1][:2]  # 槽位数 2≠4
        return r

    monkeypatch.setattr(rot, "_load_round_csv", bad_load)
    result = _run(tmp_path, monkeypatch, _make_fake_run(set(), calls),
                  cache=False)
    assert result["ok"] is True
    assert result["resumed_rounds"] == [1, 2, 4]
    assert calls == [1, 2, 3, 4, 3]  # 仅 p3 重跑
    assert result["s_params"].shape == (2, 4, 4)


@pytest.mark.skipif(not MAPES_P1_CSV.exists(),
                    reason="机器本地实档缺失（runs/ 不入库，#226）")
def test_real_150_port_archive_parses_full_width():
    # 判据④实档锚：runs/mapes_s2/rounds/p1（150 端口 A8 实跑归档，301 列）。
    # 旧解析器对本归档静默返 4 槽（本会话复现实证）；新守卫须整宽解析。
    import numpy as np

    fg, col = rot._load_round_csv(MAPES_P1_CSV, 150)
    assert fg is not None and col is not None
    data = np.loadtxt(str(MAPES_P1_CSV), delimiter=",", skiprows=1, ndmin=2)
    assert data.shape == (41, 301)
    assert len(col) == 150
    assert np.column_stack(col).shape == (41, 150)
    assert fg[0] == pytest.approx(1.0) and fg[-1] == pytest.approx(6.0)
    # 与 numpy 直切片逐值 allclose（槽 i ↔ 列 (1+2i, 2+2i)）
    for i in range(150):
        expected = data[:, 1 + 2 * i] + 1j * data[:, 2 + 2 * i]
        assert np.allclose(col[i], expected)
    # 反向回归：n_cols=301 需 603 列 > 301 → 拒绝（静默截断堵死实证）
    assert rot._load_round_csv(MAPES_P1_CSV, 301) is None
