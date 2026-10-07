"""B5 IIP2 损伤预算统一面：budget.py IP2 级联键（手算锚+跨面一致性钉）。

盘点依据：docs/audit/plan_gap_inventory_20260928.md §二 B5「IIP2 损伤预算
统一面（budget.py 现无 iip2 键）| core/budget.py + calculators」——
cascade.py 的 cascade_ipn_merge(order=2) 已做通用合并核，本件=LinkBudget
预算面补齐 IP2 键（镜像 IP3 实现同一功率和式）。

独立裁判口径（#118）：
- 手算锚：两级例 G_pre=[1,10]、IIP2=[20,30]dBm → inv_sum=1/100+10/1000
  =0.02 [1/mW] → IIP2_tot=50mW=16.9897 dBm（线性域手算，独立于实现）；
- 恒等式：OIP2_tot − IIP2_tot == 总增益（线性域定义直接推出）；
- 跨面一致性：LinkBudget(order=2) vs core.cascade.cascade_ipn_merge(
  order=2) 同幂和式两实现数值一致（次级裁判；主裁判=手算锚）。
"""

from __future__ import annotations

import pytest

from rfauto.core.budget import LinkBudget
from rfauto.core.cascade import cascade_ipn_merge


class TestIip2Cascade:
    def test_two_stage_hand_anchor(self):
        """手算锚：IIP2_tot = 1/(1/100+10/1000) = 50 mW = 16.9897 dBm。"""
        b = LinkBudget()
        b.add_stage("lna", gain_db=10.0, nf_db=1.0, oip2_dbm=30.0)
        b.add_stage("mixer", gain_db=20.0, nf_db=7.0, iip2_dbm=30.0)
        r = b.compute()
        # 级1 IIP2 = OIP2 − G = 30 − 10 = 20 dBm = 100 mW；G_pre=1 → 0.01
        # 级2 IIP2 = 30 dBm = 1000 mW；G_pre=10 → 10/1000 = 0.01
        assert r.cascade_iip2_dbm == pytest.approx(16.989700043360187, abs=1e-9)
        assert r.cascade_oip2_dbm == pytest.approx(46.98970004336019, abs=1e-9)
        assert r.cascade_gain_db == pytest.approx(30.0)

    def test_output_input_identity(self):
        """恒等式：OIP2_tot − IIP2_tot == 总增益。"""
        b = LinkBudget()
        b.add_stage("a", gain_db=12.0, nf_db=2.0, iip2_dbm=15.0)
        b.add_stage("f", gain_db=-3.0, nf_db=1.0)
        b.add_stage("b", gain_db=8.0, nf_db=3.0, oip2_dbm=40.0)
        r = b.compute()
        assert (r.cascade_oip2_dbm - r.cascade_iip2_dbm) == pytest.approx(
            r.cascade_gain_db, abs=1e-9)

    def test_transparent_stages_skip(self):
        """无 IP2 级不进求和（其增益/损耗仍进 G_pre）；全链无 IP2 → 如实 None。

        手算：amp 前有 −2dB 损耗 → G_pre=0.631，IIP2 折算到链路输入
        = 100mW/0.631 → 22.0 dBm（损耗前置使输入参考值变大，物理正确）。
        """
        b = LinkBudget()
        b.add_stage("f1", gain_db=-2.0, nf_db=0.5)
        b.add_stage("amp", gain_db=15.0, nf_db=2.0, iip2_dbm=20.0)
        b.add_stage("f2", gain_db=-1.0, nf_db=0.5)
        r = b.compute()
        assert r.cascade_iip2_dbm == pytest.approx(22.0, abs=1e-9)
        assert r.cascade_oip2_dbm == pytest.approx(34.0, abs=1e-9)
        b2 = LinkBudget()
        b2.add_stage("f", gain_db=-2.0, nf_db=0.5)
        b2.add_stage("amp", gain_db=15.0, nf_db=2.0)
        r2 = b2.compute()
        assert r2.cascade_iip2_dbm is None
        assert r2.cascade_oip2_dbm is None
        assert r2.to_dict()["cascade_iip2_dbm"] is None

    def test_cumulative_columns(self):
        """逐级累积列：首个 IP2 级起非 None，其后单调下降。"""
        b = LinkBudget()
        b.add_stage("s1", gain_db=10.0, nf_db=1.0, iip2_dbm=10.0)
        b.add_stage("s2", gain_db=10.0, nf_db=1.0, iip2_dbm=20.0)
        r = b.compute()
        assert r.stages[0].cumulative_iip2_dbm == pytest.approx(10.0, abs=1e-9)
        # 级2：G_pre=10，IIP2=100mW → 10/100=0.1 + 1/10=0.1 → 5 mW=6.9897
        assert r.stages[1].cumulative_iip2_dbm == pytest.approx(
            6.989700043360187, abs=1e-9)
        assert r.cascade_iip2_dbm == pytest.approx(6.989700043360187, abs=1e-9)

    def test_xor_guard_iip2_oip2(self):
        """iip2/oip2 双给 → 显式 ValueError（歧义拒绝）。"""
        b = LinkBudget()
        with pytest.raises(ValueError, match="二选一"):
            b.add_stage("x", gain_db=10.0, nf_db=1.0,
                        iip2_dbm=20.0, oip2_dbm=30.0)

    def test_nonfinite_rejected(self):
        b = LinkBudget()
        with pytest.raises(ValueError, match="有限"):
            b.add_stage("x", gain_db=10.0, nf_db=1.0, iip2_dbm=float("nan"))
        with pytest.raises(ValueError, match="有限"):
            b.add_stage("x", gain_db=10.0, nf_db=1.0, oip2_dbm=float("inf"))

    def test_to_dict_carries_ip2_fields(self):
        b = LinkBudget()
        b.add_stage("mixer", gain_db=-7.0, nf_db=7.0, iip2_dbm=40.0)
        d = b.compute().to_dict()
        assert d["stages"][0]["iip2_dbm"] == pytest.approx(40.0)
        assert d["stages"][0]["oip2_dbm"] is None
        assert d["cascade_iip2_dbm"] == pytest.approx(40.0)
        assert d["cascade_oip2_dbm"] == pytest.approx(33.0)

    def test_ip2_ip3_independent_sums(self):
        """同一链 IP2/IP3 各自独立求和，互不污染（期望=独立手算）。"""
        import math

        b = LinkBudget()
        b.add_stage("lna", gain_db=20.0, nf_db=0.8, oip3_dbm=30.0, iip2_dbm=25.0)
        b.add_stage("mixer", gain_db=-7.0, nf_db=7.0, oip3_dbm=10.0, oip2_dbm=50.0)
        r = b.compute()
        # IP3 手算：IIP3_1=10dBm=10mW（G_pre=1）；IIP3_2=17dBm=50.1187mW
        # （G_pre=100）→ inv=0.1+1.99526=2.09526 → −3.2124 dBm
        assert r.cascade_iip3_dbm == pytest.approx(-3.2124, abs=0.001)
        # IP2 手算（独立路径）：IIP2_1=25dBm=316.23mW；IIP2_2=57dBm（G_pre=100）
        inv = 1.0 / 10 ** 2.5 + 10 ** 2.0 / 10 ** 5.7
        expect = 10.0 * math.log10(1.0 / inv)
        assert r.cascade_iip2_dbm == pytest.approx(expect, abs=1e-12)

    def test_cross_consistency_with_cascade_ipn_merge(self):
        """跨面一致性：LinkBudget(order=2) == cascade_ipn_merge(order=2)。

        同一幂和式的两个实现（budget 逐级累积 vs cascade 一次求和）。
        """
        stages = [
            {"name": "lna", "gain_db": 15.0, "ipn_dbm": 5.0},
            {"name": "filter", "gain_db": -2.0, "ipn_dbm": 60.0},
            {"name": "mixer", "gain_db": 8.0, "ipn_dbm": 20.0},
        ]
        merged = cascade_ipn_merge(stages, order=2)
        b = LinkBudget()
        for st in stages:
            b.add_stage(st["name"], gain_db=st["gain_db"], nf_db=1.0,
                        iip2_dbm=st["ipn_dbm"])
        r = b.compute()
        assert r.cascade_iip2_dbm == pytest.approx(
            merged["ipn_total_input_dbm"], abs=1e-9)
        assert r.cascade_oip2_dbm == pytest.approx(
            merged["ipn_total_output_dbm"], abs=1e-9)

    def test_single_ip2_stage_no_gain_offset_error(self):
        """单级 oip2 折算回自身：IIP2 = OIP2 − G 精确（不丢负增益方向）。"""
        b = LinkBudget()
        b.add_stage("pad", gain_db=-6.0, nf_db=6.0, oip2_dbm=44.0)
        r = b.compute()
        assert r.cascade_iip2_dbm == pytest.approx(50.0, abs=1e-9)
        assert r.cascade_oip2_dbm == pytest.approx(44.0, abs=1e-9)
