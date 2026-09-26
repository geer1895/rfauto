"""数据工厂 B2 多保真 MFK 判读单测（合成双保真语料，零 HFSS 零真机）。

被测对象：scripts/factory_m2_mfk_rejudge.py 的纯逻辑面——
- match_freqs：argmin|Δf| 真最近邻（#294：1-ulp 频噪不错位；超容差/塌点报错）；
- synthetic_mf_rows + _fit_and_judge：Forrester 式仿射双保真语料全链
  （门判定、增值门两臂对比表、hi 点数不足报错语义、坏真值如实 FAIL）；
- load_high_anchors：合成锚点目录（anchor.json + skrf 写 s2p）离线加载；
- pair_baseline：基线臂精确同 w 配对与最近邻退化如实记 delta_w；
- 锚点计划纯函数（吸附/held-out 选取/点 id）——factory_mf_hfss_anchors 侧。

诚实口径：坏真值臂 FAIL 也如实出账，不凑绿（#122）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import types
import typing
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

smt = pytest.importorskip("smt", reason="SMT 为可选依赖（extra: smt）")

import skrf as rf

import factory_m2_mfk_rejudge as rj
from rfauto.optimization.surrogate import (  # noqa: F401  注册副作用
    poly_ridge,
    smt_kriging,
    smt_mfk,
    surrogate_registry,
)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m2():
    return _load_script("factory_m2_surrogate")


@pytest.fixture(scope="module")
def anchors_mod():
    return _load_script("factory_mf_hfss_anchors")


# ---------------------------------------------------------------- 频轴


class TestMatchFreqs:
    def test_ulp_noise_nearest_neighbor(self):
        # #294/#287：touchstone 频率带 1-ulp 噪声，最近邻不得越位一格
        grid = np.round(2.4 + 0.01 * np.arange(21), 10)
        src = grid + 1e-9  # 1-ulp 级噪声（GHz 尺度）
        idx, max_delta = rj.match_freqs(src, grid)
        assert idx == list(range(21))
        assert max_delta <= 1e-6

    def test_interleaved_grid_maps_correctly(self):
        # HFSS 41 点 0.005 步进 → 0.01 消费栅格（真最近邻，非 searchsorted）
        src = np.round(2.4 + 0.005 * np.arange(41), 10)
        dst = np.round(2.4 + 0.01 * np.arange(21), 10)
        idx, max_delta = rj.match_freqs(src, dst)
        assert idx == [int(i * 2) for i in range(21)]
        assert max_delta == 0.0

    def test_offgrid_rejected(self):
        src = np.round(2.4 + 0.02 * np.arange(11), 10)  # 无 0.01 奇数倍点
        dst = np.round(2.4 + 0.01 * np.arange(21), 10)
        with pytest.raises(ValueError, match="超容差"):
            rj.match_freqs(src, dst)

    def test_collapsed_grid_rejected(self):
        # 塌点：两个 dst 点（ulp 级近重合，容差内）最近邻落在同一 src 索引
        src = np.array([2.4, 2.5])
        with pytest.raises(ValueError, match=r"塌点|重复"):
            rj.match_freqs(src, np.array([2.4 + 5e-8, 2.4 + 8e-8]))


# ---------------------------------------------------------------- 合成链


def _synthetic_rows(m2, freqs, n_low: int = 40):
    w_grid = np.linspace(0.5, 2.0, n_low)
    return rj.synthetic_mf_rows(freqs, w_grid, [0.5, 2.0, 1.113, 0.9178],
                                [0.9946, 1.5119], m2)


class TestSyntheticChain:
    def test_gates_and_value_add_pass(self, m2):
        freqs = m2.band_freqs(0.05)
        low, train, held = _synthetic_rows(m2, freqs)
        res = rj._fit_and_judge(m2, low, train, held, freqs, lambda _m: None)
        assert res["gates_pass"] == {"gamma_lin": True, "eps_eff_rel": True,
                                     "s21_db": True}
        # 增值门：mfk |ΔΓ| 严格优于"纯 OE 直接当预测"基线（语料按此构造）
        mfk = res["arms"]["smt_mfk"]["gamma_lin"]["max"]
        base = res["arms"]["baseline_oe_direct"]["gamma_lin"]["max"]
        assert mfk <= base
        assert res["value_add_pass"] is True
        # 两臂对比表如实出账（三指标 × 两臂 + 逐点行）
        assert set(res["arms"]) == {"smt_mfk", "baseline_oe_direct"}
        assert len(res["arms"]["smt_mfk"]["per_point"]) == len(held)

    def test_run_rejudge_end_to_end_pass(self, m2, tmp_path):
        freqs = m2.band_freqs(0.05)
        low, train, held = _synthetic_rows(m2, freqs)
        out = tmp_path / "verdict.json"
        verdict = rj.run_rejudge(low, train + held, freqs, m2=m2,
                                 out_path=out, log=lambda _m: None)
        assert verdict["overall"] == "PASS"
        assert verdict["schema"] == "factory_mfk_verdict/1"
        assert verdict["synthetic_recovery"]["pass"] is True
        assert verdict["n_train_anchors"] == 4
        assert verdict["n_held_anchors"] == 2
        assert out.exists()
        reloaded = json.loads(out.read_text(encoding="utf-8"))
        assert reloaded["overall"] == "PASS"

    def test_no_heldout_anchors_pending(self, m2, tmp_path):
        freqs = m2.band_freqs(0.05)
        low, train, _held = _synthetic_rows(m2, freqs)
        verdict = rj.run_rejudge(low, train, freqs, m2=m2,
                                 out_path=tmp_path / "v.json",
                                 log=lambda _m: None)
        assert verdict["overall"] == "PENDING_HIGH_FI"
        assert verdict["synthetic_recovery"]["pass"] is True

    def test_hi_points_insufficient_raises(self, m2):
        freqs = m2.band_freqs(0.05)
        low, train, held = _synthetic_rows(m2, freqs)
        with pytest.raises(ValueError, match="≥2"):
            rj._fit_and_judge(m2, low, train[:1], held, freqs,
                              lambda _m: None)

    def test_corrupted_truth_fails_honestly(self, m2, tmp_path):
        # 坏真值（held 真值人为污染）：门 FAIL 如实出账，不凑绿（#122）
        freqs = m2.band_freqs(0.05)
        low, train, held = _synthetic_rows(m2, freqs)
        held[0]["s11_db"] = held[0]["s11_db"] + 6.0   # |ΔΓ| 必超 0.04
        held[1]["eps_eff"] = held[1]["eps_eff"] * 1.05  # εeff 超 1%
        verdict = rj.run_rejudge(low, train + held, freqs, m2=m2,
                                 out_path=tmp_path / "v.json",
                                 log=lambda _m: None)
        assert verdict["overall"] == "FAIL"
        gates = verdict["judgment"]["gates_pass"]
        assert gates["gamma_lin"] is False
        assert gates["eps_eff_rel"] is False


# ---------------------------------------------------------------- 基线臂


class TestPairBaseline:
    def test_exact_and_nearest_pairing(self, m2):
        freqs = m2.band_freqs(0.05)
        # low 网格显式含 held 精确 w（嵌套语义），另取网格外值试最近邻退化
        w_grid = np.array([0.5, 0.7, 0.9946, 1.5119, 2.0])
        low, _train, held = rj.synthetic_mf_rows(freqs, w_grid, [0.5, 2.0],
                                                 [0.9946], m2)
        off = dict(held[0])
        off["w"] = 1.25  # 不在 low 网格上
        preds, pairing = rj.pair_baseline(low, [held[0], off], freqs,
                                          m2.HEAD_EPS)
        assert pairing[0]["mode"] == "exact"
        assert pairing[0]["delta_w_mm"] == 0.0
        assert pairing[1]["mode"] == "nearest"
        assert pairing[1]["delta_w_mm"] > 0.0
        for pred in preds:
            assert m2.HEAD_EPS in pred


# ---------------------------------------------------------------- 锚点加载


def _write_synthetic_s2p(path: Path, freqs_ghz: np.ndarray,
                         s11_db: float, s21_db: float) -> None:
    n = len(freqs_ghz)
    s11 = 10 ** (s11_db / 20) * np.exp(1j * np.linspace(0.1, 0.3, n))
    s21 = 10 ** (s21_db / 20) * np.exp(1j * np.linspace(-0.4, -0.1, n))
    s = np.zeros((n, 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 1, 0] = s21
    s[:, 0, 1] = s21
    s[:, 1, 1] = s11
    net = rf.Network(frequency=rf.Frequency(freqs_ghz[0], freqs_ghz[-1], n,
                                            "ghz"), s=s)
    net.write_touchstone(str(path))


class TestLoadHighAnchors:
    def test_load_synthetic_anchor_dirs(self, m2, tmp_path):
        freqs = m2.band_freqs(0.05)
        src_grid = np.round(2.4 + 0.005 * np.arange(41), 10)
        for pid, w, group in (("mfa_w0995", 0.9946, "heldout"),
                              ("mfa_w0500", 0.5, "train")):
            d = tmp_path / pid
            d.mkdir()
            _write_synthetic_s2p(d / "sparams.s2p", src_grid,
                                 s11_db=-18.0, s21_db=-0.2)
            (d / "anchor.json").write_text(json.dumps({
                "schema": "factory_mf_anchor/1", "point_id": pid,
                "group": group, "w_mm": w, "status": "done",
                "eps_eff_slope_span": 2.9,
                "touchstone": "sparams.s2p"}), encoding="utf-8")
        rows, notes = rj.load_high_anchors(tmp_path, freqs, m2)
        assert notes == []
        assert len(rows) == 2
        by_pid = {r["point_id"]: r for r in rows}
        assert by_pid["mfa_w0995"]["group"] == "heldout"
        assert by_pid["mfa_w0995"]["w"] == pytest.approx(0.9946)
        assert by_pid["mfa_w0995"]["eps_eff"] == pytest.approx(2.9)
        # 最近邻取栅格：|S11|dB 还原（常数幅值语料）
        assert by_pid["mfa_w0500"]["s11_db"] == pytest.approx(
            np.full(len(freqs), -18.0), abs=1e-6)
        assert by_pid["mfa_w0500"]["s21_db"] == pytest.approx(
            np.full(len(freqs), -0.2), abs=1e-6)
        assert by_pid["mfa_w0500"]["freq_match_max_delta_ghz"] <= 1e-6

    def test_not_done_and_missing_s2p_skipped(self, m2, tmp_path):
        freqs = m2.band_freqs(0.05)
        d1 = tmp_path / "mfa_w0001"
        d1.mkdir()
        (d1 / "anchor.json").write_text(json.dumps(
            {"point_id": "mfa_w0001", "status": "failed", "w_mm": 0.5}),
            encoding="utf-8")
        d2 = tmp_path / "mfa_w0002"
        d2.mkdir()
        (d2 / "anchor.json").write_text(json.dumps(
            {"point_id": "mfa_w0002", "status": "done", "w_mm": 0.6,
             "eps_eff_slope_span": 2.9, "group": "train"}),
            encoding="utf-8")
        rows, notes = rj.load_high_anchors(tmp_path, freqs, m2)
        assert rows == []
        assert len(notes) == 2

    def test_missing_root_returns_note(self, m2, tmp_path):
        rows, notes = rj.load_high_anchors(tmp_path / "nope", m2.band_freqs(1),
                                           m2)
        assert rows == [] and len(notes) == 1


# ---------------------------------------------------------------- 锚点计划


class TestAnchorPlan:
    DATASET_WS: typing.ClassVar[list[float]] = [
                  0.5, 2.0, 1.113, 0.745, 1.182,
                  0.9177777777777778, 0.918141211965742,
                  0.9946453683526097, 0.9865508484454399,
                  1.5119056297406015, 1.5170390659527802, 1.6]

    def test_resolve_snaps_to_dataset_value(self, anchors_mod):
        res = anchors_mod.resolve_anchor_ws(self.DATASET_WS)
        by_nominal = {r["nominal"]: r for r in res}
        assert by_nominal[0.5]["snapped"] is False
        assert by_nominal[0.9178]["run"] == pytest.approx(0.9177777777777778)
        assert by_nominal[0.9178]["snap_delta_mm"] == pytest.approx(
            2.222e-05, rel=1e-2)

    def test_resolve_rejects_unsnappable(self, anchors_mod):
        with pytest.raises(ValueError, match="吸附容差"):
            anchors_mod.resolve_anchor_ws([0.5, 2.0],
                                          anchors=(0.75,))

    def test_heldout_selection_in_range(self, anchors_mod):
        res = anchors_mod.select_heldout_ws(self.DATASET_WS)
        picks = [r["run"] for r in res]
        assert picks[0] == pytest.approx(0.9946453683526097)
        assert picks[1] == pytest.approx(1.5119056297406015)
        for r, (lo, hi) in zip(res, anchors_mod.HELDOUT_RANGES, strict=True):
            assert lo <= r["run"] <= hi

    def test_heldout_empty_range_rejected(self, anchors_mod):
        with pytest.raises(ValueError, match="区间"):
            anchors_mod.select_heldout_ws([0.5, 2.0],
                                          ranges=((0.95, 1.05),))

    def test_build_plan_groups_and_ids(self, anchors_mod):
        plan = anchors_mod.build_anchor_plan(self.DATASET_WS, full=True)
        groups = [p["group"] for p in plan]
        assert groups.count("train") == 6  # 4 基础 + 2 可选
        assert groups.count("heldout") == 2
        assert all(p["line_len_mm"] == anchors_mod.LINE_LEN_MM for p in plan)
        ids = [p["point_id"] for p in plan]
        assert len(ids) == len(set(ids))
        held_ws = [p["w_mm"] for p in plan if p["group"] == "heldout"]
        base_ws = set(self.DATASET_WS)
        assert all(any(abs(w - b) <= 1e-12 for b in base_ws)
                   for w in held_ws)


class TestExtraAnchorWS:
    """resolve_extra_anchor_ws（--extra-w 补充锚；round6 L-E5 单测+吸附去重）。

    与 resolve_anchor_ws 的 SNAP_TOL 吸附不同：直接取最近数据集精确值、
    excluded_ws 剔除既有锚；同批多个 --extra-w 不得吸附到同一数据集值
    （吸附去重，round6 L-E5 后半）。
    """

    WS: typing.ClassVar[list[float]] = TestAnchorPlan.DATASET_WS

    def test_extra_snaps_to_nearest_exact_value(self, anchors_mod):
        res = anchors_mod.resolve_extra_anchor_ws(self.WS, (1.5,))
        assert len(res) == 1
        assert res[0]["run"] == pytest.approx(1.5119056297406015)
        assert res[0]["snapped"] is True
        assert res[0]["snap_delta_mm"] == pytest.approx(
            abs(1.5119056297406015 - 1.5))
        assert res[0]["nominal"] == 1.5

    def test_extra_excludes_existing_anchor_runs(self, anchors_mod):
        # excluded_ws=既有锚值（含 held-out 门点）从候选剔除：最近值被剔
        # 后取次近（门点不入训练，anchor15_criteria.md §1）
        used = 1.5119056297406015
        res = anchors_mod.resolve_extra_anchor_ws(self.WS, (1.5,),
                                                  excluded_ws=(used,))
        assert res[0]["run"] == pytest.approx(1.5170390659527802)
        assert abs(res[0]["run"] - used) > 1e-9

    def test_dedup_two_extras_never_share_one_dataset_value(self, anchors_mod):
        # 吸附去重（round6 L-E5）：两个名义都最近 1.5119…，第一个吸附后
        # 该值出候选，第二个取次近——不得两锚落同一点
        res = anchors_mod.resolve_extra_anchor_ws(self.WS, (1.4, 1.5))
        runs = [r["run"] for r in res]
        assert len(set(runs)) == 2
        assert runs[0] == pytest.approx(1.5119056297406015)
        assert runs[1] == pytest.approx(1.5170390659527802)

    def test_dedup_duplicate_nominal_inputs(self, anchors_mod):
        # 同名义重复传参（--extra-w 1.5 1.5）同样去重，不产生重复锚点
        res = anchors_mod.resolve_extra_anchor_ws(self.WS, (1.5, 1.5))
        runs = [r["run"] for r in res]
        assert len(set(runs)) == 2

    def test_candidates_exhausted_rejected(self, anchors_mod):
        with pytest.raises(ValueError, match="无候选"):
            anchors_mod.resolve_extra_anchor_ws([0.5], (0.6,),
                                                excluded_ws=(0.5,))

    def test_build_plan_with_extra_has_distinct_w(self, anchors_mod):
        # 集成面：extra 经 build_anchor_plan 进 train 组且剔除既有锚含
        # held-out 门点（名义 1.5 的 extra 落 1.5170 而非门点 1.5119）
        plan = anchors_mod.build_anchor_plan(self.WS, extra_ws=(1.5, 1.4))
        ws = [p["w_mm"] for p in plan]
        assert len(ws) == len(set(ws))
        extra = [p for p in plan if p["group"] == "train"
                 and p["w_mm_nominal"] in (1.5, 1.4)]
        assert [(p["w_mm_nominal"], pytest.approx(p["w_mm"]))
                for p in extra] == [(1.5, pytest.approx(1.5170390659527802)),
                                    (1.4, pytest.approx(1.6))]
        # held-out 门点不被补充锚占用（gate 独立性）
        gate = [p for p in plan if p["group"] == "heldout"]
        assert any(p["w_mm"] == pytest.approx(1.5119056297406015)
                   for p in gate)


class TestKillDesktopsOrphanOnly:
    """_kill_desktops 孤儿专用语义钉（round5 E-HIGH-1）。

    旧实现 `Get-Process|Stop-Process -Force` 无条件代杀全部 ansysedt
    （每点每 attempt 调用）——#245/#265 违规。新语义：先枚举（PID/PPID/
    命令行），只杀**父进程已死**的孤儿；活桌面（父进程在）与枚举失败一律
    fail-closed 抛错不代杀（对齐 hfss_interdigital_check.
    _assert_existing_desktops_none 口径）。subprocess.run 全 mock，零真机。
    """

    @staticmethod
    def _ps_result(rc: int, out: str, err: str = ""):
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    @staticmethod
    def _enum_line(pid: int, ppid: int) -> str:
        return f"{pid}|{ppid}|C:\\tools\\ansysedt.exe -grpcsrv -ng"

    def _install_fake_run(self, monkeypatch, *, enum_lines: list[str],
                          enum_rc: int, parent_alive: bool = False,
                          kills: list[int] | None = None) -> dict:
        state = {"enums": 0}
        kills = kills if kills is not None else []

        def fake_run(cmd, **_kw):
            joined = " ".join(cmd)
            if "Get-CimInstance" in joined:
                state["enums"] += 1
                lines = enum_lines if state["enums"] == 1 else []
                return self._ps_result(
                    enum_rc, "\n".join(lines),
                    "" if enum_rc == 0 else "boom")
            if "Get-Process -Id" in joined:
                return self._ps_result(
                    0, "alive" if parent_alive else "dead")
            if "Stop-Process" in joined:
                m = re.search(r"Stop-Process -Id (\d+)", joined)
                assert m is not None, joined
                kills.append(int(m.group(1)))
                return self._ps_result(0, "")
            raise AssertionError(f"未预期的 subprocess 调用: {joined[:120]}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        return state

    def test_live_desktop_not_killed_fail_closed(self, anchors_mod,
                                                 monkeypatch):
        kills: list[int] = []
        self._install_fake_run(monkeypatch,
                               enum_lines=[self._enum_line(111, 222)],
                               enum_rc=0, parent_alive=True, kills=kills)
        monkeypatch.setattr(anchors_mod.time, "sleep", lambda _s: None)
        with pytest.raises(RuntimeError, match="活桌面"):
            anchors_mod._kill_desktops(log=lambda _m: None)
        assert kills == [], "活桌面（父进程在）绝不代杀（#245）"

    def test_orphan_parent_dead_killed_then_verified(self, anchors_mod,
                                                     monkeypatch):
        kills: list[int] = []
        self._install_fake_run(monkeypatch,
                               enum_lines=[self._enum_line(111, 222)],
                               enum_rc=0, parent_alive=False, kills=kills)
        sleeps: list[float] = []
        monkeypatch.setattr(anchors_mod.time, "sleep", sleeps.append)
        logs: list[str] = []
        anchors_mod._kill_desktops(log=logs.append)
        assert kills == [111], "孤儿（父进程已死）点杀该 PID"
        assert sleeps and sleeps[0] > 0, "杀后留退出窗再复核"
        assert any("111" in m for m in logs)

    def test_enum_failure_fail_closed_no_kill(self, anchors_mod,
                                              monkeypatch):
        kills: list[int] = []
        self._install_fake_run(monkeypatch, enum_lines=[], enum_rc=1,
                               kills=kills)
        monkeypatch.setattr(anchors_mod.time, "sleep", lambda _s: None)
        with pytest.raises(RuntimeError, match="枚举失败"):
            anchors_mod._kill_desktops(log=lambda _m: None)
        assert kills == [], "枚举失败 fail-closed，不盲杀（#245）"
