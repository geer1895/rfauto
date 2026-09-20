"""A1 子项③：Meep mline 批量采样扩容编排服务测试（meep_sampling）。

离线、确定性、tmp_path 隔离（不触 runs/，#144）：
- 批量渲染：w_mm × line_len_mm 笛卡尔积逐点落盘 + manifest/samples 契约；
- stub-meep exec 几何审计（沿用 test_meep_adapter 基建，#212 精神）：
  批中每点脚本可 exec、几何随 w_mm/line_len_mm 逐点变化、频点数组逐点相同；
- 代理采样契约：samples.json 喂 active_learning.propose_next_points
  （metrics 由 CI 真跑回收后并入——测试用确定性合成函数模拟该步）；
- 校验：≤256 防爆量守卫 + 非法网格显式报错（校验失败零落盘）。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from tests.unit.test_meep_adapter import RECORD, _exec_script, _install_stub_meep

W_GRID = [0.8, 1.113, 1.5]
L_GRID = [20.0, 40.0]
FREQS_GHZ = [2.25, 2.5, 2.75]
RES = 2.0


def _build(tmp_path, w=None, lens=None, freqs=None, **kw):
    from rfauto.service.meep_sampling import build_mline_sampling_batch
    opts = {"resolution": RES}
    opts.update(kw)
    return build_mline_sampling_batch(
        w if w is not None else W_GRID,
        lens if lens is not None else L_GRID,
        freqs if freqs is not None else FREQS_GHZ,
        tmp_path / "batch",
        **opts)


# ── 批量渲染 + 逐点 exec 几何审计 ─────────────────────────────────────────────

class TestBatchRenderAndAudit:
    def test_cartesian_product_layout_and_manifest_count(self, tmp_path):
        r = _build(tmp_path)
        assert r["ok"] is True and r["n_points"] == 6
        for idx in range(6):
            d = tmp_path / "batch" / f"{idx:04d}"
            assert (d / "meep_mline_sim.py").exists()
        assert (tmp_path / "batch" / "manifest.json").exists()
        assert (tmp_path / "batch" / "samples.json").exists()

    def test_each_script_execs_geometry_varies_freqs_shared(self, tmp_path, monkeypatch):
        _install_stub_meep(monkeypatch)
        _build(tmp_path)
        freq_arrays: list[np.ndarray] = []
        for i, point in enumerate(
                json.loads((tmp_path / "batch" / "manifest.json").read_text(
                    encoding="utf-8"))["points"]):
            RECORD.clear()
            script = (tmp_path / "batch" / point["script"]).read_text(encoding="utf-8")
            ns = _exec_script(script)
            _sim, _mon = ns["build_sim"](1)
            blocks = [b[1] for b in RECORD if b[0] == "Block"]
            w_expect = W_GRID[i // len(L_GRID)]     # 行主序：外层 w、内层 line_len
            l_expect = L_GRID[i % len(L_GRID)]
            assert blocks[2].size.x == pytest.approx(w_expect)   # 信号带随 w 变
            assert ns["W"] == pytest.approx(w_expect)
            assert ns["L"] == pytest.approx(l_expect)
            # cell y = L + 2·SRC_GAP + 2·DPML（随 line_len 逐点变化）
            assert ns["CELL"].y == pytest.approx(l_expect + 2 * 2.0 + 2 * 2.0)
            freq_arrays.append(np.array(ns["FREQS_HZ"], dtype=float))
        # 共享网格：全批逐点相同（compare_beta_three_way 对齐前提）
        for arr in freq_arrays[1:]:
            assert np.array_equal(arr, freq_arrays[0])
        assert freq_arrays[0].tolist() == [f * 1e9 for f in FREQS_GHZ]

    def test_lossy_sigma_d_identical_across_points_and_kernel_equal(
            self, tmp_path, monkeypatch):
        """共享网格 + 共享层叠 ⇒ 钉频带中心的 σ_D 全批同值 == 内核值。"""
        from rfauto.adapters.meep_adapter import tand_to_d_conductivity
        _install_stub_meep(monkeypatch)
        _build(tmp_path)
        sigds: list[float] = []
        for idx in range(6):
            script = (tmp_path / "batch" / f"{idx:04d}" / "meep_mline_sim.py").read_text(
                encoding="utf-8")
            ns = _exec_script(script)
            sigds.append(float(ns["SIGD"]))
        expected = tand_to_d_conductivity(
            0.5 * (FREQS_GHZ[0] + FREQS_GHZ[-1]) * 1e9, 0.0037)
        for s in sigds:
            assert s == pytest.approx(expected)
        assert not math.isnan(expected)


# ── manifest / samples 契约 ──────────────────────────────────────────────────

class TestContracts:
    def test_manifest_fields(self, tmp_path):
        from rfauto.service.meep_sampling import load_batch_manifest
        _build(tmp_path, stackup={"epsilon_r": 3.66, "thickness_mm": 0.508,
                                  "loss_tangent": 0.0037, "name": "rogers4350b"})
        m = load_batch_manifest(tmp_path / "batch")
        assert m["kind"] == "meep_mline_sampling_batch"
        assert m["template"] == "mline"
        assert m["n_points"] == 6
        assert m["shared_freqs_ghz"] == FREQS_GHZ
        assert m["stackup"]["epsilon_r"] == pytest.approx(3.66)
        assert m["grid"] == {"w_mm": W_GRID, "line_len_mm": L_GRID,
                             "order": "w_mm-major"}
        assert m["render_options"]["resolution"] == pytest.approx(RES)
        # 点序/参数/脚本相对路径逐点核对
        for i, p in enumerate(m["points"]):
            assert p["idx"] == i and p["dir"] == f"{i:04d}"
            assert p["params"] == {"w_mm": W_GRID[i // 2], "line_len_mm": L_GRID[i % 2]}
            assert p["script"] == f"{i:04d}/meep_mline_sim.py"

    def test_expected_outputs_are_solver_csv_names(self, tmp_path):
        from rfauto.service.meep_sampling import EXPECTED_OUTPUTS
        _build(tmp_path)
        m = json.loads((tmp_path / "batch" / "manifest.json").read_text(encoding="utf-8"))
        for p in m["points"]:
            names = [rel.split("/", 1)[1] for rel in p["expected_outputs"]]
            assert names == list(EXPECTED_OUTPUTS)
            assert names == ["meep_sparams_p1.csv", "meep_sparams_p2.csv",
                             "meep_port_beta_p1.csv", "meep_port_beta_p2.csv"]

    def test_samples_shape_and_bounds(self, tmp_path):
        _build(tmp_path)
        doc = json.loads((tmp_path / "batch" / "samples.json").read_text(encoding="utf-8"))
        assert len(doc["samples"]) == 6
        for i, s in enumerate(doc["samples"]):
            assert s["params"] == {"w_mm": W_GRID[i // 2], "line_len_mm": L_GRID[i % 2]}
        assert doc["bounds"]["w_mm"] == [min(W_GRID), max(W_GRID)]
        assert doc["bounds"]["line_len_mm"] == [min(L_GRID), max(L_GRID)]

    def test_samples_feed_propose_next_points_after_metrics_merge(self, tmp_path):
        """契约闭环：metrics（CI 真跑回收后并入；此处确定性合成模拟）→
        propose_next_points（≥5 点、kind=nn 支持 uncertainty）ok。"""
        from rfauto.service.active_learning import propose_next_points
        _build(tmp_path)
        path = tmp_path / "batch" / "samples.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert len(doc["samples"]) == 6 >= 5
        for s in doc["samples"]:   # 确定性合成 metrics（测试夹具，非物理声明）
            p = s["params"]
            s["metrics"] = {"cost": (p["w_mm"] - 1.0) ** 2 + (p["line_len_mm"] - 30.0) ** 2}
        path.write_text(json.dumps(doc), encoding="utf-8")
        out = propose_next_points(path, k=2, n_candidates=200)
        assert out["ok"], out.get("errors")
        assert out["n_existing"] == 6
        assert len(out["proposed"]) == 2

    def test_load_manifest_missing_raises(self, tmp_path):
        from rfauto.service.meep_sampling import load_batch_manifest
        with pytest.raises(FileNotFoundError):
            load_batch_manifest(tmp_path / "nope")


# ── 校验：防爆量守卫 + 非法网格显式报错（校验失败零落盘）──────────────────────

class TestValidation:
    def test_batch_over_256_rejected_before_any_io(self, tmp_path):
        from rfauto.service.meep_sampling import MAX_BATCH_POINTS
        assert MAX_BATCH_POINTS == 256
        out = tmp_path / "batch"
        with pytest.raises(ValueError, match="超过上限"):
            _build(tmp_path, w=[0.5 + 0.01 * i for i in range(17)],
                   lens=[20.0 + i for i in range(16)])       # 17×16=272
        assert not out.exists()

    def test_exact_boundary_256_points_ok(self, tmp_path):
        r = _build(tmp_path, w=[0.5 + 0.01 * i for i in range(16)],
                   lens=[20.0 + i for i in range(16)])       # 16×16=256
        assert r["n_points"] == 256

    def test_invalid_grids_rejected_with_zero_artifacts(self, tmp_path):
        out = tmp_path / "batch"
        with pytest.raises(ValueError, match="非空列表"):
            _build(tmp_path, w=[])
        with pytest.raises(ValueError, match="必须为正"):
            _build(tmp_path, w=[0.8, -1.0])
        with pytest.raises(ValueError, match="≥2 点"):
            _build(tmp_path, freqs=[2.5])
        with pytest.raises(ValueError, match="必须为正"):
            _build(tmp_path, freqs=[2.25, -2.5])
        with pytest.raises(ValueError, match="严格递增"):
            _build(tmp_path, freqs=[2.5, 2.25])
        with pytest.raises(ValueError, match="分辨率必须为正"):
            _build(tmp_path, resolution=0.0)
        assert not out.exists()

    def test_bad_stackup_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="epsilon_r"):
            _build(tmp_path, stackup={"epsilon_r": 0.5})
        with pytest.raises(ValueError, match="thickness_mm"):
            _build(tmp_path, stackup={"thickness_mm": 0.0})
