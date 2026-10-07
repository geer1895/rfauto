"""SV-3：Palace Floquet/周期结构配置接线单元测试（官方 schema 实录锚）。

grounding（2026-10-03 实录）：GitHub awslabs/palace tag v0.18.1
``scripts/schema/config-schema.json``——
- ``Boundaries.Periodic``＝BoundaryPairs（Donor/ReceiverAttributes +
  Translation|Affine 二选一互斥）＋FloquetWaveVector（3 元，
  每网格长度单位弧度，缺省 [0,0,0]）＋FloquetReferenceFrequency（GHz）；
- ``Boundaries.FloquetPort``＝Index(>0)/Attributes/
  IncidentPolarization(TE|TM|RHC|LHC)/MaxOrder(≥0)/Excitation|
  ExcitationIndex；
- 官方注记：FloquetPort 需要两个横向 BoundaryPairs（warning 级检查）；
  Index 重复=致命；官方 schema 无 Lattice/独立 2D 节（不虚设接口）；
- Solver.Driven.Samples 接口与 palace_solver.py 生成器同源（v0.18.1
  实录，顶层 MinFreq/MaxFreq 已废弃）。

判据=纯配置数学（离线全测）：键名/互斥/枚举/维数 fail-closed 校验、
Γ→X 扫 k 轨迹端点、装配产物五分节键集、一致性检查分级。
"""

from __future__ import annotations

import pytest

from rfauto.adapters.sv.palace_floquet import (
    build_boundary_pair,
    build_floquet_port,
    build_periodic_section,
    check_floquet_consistency,
    wavevector_axis,
)


def _pair(**kw):
    return build_boundary_pair([1], [2], **kw)


class TestBoundaryPair:
    def test_translation_pair(self):
        p = _pair(translation=[1.0, 0.0, 0.0])
        assert p["DonorAttributes"] == [1]
        assert p["ReceiverAttributes"] == [2]
        assert p["Translation"] == [1.0, 0.0, 0.0]

    def test_affine_pair(self):
        p = _pair(affine=[1.0] + [0.0] * 14 + [1.0])
        assert len(p["AffineTransformation"]) == 16

    def test_translation_affine_exclusive(self):
        with pytest.raises(ValueError, match="互斥"):
            _pair(translation=[1, 0, 0], affine=[0.0] * 16)

    def test_bad_attributes(self):
        with pytest.raises(ValueError, match="正整数"):
            build_boundary_pair([0], [2])
        with pytest.raises(ValueError, match="不得为空"):
            build_boundary_pair([], [])
        with pytest.raises(ValueError, match="16 元"):
            _pair(affine=[1.0] * 15)
        with pytest.raises(ValueError, match="3 元"):
            _pair(translation=[1.0, 0.0])


class TestPeriodicSection:
    def test_full_section_defaults(self):
        sec = build_periodic_section([_pair()])
        assert sec["FloquetWaveVector"] == [0.0, 0.0, 0.0]
        assert sec["FloquetReferenceFrequency"] == 0.0
        assert len(sec["BoundaryPairs"]) == 1

    def test_wave_vector_and_validation(self):
        sec = build_periodic_section(
            [_pair(), _pair()], wave_vector=(0.5, 0.0, 0.0),
            reference_frequency_ghz=5.0)
        assert sec["FloquetWaveVector"] == [0.5, 0.0, 0.0]
        assert sec["FloquetReferenceFrequency"] == 5.0
        with pytest.raises(ValueError, match="不得为空"):
            build_periodic_section([])
        with pytest.raises(ValueError, match="3 元"):
            build_periodic_section([_pair()], wave_vector=(1.0, 2.0))
        with pytest.raises(ValueError, match="≥0"):
            build_periodic_section([_pair()], reference_frequency_ghz=-1.0)
        with pytest.raises(ValueError, match="Donor"):
            build_periodic_section([{"Translation": [0, 0, 0]}])


class TestFloquetPort:
    def test_defaults(self):
        port = build_floquet_port(1, [3])
        assert port == {"Index": 1, "Attributes": [3],
                        "IncidentPolarization": "TE", "MaxOrder": 0}

    def test_excitation_forms(self):
        assert build_floquet_port(1, [3], excitation=True)["Excitation"] is True
        assert build_floquet_port(1, [3], excitation_index=2)[
            "ExcitationIndex"] == 2
        assert "Excitation" not in build_floquet_port(1, [3],
                                                      excitation_index=2)

    def test_validation(self):
        with pytest.raises(ValueError, match=">0"):
            build_floquet_port(0, [3])
        with pytest.raises(ValueError, match="IncidentPolarization"):
            build_floquet_port(1, [3], polarization="LHCP")
        with pytest.raises(ValueError, match="MaxOrder"):
            build_floquet_port(1, [3], max_order=-1)
        with pytest.raises(ValueError, match="Attributes"):
            build_floquet_port(1, [])


class TestConsistencyChecks:
    def test_few_pairs_warns(self):
        periodic = build_periodic_section([_pair()])
        issues = check_floquet_consistency(periodic, [build_floquet_port(1, [3])])
        assert any("两个横向" in i for i in issues)

    def test_duplicate_index_fatal(self):
        periodic = build_periodic_section([_pair(), _pair()])
        issues = check_floquet_consistency(
            periodic, [build_floquet_port(1, [3]), build_floquet_port(1, [4])])
        assert any("Index 重复" in i for i in issues)

    def test_no_ports_no_issues(self):
        periodic = build_periodic_section([_pair(), _pair()])
        assert check_floquet_consistency(periodic, []) == []


class TestAssemble:
    def test_five_sections_and_samples_interface(self):
        from rfauto.adapters.sv.palace_floquet import assemble_floquet_config
        cfg = assemble_floquet_config(
            mesh_file="mesh/unit_cell.msh", l0_m=1e-3,
            materials=[{"Attributes": [1], "epsilon_r": 2.1}],
            boundary_pairs=[_pair(translation=[1.0, 0.0, 0.0]),
                            _pair(translation=[0.0, 1.0, 0.0])],
            wave_vector=(0.0, 0.0, 0.0),
            floquet_ports=[build_floquet_port(1, [5], excitation=True)],
            freq_range_ghz=(8.0, 12.0, 41))
        assert set(cfg) == {"Problem", "Model", "Domains", "Boundaries",
                            "Solver"}
        assert cfg["Problem"]["Type"] == "Driven"
        assert cfg["Model"]["L0"] == 1e-3
        sample = cfg["Solver"]["Driven"]["Samples"][0]
        assert sample == {"Type": "Linear", "MinFreq": 8.0, "MaxFreq": 12.0,
                          "NSample": 41}
        assert "Periodic" in cfg["Boundaries"]

    def test_fatal_duplicate_index_raises_in_assemble(self):
        from rfauto.adapters.sv.palace_floquet import assemble_floquet_config
        with pytest.raises(ValueError, match="Index 重复"):
            assemble_floquet_config(
                mesh_file="m.msh", l0_m=1e-3,
                materials=[{"Attributes": [1]}],
                boundary_pairs=[_pair(), _pair()],
                floquet_ports=[build_floquet_port(1, [5]),
                               build_floquet_port(1, [6])])

    def test_validation(self):
        from rfauto.adapters.sv.palace_floquet import assemble_floquet_config
        kw = dict(l0_m=1e-3,
                  materials=[{"Attributes": [1]}],
                  boundary_pairs=[_pair()])
        with pytest.raises(ValueError, match="mesh_file"):
            assemble_floquet_config(mesh_file="", **kw)
        with pytest.raises(ValueError, match="L0"):
            assemble_floquet_config(mesh_file="m", **{**kw, "l0_m": 0.0})
        with pytest.raises(ValueError, match="Materials"):
            assemble_floquet_config(mesh_file="m", l0_m=1e-3, materials=[],
                                    boundary_pairs=[_pair()])
        with pytest.raises(ValueError, match="Attributes"):
            assemble_floquet_config(mesh_file="m", l0_m=1e-3,
                                    materials=[{"epsilon_r": 2.0}],
                                    boundary_pairs=[_pair()])
        with pytest.raises(ValueError, match="扫频栅格"):
            assemble_floquet_config(mesh_file="m", **kw,
                                    freq_range_ghz=(12.0, 8.0, 10))


class TestWavevectorAxis:
    def test_gamma_to_x(self):
        path = wavevector_axis(0, 0.5, 5)
        assert path[0] == (0.0, 0.0, 0.0)          # Γ
        assert path[-1] == (0.5, 0.0, 0.0)         # X
        assert len(path) == 5
        assert path[2] == (0.25, 0.0, 0.0)

    def test_validation(self):
        with pytest.raises(ValueError, match="axis"):
            wavevector_axis(3, 0.5, 5)
        with pytest.raises(ValueError, match="≥2"):
            wavevector_axis(0, 0.5, 1)
        with pytest.raises(ValueError, match="k_max"):
            wavevector_axis(0, -0.1, 5)
