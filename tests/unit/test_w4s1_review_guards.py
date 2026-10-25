"""aurora_g W4-S1 审查波守卫漏网修复批定向门（W3-S1/W3-S2 审查报告清偿）。

审查依据：内部证据档（P2-1 fec OverflowError 域上限
+ P3×5）+ review_w3_ui_eng.md（P1-1 surrogate_playground run_id 第 9 处
守卫漏网 / P2-1 profile timeoutMs 豁免 / P2-2 campaign_dashboard 第 10 处）。

七件（每件修法+回归钉同笔）：
1. P1-1 safe_run_id 单源接入 surrogate_playground._load_artifacts——
   "../docs" 相对穿越读 runs 外定名 JSON（存在性 oracle）/NUL 500 两形态
   收口，合法 run 直通不受扰；
2. P2-2 safe_run_id 接入 campaign_dashboard（第 10 处拼接点）——".." 直通
   runs 根 is_dir 通过→"无 trials"存在性 oracle 收口；
3. P2-1(UI) POST /api/profile 长跑豁免 timeoutMs:0（源码文本钉；超时机制
   本体行为钉在 test_ui_r12_deepening.TestUnifiedApiBehavioral 不重复）；
4. P2-1(kernel) fec block_n 声明域上限收缩 1024→1020——1021–1024 的
   i·C(n,i) int→float 转换必 OverflowError（声明域内不可服务矛盾），越界
   走 _as_int 显式"参数名+域"拒绝；1020 上沿活体+1021 显式拒绝双钉；
5. P3-1 registry 六组分组头计数与 CALC_GROUP_TABLE 实测对账（纯注释漂移
   曾无门覆盖——本钉常驻化防再漂）；
6. P3-2 三 W2-S2 模块 bool 显式拒收（_finite_nb；原"自然拒收"声明失实，
   float(True)=1.0 静默污染，对齐 fec_codes._as_int 先例）；
7. P3-3 shannon snr_db 上限 3000（10**(db/10) 溢出面收缩为显式域拒绝）
   + P3-5 crlh_balanced_synthesis 入 __all__（公开导出口径补全）。
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import ClassVar

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.crlh import __all__ as _CRLH_ALL
from rfauto.service._helpers import safe_run_id
from rfauto.service.calculator_service import run_calculator
from rfauto.service.campaign_dashboard_service import campaign_dashboard
from rfauto.service.surrogate_playground import (
    _load_artifacts,
    explore,
    playground_predict,
)

_STATIC = SRC / "rfauto" / "ui" / "static"


# ───────────── 1. P1-1 surrogate_playground run_id 守卫 ─────────────


def _make_calibrated_run(tmp_path: Path, run_id: str) -> None:
    """线性语料校准产物（test_surrogate_playground 同款最小形）。"""
    base = tmp_path / "runs" / run_id / "calibration"
    base.mkdir(parents=True)
    samples = [{"params": {"a_mm": 1.0 + i * 0.1, "b_mm": 5.0},
                "metrics": {"m": 2.0 * (1.0 + i * 0.1) + 5.0}}
               for i in range(12)]
    (base / "samples.json").write_text(json.dumps({
        "bounds": {"a_mm": [1.0, 2.1], "b_mm": [5.0, 5.0]},
        "objectives": [{"metric": "m"}],
        "samples": samples,
    }), encoding="utf-8")
    (base / "campaign.json").write_text(json.dumps(
        {"best_surrogate": "poly_ridge", "n_samples": 12}), encoding="utf-8")


class TestPlaygroundRunIdGuard:
    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path, isolated_cache_off):
        # 穿越诱饵：runs/ 外的 docs/calibration 放**合法**产物——修复前
        # "../docs" 解析到此成功预测，修复后必须守卫拒绝（不是靠缺产物
        # 假绿）
        base = tmp_path / "docs" / "calibration"
        base.mkdir(parents=True)
        (base / "samples.json").write_text(json.dumps({
            "bounds": {"a_mm": [1.0, 2.0]},
            "objectives": [{"metric": "m"}],
            "samples": [{"params": {"a_mm": 1.0}, "metrics": {"m": 1.0}}],
        }), encoding="utf-8")
        _make_calibrated_run(tmp_path, "20260101_000000_ok")
        yield

    @pytest.mark.parametrize("bad", ["../docs", "..", "a/b", "bad\x00id"])
    def test_traversal_and_nul_rejected_predict(self, bad):
        r = playground_predict(bad, {"a_mm": 1.5})
        assert r["ok"] is False
        assert "非法 run_id" in r["error"]

    @pytest.mark.parametrize("bad", ["../docs", "..", "a/b", "bad\x00id"])
    def test_traversal_and_nul_rejected_explore(self, bad):
        r = explore(bad, None, {"axis": "a_mm", "n": 5})
        assert r["ok"] is False
        assert "非法 run_id" in r["error"]

    def test_load_artifacts_raises_guard_error(self):
        with pytest.raises(ValueError, match="非法 run_id"):
            _load_artifacts("../docs")

    def test_legal_run_still_predicts(self):
        r = playground_predict("20260101_000000_ok", {"a_mm": 1.5})
        assert r["ok"] is True and r["run_id"] == "20260101_000000_ok"


# ───────────── 2. P2-2 campaign_dashboard run_id 守卫 ─────────────


def _write_trial(run_dir: Path, number: int, params: dict, cost: float,
                 ) -> None:
    tdir = run_dir / "trials"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"trial_{number:04d}.json").write_text(
        json.dumps({"trial_number": number, "params": params,
                    "metrics": {}, "cost": cost}), encoding="utf-8")


class TestCampaignDashboardRunIdGuard:
    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path, isolated):
        # 祖先目录放 trials 诱饵：修复前 ".." is_dir 通过→读到 tmp/trials
        # （存在性 oracle+无谓扫描）；修复后守卫前置，不触 trials 面
        _write_trial(tmp_path, 0, {"w": 0.0, "er": 1.0}, 0.0)
        _write_trial(tmp_path / "runs" / "camp1", 0,
                     {"w": 1.0, "er": 2.0}, 1.0)
        _write_trial(tmp_path / "runs" / "camp1", 1,
                     {"w": 2.0, "er": 3.0}, 3.0)
        yield

    @pytest.mark.parametrize("bad", ["..", "a/b", "bad\x00id", "../x"])
    def test_bad_ids_rejected_before_trials_read(self, bad):
        r = campaign_dashboard(bad)
        assert r["ok"] is False and r["errors"]
        assert "非法 run_id" in r["errors"][0]
        assert "无 trials" not in r["errors"][0]

    def test_legal_run_still_renders(self):
        r = campaign_dashboard("camp1")
        assert r["ok"] is True and r["n_trials_total"] == 2


# ───────────── 3. P2-1(UI) profile 长跑豁免（源码文本钉） ─────────────


class TestProfileTimeoutExemption:
    """POST /api/profile 必带 timeoutMs:0（profile_run 同步阻塞 duration_s，
    缺省 30s 采样与 apiFetch 缺省超时竞速必现假"请求超时"——W3-S2 审查
    P2-1）。机制行为钉在 test_ui_r12_deepening（timeoutMs:0 → 零超时
    signal），此处只钉本调用点接线。"""

    def test_view_profile_post_carries_zero_timeout(self):
        src = (_STATIC / "pages" / "view_profile.js").read_text(
            encoding="utf-8")
        # POST 调用点（动作面）显式豁免；GET（状态探测，秒级）不需豁免
        assert 'body: JSON.stringify(body), timeoutMs: 0 }' in src, \
            "POST /api/profile 缺 timeoutMs:0 长跑豁免"
        assert src.count('apiFetch("/api/profile"') == 2

    def test_api_js_exemption_list_mentions_profile(self):
        src = (_STATIC / "pages" / "api.js").read_text(encoding="utf-8")
        assert "/api/profile" in src  # 头注④长跑豁免清单补行


# ───────────── 4. P2-1(kernel) fec block_n 域上限 1020 ─────────────


class TestFecBlockNDomainCap:
    H74: ClassVar[dict[str, object]] = {"scheme": "bpsk", "target_ber": 1e-5}

    def test_upper_edge_1020_serviceable(self):
        """声明域上沿活体：n=k=1020、t=0 档全链可解（G≡0 恒等锚同值）。

        修复前 1021–1024 域内必 OverflowError；收缩后 1020 恰为可服务
        上沿（中央项 i·C(1020,510)≈1.4e308 < DBL_MAX，实测留 ~26% 余量）。
        """
        r = run_calculator("coded_ebn0_requirement",
                           {**self.H74, "block_n": 1020, "info_k": 1020,
                            "t_correct": 0})
        assert r["ok"] is True
        assert r["result"]["net_coding_gain_db"] == 0.0

    @pytest.mark.parametrize("n", [1021, 1024])
    def test_above_cap_explicit_domain_rejection(self, n):
        """越界走 _as_int"参数名+域"显式拒绝（非裸 OverflowError 串）。"""
        r = run_calculator("coded_ebn0_requirement",
                           {**self.H74, "block_n": n, "info_k": n,
                            "t_correct": 0})
        assert r["ok"] is False
        assert f"block_n 必须在 [2, 1020] 内，得到 {n}" in r["error"]

    def test_module_docstring_declares_new_cap(self):
        from rfauto.core.calc_families import fec_codes

        src = Path(fec_codes.__file__).read_text(encoding="utf-8")
        assert "[2,1024]" not in src.replace("[2,1020]", "")
        assert fec_codes._MAX_BLOCK_N == 1020


# ───────────── 5. P3-1 registry 分组头计数对账 ─────────────


class TestRegistryGroupHeaderCounts:
    """分组头注释计数（纯注释曾无门覆盖，W3-S1 审查 P3-1）与
    CALC_GROUP_TABLE 实测逐组对账——防再漂常驻钉。"""

    def test_headers_match_table_counts(self):
        from rfauto.core.calc_families.registry import (
            CALC_GROUP_ORDER,
            CALC_GROUP_TABLE,
        )

        src = Path(
            sys.modules["rfauto.core.calc_families.registry"].__file__
        ).read_text(encoding="utf-8")
        headers: dict[str, int] = {}
        for m in re.finditer(r"# ── (.+?)（(\d+)）──", src):
            headers[m.group(1)] = int(m.group(2))
        actual = Counter(CALC_GROUP_TABLE.values())
        for group in CALC_GROUP_ORDER:
            assert headers.get(group) == actual.get(group, 0), (
                f"分组头计数漂移: {group}（头注 {headers.get(group)} vs 实测 "
                f"{actual.get(group, 0)}）——注册键后同步 registry.py 分组头")


# ───────────── 6. P3-2 三模块 bool 显式拒收 ─────────────


class TestBoolExplicitRejection:
    """float(True)=1.0 静默污染面收口（_finite_nb，fec_codes._as_int
    同款先例；W3-S1 审查 P3-2"自然拒收"声明失实）。"""

    @pytest.mark.parametrize("callee, params, field", [
        ("dgs_dumbbell_lc_extract",
         {"f0_ghz": True, "f3db_ghz": 1.8}, "f0_ghz"),
        ("dgs_notch_response",
         {"l_nh": True, "c_pf": 1.5, "z0_ohm": 50, "freq_ghz": [2.4]},
         "l_nh"),
        ("bandpass_sampling_plan",
         {"f_center_hz": True, "bw_hz": 20e6}, "f_center_hz"),
        ("alias_fold_check",
         {"f_center_hz": True, "bw_hz": 20e6, "fs_hz": 54e6}, "f_center_hz"),
        ("wg_dielectric_window",
         {"a_mm": 22.86, "f_ghz": True, "eps_r": 2.2}, "f_ghz"),
        ("wg_dielectric_window",
         {"a_mm": 22.86, "f_ghz": 10.0, "eps_r": True}, "eps_r"),
    ])
    def test_bool_rejected_with_param_name(self, callee, params, field):
        r = run_calculator(callee, params)
        assert r["ok"] is False
        assert "不接受 bool" in r["error"] and field in r["error"]

    def test_numeric_path_unaffected(self):
        r = run_calculator("dgs_dumbbell_lc_extract",
                           {"f0_ghz": 2.4, "f3db_ghz": 1.8, "z0_ohm": 50.0})
        assert r["ok"] is True


# ───────────── 7. P3-3/P3-5 shannon dB 上限 + crlh 导出 ─────────────


class TestShannonSnrDbCap:
    def test_3000_serviceable_3001_rejected(self):
        ok = run_calculator("shannon_capacity",
                            {"bandwidth_hz": 1e6, "snr_db": 3000.0})
        assert ok["ok"] is True
        bad = run_calculator("shannon_capacity",
                             {"bandwidth_hz": 1e6, "snr_db": 3001.0})
        assert bad["ok"] is False
        assert "snr_db" in bad["error"] and "3000" in bad["error"]

    def test_linear_branch_untouched(self):
        r = run_calculator("shannon_capacity",
                           {"bandwidth_hz": 1.0, "snr_linear": 1.0})
        assert r["ok"] is True and r["result"]["snr_db"] == 0.0


class TestCrlhBalancedSynthesisExported:
    def test_in_all_and_callable(self):
        assert "crlh_balanced_synthesis" in _CRLH_ALL
        import rfauto.core.crlh as crlh

        assert callable(crlh.crlh_balanced_synthesis)

    def test_all_entries_all_exist(self):
        import rfauto.core.crlh as crlh

        assert all(hasattr(crlh, name) for name in _CRLH_ALL)


# ───────────── 0. 守卫单源判据回归（防接入面再漂） ─────────────


class TestSafeRunIdJudgeBaseline:
    """接入批共用的单源判据最小回归（完整判据树在
    test_w1s1_ui_deploy_hardening.TestSafeRunIdSingleSource，不重复）。"""

    @pytest.mark.parametrize("bad", ["", "..", "../docs", "a/b", "x\x00y"])
    def test_reject(self, bad):
        assert safe_run_id(bad) is None

    def test_legit_passthrough(self):
        assert safe_run_id("20260101_000000_ok") == "20260101_000000_ok"
