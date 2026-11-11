"""core/neural_batch + service/neural_batch_service 单测（aurora_r R-28 / C2 前半）。

分层（与 test_neural_surrogate 同口径）：
- torch 依赖钉用 skipif 钉住，装了才跑；torch 缺失环境跳过该组，其余组
  照常全跑。逐位一致的诚实两层（#122，实证 torch 2.14.0+cpu/Windows
  MKL dgemm/dgemv 按批量维重结合、批量 M=N vs 逐个 M=1 非逐位）：
  ①单候选 batch_evaluate 与 R-05 predict_mlp 逐个前向**逐位一致**
  （同 M=1 内核路径）+ 双跑确定性逐位；②批量 vs 逐个 ≤1e-12 相对一致；
- numpy 降级路径：批量 vs 逐行 ≤1e-15 相对一致（BLAS dgemm 阻塞随批量
  维变化、无逐位保证——house 口径同 test_neural_surrogate
  test_batch_and_vector_forms）；
- numpy vs torch 跨引擎等价钉（小规模，#118 双源对拍口径 ≤1e-12）；
- 打分注入合成：score_fn 按调用序回收已知分数表 → 已知最优候选可回收
  +并列分数稳定序（同分按候选原始下标，select_by_sigma 同口径）；
- 上限棘轮（n_candidates=100001 显式拒绝点名 100000）与 unavailable
  信封透传；service 编排（LHS 候选域/命中明细/确定性复现/模型文件装载）。

夹具：神经网络权重由 default_rng 确定性生成、以纯 list state 手工装配
fit 信封（零 torch 依赖可构造；torch 引擎经 state 回载同权重消费）——
曲线数值为夹具非物理断言（test_neural_surrogate 同纪律）。
"""

from __future__ import annotations

import json
import math
import sys
import typing
from pathlib import Path

import numpy as np
import pytest

_src_dir = Path(__file__).parent.parent.parent / "src"
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

import rfauto.core.neural_batch as nb
from rfauto.core.neural_batch import batch_evaluate
from rfauto.core.neural_surrogate import (
    TORCH_INSTALL_HINT,
    MLPSpec,
    build_sparam_dataset,
    fit_normalization,
    mlp_spec_to_dict,
    predict_mlp,
    torch_available,
)
from rfauto.service.neural_batch_service import (
    NEURAL_BATCH_MAX_CANDIDATES,
    curve_measures,
    make_target_score_fn,
    optimize_with_neural_surrogate,
    parse_inverse_targets,
    score_against_targets,
)


def _torch_ok() -> bool:
    """torch 可用性懒探测（skipif 条件；无 torch 环境不炸收集）。"""
    try:
        return torch_available()
    except Exception:  # pragma: no cover - 探测自身异常按缺失处理
        return False


_requires_torch = pytest.mark.skipif(
    not _torch_ok(), reason="torch 为可选依赖（extra: torch），未安装跳过")

_FREQS = np.linspace(1.0e9, 2.0e9, 8)


def _curve(x: float, k: int) -> complex:
    """单参数光滑复响应夹具（衰减+线性相位，数值非物理断言）。"""
    return complex(0.6 - 0.3 * x, -0.05 * x * k)


def _hand_env(param_names: tuple[str, ...] = ("x",),
              fixed_params: tuple[str, ...] = (),
              const_value: float = 2.0) -> dict:
    """手工装配 fit 信封（纯 list state，零 torch 依赖；torch 引擎经
    state 回载同权重消费——两引擎同权重的公平对拍面）。
    ``fixed_params`` 内的参数取定值 const_value（构造退化维/全退化域）。"""
    samples = []
    for i in range(12):
        x = i / 11.0
        params: dict[str, float] = {
            nm: float(const_value) if nm in fixed_params else float(x)
            for nm in param_names}
        samples.append({
            "params": params,
            "curves": {"s21": [_curve(float(x), k) for k in range(8)]},
        })
    ds = build_sparam_dataset(samples, freqs_hz=_FREQS.tolist())
    spec = MLPSpec(n_inputs=len(param_names), n_outputs=ds["n_outputs"],
                   hidden=(6, 6), activation="tanh")
    rng = np.random.default_rng(7)
    dims = [spec.n_inputs, *spec.hidden, spec.n_outputs]
    state = {"layers": [
        {"W": rng.normal(0.0, 0.3, (dims[i + 1], dims[i])).tolist(),
         "b": rng.normal(0.0, 0.1, dims[i + 1]).tolist()}
        for i in range(len(dims) - 1)]}
    nx = fit_normalization(np.asarray(ds["X"], dtype=float), "minmax")
    ny = fit_normalization(np.asarray(ds["Y"], dtype=float), "minmax")
    return {
        "ok": True,
        "kind": "neural_surrogate_mlp",
        "spec": mlp_spec_to_dict(spec),
        "state": state,
        "norm_x": nx.to_dict(),
        "norm_y": ny.to_dict(),
        "param_names": ds["param_names"],
        "channels": ds["channels"],
        "freqs_hz": ds["freqs_hz"],
        "channel_offsets": ds["channel_offsets"],
        "n_grid": ds["n_grid"],
        "n_outputs": ds["n_outputs"],
    }


def _candidates(n: int = 9) -> list[dict[str, float]]:
    return [{"x": float(v)} for v in np.linspace(0.05, 0.95, n)]


def _score_first_re(resp: dict) -> float:
    return float(resp["curves"]["s21"]["re"][0])


def _curves_of(entry: dict) -> tuple[np.ndarray, np.ndarray]:
    c = entry["pred_response"]["curves"]["s21"]
    return (np.asarray(c["re"], dtype=float),
            np.asarray(c["im"], dtype=float))


# ─── 钉① torch 引擎：批量前向 vs 逐个前向（逐位边界诚实两层） ──────────────


@_requires_torch
class TestTorchBatchForward:
    def test_batch_vs_row_equivalence(self):
        """批量（M=N 单次矩阵 forward）vs 逐个（batch=1 循环）前向等价。

        诚实边界（模块 docstring 批量口径节）：torch/Windows MKL 的
        dgemm/dgemv 按批量维重结合（实证 max abs ~2e-15），本钉为
        ≤1e-12 相对一致（#118 跨实现对拍同容差）+ 排序一致 + 分数一致；
        逐位钉见 test_single_candidate_vs_predict_mlp_bitwise（M=1 同
        内核路径，逐位成立）。
        """
        env = _hand_env()
        cands = _candidates(9)
        whole = batch_evaluate(env, cands, _score_first_re)
        assert whole["ok"] is True
        assert whole["engine"] == "torch_batch"
        assert whole["n_evaluated"] == 9
        per = [batch_evaluate(env, [c], _score_first_re) for c in cands]
        per_scores = [e["ranked"][0]["score"] for e in per]
        expect_order = sorted(range(len(per_scores)),
                              key=lambda i: (-per_scores[i], i))
        assert [e["index"] for e in whole["ranked"]] == expect_order
        for w in whole["ranked"]:
            p = per[w["index"]]["ranked"][0]
            assert p["index"] == 0  # 单候选调用：原始下标恒 0
            np.testing.assert_allclose(
                [w["score"]], [p["score"]], rtol=1e-12, atol=1e-12)
            wr, wi = _curves_of(w)
            pr, pi = _curves_of(p)
            np.testing.assert_allclose(wr, pr, rtol=1e-12, atol=1e-12)
            np.testing.assert_allclose(wi, pi, rtol=1e-12, atol=1e-12)
            assert w["params"] == p["params"] == cands[w["index"]]

    def test_single_candidate_vs_predict_mlp_bitwise(self):
        """逐位钉（M=1 同内核路径）：单候选 batch_evaluate 与 R-05
        predict_mlp 逐个前向逐位一致（曲线 re/im + 分数全部 ==）。"""
        env = _hand_env()
        cands = _candidates(9)
        whole = batch_evaluate(env, cands, _score_first_re)
        for w in whole["ranked"]:
            c = cands[w["index"]]
            single = batch_evaluate(env, [c], _score_first_re)["ranked"][0]
            pm = predict_mlp(env, c)
            assert pm["ok"] is True
            sr, si = _curves_of(single)
            pr = np.asarray(pm["curves"]["s21"]["re"], dtype=float)
            pi = np.asarray(pm["curves"]["s21"]["im"], dtype=float)
            assert np.array_equal(sr, pr)  # 逐位（bitwise）
            assert np.array_equal(si, pi)
            assert single["score"] == w["score"]  # 逐位（float ==）

    def test_double_run_deterministic_bitwise(self):
        """同调用双跑确定性：同权重同输入两次批量前向曲线逐位一致。"""
        env = _hand_env()
        cands = _candidates(9)
        r1 = batch_evaluate(env, cands, _score_first_re)
        r2 = batch_evaluate(env, cands, _score_first_re)
        assert json.dumps(r1["ranked"], sort_keys=True) \
            == json.dumps(r2["ranked"], sort_keys=True)
        for a, b in zip(r1["ranked"], r2["ranked"], strict=True):
            ar, ai = _curves_of(a)
            br, bi = _curves_of(b)
            assert np.array_equal(ar, br)
            assert np.array_equal(ai, bi)

    def test_single_forward_not_per_row_loop(self):
        """批量收益面钉：一次调用只做一次矩阵 forward 的可观察证据 =
        候选数翻倍时 torch 重建次数不变（每调用恒一次 build+load）。"""
        env = _hand_env()
        r9 = batch_evaluate(env, _candidates(9), _score_first_re)
        r18 = batch_evaluate(env, _candidates(18), _score_first_re)
        assert r9["n_candidates"] == 9 and r18["n_candidates"] == 18
        assert r9["engine"] == r18["engine"] == "torch_batch"


# ─── 钉② numpy 降级：批量 vs 逐行 ≤1e-15（house 口径） ────────────────────


class TestNumpyDegraded:
    def test_degraded_engine_batch_vs_row(self, monkeypatch):
        monkeypatch.setattr(nb, "_load_torch", lambda: None)
        env = _hand_env()
        cands = _candidates(9)
        whole = batch_evaluate(env, cands, _score_first_re)
        assert whole["ok"] is True
        assert whole["engine"] == "numpy_degraded"
        assert "非 torch/GPU 档" in whole["engine_note"]
        per = [batch_evaluate(env, [c], _score_first_re) for c in cands]
        per_scores = [e["ranked"][0]["score"] for e in per]
        expect_order = sorted(range(len(per_scores)),
                              key=lambda i: (-per_scores[i], i))
        assert [e["index"] for e in whole["ranked"]] == expect_order
        for w in whole["ranked"]:
            p = per[w["index"]]["ranked"][0]
            wr, wi = _curves_of(w)
            pr, pi = _curves_of(p)
            # BLAS dgemm 阻塞随批量维变化：≤1e-15 相对一致，无逐位保证
            np.testing.assert_allclose(wr, pr, rtol=1e-15, atol=0.0)
            np.testing.assert_allclose(wi, pi, rtol=1e-15, atol=0.0)
            np.testing.assert_allclose(
                [w["score"]], [p["score"]], rtol=1e-15, atol=0.0)

    @_requires_torch
    def test_numpy_matches_torch(self, monkeypatch):
        """降级路径 numpy 与 torch 等价钉（小规模，#118 双源对拍口径）。"""
        env = _hand_env()
        cands = _candidates(9)
        t = batch_evaluate(env, cands, _score_first_re)
        monkeypatch.setattr(nb, "_load_torch", lambda: None)
        n = batch_evaluate(env, cands, _score_first_re)
        assert t["engine"] == "torch_batch"
        assert n["engine"] == "numpy_degraded"
        assert [e["index"] for e in t["ranked"]] == \
            [e["index"] for e in n["ranked"]]
        for et, en in zip(t["ranked"], n["ranked"], strict=True):
            tr, ti = _curves_of(et)
            nr, ni = _curves_of(en)
            np.testing.assert_allclose(tr, nr, rtol=1e-12, atol=1e-12)
            np.testing.assert_allclose(ti, ni, rtol=1e-12, atol=1e-12)
            np.testing.assert_allclose(
                [et["score"]], [en["score"]], rtol=1e-12, atol=1e-12)

    def test_numpy_env_json_roundtrip(self, monkeypatch):
        """state 为纯 list 权重：信封 JSON 往返后降级引擎逐位复现
        （无 torch 环境的部署面前置，mlp_forward_numpy docstring 口径）。"""
        monkeypatch.setattr(nb, "_load_torch", lambda: None)
        env = _hand_env()
        cands = _candidates(5)
        r1 = batch_evaluate(env, cands, _score_first_re)
        env2 = json.loads(json.dumps(env))
        r2 = batch_evaluate(env2, json.loads(json.dumps(cands)),
                            _score_first_re)
        assert np.array_equal(
            np.asarray(r1["ranked"][0]["pred_response"]["curves"]["s21"]["re"]),
            np.asarray(r2["ranked"][0]["pred_response"]["curves"]["s21"]["re"]))


# ─── 钉③ 打分注入合成：已知最优候选可回收 ──────────────────────────────────


class TestScoreInjection:
    def test_known_best_recovered(self):
        """score_fn 按调用序（=候选序）回收已知分数表：已知最优=表 argmax
        （并列取先出现者），ranked[0] 必须回收该候选。"""
        env = _hand_env()
        cands = _candidates(5)
        table = [0.5, -1.0, 3.0, 3.0, 0.0]
        calls: list[int] = []

        def sf(_resp: dict) -> float:
            calls.append(1)
            return table[len(calls) - 1]

        r = batch_evaluate(env, cands, sf, top_k=3)
        assert r["ok"] is True
        assert r["n_evaluated"] == 5
        assert len(calls) == 5  # 逐候选调用序=候选序（打分合同）
        assert [e["index"] for e in r["ranked"]] == [2, 3, 0]
        assert r["ranked"][0]["score"] == 3.0
        assert r["ranked"][0]["params"] == cands[2]
        assert r["top_k"] == 3

    def test_score_fn_from_targets_recovers_measures(self):
        """make_target_score_fn 注入：以合成深谷曲线构造已知最优候选
        （谷对准目标 f0/dip），同批干扰候选 → 最优必被回收。"""
        targets = {"t1": {"f0_ghz": 1.5, "dip_db": -40.0,
                          "tol_freq_rel": 0.02, "tol_dip_db": 1.0}}
        sf = make_target_score_fn(targets, "s21")
        grid = np.linspace(1.0e9, 2.0e9, 21)

        def resp_with_dip(f0_hz: float, depth: float) -> dict:
            f_ghz = grid / 1e9
            mag = 0.5 - (0.5 - depth) * np.exp(
                -((f_ghz - f0_hz / 1e9) ** 2) / (2 * 0.02 ** 2))
            return {"curves": {"s21": {"re": mag.tolist(),
                                       "im": [0.0] * grid.size}},
                    "freqs_hz": grid.tolist(), "channels": ["s21"]}

        good = resp_with_dip(1.5e9, 0.01)   # 谷对准目标：f0=1.5, dip≈-40
        bad1 = resp_with_dip(1.8e9, 0.01)   # 频偏
        bad2 = resp_with_dip(1.5e9, 0.45)   # 谷浅
        assert sf(good) > sf(bad1)
        assert sf(good) > sf(bad2)
        env = _hand_env()
        cands = [{"x": 0.1}, {"x": 0.5}, {"x": 0.9}]
        table = [sf(bad1), sf(good), sf(bad2)]
        calls: list[int] = []

        def injected(_resp: dict) -> float:
            calls.append(1)
            return table[len(calls) - 1]

        r = batch_evaluate(env, cands, injected)
        assert r["ranked"][0]["index"] == 1  # 已知最优候选回收
        assert r["ranked"][0]["score"] == pytest.approx(sf(good))


# ─── 钉④ top-k 排序边界：并列分数稳定序 ────────────────────────────────────


class TestTopKStableOrder:
    def test_tie_breaks_by_original_index(self):
        env = _hand_env()
        cands = _candidates(5)
        r = batch_evaluate(env, cands, lambda _r: 3.0)
        assert [e["index"] for e in r["ranked"]] == [0, 1, 2, 3, 4]
        assert all(e["score"] == 3.0 for e in r["ranked"])

    def test_top_k_truncates_and_none_returns_all(self):
        env = _hand_env()
        cands = _candidates(6)
        full = batch_evaluate(env, cands, lambda _r: 1.0)
        assert full["top_k"] == 6 and len(full["ranked"]) == 6
        k3 = batch_evaluate(env, cands, lambda _r: 1.0, top_k=4)
        assert k3["top_k"] == 4
        assert [e["index"] for e in k3["ranked"]] == [0, 1, 2, 3]
        assert [e["rank"] for e in k3["ranked"]] == [0, 1, 2, 3]

    def test_top_k_larger_than_pool(self):
        env = _hand_env()
        r = batch_evaluate(env, _candidates(3),
                           lambda _r: 0.0, top_k=99)
        assert len(r["ranked"]) == 3 and r["top_k"] == 3

    def test_top_k_invalid(self):
        env = _hand_env()
        assert batch_evaluate(env, _candidates(3), lambda _r: 0.0,
                              top_k=0)["ok"] is False
        assert batch_evaluate(env, _candidates(3), lambda _r: 0.0,
                              top_k=-2)["ok"] is False


# ─── 钉⑤ 信封守卫面（core）：结构违例/丢弃/评分排除/unavailable ────────────


class TestCoreGuards:
    def test_score_fn_not_callable(self):
        r = batch_evaluate(_hand_env(), _candidates(3), "not-callable")
        assert r["ok"] is False and "score_fn" in r["errors"][0]

    def test_unavailable_env_passthrough(self):
        env = {"ok": False, "unavailable": True,
               "errors": ["torch 未安装"], "install_hint": TORCH_INSTALL_HINT}
        r = batch_evaluate(env, _candidates(3), _score_first_re)
        assert r["ok"] is False
        assert r["unavailable"] is True
        assert r["install_hint"] == TORCH_INSTALL_HINT
        assert "numpy 降级也无 state 可前向" in r["errors"][0]

    def test_not_ok_env_without_unavailable(self):
        r = batch_evaluate({"ok": False, "errors": ["x"]},
                           _candidates(3), _score_first_re)
        assert r["ok"] is False and r.get("unavailable") is not True

    def test_malformed_env_missing_keys(self):
        env = _hand_env()
        del env["norm_y"]
        r = batch_evaluate(env, _candidates(3), _score_first_re)
        assert r["ok"] is False and "norm_y" in r["errors"][0]

    def test_empty_candidates(self):
        r = batch_evaluate(_hand_env(), [], _score_first_re)
        assert r["ok"] is False and "为空" in r["errors"][0]

    def test_candidates_shape_violation(self):
        r = batch_evaluate(_hand_env(), {"x": 0.5}, _score_first_re)
        assert r["ok"] is False and "参数字典序列" in r["errors"][0]

    def test_candidate_missing_param_named(self):
        r = batch_evaluate(_hand_env(), [{"y": 0.5}, {"x": 0.5}],
                           _score_first_re)
        assert r["ok"] is False
        assert "候选 0" in r["errors"][0] and "['x']" in r["errors"][0]

    def test_candidate_non_numeric_named(self):
        r = batch_evaluate(_hand_env(), [{"x": "0.5"}], _score_first_re)
        assert r["ok"] is False and "非数值化" in r["errors"][0]

    def test_nonfinite_param_dropped_with_count(self):
        env = _hand_env()
        cands = [{"x": 0.1}, {"x": float("nan")}, {"x": 0.9}]
        r = batch_evaluate(env, cands, _score_first_re)
        assert r["ok"] is True
        assert r["n_candidates"] == 3 and r["n_dropped"] == 1
        assert r["dropped"][0]["index"] == 1
        assert all(e["index"] != 1 for e in r["ranked"])

    def test_all_dropped_is_error(self):
        r = batch_evaluate(_hand_env(),
                           [{"x": float("inf")}, {"x": float("nan")}],
                           _score_first_re)
        assert r["ok"] is False and "全部候选" in r["errors"][0]

    def test_score_nonfinite_excluded(self):
        env = _hand_env()
        calls: list[int] = []

        def sf(resp: dict) -> float:
            calls.append(1)
            v = float(resp["curves"]["s21"]["re"][0])
            return float("nan") if len(calls) == 3 else v  # 第 3 候选非法

        r = batch_evaluate(env, _candidates(5), sf)
        assert r["ok"] is True and r["n_score_invalid"] == 1
        assert {e["index"] for e in r["ranked"]} == {0, 1, 3, 4}

    def test_score_bool_excluded(self):
        r = batch_evaluate(_hand_env(), _candidates(3), lambda _r: True)
        assert r["ok"] is True and r["n_score_invalid"] == 3
        assert r["n_evaluated"] == 0 and r["ranked"] == []

    def test_score_exception_recorded_not_fatal(self):
        env = _hand_env()
        calls: list[int] = []

        def sf(resp: dict) -> float:
            calls.append(1)
            if len(calls) == 3:  # 第 3 候选打分器炸（调用序=候选序合同）
                raise RuntimeError("打分器炸了")
            return float(resp["curves"]["s21"]["re"][0])

        r = batch_evaluate(env, _candidates(5), sf)
        assert r["ok"] is True and r["n_score_failed"] == 1
        assert r["score_failures"][0]["index"] == 2
        assert r["score_failures"][0]["error"].startswith("RuntimeError")
        assert not r["score_failures_truncated"]
        assert {e["index"] for e in r["ranked"]} == {0, 1, 3, 4}


# ─── 测度提取与命中度纯函数（em_bench inverse_design 判据同口径） ───────────


class TestMeasuresAndTargets:
    GRID: typing.ClassVar[list[float]] = [1.0e9, 1.25e9, 1.5e9, 1.75e9, 2.0e9]

    def _resp(self, mags: list[float]) -> dict:
        return {"curves": {"s21": {"re": mags, "im": [0.0] * len(mags)}},
                "freqs_hz": self.GRID, "channels": ["s21"]}

    def test_curve_measures_argmin_and_floor(self):
        m = curve_measures(self._resp([0.5, 0.2, 0.01, 0.3, 0.4]), "s21")
        assert m["f0_ghz"] == 1.5  # argmin 频点（1.5e9/1e9 逐位精确）
        assert m["dip_db"] == pytest.approx(-40.0, abs=1e-9)
        assert m["f0_index"] == 2

    def test_curve_measures_db_floor(self):
        m = curve_measures(self._resp([0.0, 0.5, 0.3, 0.2, 0.1]), "s21")
        assert m["dip_db"] == pytest.approx(-240.0, abs=1e-6)  # 地板 -240 dB

    def test_curve_measures_channel_missing(self):
        with pytest.raises(ValueError, match="缺通道"):
            curve_measures(self._resp([0.5] * 5), "s11")

    def test_curve_measures_shape_violation(self):
        with pytest.raises(ValueError, match="形状违例"):
            curve_measures(self._resp([0.5] * 3), "s21")

    def test_parse_targets_fail_closed(self):
        ok = {"targets": {"t": {"f0_ghz": 1.0, "dip_db": -40.0,
                                "tol_freq_rel": 0.1, "tol_dip_db": 2.0}}}
        assert parse_inverse_targets(ok)["t"]["f0_ghz"] == 1.0
        for bad in [{}, {"targets": {}}, {"targets": {"t": {}}},
                    {"targets": {"t": {"f0_ghz": 0.0, "dip_db": -40.0,
                                       "tol_freq_rel": 0.1,
                                       "tol_dip_db": 2.0}}},
                    {"targets": {"t": {"f0_ghz": 1.0, "dip_db": -40.0}}},
                    {"targets": {"t": {"f0_ghz": 1.0, "dip_db": -40.0,
                                       "tol_freq_rel": -0.1,
                                       "tol_dip_db": 2.0}}}]:
            with pytest.raises(ValueError):
                parse_inverse_targets(bad)

    def test_hit_boundary_and_score_hand_computed(self):
        # 1.0/1.25/0.25 全为二进制精确值——dev == tol 边界逐位可判
        targets = {"t": {"f0_ghz": 1.0, "dip_db": -40.0,
                         "tol_freq_rel": 0.25, "tol_dip_db": 1.0}}
        # 边界恰等：dev == tol → hit（≤ 语义同 em_bench）
        det = score_against_targets(
            {"f0_ghz": 1.25, "dip_db": -41.0}, targets)
        assert det["rows"][0]["freq_dev_rel"] == 0.25
        assert det["rows"][0]["hit"] is True
        assert det["n_hits"] == 1 and det["score"] == 1.0
        # miss：freq_dev=0.5/tol=0.25 → ratio 2.0 → excess 1.0；dip 轴达标
        det2 = score_against_targets({"f0_ghz": 1.5, "dip_db": -40.5}, targets)
        assert det2["rows"][0]["hit"] is False
        # 单目标 miss：excess=2.0−1=1.0 → 封顶 1 → score = 0 − 1/2
        assert det2["score"] == pytest.approx(-0.5)
        # 命中数严格主导：2 目标 1 命中 > 0 命中（罚项封顶 + /(T+1) 性质）
        t2 = {"a": targets["t"],
              "b": {"f0_ghz": 2.0, "dip_db": -30.0,
                    "tol_freq_rel": 0.25, "tol_dip_db": 1.0}}
        d_hit1 = score_against_targets(
            {"f0_ghz": 1.0, "dip_db": -40.0}, t2)
        d_hit0 = score_against_targets(
            {"f0_ghz": 1.5, "dip_db": -35.0}, t2)
        assert d_hit1["n_hits"] == 1 > d_hit0["n_hits"] == 0
        assert d_hit1["score"] == pytest.approx(1.0 - 1.0 / 3.0)
        assert d_hit0["score"] == pytest.approx(-2.0 / 3.0)
        assert d_hit1["score"] > d_hit0["score"]

    def test_tol_zero_semantics(self):
        targets = {"t": {"f0_ghz": 1.5, "dip_db": -40.0,
                         "tol_freq_rel": 0.0, "tol_dip_db": 0.0}}
        exact = score_against_targets({"f0_ghz": 1.5, "dip_db": -40.0}, targets)
        assert exact["rows"][0]["hit"] is True  # 恰等命中（tol=0 合法预声明）
        assert exact["score"] == 1.0 and math.isfinite(exact["score"])
        miss = score_against_targets({"f0_ghz": 1.5, "dip_db": -39.0}, targets)
        assert miss["rows"][0]["hit"] is False
        # 巨额比值被罚项封顶接管：score = 0 − 1/2（有限、确定性沉底）
        assert math.isfinite(miss["score"])
        assert miss["score"] == pytest.approx(-0.5)


# ─── 钉⑥ service 编排：候选域/棘轮/unavailable/确定性/模型文件 ─────────────


class TestOptimizeService:
    TARGETS: typing.ClassVar[dict] = {"t1": {"f0_ghz": 1.4, "dip_db": -30.0,
                                             "tol_freq_rel": 0.5,
                                             "tol_dip_db": 30.0}}

    def _run(self, env: dict, **kw) -> dict:
        spec = {"targets": {tid: dict(t) for tid, t in self.TARGETS.items()}}
        spec.update({k: v for k, v in kw.items() if k == "channel"})
        return optimize_with_neural_surrogate(
            env, spec, n_candidates=kw.pop("n_candidates", 32),
            top_k=kw.pop("top_k", 4), seed=kw.pop("seed", 3),
            bounds=kw.pop("bounds", None))

    def test_happy_path_norm_window_and_hit_detail(self):
        env = _hand_env()
        res = self._run(env)
        assert res["ok"] is True
        assert res["kind"] == "neural_batch_optimize"
        assert res["n_candidates"] == 32 and res["top_k"] == 4
        assert len(res["ranked"]) == 4
        assert res["best"] == res["ranked"][0]
        assert res["bounds_source"] == "norm_window"
        assert res["fixed_dims"] == {}
        assert res["engine"] in ("torch_batch", "numpy_degraded")
        assert res["elapsed_s"] >= 0.0
        for e in res["ranked"]:
            v = e["params"]["x"]
            lo, hi = res["bounds"]["x"]
            assert lo <= v <= hi  # LHS 候选落在派生观测窗内
            assert "measures" in e and "hit_detail" in e
            rows = e["hit_detail"]["rows"]
            assert rows[0]["target_id"] == "t1"
            assert {"freq_dev_rel", "dip_dev_db", "tol_freq_rel",
                    "tol_dip_db", "hit"} <= set(rows[0])
            # 明细与 measures 自洽（同纯函数重算的确定性一致面）
            assert e["hit_detail"]["score"] == pytest.approx(e["score"])

    def test_determinism_same_seed(self):
        env = _hand_env()
        r1 = self._run(env, seed=11)
        r2 = self._run(env, seed=11)
        r1.pop("elapsed_s"), r2.pop("elapsed_s")
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)

    def test_explicit_bounds_honored(self):
        res = self._run(_hand_env(), bounds={"x": (0.2, 0.6)})
        assert res["ok"] is True
        assert res["bounds_source"] == "explicit"
        for e in res["ranked"]:
            assert 0.2 <= e["params"]["x"] <= 0.6

    def test_degenerate_dim_fixed(self):
        env = _hand_env(param_names=("x", "y"), fixed_params=("y",))
        res = self._run(env)
        assert res["ok"] is True
        assert res["fixed_dims"] == {"y": 2.0}
        assert "y" not in res["bounds"]
        assert all(e["params"]["y"] == 2.0 for e in res["ranked"])

    def test_ratchet_cap(self):
        assert NEURAL_BATCH_MAX_CANDIDATES == 100000
        r = self._run(_hand_env(), n_candidates=100001)
        assert r["ok"] is False
        assert "100000" in r["errors"][0]
        assert self._run(_hand_env(), n_candidates=0)["ok"] is False
        assert self._run(_hand_env(), top_k=0)["ok"] is False
        assert optimize_with_neural_surrogate(
            _hand_env(), {"targets": self.TARGETS}, n_candidates="abc",
            top_k=2)["ok"] is False

    def test_spec_and_model_guards(self):
        env = _hand_env()
        assert optimize_with_neural_surrogate(
            env, {}, n_candidates=8, top_k=2)["ok"] is False  # 缺 targets
        assert optimize_with_neural_surrogate(
            env, {"targets": self.TARGETS, "channel": "s22"},
            n_candidates=8, top_k=2)["ok"] is False  # 未知通道
        bad_bounds = optimize_with_neural_surrogate(
            env, {"targets": self.TARGETS}, n_candidates=8, top_k=2,
            bounds={"x": (0.0, 1.0), "zz": (0.0, 1.0)})
        assert bad_bounds["ok"] is False  # bounds 键集须=param_names

    def test_unavailable_and_malformed_model(self):
        un = {"ok": False, "unavailable": True, "errors": ["torch 未安装"],
              "install_hint": TORCH_INSTALL_HINT}
        r = optimize_with_neural_surrogate(
            un, {"targets": self.TARGETS}, n_candidates=8, top_k=2)
        assert r["ok"] is False and r["unavailable"] is True
        r2 = optimize_with_neural_surrogate(
            {"ok": False, "errors": ["x"]}, {"targets": self.TARGETS},
            n_candidates=8, top_k=2)
        assert r2["ok"] is False and r2.get("unavailable") is not True
        env = _hand_env()
        del env["state"]
        r3 = optimize_with_neural_surrogate(
            env, {"targets": self.TARGETS}, n_candidates=8, top_k=2)
        assert r3["ok"] is False  # batch 侧缺键校验透传

    def test_model_file_roundtrip(self, tmp_path):
        env = _hand_env()
        path = tmp_path / "fit_env.json"
        path.write_text(json.dumps(env), encoding="utf-8")
        r = optimize_with_neural_surrogate(
            str(path), {"targets": self.TARGETS}, n_candidates=16, top_k=2)
        assert r["ok"] is True
        # 与 dict 直传同结果（elapsed_s 除外）
        r2 = optimize_with_neural_surrogate(
            env, {"targets": self.TARGETS}, n_candidates=16, top_k=2)
        r.pop("elapsed_s"), r2.pop("elapsed_s")
        assert json.dumps(r, sort_keys=True) == json.dumps(r2, sort_keys=True)
        assert optimize_with_neural_surrogate(
            tmp_path / "nope.json", {"targets": self.TARGETS},
            n_candidates=8, top_k=2)["ok"] is False
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert optimize_with_neural_surrogate(
            str(bad), {"targets": self.TARGETS},
            n_candidates=8, top_k=2)["ok"] is False
        arr = tmp_path / "arr.json"
        arr.write_text("[1, 2]", encoding="utf-8")
        assert optimize_with_neural_surrogate(
            str(arr), {"targets": self.TARGETS},
            n_candidates=8, top_k=2)["ok"] is False

    def test_all_degenerate_domain_rejected(self):
        env = _hand_env(param_names=("y",), fixed_params=("y",))
        r = optimize_with_neural_surrogate(
            env, {"targets": self.TARGETS}, n_candidates=8, top_k=2)
        assert r["ok"] is False and "全退化" in r["errors"][0]
