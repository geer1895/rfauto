"""core/pim_products.py 单测：双载波 PIM 产物枚举 + 落带 + 实测幅度归并。

判据（#118 双路径/手算守恒）：
- 2f1−f2 落点逐位（f1=2.4, f2=2.41 GHz → 2.39 GHz）；
- 阶数域守恒：枚举数 = 手算组合数（m,n≥1、2≤m+n≤p_max，每对 ± 两侧）；
- 幅度只接收实测/规格 dBc（铁律 7）——未知/重复键 fail-fast；
- 边界：f≤0、f1==f2、p_max<2、负带宽 → ValueError；
- to_dict JSON 往返 + 确定性枚举。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.pim_products import enumerate_pim_products


def _find(products, m, n, side):
    return next(p for p in products if (p.m, p.n, p.side) == (m, n, side))


class TestPimEnumeration:
    def test_2f1_minus_f2_exact(self):
        ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=7)
        p = _find(ps.products, 2, 1, "-")
        assert p.f_hz == 2.39e9  # 逐位
        assert p.order == 3 and p.hazard == "high"

    def test_sum_product_side_exact(self):
        ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=3)
        p = _find(ps.products, 1, 1, "+")
        assert p.f_hz == 4.81e9  # 逐位
        assert p.order == 2 and p.hazard == "high"  # 阶 2 ≤3 → high

    def test_order_domain_conservation_pmax3(self):
        # 手算组合数：m,n≥1、m+n≤3 → (1,1),(1,2),(2,1) 共 3 对 × 2 侧 = 6
        ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=3)
        assert ps.n_products == 6
        assert all(2 <= p.order <= 3 for p in ps.products)
        assert all(p.m >= 1 and p.n >= 1 for p in ps.products)
        # (3,1)/(1,3) 等阶 4 产物缺席（阶数域截断守恒）
        with pytest.raises(StopIteration):
            _find(ps.products, 3, 1, "-")

    def test_order_domain_conservation_pmax5(self):
        # 手算：s=2..5 的 (m,n) 对数 1+2+3+4=10 → 20 产物（无 DC 退化：
        # |m·f1−n·f2|=0 需 m/n=241/240，域内不可达）
        ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=5)
        assert ps.n_products == 20
        orders = sorted({p.order for p in ps.products})
        assert orders == [2, 3, 4, 5]

    def test_hazard_ladder(self):
        ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=7)
        assert _find(ps.products, 1, 1, "+").hazard == "high"     # 阶 2 ≤3
        assert _find(ps.products, 2, 1, "-").hazard == "high"     # 阶 3
        assert _find(ps.products, 3, 2, "-").hazard == "medium"   # 阶 5
        assert _find(ps.products, 3, 4, "-").hazard == "low"      # 阶 7

    def test_deterministic_ordering(self):
        a = enumerate_pim_products(2.4e9, 2.41e9, p_max=5)
        b = enumerate_pim_products(2.4e9, 2.41e9, p_max=5)
        assert [p.to_dict() for p in a.products] == \
               [p.to_dict() for p in b.products]
        keys = [(p.order, p.f_hz, p.m, p.n, p.side) for p in a.products]
        assert keys == sorted(keys)


class TestPimRxFlag:
    def test_in_band_flag_and_offset(self):
        ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=3,
                                    rx_center_hz=2.39e9, rx_bw_hz=1e6)
        hit = _find(ps.products, 2, 1, "-")
        assert hit.in_rx_band is True
        # offset 经 f−rx_center 浮点路径（与 f_hz 字面量路径不同源），带容差
        assert abs(hit.offset_from_rx_center_hz) <= 1e-3
        miss = _find(ps.products, 1, 1, "-")  # |f1−f2| = 10 MHz，远高于带
        assert miss.in_rx_band is False
        # offset = 产物频率 − rx_center = 10 MHz − 2.39 GHz
        assert abs(miss.offset_from_rx_center_hz
                   - (10e6 - 2.39e9)) <= 1e-3
        assert ps.n_in_band == 1

    def test_rx_none_means_not_judged(self):
        ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=3)
        assert all(p.in_rx_band is None for p in ps.products)
        assert all(p.offset_from_rx_center_hz is None for p in ps.products)
        assert ps.n_in_band is None  # 未判非判外（判缺失 is not None 语义）


class TestPimAmplitudes:
    def test_measured_spec_merge(self):
        # 幅度只接收实测/规格 dBc（IEC 62037 口径）——未给者 None
        ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=3,
                                    amplitudes=[
                                        {"m": 2, "n": 1, "side": "-",
                                         "dbc": -160.0}])
        hit = _find(ps.products, 2, 1, "-")
        assert hit.dbc == -160.0
        assert hit.amplitude_source == "measured_spec"
        others = [p for p in ps.products if p.dbc is not None]
        assert len(others) == 1

    def test_unknown_product_rejected(self):
        with pytest.raises(ValueError, match="不在枚举域"):
            enumerate_pim_products(2.4e9, 2.41e9, p_max=3,
                                   amplitudes=[{"m": 7, "n": 1, "side": "-",
                                                "dbc": -160.0}])

    def test_duplicate_and_bad_spec_rejected(self):
        amps = [{"m": 2, "n": 1, "side": "-", "dbc": -160.0}]
        with pytest.raises(ValueError, match="重复"):
            enumerate_pim_products(2.4e9, 2.41e9, p_max=3,
                                   amplitudes=amps + amps)
        with pytest.raises(ValueError, match="side"):
            enumerate_pim_products(2.4e9, 2.41e9, p_max=3,
                                   amplitudes=[{"m": 2, "n": 1,
                                                "side": "x", "dbc": -1.0}])
        with pytest.raises(ValueError, match="dbc"):
            enumerate_pim_products(2.4e9, 2.41e9, p_max=3,
                                   amplitudes=[{"m": 2, "n": 1, "side": "-",
                                                "dbc": float("nan")}])


class TestPimValidation:
    def test_carrier_validation(self):
        with pytest.raises(ValueError, match="f1_hz"):
            enumerate_pim_products(0.0, 2.41e9)
        with pytest.raises(ValueError, match="f2_hz"):
            enumerate_pim_products(2.4e9, -1.0)
        with pytest.raises(ValueError, match="退化单载波"):
            enumerate_pim_products(2.4e9, 2.4e9)
        with pytest.raises(ValueError, match="实数"):
            enumerate_pim_products(True, 2.41e9)

    def test_order_domain_validation(self):
        with pytest.raises(ValueError, match="p_max"):
            enumerate_pim_products(2.4e9, 2.41e9, p_max=1)
        with pytest.raises(ValueError, match="整数"):
            enumerate_pim_products(2.4e9, 2.41e9, p_max=3.0)
        with pytest.raises(ValueError, match="防呆上限"):
            enumerate_pim_products(2.4e9, 2.41e9, p_max=65)

    def test_rx_bandwidth_validation(self):
        with pytest.raises(ValueError, match="rx_center_hz"):
            enumerate_pim_products(2.4e9, 2.41e9, rx_bw_hz=1e6)
        with pytest.raises(ValueError, match="rx_bw_hz"):
            enumerate_pim_products(2.4e9, 2.41e9, rx_center_hz=2.39e9,
                                   rx_bw_hz=-1.0)


class TestPimToJson:
    def test_to_dict_json_round_trip(self):
        ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=3,
                                    rx_center_hz=2.39e9, rx_bw_hz=1e6,
                                    amplitudes=[{"m": 2, "n": 1, "side": "-",
                                                 "dbc": -160.0}])
        payload = json.loads(json.dumps(ps.to_dict(), allow_nan=False))
        assert payload["n_products"] == 6
        assert payload["n_in_band"] == 1
        assert payload["f1_hz"] == 2.4e9 and payload["f2_hz"] == 2.41e9
        assert "IEC 62037" in payload["amplitude_convention"]
        hit = next(p for p in payload["products"]
                   if (p["m"], p["n"], p["side"]) == (2, 1, "-"))
        assert hit["dbc"] == -160.0
        assert hit["f_hz"] == 2.39e9
