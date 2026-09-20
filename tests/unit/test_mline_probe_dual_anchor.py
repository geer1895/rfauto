"""mline 探针双锚判据单测（队列3-A，廿八未尽①；纯函数零真机）。

锚值来源（归因档 runs/mline_repro_attribution_20260911.md §二 + 旧判读
runs/mline_repro_diag4_originfix.log:54）：
  openEMS β 金标准 2.886（#189 收敛值族 2.8813~2.8884，采 2.886）
  HJ 准静态闭式 2.8526（forward_z0 rogers4350b w=1.113）
  HFSS 真机 2.9200（diag4）/ 2.9249（diag5）
判据：主锚 |Δ vs openEMS β| ≤2%；副锚 |Δ vs HJ| ≤3%（放宽口径，理由见
scripts/hfss_mline_probe.py 模块 docstring）；匹配门 |S11|min < -10dB。
"""

from __future__ import annotations

import inspect
import sys
import typing
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO / "scripts"), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import hfss_mline_probe
import rfauto.core.anchor_verdict as anchor_verdict
from hfss_mline_probe import (
    EPS_EFF_OPENEMS_BETA,
    SUB_ANCHOR_TOL_PCT,
    dual_anchor_verdict,
)
from rfauto.core.anchor_verdict import mline_benchmark_verdict

EPS_OPENEMS = 2.886
EPS_HJ = 2.8526


class TestGoldAnchorConstants:
    def test_gold_constant_matches_attribution_doc(self):
        # 归因档 §二："openEMS β 金标准 2.886（+1.2%，跨引擎一致）"
        assert EPS_EFF_OPENEMS_BETA == 2.886

    def test_sub_tolerance_is_relaxed_to_3pct(self):
        assert SUB_ANCHOR_TOL_PCT == 3.0


class TestDualAnchorVerdictRealMachine:
    """真机实测数回放：旧 ±2% HJ 单门下的 PARTIAL 项，双锚口径下判读。"""

    def test_diag4_originfix_passes_dual_anchor(self):
        # diag4：HFSS εeff=2.9200 → 对 openEMS +1.18%、对 HJ +2.36%
        r = dual_anchor_verdict(-51.97, 2.9200, EPS_OPENEMS, EPS_HJ)
        assert r["delta_openems_pct"] == pytest.approx(1.178, abs=0.01)
        assert r["delta_hj_pct"] == pytest.approx(2.362, abs=0.01)
        assert r["main_ok"] is True
        assert r["sub_ok"] is True
        assert r["match_ok"] is True
        assert r["verdict"] == "PASS"
        assert r["reason"] == ""

    def test_diag5_flush_originfix_passes_dual_anchor(self):
        # diag5：HFSS εeff=2.9249 → 对 HJ +2.53%（旧单门超 2% 的第二实测）
        r = dual_anchor_verdict(-52.0, 2.9249, EPS_OPENEMS, EPS_HJ)
        assert r["delta_hj_pct"] == pytest.approx(2.534, abs=0.01)
        assert r["verdict"] == "PASS"

    def test_cross_engine_offset_consistency(self):
        # openEMS 自身对 HJ +1.18%（归因档 §二）——主锚与副锚偏移应同向
        r = dual_anchor_verdict(-52.0, 2.886, EPS_OPENEMS, EPS_HJ)
        assert r["delta_openems_pct"] == pytest.approx(0.0, abs=1e-9)
        assert r["delta_hj_pct"] == pytest.approx(1.176, abs=0.01)
        assert r["main_ok"] is True and r["sub_ok"] is True


class TestDualAnchorVerdictFailures:
    """三门各自可独立判 FAIL（如实不凑绿语义）。"""

    def test_main_anchor_violation_fails(self):
        r = dual_anchor_verdict(-40.0, 3.05, EPS_OPENEMS, EPS_HJ)
        assert r["main_ok"] is False
        assert r["verdict"] == "FAIL"
        assert "主锚超门" in str(r["reason"])

    def test_sub_anchor_violation_fails_while_main_ok(self):
        # 选点：对 openEMS +1.94%（主锚内）且对 HJ +3.13%（副锚超 3%）
        eps = 2.942
        r = dual_anchor_verdict(-40.0, eps, EPS_OPENEMS, EPS_HJ)
        assert r["main_ok"] is True
        assert r["sub_ok"] is False
        assert r["verdict"] == "FAIL"
        assert "副锚超门" in str(r["reason"])

    def test_match_gate_fails_even_with_good_eps(self):
        r = dual_anchor_verdict(-8.0, 2.9200, EPS_OPENEMS, EPS_HJ)
        assert r["match_ok"] is False
        assert r["verdict"] == "FAIL"
        assert "|S11|" in str(r["reason"])


class TestDualAnchorToleranceSemantics:
    @staticmethod
    def _delta_pct(eps: float, ref: float) -> float:
        return (eps / ref - 1.0) * 100.0

    def test_boundaries_are_inclusive(self):
        # 用"恰等于实测偏移的容差"钉死比较符是 ≤（不是 <）——
        # 容差取该 eps 相对锚的精确浮点 delta，规避边界浮点毛刺
        eps_main = EPS_OPENEMS * 1.02
        d_main = self._delta_pct(eps_main, EPS_OPENEMS)
        r_main = dual_anchor_verdict(-40.0, eps_main, EPS_OPENEMS, EPS_HJ,
                                     main_tol_pct=d_main)
        assert r_main["main_ok"] is True
        eps_sub = EPS_HJ * 1.03
        d_sub = self._delta_pct(eps_sub, EPS_HJ)
        r_sub = dual_anchor_verdict(-40.0, eps_sub, EPS_OPENEMS, EPS_HJ,
                                    sub_tol_pct=d_sub)
        assert r_sub["sub_ok"] is True

    def test_just_outside_sub_boundary_fails(self):
        eps = EPS_HJ * 1.03                        # +3%（准）
        d_sub = self._delta_pct(eps, EPS_HJ)
        r = dual_anchor_verdict(-40.0, eps, EPS_OPENEMS, EPS_HJ,
                                sub_tol_pct=d_sub * (1 - 1e-9))
        assert r["sub_ok"] is False
        assert r["verdict"] == "FAIL"

    def test_custom_tolerances_are_pure_parameters(self):
        # 判读函数不依赖模块常量（重标定只改传参，不改内核）
        r = dual_anchor_verdict(-40.0, 2.9200, EPS_OPENEMS, EPS_HJ,
                                main_tol_pct=1.0)
        assert r["main_ok"] is False and r["verdict"] == "FAIL"


class TestRuffGateFixContract:
    """ruff 门 18 错修复实体回归钉子（修复轨 e11-b34 收口）。

    门 18 错 = hfss_builder_utils.py 六处 UP037（Quantity 六个 dunder 方法
    签名的引号注解）+ 本文件 RUF100（失效 noqa）/SIM300（Yoda 比较）。UP037
    去引号的运行时安全前提是模块级 ``from __future__ import annotations``
    （PEP 563：类体内无引号注解不被急切求值，否则 import 即 NameError）；
    该前提与修复实体同属未提交树内容，丢失则干净树上 ruff 门复红。钉死：
    ① future import 不得从源内丢失；② 全模块注解可被 get_type_hints 解析
    （防后续注解编辑引入悬空前向引用）。离线零真机。
    """

    def test_future_annotations_import_kept(self):
        import rfauto.adapters.hfss_builder_utils as hbu

        assert "from __future__ import annotations" in inspect.getsource(hbu)

    def test_builder_annotations_resolve_at_runtime(self):
        import rfauto.adapters.hfss_builder_utils as hbu

        checked = 0
        for _, fn in inspect.getmembers(hbu, inspect.isfunction):
            if getattr(fn, "__module__", None) == hbu.__name__:
                typing.get_type_hints(fn)
                checked += 1
        typing.get_type_hints(hbu.Quantity)
        for attr in vars(hbu.Quantity).values():
            fn = getattr(attr, "__func__", attr)
            if inspect.isfunction(fn):
                typing.get_type_hints(fn)
                checked += 1
        # 下限防 introspection 空转：Quantity 自身 ≥17 个带签名方法
        assert checked >= 15, f"只核验了 {checked} 个注解对象，过滤疑似失效"
        # 抽样钉死原 UP037 六行之一：__add__ 签名 (other: Quantity) -> Quantity
        hints = typing.get_type_hints(hbu.Quantity.__add__)
        assert hints["other"] is hbu.Quantity
        assert hints["return"] is hbu.Quantity


class TestCoreAnchorVerdictSource:
    """判据内核单一事实源契约（WP1.2 收尾，防 scripts 副本漂移 #116 同族）。

    2026-09-12 起常量+dual_anchor_verdict 本体在
    src/rfauto/core/anchor_verdict.py；探针/harness/sweep_assert 三脚本
    同源消费。丢失 import 或把实现拷回 scripts 即红灯。
    """

    def test_probe_reexports_core_function_object(self):
        # 同一函数对象：探针的判读就是内核判读（非拷贝）
        assert hfss_mline_probe.dual_anchor_verdict \
            is anchor_verdict.dual_anchor_verdict

    def test_gold_constant_single_source(self):
        assert anchor_verdict.EPS_EFF_MLINE_GOLD == 2.886
        assert hfss_mline_probe.EPS_EFF_OPENEMS_BETA \
            == anchor_verdict.EPS_EFF_MLINE_GOLD
        assert hfss_mline_probe.SUB_ANCHOR_TOL_PCT \
            == anchor_verdict.SUB_ANCHOR_TOL_PCT == 3.0

    def test_probe_has_no_local_impl_copy(self):
        # 实体已迁 core：探针模块内不得再出现本地 def 副本（#116：
        # 大文件尾部同名 def 会遮蔽 import，新实现成死代码）
        src = inspect.getsource(hfss_mline_probe)
        assert "def dual_anchor_verdict" not in src

    def test_engine_harness_consumes_core_kernel(self):
        # 不 import harness（模块顶层 argparse 在 pytest argv 下会
        # SystemExit），以源文本钉消费关系
        harness_src = (REPO / "scripts" / "engine_benchmark_mline.py")
        text = harness_src.read_text(encoding="utf-8")
        assert "mline_benchmark_verdict" in text
        assert "anchor_verdict" in text


class TestEngineBenchmarkVerdict:
    """WP1.2 harness 判读（core/anchor_verdict.mline_benchmark_verdict）。

    判据显式决策（廿八未尽①收口）：收敛<1% + 最细档双锚
    （对金标准 ≤2%/对 HJ ≤3%）+ 健康 |S11|max<-10dB。
    """

    # #189 真实收敛数据回放（runs/benchmark/mline_mesh_convergence.json）
    EPS_FINEST_189 = 2.8813
    CONV_189 = 0.0534
    S11_WORST_189 = -23.93   # ok 档全带最差（auto 档）

    def test_historical_189_replay_passes_dual_anchor(self):
        # 历史数据在新判据下不误杀：对 gold −0.16%/对 HJ +1.01%
        r = mline_benchmark_verdict(self.EPS_FINEST_189, self.CONV_189,
                                    self.S11_WORST_189,
                                    EPS_OPENEMS, EPS_HJ)
        assert r["delta_gold_pct"] == pytest.approx(-0.163, abs=0.01)
        assert r["delta_hj_pct"] == pytest.approx(1.005, abs=0.01)
        assert r["convergence_ok"] is True
        assert r["main_ok"] is True
        assert r["sub_ok"] is True
        assert r["health_ok"] is True
        assert r["verdict"] == "PASS"
        assert r["reason"] == ""

    def test_main_anchor_violation_fails(self):
        # 对 gold +2.1% → 主锚超门判 FAIL。注：gold(2.886) 比 HJ(2.8526)
        # 高 ~1.17%，对 gold 超 +2% 蕴含对 HJ 超 ~+3.27%（副锚同超）——
        # 主锚是判废主力，副锚为解析哨兵兜底（金标准重标定时独立生效）
        eps = EPS_OPENEMS * 1.021
        r = mline_benchmark_verdict(eps, self.CONV_189, self.S11_WORST_189,
                                    EPS_OPENEMS, EPS_HJ)
        assert r["main_ok"] is False
        assert r["verdict"] == "FAIL"
        assert "主锚超门" in str(r["reason"])

    def test_sub_anchor_violation_fails_while_main_ok(self):
        # 对 gold +1.9%（主锚内）且对 HJ +3.09%（副锚超 3%）
        eps = EPS_OPENEMS * 1.019
        r = mline_benchmark_verdict(eps, self.CONV_189, self.S11_WORST_189,
                                    EPS_OPENEMS, EPS_HJ)
        assert r["main_ok"] is True
        assert r["sub_ok"] is False
        assert r["verdict"] == "FAIL"
        assert "副锚超门" in str(r["reason"])

    def test_convergence_violation_fails(self):
        r = mline_benchmark_verdict(self.EPS_FINEST_189, 1.5,
                                    self.S11_WORST_189,
                                    EPS_OPENEMS, EPS_HJ)
        assert r["convergence_ok"] is False
        assert r["verdict"] == "FAIL"
        assert "收敛超门" in str(r["reason"])

    def test_health_gate_violation_fails(self):
        r = mline_benchmark_verdict(self.EPS_FINEST_189, self.CONV_189,
                                    -9.5, EPS_OPENEMS, EPS_HJ)
        assert r["health_ok"] is False
        assert r["verdict"] == "FAIL"
        assert "健康门" in str(r["reason"])

    def test_missing_inputs_fail_honestly(self):
        # 产物缺失（无成功档/收敛不可算/无 S11）→ 如实 FAIL 不凑绿
        r = mline_benchmark_verdict(None, None, None, EPS_OPENEMS, EPS_HJ)
        assert r["verdict"] == "FAIL"
        assert r["main_ok"] is False and r["sub_ok"] is False
        assert "缺失" in str(r["reason"])
        r2 = mline_benchmark_verdict(self.EPS_FINEST_189, None,
                                     self.S11_WORST_189,
                                     EPS_OPENEMS, EPS_HJ)
        assert r2["verdict"] == "FAIL"
        assert "不可判" in str(r2["reason"])
        r3 = mline_benchmark_verdict(self.EPS_FINEST_189, self.CONV_189,
                                     None, EPS_OPENEMS, EPS_HJ)
        assert r3["health_ok"] is False and r3["verdict"] == "FAIL"

    def test_boundaries_convergence_strict_and_tolerances_inclusive(self):
        # 收敛门是严格 <1%（恰 1.0% 判 FAIL）；锚容差是 ≤（恰等判 PASS）
        r = mline_benchmark_verdict(self.EPS_FINEST_189, 1.0,
                                    self.S11_WORST_189,
                                    EPS_OPENEMS, EPS_HJ)
        assert r["convergence_ok"] is False
        eps = EPS_OPENEMS * 1.02
        d_main = (eps / EPS_OPENEMS - 1.0) * 100.0
        r2 = mline_benchmark_verdict(eps, self.CONV_189,
                                     self.S11_WORST_189,
                                     EPS_OPENEMS, EPS_HJ,
                                     main_tol_pct=d_main)
        assert r2["main_ok"] is True
        # 健康门同样严格 <：恰 -10dB 判 FAIL
        r3 = mline_benchmark_verdict(self.EPS_FINEST_189, self.CONV_189,
                                     -10.0, EPS_OPENEMS, EPS_HJ)
        assert r3["health_ok"] is False
