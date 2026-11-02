"""perf_profile_service 单测（aurora_p G3 席）。

钉面（任务书 §3 验收）：
- 套件确定性：同 spec 两跑数值列（rmse/mae/r2/spearman_rho）逐位相等
  （墙钟列天然波动豁免）；
- diff 红绿两态：注入劣化假行/假快照 → 红项如实抓出（RMSE 漂移 >25%、
  墙钟比 >2×、ok→error 状态面）；
- 信封契约：ok/error 构造器形态（errors 恒 list[str]、ok 面带 schema/
  profile_id/profile_path/diff_path）；
- 预算封顶：BUDGET_CAP_S=300 写死；超限 budget_ok=False 如实标注不静默；
- 负例：空键集/未知键显式报错信封（不静默空跑）；
- #144 免疫：service 无 cwd 相对缺省落盘——chdir tmp 后 runs/ 不生。

模型侧全部走小键（poly_ridge/nn），单测墙钟预算 ~1s。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from rfauto.service import perf_profile_service as pps

_REPO = Path(__file__).resolve().parents[2]


# ── 套件定义面 ───────────────────────────────────────────────────────────────


class TestSuiteDefinition:
    def test_default_suite_five_keys(self) -> None:
        keys = [s.key for s in pps.DEFAULT_SUITE]
        assert keys == ["poly_ridge", "gbdt", "nn", "svgp", "saas_gp"]
        assert len(set(keys)) == len(keys)

    def test_build_suite_filter_keeps_order(self) -> None:
        suite = pps.build_suite(["nn", "poly_ridge"])
        # 保持套件定义序（不按调用方顺序重排——快照行序稳定）
        assert [s.key for s in suite] == ["poly_ridge", "nn"]

    def test_build_suite_empty_explicit_error(self) -> None:
        with pytest.raises(ValueError, match="至少需要 1 个键"):
            pps.build_suite([])

    def test_build_suite_unknown_key_explicit_error(self) -> None:
        with pytest.raises(ValueError, match="未知画像键"):
            pps.build_suite(["no_such_key"])

    def test_budget_cap_frozen(self) -> None:
        assert pps.BUDGET_CAP_S == 300.0

    def test_thresholds_frozen(self) -> None:
        assert pps.RMSE_DRIFT_RED == 0.25
        assert pps.WALL_RATIO_RED == 2.0
        assert pps.WALL_FLOOR_S == 0.05


# ── 套件确定性（数值列逐位；墙钟豁免） ──────────────────────────────────────


def _numeric_fingerprint(row: dict) -> tuple:
    return tuple(repr(row.get(k)) for k in
                 ("rmse", "mae", "r2", "spearman_rho", "status"))


class TestDeterminism:
    def test_case_numeric_columns_bitwise(self) -> None:
        """同 spec 两跑：数值列逐位相等（墙钟列允许波动）。"""
        suite = pps.build_suite(["poly_ridge", "nn"])
        tp = pps._test_points()
        run_a = [pps.run_case(spec, tp) for spec in suite]
        run_b = [pps.run_case(spec, tp) for spec in suite]
        assert len(run_a) == len(run_b) == 2
        for ra, rb in zip(run_a, run_b, strict=True):
            assert _numeric_fingerprint(ra) == _numeric_fingerprint(rb), (
                f"{ra['key']} 数值列不逐位: {ra.get('rmse')!r} vs "
                f"{rb.get('rmse')!r}")

    def test_samples_fixed_seed_bitwise(self) -> None:
        a = pps._make_scalar_samples(50)
        b = pps._make_scalar_samples(50)
        assert a == b

    def test_test_points_deterministic(self) -> None:
        assert pps._test_points() == pps._test_points()
        assert len(pps._test_points()) == 216


# ── diff 口径（纯函数注入两态） ──────────────────────────────────────────────


def _row(key: str, rmse: float | None, fit_s: float = 0.1,
         predict_s: float = 0.05, status: str = "ok",
         error: str | None = None) -> dict:
    return {"key": key, "tier": "t", "status": status, "fit_s": fit_s,
            "predict_s": predict_s, "rmse": rmse,
            "mae": (rmse / 2 if rmse is not None else None),
            "r2": 0.9, "spearman_rho": 0.95, "notes": "", "error": error}


class TestDiffRows:
    def test_first_run_baseline(self) -> None:
        d = pps.diff_rows([_row("poly_ridge", 0.5)], None)
        assert d["n_red"] == 0
        assert "基线建立态" in d["summary"]

    def test_green_identical(self) -> None:
        cur = [_row("poly_ridge", 0.5)]
        prev = [_row("poly_ridge", 0.5)]
        d = pps.diff_rows(cur, prev)
        assert d["n_red"] == 0
        assert d["items"][0]["verdict"] == "ok"

    def test_red_rmse_drift(self) -> None:
        # prev 0.5 → cur 0.75：漂移 50% > 25% → 红
        d = pps.diff_rows([_row("poly_ridge", 0.75)],
                          [_row("poly_ridge", 0.5)])
        assert d["n_red"] == 1
        assert any("rmse" in r for r in d["items"][0]["red"])

    def test_green_rmse_small_drift(self) -> None:
        # 10% 漂移 < 25% → 绿
        d = pps.diff_rows([_row("poly_ridge", 0.55)],
                          [_row("poly_ridge", 0.5)])
        assert d["n_red"] == 0

    def test_red_wall_ratio(self) -> None:
        # fit 0.1s→0.3s：3× > 2× → 红
        d = pps.diff_rows([_row("poly_ridge", 0.5, fit_s=0.3)],
                          [_row("poly_ridge", 0.5, fit_s=0.1)])
        assert d["n_red"] == 1
        assert any("fit" in r for r in d["items"][0]["red"])

    def test_red_predict_wall_ratio(self) -> None:
        d = pps.diff_rows([_row("poly_ridge", 0.5, predict_s=0.2)],
                          [_row("poly_ridge", 0.5, predict_s=0.05)])
        assert d["n_red"] == 1
        assert any("predict" in r for r in d["items"][0]["red"])

    def test_red_ok_to_error(self) -> None:
        d = pps.diff_rows(
            [_row("poly_ridge", None, status="error", error="ValueError: x")],
            [_row("poly_ridge", 0.5)])
        assert d["n_red"] == 1
        assert any("prev ok" in r for r in d["items"][0]["red"])

    def test_red_prev_zero_rmse_cur_positive(self) -> None:
        d = pps.diff_rows([_row("poly_ridge", 0.1)],
                          [_row("poly_ridge", 0.0)])
        assert d["n_red"] == 1

    def test_green_both_zero_rmse(self) -> None:
        d = pps.diff_rows([_row("poly_ridge", 0.0)],
                          [_row("poly_ridge", 0.0)])
        assert d["n_red"] == 0

    def test_new_key_note_not_red(self) -> None:
        d = pps.diff_rows([_row("poly_ridge", 0.5), _row("nn", 0.2)],
                          [_row("poly_ridge", 0.5)])
        assert d["n_red"] == 0
        nn_item = next(it for it in d["items"] if it["key"] == "nn")
        assert nn_item["verdict"] == "note"
        assert "新键" in nn_item["details"][0]

    def test_recovery_note_not_red(self) -> None:
        # prev error → cur ok：修复面记 note 不红（如实）
        d = pps.diff_rows([_row("poly_ridge", 0.5)],
                          [_row("poly_ridge", 0.5, status="error",
                                error="x")])
        assert d["n_red"] == 0
        assert "恢复" in d["items"][0]["details"][0]

    def test_prev_wall_zero_exempt(self) -> None:
        d = pps.diff_rows([_row("poly_ridge", 0.5)],
                          [_row("poly_ridge", 0.5, fit_s=0.0)])
        assert d["n_red"] == 0
        assert any("豁免" in (dt or "") for dt in d["items"][0]["details"])

    def test_wall_floor_millisecond_exempt(self) -> None:
        """prev 低于地板=毫秒级计时噪声主导：100× 表观比也豁免不红。"""
        d = pps.diff_rows([_row("poly_ridge", 0.5, fit_s=1.0)],
                          [_row("poly_ridge", 0.5, fit_s=0.01)])
        assert d["n_red"] == 0
        assert any("地板" in (dt or "") for dt in d["items"][0]["details"])

    def test_wall_floor_boundary_in_gate(self) -> None:
        """prev 恰在地板上（0.05 不严格小于）→ 在门内，3× 判红。"""
        d = pps.diff_rows([_row("poly_ridge", 0.5, fit_s=0.15)],
                          [_row("poly_ridge", 0.5, fit_s=0.05)])
        assert d["n_red"] == 1


# ── run_profile 信封 + 落盘 + 预算/负例 ──────────────────────────────────────


class TestRunProfile:
    def test_ok_envelope_first_run(self, tmp_path: Path) -> None:
        out = tmp_path / "perf_profile"
        r = pps.run_profile(out, keys=["poly_ridge"])
        assert r["ok"] is True
        assert r["schema"] == "perf_profile/v1"
        assert r["profile_id"] == "profile_0001"
        assert r["first_run"] is True
        assert r["diff_against"] is None
        assert r["n_keys"] == 1 and r["n_ok"] == 1 and r["n_error"] == 0
        assert r["budget_ok"] is True
        assert r["n_red"] == 0
        assert Path(r["profile_path"]).exists()
        assert Path(r["diff_path"]).exists()
        doc = json.loads(Path(r["profile_path"]).read_text(encoding="utf-8"))
        assert doc["schema"] == "perf_profile/v1"
        assert "基线建立态" in Path(r["diff_path"]).read_text("utf-8")

    def test_second_run_numbers_and_diff(self, tmp_path: Path) -> None:
        out = tmp_path / "perf_profile"
        pps.run_profile(out, keys=["poly_ridge"])
        r2 = pps.run_profile(out, keys=["poly_ridge"])
        assert r2["profile_id"] == "profile_0002"
        assert r2["diff_against"] == "profile_0001"
        assert r2["first_run"] is False
        assert r2["n_red"] == 0  # 同 seed 数值列逐位 → 无红

    def test_empty_keys_error_envelope(self, tmp_path: Path) -> None:
        r = pps.run_profile(tmp_path, keys=[])
        assert r["ok"] is False
        assert isinstance(r["errors"], list)
        assert all(isinstance(e, str) for e in r["errors"])
        assert any("至少需要 1 个键" in e for e in r["errors"])

    def test_unknown_keys_error_envelope(self, tmp_path: Path) -> None:
        r = pps.run_profile(tmp_path, keys=["bogus"])
        assert r["ok"] is False
        assert any("未知画像键" in e for e in r["errors"])

    def test_budget_exceeded_honest_annotation(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pps, "BUDGET_CAP_S", 1e-6)
        r = pps.run_profile(tmp_path, keys=["poly_ridge"])
        assert r["ok"] is True  # 画像本身成立
        assert r["budget_ok"] is False  # 超限如实标注不静默
        doc = json.loads(Path(r["profile_path"]).read_text(encoding="utf-8"))
        assert doc["budget_ok"] is False
        assert "budget_ok=False" in Path(r["diff_path"]).read_text("utf-8")


# ── 注入法端到端红项抓出 ─────────────────────────────────────────────────────


def _write_fake_profile(out: Path, n: int, rmse: float, fit_s: float) -> None:
    out.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": pps.SCHEMA,
        "profile_id": f"profile_{n:04d}",
        "results": [_row("poly_ridge", rmse, fit_s=fit_s)],
    }
    (out / f"profile_{n:04d}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")


class TestInjectionEndToEnd:
    def test_degraded_prev_snapshot_catches_red(self, tmp_path: Path) -> None:
        out = tmp_path / "perf_profile"
        # prev: rmse=0.2, fit=0.05s（劣化注入源）
        _write_fake_profile(out, 1, rmse=0.2, fit_s=0.05)
        r = pps.run_profile(out, keys=["poly_ridge"])
        assert r["ok"] is True
        assert r["profile_id"] == "profile_0002"
        assert r["diff_against"] == "profile_0001"
        # poly_ridge 真跑 rmse≈0.54 vs prev 0.2 → 漂移 ~170% > 25% → 红
        assert r["n_red"] >= 1
        assert r["red_items"], "注入劣化快照必须抓出红项"
        keys_red = {it["key"] for it in r["red_items"]}
        assert "poly_ridge" in keys_red
        md = Path(r["diff_path"]).read_text("utf-8")
        assert "| poly_ridge | red" in md

    def test_green_prev_snapshot_no_red(self, tmp_path: Path) -> None:
        out = tmp_path / "perf_profile"
        # 先真跑一次拿真实数值，再回写为 prev → 第二跑必绿
        first = pps.run_profile(out, keys=["poly_ridge"])
        doc = json.loads(Path(first["profile_path"]).read_text("utf-8"))
        row = doc["results"][0]
        prev = {
            "schema": pps.SCHEMA,
            "profile_id": "profile_9001",
            "results": [_row("poly_ridge", row["rmse"],
                             fit_s=row["fit_s"] * 0.5)],
        }
        (out / "profile_9001.json").write_text(
            json.dumps(prev, ensure_ascii=False) + "\n", encoding="utf-8")
        r2 = pps.run_profile(out, keys=["poly_ridge"])
        assert r2["n_red"] == 0
        assert r2["red_items"] == []


# ── 快照编号发现 ─────────────────────────────────────────────────────────────


class TestLatestProfile:
    def test_latest_picks_max_number(self, tmp_path: Path) -> None:
        _write_fake_profile(tmp_path, 1, 0.5, 0.1)
        _write_fake_profile(tmp_path, 3, 0.5, 0.1)
        found = pps.latest_profile(tmp_path)
        assert found is not None
        assert found[0] == 3

    def test_none_when_empty(self, tmp_path: Path) -> None:
        assert pps.latest_profile(tmp_path) is None

    def test_non_matching_glob_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "profile_broken.json").write_text("{}", encoding="utf-8")
        assert pps.latest_profile(tmp_path) is None


# ── #144 免疫 + 驱动白名单 ───────────────────────────────────────────────────


class TestIsolationAndDriver:
    def test_no_cwd_relative_writes(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """chdir tmp 后跑画像：cwd 侧不得生 runs/（#144 家族免疫）。"""
        monkeypatch.chdir(tmp_path)
        r = pps.run_profile(tmp_path / "out", keys=["poly_ridge"])
        assert r["ok"] is True
        assert not (tmp_path / "runs").exists()

    def test_driver_default_out_pinned_to_whitelist(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "g3_perf_profile_driver",
            _REPO / "scripts" / "perf_profile.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("g3_perf_profile_driver", mod)
        spec.loader.exec_module(mod)
        assert mod.DEFAULT_OUT == _REPO / "runs" / "perf_profile"

    def test_driver_main_json_error_envelope(
            self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
            monkeypatch: pytest.MonkeyPatch) -> None:
        spec = importlib.util.spec_from_file_location(
            "g3_perf_profile_driver_err",
            _REPO / "scripts" / "perf_profile.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("g3_perf_profile_driver_err", mod)
        spec.loader.exec_module(mod)
        monkeypatch.chdir(tmp_path)
        rc = mod.main(["--out", str(tmp_path / "out"), "--keys", "",
                       "--json"])
        assert rc == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)
