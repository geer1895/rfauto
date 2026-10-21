"""架构批 W2-S9：EC-1 skrf port-name 运算采纳 + EC-3 skrf 第三裁判单测。

EC-1（adapters/touchstone_interop.py 件 3）：attach_port_names /
resolve_port_key / connect_by_name / reorder_ports_by_name——skrf v2.1
port-name 网络运算采纳面（#314 掩码族上游防线）。

EC-3（core/conductor_loss.py skrf_surface_impedance_crosscheck）：skrf
``tlineFunctions.surface_impedance`` 作第三来源对拍裁判——光滑叠层两条
独立分层 TL 级联实现硬门（实测 1e-8 量级，阈值 1e-6）+ 粗糙档信息性比值。

裁判口径（#118 双来源）：
- EC-1：按名 connect == 按索引 connect 恒等（skrf 单源两种寻址）；
  置换-复原 roundtrip 逐位恒等（纯坐标变换不变量）；TS 文件 ! Port[k]
  名字往返（写 2.1 → 读回 + read_hfss_touchstone_comments 双读面对拍）；
  校验族（长度/重名/换行注入/前导 '!'）逐条显式拒绝。
- EC-3：ENIG 缺省叠层 1/10 GHz 光滑 rel_dev ≤1e-6（硬门，实测 ~5e-8）；
  单导体光滑极限 (1+j)Rs 恒等 ≤1e-6；粗糙档比值>1（信息性字段存在性+
  skrf CDF 增益不饱和于 2 的模型差声明）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

import skrf

from rfauto.adapters.touchstone_interop import (
    attach_port_names,
    connect_by_name,
    read_hfss_touchstone_comments,
    reorder_ports_by_name,
    resolve_port_key,
    write_touchstone_v2,
)
from rfauto.core.conductor_loss import (
    skrf_surface_impedance_crosscheck,
    smooth_surface_resistance,
)


def _net4(names: list[str] | None = None) -> skrf.Network:
    """4 端口测试网络（3 频点；非对称 S 分布便于置换断言）。"""
    freq = skrf.Frequency(1, 3, 3, unit="ghz")
    s = np.zeros((3, 4, 4), dtype=complex)
    s[:, 0, 1] = 0.5
    s[:, 1, 2] = 0.2 - 0.1j
    s[:, 2, 3] = 0.3
    s[:, 3, 0] = 0.1
    n = skrf.Network(frequency=freq, s=s)
    if names is not None:
        attach_port_names(n, names)
    return n


# ─── EC-1：port-name 运算采纳 ────────────────────────────────────────────────

class TestAttachPortNames:
    def test_roundtrip_set_get(self) -> None:
        n = _net4(["P1", "P2", "P3", "P4"])
        assert n.port_names == ["P1", "P2", "P3", "P4"]

    def test_length_mismatch_rejected(self) -> None:
        n = _net4()
        with pytest.raises(ValueError, match="不一致"):
            attach_port_names(n, ["A", "B", "C"])

    def test_duplicate_rejected(self) -> None:
        n = _net4()
        with pytest.raises(ValueError, match="重复"):
            attach_port_names(n, ["X", "X", "P3", "P4"])
        # skrf 原生 setter 不查重（行为差声明）——本函数补齐的防线
        native = skrf.Network(frequency=skrf.Frequency(1, 1, 1, "ghz"),
                              s=np.zeros((1, 2, 2), dtype=complex))
        native.port_names = ["X", "X"]
        assert native.port_names == ["X", "X"]

    def test_newline_injection_rejected(self) -> None:
        n = _net4()
        with pytest.raises(ValueError, match="换行"):
            attach_port_names(n, ["P1\n0.0 0.0", "P2", "P3", "P4"])

    def test_leading_bang_rejected(self) -> None:
        n = _net4()
        with pytest.raises(ValueError, match="'!'"):
            attach_port_names(n, ["!Port", "P2", "P3", "P4"])


class TestResolvePortKey:
    def test_int_and_str_resolve(self) -> None:
        n = _net4(["IN", "OUT", "G1", "G2"])
        assert resolve_port_key(n, 1) == 1
        assert resolve_port_key(n, "G2") == 3

    def test_unnamed_rejected(self) -> None:
        n = _net4()
        with pytest.raises(ValueError, match="未命名"):
            resolve_port_key(n, "P1")

    def test_unknown_and_ambiguous_rejected(self) -> None:
        n = _net4(["A", "B", "C", "D"])
        with pytest.raises(ValueError, match="不存在"):
            resolve_port_key(n, "Z")
        m = _net4()
        # 外部直 setter 绕过 attach 校验造成的重名（容忍面，解析端拒绝）
        m.port_names = ["K", "B", "K", "D"]
        with pytest.raises(ValueError, match="重名"):
            resolve_port_key(m, "K")

    def test_bool_rejected(self) -> None:
        n = _net4(["A", "B", "C", "D"])
        with pytest.raises(ValueError, match="bool"):
            resolve_port_key(n, True)


class TestConnectByName:
    def test_name_connect_equals_index_connect(self) -> None:
        """按名级联 == 按索引级联（skrf 单源双寻址恒等）。"""
        a = _net4(["P1", "P2", "P3", "P4"])
        b = _net4(["Q1", "Q2", "Q3", "Q4"])
        by_name = connect_by_name(a, "P2", b, "Q1")
        by_idx = skrf.network.connect(_net4(["P1", "P2", "P3", "P4"]), 1,
                                      _net4(["Q1", "Q2", "Q3", "Q4"]), 0)
        assert np.array_equal(by_name.s, by_idx.s)
        # 名字传播：被连接端口消费，其余按序保留（skrf 2.1 实测行为钉）
        assert by_name.port_names == ["P1", "P3", "P4", "Q2", "Q3", "Q4"]

    def test_connect_result_names_usable_downstream(self) -> None:
        """级联结果可继续按名运算（装配链）。"""
        a = _net4(["P1", "P2", "P3", "P4"])
        b = _net4(["Q1", "Q2", "Q3", "Q4"])
        c = connect_by_name(a, "P2", b, "Q1")
        assert resolve_port_key(c, "Q4") == 5

    def test_unnamed_network_rejected(self) -> None:
        a = _net4()
        b = _net4()
        with pytest.raises(ValueError, match="未命名"):
            connect_by_name(a, "P2", b, "Q1")


class TestReorderPortsByName:
    def test_reorder_restore_roundtrip_bitwise(self) -> None:
        """置换-复原 roundtrip：S/z0/名字四方逐位恒等（纯坐标变换）。"""
        n = _net4(["A", "B", "C", "D"])
        s0 = np.array(n.s)
        z0_0 = np.array(n.z0)
        p = np.array(n.s)
        reorder_ports_by_name(n, ["D", "C", "B", "A"])
        assert not np.array_equal(np.array(n.s), p)
        assert n.port_names == ["D", "C", "B", "A"]
        reorder_ports_by_name(n, ["A", "B", "C", "D"])
        assert np.array_equal(np.array(n.s), s0)
        assert np.array_equal(np.array(n.z0), z0_0)

    def test_reorder_preserves_s_values_multiset(self) -> None:
        """重排后 S 参数多重集不变（值集合不变量）。"""
        n = _net4(["A", "B", "C", "D"])
        vals_before = np.sort(np.abs(np.array(n.s)).ravel())
        reorder_ports_by_name(n, ["C", "A", "D", "B"])
        vals_after = np.sort(np.abs(np.array(n.s)).ravel())
        assert np.allclose(vals_before, vals_after, rtol=0, atol=0)

    def test_non_permutation_rejected(self) -> None:
        n = _net4(["A", "B", "C", "D"])
        with pytest.raises(ValueError, match="置换"):
            reorder_ports_by_name(n, ["A", "A", "B", "C"])

    def test_unnamed_rejected(self) -> None:
        n = _net4()
        with pytest.raises(ValueError, match="未命名"):
            reorder_ports_by_name(n, ["A", "B", "C", "D"])


class TestTs21PortNameRoundtrip:
    def test_write21_read_back_names(self, tmp_path) -> None:
        """TS 2.1 写出 → skrf 读回 + read_hfss_touchstone_comments 双读面
        均还原名字（! Port[k] 注释行载体）。"""
        n = _net4(["IN", "OUT", "G1", "G2"])
        path = write_touchstone_v2(n, tmp_path / "t.s4p")
        r = skrf.Network(str(path))
        assert r.port_names == ["IN", "OUT", "G1", "G2"]
        assert np.allclose(r.s, n.s)
        comments = read_hfss_touchstone_comments(path)
        assert comments["port_names"] == ["IN", "OUT", "G1", "G2"]

    def test_named_connect_export_roundtrip(self, tmp_path) -> None:
        """按名级联 → TS2.1 写出 → 读回：名字链全程存活（装配面闭环）。"""
        a = _net4(["P1", "P2", "P3", "P4"])
        b = _net4(["Q1", "Q2", "Q3", "Q4"])
        c = connect_by_name(a, "P2", b, "Q1")
        path = write_touchstone_v2(c, tmp_path / "c.s6p")
        r = skrf.Network(str(path))
        assert r.port_names == ["P1", "P3", "P4", "Q2", "Q3", "Q4"]


# ─── EC-3：skrf 第三来源裁判 ────────────────────────────────────────────────

_ENIG_LAYERS = [
    {"material": "au", "thickness_m": 7.5e-8, "conductivity_s_per_m": 4.1e7},
    {"material": "ni", "thickness_m": 3.0e-6, "conductivity_s_per_m": 1.45e7},
    {"material": "cu", "conductivity_s_per_m": 5.8e7},
]


class TestSkrfCrosscheck:
    def test_enig_smooth_referee_pass(self) -> None:
        """ENIG 缺省叠层光滑裁判 ≤1e-6（实测 ~2e-8 量级）。"""
        for f in (1e9, 10e9):
            r = skrf_surface_impedance_crosscheck(f, _ENIG_LAYERS)
            assert r["referee_pass"] is True
            assert r["rel_dev_smooth"] <= 1e-6

    def test_single_conductor_smooth_limit(self) -> None:
        """单导体光滑极限：双侧均回 (1+j)Rs（恒等式，≤1e-6）。"""
        f, s = 5e9, 5.8e7
        r = skrf_surface_impedance_crosscheck(
            f, [{"material": "cu", "conductivity_s_per_m": s}])
        rs = smooth_surface_resistance(f, s)
        assert r["referee_pass"] is True
        assert abs(complex(r["rfauto_z_in"]) - (1 + 1j) * rs) \
            <= 1e-6 * abs((1 + 1j) * rs)
        assert abs(complex(r["skrf_zs_smooth"]) - (1 + 1j) * rs) \
            <= 1e-6 * abs((1 + 1j) * rs)

    def test_rough_diagnostics_informational(self) -> None:
        """粗糙档：字段齐备、skrf CDF 增益不饱和于 2（模型差声明的实证）。"""
        r = skrf_surface_impedance_crosscheck(10e9, _ENIG_LAYERS,
                                              rms_roughness_m=0.5e-6)
        assert r["referee_pass"] is True  # 光滑裁判独立于粗糙档
        assert r["rough_gain_skrf"] > 1.0
        assert r["hammerstad_K_H"] >= 1.0
        assert r["hammerstad_K_H"] <= 2.0  # HJ RF=2 饱和上界
        assert r["rough_gain_ratio"] > 0.0  # 信息性比值（skrf 不饱和）
        assert r["skrf_zs_rough"] is not None

    def test_layer_semantics_inherited(self) -> None:
        """镀层透明极限：t_au=0 精确透传（层语义与 layered 面一致）。"""
        layers = [
            {"material": "au", "thickness_m": 0.0,
             "conductivity_s_per_m": 4.1e7},
            {"material": "cu", "conductivity_s_per_m": 5.8e7},
        ]
        r = skrf_surface_impedance_crosscheck(1e9, layers)
        assert r["referee_pass"] is True

    def test_negative_roughness_rejected(self) -> None:
        with pytest.raises(ValueError, match="rms_roughness_m"):
            skrf_surface_impedance_crosscheck(1e9, _ENIG_LAYERS,
                                              rms_roughness_m=-1e-6)

    def test_bad_layers_rejected(self) -> None:
        with pytest.raises(ValueError, match="layers"):
            skrf_surface_impedance_crosscheck(1e9, [])
