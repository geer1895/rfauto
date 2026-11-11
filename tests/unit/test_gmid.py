"""gm/ID 查表定尺寸内核单测（AX-7，aurora_r R-19 席；core/gmid.py）。

覆盖：
- 合成源物理极限钉（强反型 2/Vov 平方律渐近、弱反型 1/(n·UT) 亚阈极限）；
- #118 独立口径对拍：lookup 节点回收 -> 独立重导 EKV 闭式比
  σ(x)/(n·UT·ln(1+e^x))（与 src 的 gm/id 分算路径独立）；size 结果回代
  平方律闭式 2/Vov 直算 gm/ID 对拍 ≤1e-6（任务书钉，gmid=2 深强反型点）；
- size 双维反解闭环（size(lookup(x))≈x）与 (id,w)/(gm,w) 两路径互证；
- size_from_ft 节点精确 + 节点间线性反解 + 越界 flag；
- 越界 nearest-with-flag（lookup/size/size_from_ft 全家，不静默外推）；
- YAML 落盘逐位回读 + schema/版本/来源键 + 非法载荷显式报错；
- 缓存三件套（指纹寻址命中/参数变化 miss/文件删除重建/外部 mtime 改动
  重读不重建）；
- _fall_mask 折返防护（双值假源只落下降支 + 网格越峰显式报错）；
- refine=False 线性分箱档的诚实误差量级；W 无关性；确定性。

精度归属：合成源=教科书闭式教学级（非 PDK 级），本文件闭式均独立重导。
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.gmid import (
    GmIdTable,
    SyntheticMosSource,
    build_gmid_table,
    clear_table_cache,
    get_or_build_table,
    lookup,
    size,
    size_from_ft,
)

# ---------------------------------------------------------------------------
# 独立口径闭式（测试文件内独立重导，不 import src 内部 helper）
# ---------------------------------------------------------------------------
_K_B = 1.380649e-23  # J/K（SI 定义常数）
_Q_E = 1.602176634e-19  # C（SI 定义常数）
_VT0 = 0.4
_N_SUB = 1.3
_TEMP_K = 300.0


def _ut_v(temp_k: float = _TEMP_K) -> float:
    return _K_B * temp_k / _Q_E


def _cf_gmid(vgs_v: float) -> float:
    """EKV 平滑式 gm/ID 闭式比 sigma(x)/(n*UT*ln(1+e^x))——独立计算路径。

    src 侧 gm 与 id 分算后相除；此处直接按解析比式计算（tanh/logaddexp
    数值路径也不同）——两路径同式异码，即 #118 的"独立来源解析值"。
    """
    nut = _N_SUB * _ut_v()
    x = (vgs_v - _VT0) / (2.0 * nut)
    s = float(np.logaddexp(0.0, x))
    sig = 0.5 * (1.0 + math.tanh(x / 2.0))
    return sig / (nut * s)


L_GRID = [0.18e-6, 0.36e-6, 0.6e-6, 1.0e-6]
GMID_GRID = [2.0 + 0.5 * i for i in range(53)]  # 2.0 .. 28.0 V^-1

_L_SMALL = [0.5e-6, 1.0e-6]
_G_SMALL = [4.0, 8.0, 12.0, 16.0, 20.0]


def _small_table(refine: bool = True, w_unit_m: float = 1.0e-6,
                 gmid_grid: list[float] | None = None) -> GmIdTable:
    return build_gmid_table(
        SyntheticMosSource(),
        source_meta=SyntheticMosSource().source_meta(),
        l_grid_m=_L_SMALL,
        gmid_grid_per_v=gmid_grid if gmid_grid is not None else _G_SMALL,
        w_unit_m=w_unit_m, f_char_hz=1.0e6,
        vgs_start_v=0.0, vgs_stop_v=1.6, vgs_step_v=4.0e-3, refine=refine)


@pytest.fixture(scope="module")
def table() -> GmIdTable:
    """全网格主表（refine=True，节点行=源直接评估）。"""
    return build_gmid_table(
        SyntheticMosSource(),
        source_meta=SyntheticMosSource().source_meta(),
        l_grid_m=L_GRID, gmid_grid_per_v=GMID_GRID)


# ---------------------------------------------------------------------------
# 合成源物理极限（源自身的独立物理钉）
# ---------------------------------------------------------------------------
class TestSyntheticSourceLimits:
    def test_strong_inversion_square_law_asymptote(self):
        src = SyntheticMosSource()
        d = src(1.0e-6, 1.0e-6, 1.4, 1.0e6)
        gmid = d["gm"] / d["id"]
        # 平方律闭式 gm/ID = 2/Vov（CLM 因子在比值中相消）；EKV 平滑修正
        # 相对偏差 = e^-x(1+1/x) ≈ 3.69e-7，绝对偏差 = 2.0×3.69e-7 ≈ 7.4e-7
        assert abs(gmid - 2.0 / (1.4 - _VT0)) <= 1.0e-6

    def test_weak_inversion_subthreshold_limit(self):
        src = SyntheticMosSource()
        d = src(1.0e-6, 1.0e-6, 0.05, 1.0e6)
        gmid = d["gm"] / d["id"]
        limit = 1.0 / (_N_SUB * _ut_v())
        # VGS=0.05 处距极限偏差 ~e^x/2（x=(0.05-0.4)/(2nUT)≈-5.2）≈ 0.3%
        assert abs(gmid / limit - 1.0) <= 0.01

    def test_bad_params_rejected(self):
        with pytest.raises(ValueError, match="n_sub"):
            SyntheticMosSource(n_sub=0.0)
        with pytest.raises(ValueError, match="lambda"):
            SyntheticMosSource(lambda_v_per_v_per_um=-1.0)


# ---------------------------------------------------------------------------
# lookup：节点回收 + #118 独立口径对拍 + 越界 flag
# ---------------------------------------------------------------------------
class TestLookup:
    def test_node_closure_against_independent_closed_form(self, table):
        """全部 4x53 节点：行 VGS 回代独立闭式比，gmid 闭合 <=1e-9。"""
        worst = 0.0
        for l_m in L_GRID:
            for g in GMID_GRID:
                row = lookup(table, l_m, g)
                assert row.clamped_axes == ()
                worst = max(worst, abs(_cf_gmid(row.vgs_v) - g))
        assert worst <= 1.0e-9

    def test_square_law_closure_at_gmid2_le_1e6(self, table):
        """任务书钉：size/lookup 结果回代平方律闭式 2/Vov，对拍 <=1e-6。

        gmid=2.0 为深强反型点（Vov≈1V，x≈14.9），EKV 平滑修正
        ~e^-x(1+1/x)≈3.7e-7 < 1e-6——闭式与查表在该点应闭合。
        """
        row = lookup(table, 1.0e-6, 2.0)
        gmid_sq = 2.0 / (row.vgs_v - _VT0)
        assert abs(gmid_sq - 2.0) <= 1.0e-6

    def test_interior_interpolation_between_nodes(self, table):
        lo = lookup(table, 0.36e-6, 10.0)
        mid = lookup(table, 0.36e-6, 10.25)
        hi = lookup(table, 0.36e-6, 10.5)
        assert mid.clamped_axes == ()
        for a, c, b in ((lo.id_w_a_per_m, mid.id_w_a_per_m, hi.id_w_a_per_m),
                        (lo.vgs_v, mid.vgs_v, hi.vgs_v),
                        (lo.f_t_hz, mid.f_t_hz, hi.f_t_hz)):
            assert min(a, b) <= c <= max(a, b)

    def test_out_of_range_nearest_with_flag(self, table):
        """越界=最近边界端点+flag（值与边界节点逐位一致，不静默外推）。"""
        r_l = lookup(table, 2.0e-6, 12.0)  # L 越上界
        ref_l = lookup(table, 1.0e-6, 12.0)
        assert r_l.clamped_axes == ("l",)
        assert r_l.id_w_a_per_m == ref_l.id_w_a_per_m
        assert r_l.vgs_v == ref_l.vgs_v
        r_g = lookup(table, 0.36e-6, 40.0)  # gmid 越上界
        ref_g = lookup(table, 0.36e-6, 28.0)
        assert r_g.clamped_axes == ("gmid",)
        assert r_g.vgs_v == ref_g.vgs_v
        r_both = lookup(table, 2.0e-6, 40.0)
        assert r_both.clamped_axes == ("l", "gmid")
        r_low = lookup(table, 0.1e-6, 1.0)  # 双轴越下界
        ref_low = lookup(table, 0.18e-6, 2.0)
        assert r_low.clamped_axes == ("l", "gmid")
        assert r_low.vgs_v == ref_low.vgs_v
        with pytest.raises(ValueError, match="有限"):
            lookup(table, float("nan"), 10.0)

    def test_off_grid_l_bilinear(self, table):
        """L 轴节点间：双线性内点值介于两邻行之间。"""
        a = lookup(table, 0.36e-6, 10.0)
        b = lookup(table, 0.6e-6, 10.0)
        m = lookup(table, 0.48e-6, 10.0)
        assert m.clamped_axes == ()
        assert min(a.id_w_a_per_m, b.id_w_a_per_m) <= m.id_w_a_per_m \
            <= max(a.id_w_a_per_m, b.id_w_a_per_m)


# ---------------------------------------------------------------------------
# size：双维反解闭环
# ---------------------------------------------------------------------------
class TestSize:
    def test_size_of_lookup_roundtrip(self, table):
        """size(lookup(x))≈x：双维反解闭环（任务书钉）。"""
        row = lookup(table, 0.6e-6, 12.0)
        w0 = 25.0e-6
        r = size(table, l_m=0.6e-6, id_a=row.id_w_a_per_m * w0,
                 gm_s=12.0 * row.id_w_a_per_m * w0)
        assert r.clamped_axes == ()
        assert r.w_m == pytest.approx(w0, rel=1.0e-12)
        assert r.gmid_per_v == pytest.approx(12.0, rel=1.0e-12)
        assert r.vgs_v == pytest.approx(row.vgs_v, abs=1.0e-12)
        assert r.l_m == 0.6e-6

    def test_id_gm_path_direct(self, table):
        r = size(table, l_m=1.0e-6, id_a=100.0e-6, gm_s=100.0e-6 * 10.0)
        assert r.gmid_per_v == pytest.approx(10.0, rel=1.0e-12)
        assert r.w_m > 0.0
        assert not r.clamped_axes

    def test_id_w_and_gm_w_paths_consistent(self, table):
        """(id,w)/(gm,w) 两反解路径与 (id,gm) 直查路径三向互证（节点点）。"""
        row = lookup(table, 0.36e-6, 10.0)
        w0 = 40.0e-6
        id0 = row.id_w_a_per_m * w0
        gm0 = 10.0 * id0
        r_iw = size(table, l_m=0.36e-6, id_a=id0, w_m=w0)
        r_gw = size(table, l_m=0.36e-6, gm_s=gm0, w_m=w0)
        for r in (r_iw, r_gw):
            assert r.gmid_per_v == pytest.approx(10.0, abs=1.0e-9)
            assert r.vgs_v == pytest.approx(row.vgs_v, abs=1.0e-9)
            assert r.w_m == w0

    def test_dimension_count_and_positivity_guarded(self, table):
        with pytest.raises(ValueError, match="两维"):
            size(table, l_m=0.36e-6, id_a=1.0e-4)
        with pytest.raises(ValueError, match="两维"):
            size(table, l_m=0.36e-6, id_a=1.0e-4, gm_s=1.0e-3, w_m=1.0e-5)
        with pytest.raises(ValueError, match="正有限"):
            size(table, l_m=0.36e-6, id_a=-1.0, gm_s=1.0e-3)
        with pytest.raises(ValueError, match="正有限"):
            size(table, l_m=0.36e-6, id_a=1.0e-4, gm_s=float("nan"))

    def test_out_of_range_clamped(self, table):
        r = size(table, l_m=0.36e-6, id_a=1.0e-3, gm_s=1.0e-3 * 40.0)
        assert "gmid" in r.clamped_axes  # gmid=40 超出网格上端 28
        r2 = size(table, l_m=5.0e-6, id_a=1.0e-4, gm_s=1.0e-3)
        assert "l" in r2.clamped_axes


# ---------------------------------------------------------------------------
# size_from_ft：fT 反查
# ---------------------------------------------------------------------------
class TestSizeFromFt:
    def test_node_exact(self, table):
        il = L_GRID.index(0.36e-6)
        j = GMID_GRID.index(10.0)
        ft_node = float(table.f_t_hz[il, j])
        r = size_from_ft(table, f_t_hz=ft_node, l_m=0.36e-6)
        assert r.w_m is None  # 未给 id：欠定维度如实 None
        assert r.gmid_per_v == pytest.approx(10.0, abs=1.0e-9)
        assert r.vgs_v == pytest.approx(float(table.vgs_v[il, j]), abs=1.0e-12)
        r2 = size_from_ft(table, f_t_hz=ft_node, l_m=0.36e-6, id_a=1.0e-4)
        assert r2.w_m == pytest.approx(1.0e-4 / float(table.id_w_a_per_m[il, j]),
                                       rel=1.0e-12)

    def test_between_nodes_linear_inversion(self, table):
        il = L_GRID.index(0.36e-6)
        j = GMID_GRID.index(10.0)
        ft_mid = 0.5 * (float(table.f_t_hz[il, j]) + float(table.f_t_hz[il, j + 1]))
        r = size_from_ft(table, f_t_hz=ft_mid, l_m=0.36e-6)
        # 反解 gmid 落在节点间（线性列反解 + 光滑列 => 误差远小于半格）
        assert r.gmid_per_v == pytest.approx(10.25, abs=0.05)
        # 回查行 fT 与目标闭合（同一线性插值族）
        assert r.f_t_hz == pytest.approx(ft_mid, rel=1.0e-12)

    def test_out_of_range_clamped(self, table):
        il = L_GRID.index(0.36e-6)
        ft_max = float(np.max(table.f_t_hz[il]))
        r = size_from_ft(table, f_t_hz=ft_max * 10.0, l_m=0.36e-6)
        assert "gmid" in r.clamped_axes
        # 夹到 fT 最大端（gmid 下端节点）
        assert r.gmid_per_v == pytest.approx(float(table.gmid_per_v[0]),
                                             rel=1.0e-12)
        with pytest.raises(ValueError, match="正有限"):
            size_from_ft(table, f_t_hz=-1.0, l_m=0.36e-6)


# ---------------------------------------------------------------------------
# 落盘格式：YAML 逐位回读 + 版本/来源键 + 非法载荷
# ---------------------------------------------------------------------------
class TestTableIo:
    def test_yaml_roundtrip_bit_exact(self, table, tmp_path):
        p = tmp_path / "gmid_table.yaml"
        assert table.save_yaml(p) == p
        text = p.read_text(encoding="utf-8")
        assert "schema: rfauto-gmid-table-v1" in text
        assert "table_version: 1" in text
        assert "name: ekv_synthetic_mos" in text
        assert "kind: synthetic" in text
        assert "not PDK-grade" in text  # 精度归属键在档
        t2 = GmIdTable.load_yaml(p)
        assert np.array_equal(t2.l_um, table.l_um)
        assert np.array_equal(t2.gmid_per_v, table.gmid_per_v)
        for col in ("id_w_a_per_m", "gm_gds", "f_t_hz", "vgs_v"):
            assert np.array_equal(getattr(t2, col), getattr(table, col)), col
        assert t2.source == table.source
        assert t2.sweep == table.sweep
        assert t2.sweep["refine"] is True

    def test_from_dict_rejects_bad_payload(self, table):
        d = table.to_dict()
        with pytest.raises(ValueError, match="schema"):
            GmIdTable.from_dict({**d, "schema": "other"})
        with pytest.raises(ValueError, match="table_version"):
            GmIdTable.from_dict({**d, "table_version": 2})
        with pytest.raises(ValueError, match="columns"):
            GmIdTable.from_dict({**d, "columns": ["a", "b", "c", "d"]})
        with pytest.raises(ValueError, match="严格递增"):
            GmIdTable.from_dict({**d, "gmid_per_v": list(reversed(d["gmid_per_v"]))})
        with pytest.raises(ValueError, match="values 行数"):
            GmIdTable.from_dict({**d, "values": d["values"][:-1]})
        d_nan = {**d, "values": [dict(v) for v in d["values"]]}
        d_nan["values"][0]["rows"] = [list(r) for r in d_nan["values"][0]["rows"]]
        d_nan["values"][0]["rows"][0][0] = float("nan")
        with pytest.raises(ValueError, match="非有限"):
            GmIdTable.from_dict(d_nan)


# ---------------------------------------------------------------------------
# 首调建表 + 缓存（指纹 + 表文件 mtime）
# ---------------------------------------------------------------------------
class TestGetOrBuildCache:
    @staticmethod
    def _counting_source(counter: dict[str, int]):
        base = SyntheticMosSource()

        def src(w_m: float, l_m: float, vgs_v: float, f_hz: float):
            counter["n"] += 1
            return base(w_m, l_m, vgs_v, f_hz)

        return src

    def test_hit_miss_invalidate(self, tmp_path):
        clear_table_cache()
        cache_dir = tmp_path / "cache"
        counter = {"n": 0}
        src = self._counting_source(counter)
        kw = dict(source_meta={"name": "counting_ekv", "kind": "synthetic",
                               "params": {}},
                  l_grid_m=_L_SMALL, gmid_grid_per_v=_G_SMALL,
                  vgs_start_v=0.0, vgs_stop_v=1.6, vgs_step_v=4.0e-3)
        t1 = get_or_build_table(src, cache_dir=cache_dir, **kw)
        n1 = counter["n"]
        assert n1 > 0  # 首调真建表
        files = list(cache_dir.glob("gmid_*.yaml"))
        assert len(files) == 1
        t2 = get_or_build_table(src, cache_dir=cache_dir, **kw)
        assert counter["n"] == n1  # 命中：零特性化调用
        assert np.array_equal(t2.id_w_a_per_m, t1.id_w_a_per_m)
        # 指纹失效：gmid 网格变化 -> 新文件 + 重建
        n_before = counter["n"]
        t3 = get_or_build_table(src, cache_dir=cache_dir,
                                source_meta=kw["source_meta"],
                                l_grid_m=_L_SMALL,
                                gmid_grid_per_v=[4.0, 8.0, 12.0, 16.0, 21.0],
                                vgs_start_v=0.0, vgs_stop_v=1.6,
                                vgs_step_v=4.0e-3)
        assert counter["n"] > n_before
        assert t3.gmid_per_v[-1] == 21.0
        assert len(list(cache_dir.glob("gmid_*.yaml"))) == 2
        # 文件删除 -> 重建
        for f in cache_dir.glob("gmid_*.yaml"):
            f.unlink()
        clear_table_cache()
        n_before = counter["n"]
        get_or_build_table(src, cache_dir=cache_dir, **kw)
        assert counter["n"] > n_before
        # 外部改表文件 mtime -> memo 失效重读磁盘（不重新特性化）
        t4 = get_or_build_table(src, cache_dir=cache_dir, **kw)
        n4 = counter["n"]
        path = next(cache_dir.glob("gmid_*.yaml"))
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        t5 = get_or_build_table(src, cache_dir=cache_dir, **kw)
        assert counter["n"] == n4  # 重读而非重建
        assert np.array_equal(t5.id_w_a_per_m, t4.id_w_a_per_m)

    def test_external_source_requires_meta(self, tmp_path):
        def src(w_m: float, l_m: float, vgs_v: float, f_hz: float):
            return {"id": 1.0e-4, "gm": 1.0e-3, "gds": 1.0e-5, "cgg": 1.0e-14}

        with pytest.raises(ValueError, match="source_meta"):
            get_or_build_table(src, cache_dir=tmp_path, l_grid_m=_L_SMALL,
                               gmid_grid_per_v=_G_SMALL)


# ---------------------------------------------------------------------------
# 建表器守卫：_fall_mask 折返防护 / 覆盖显式报错 / 源契约 / refine 档
# ---------------------------------------------------------------------------
def _double_valued_source(w_m: float, l_m: float, vgs_v: float,
                          f_hz: float) -> dict[str, float]:
    """gmid(VGS)=6+8*exp(-((vgs-0.5)/0.15)^2) 假源：峰值 14 两侧双值。"""
    gmid = 6.0 + 8.0 * math.exp(-((vgs_v - 0.5) / 0.15) ** 2)
    id_a = 1.0e-5 * math.exp(3.0 * vgs_v)
    return {"id": id_a, "gm": gmid * id_a, "gds": 0.1 * id_a, "cgg": 1.0e-14}


_META_FAKE = {"name": "fake_double_valued", "kind": "synthetic", "params": {}}


class TestBuilderGuards:
    def test_fall_mask_keeps_descending_branch_only(self):
        tbl = build_gmid_table(
            _double_valued_source, source_meta=_META_FAKE,
            l_grid_m=[1.0e-6], gmid_grid_per_v=[7.0, 9.0, 11.0, 13.0],
            vgs_start_v=0.0, vgs_stop_v=1.2, vgs_step_v=1.0e-2)
        for g in (7.0, 9.0, 11.0, 13.0):
            row = lookup(tbl, 1.0e-6, g)
            # 只落峰值右侧下降支（亚阈上升支被丢弃，双值不静默混入）
            assert row.vgs_v > 0.5
            gmid_cf = 6.0 + 8.0 * math.exp(-((row.vgs_v - 0.5) / 0.15) ** 2)
            assert abs(gmid_cf - g) <= 1.0e-9

    def test_grid_above_peak_rejected_loudly(self):
        with pytest.raises(ValueError, match="超出源可达峰值"):
            build_gmid_table(
                _double_valued_source, source_meta=_META_FAKE,
                l_grid_m=[1.0e-6], gmid_grid_per_v=[7.0, 15.0],
                vgs_start_v=0.0, vgs_stop_v=1.2, vgs_step_v=1.0e-2)

    def test_grid_below_sweep_floor_rejected_loudly(self):
        src = SyntheticMosSource()
        with pytest.raises(ValueError, match="低于源可达最小"):
            build_gmid_table(
                src, source_meta=src.source_meta(),
                l_grid_m=[1.0e-6], gmid_grid_per_v=[1.0, 2.0],
                vgs_start_v=0.0, vgs_stop_v=1.2, vgs_step_v=2.0e-3)

    def test_source_contract_violations(self):
        def missing_keys(w_m: float, l_m: float, vgs_v: float, f_hz: float):
            return {"id": 1.0e-4, "gm": 1.0e-3}

        with pytest.raises(ValueError, match="缺键"):
            build_gmid_table(missing_keys, source_meta=_META_FAKE,
                             l_grid_m=[1.0e-6], gmid_grid_per_v=[4.0, 8.0])

        def zero_id(w_m: float, l_m: float, vgs_v: float, f_hz: float):
            return {"id": 0.0, "gm": 0.0, "gds": 1.0e-5, "cgg": 1.0e-14}

        with pytest.raises(ValueError, match="id<=0"):
            build_gmid_table(zero_id, source_meta=_META_FAKE,
                             l_grid_m=[1.0e-6], gmid_grid_per_v=[4.0, 8.0])
        with pytest.raises(ValueError, match="vgs 扫描参数非法"):
            build_gmid_table(SyntheticMosSource(),
                             source_meta=SyntheticMosSource().source_meta(),
                             l_grid_m=[1.0e-6], gmid_grid_per_v=[4.0, 8.0],
                             vgs_step_v=0.0)

    def test_refine_false_interpolation_budget(self):
        """refine=False 档：线性分箱插值误差的诚实量级钉（<=1e-3）。"""
        tbl = build_gmid_table(
            SyntheticMosSource(),
            source_meta=SyntheticMosSource().source_meta(),
            l_grid_m=[1.0e-6], gmid_grid_per_v=[4.0, 6.0, 8.0, 10.0],
            vgs_start_v=0.0, vgs_stop_v=1.8, vgs_step_v=2.0e-3, refine=False)
        assert tbl.sweep["refine"] is False
        worst = 0.0
        for g in (4.0, 6.0, 8.0, 10.0):
            row = lookup(tbl, 1.0e-6, g)
            worst = max(worst, abs(_cf_gmid(row.vgs_v) - g))
        assert worst <= 1.0e-3


# ---------------------------------------------------------------------------
# 方法论不变量与确定性
# ---------------------------------------------------------------------------
class TestMethodology:
    def test_unit_width_independence(self):
        """四列与 W 无关（gm/ID 枢轴量方法论内核）：换建表宽逐列一致。"""
        t1 = _small_table(w_unit_m=1.0e-6)
        t2 = _small_table(w_unit_m=20.0e-6)
        for col in ("id_w_a_per_m", "gm_gds", "f_t_hz", "vgs_v"):
            assert np.allclose(getattr(t1, col), getattr(t2, col),
                               rtol=1.0e-12, atol=0.0), col

    def test_build_deterministic(self):
        t1 = _small_table()
        t2 = _small_table()
        for col in ("id_w_a_per_m", "gm_gds", "f_t_hz", "vgs_v"):
            assert np.array_equal(getattr(t1, col), getattr(t2, col)), col

    def test_column_monotonicity_synthetic(self, table):
        """合成源表列单调性（反解前提）：id_w/f_t 随 gmid 降、gm_gds 升。"""
        il = L_GRID.index(0.36e-6)
        assert np.all(np.diff(table.id_w_a_per_m[il]) < 0.0)
        assert np.all(np.diff(table.f_t_hz[il]) < 0.0)
        assert np.all(np.diff(table.gm_gds[il]) > 0.0)
        assert np.all(np.diff(table.vgs_v[il]) < 0.0)

    def test_row_and_size_result_to_dict(self, table):
        row = lookup(table, 0.36e-6, 10.0)
        d = row.to_dict()
        assert d["gmid_per_v"] == 10.0
        assert d["clamped_axes"] == []
        r = size(table, l_m=0.36e-6, id_a=1.0e-4, gm_s=1.0e-3)
        assert r.to_dict()["w_m"] == r.w_m
        r2 = size_from_ft(table, f_t_hz=float(table.f_t_hz[1, 4]),
                          l_m=0.36e-6)
        assert r2.to_dict()["w_m"] is None
