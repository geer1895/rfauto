"""HFSS Touchstone 导出端口数通用化测试（1/N 端口一律按实际，不写死 2 端口）。

wp34 patch GT 战役 2026-09-16 故障回归：插件契约声明 2 端口而单馈 patch 的
HFSS 设计实际 1 端口，``export_touchstone`` 原条件 ``n_ports >= 2`` 把单端口
排除在扩展名修正之外 → 1 端口数据落进 ``params.s2p`` → 契约校验
``skrf.Network(.s2p)`` 按 2x2 reshape 抛 "cannot reshape array of size N
into shape (4,newaxis)"。

全部 mock PyAEDT 通道（单测禁真打 HFSS， 硬规则）；Touchstone 样例用
skrf 合成（1/2/3/4/5 端口往返）+ 内嵌 HFSS ExportNetworkData 导出格式片段
（2025.1 真机 .s1p 头部原样摘录，数值截短），不读 runs/。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import skrf as rf

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.hfss_adapter import (
    HfssAdapter,
    contract_for_port_count,
    infer_touchstone_port_count,
    touchstone_path_for_ports,
)
from rfauto.adapters.hfss_session import HfssSession
from rfauto.core.contracts import AdsExchangeContract, TouchstoneContract
from rfauto.core.errors import ContractViolationError

# ─── HFSS 2025.1 ExportNetworkData 单端口导出格式片段（真机 .s1p 头部原样） ──

_HFSS_S1P_SAMPLE = """\
! Touchstone file exported from HFSS 2025.1.0
!        File:           D:/rf_workspace/runs/wp34_patch_gt/diag/diag_build.aedt
!        Design:         RFADesign
!        Setup:          Setup1
!        Solution:       Sweep1
!
! Variables:
!        coax_r = 1.5mm
!        patch_len = 41.574447mm
!
!Data is not renormalized
!S-parameter data
# GHz S MA R 50
!Freq          magS11           angS11
2.0000000000000 0.69906280 -120.17410
2.1000000000000 0.68271143 -126.56723
2.2000000000000 0.65922851 -133.63498
"""


def _synth_touchstone(path: Path, n_ports: int, n_freq: int, *, z0: float = 50.0) -> rf.Network:
    """skrf 合成 n 端口 Touchstone 1.0 文件（确定性随机 S，不含物理含义）。"""
    freq = rf.Frequency(1, 3, n_freq, "GHz")
    rng_re = np.random.default_rng(1000 + n_ports)
    rng_im = np.random.default_rng(2000 + n_ports)
    s = (rng_re.standard_normal((n_freq, n_ports, n_ports))
         + 1j * rng_im.standard_normal((n_freq, n_ports, n_ports))) * 0.3
    net = rf.Network(frequency=freq, s=s, z0=z0)
    net.write_touchstone(str(path))
    return net


# ─── infer_touchstone_port_count：数据行结构反推端口数 ─────────────────────

class TestInferPortCount:
    @pytest.mark.parametrize("n_ports", [1, 2, 3, 4, 5])
    @pytest.mark.parametrize("n_freq", [1, 5, 29])
    def test_skrf_roundtrip(self, tmp_path, n_ports, n_freq):
        """skrf 写出的 1/2/3/4/5 端口文件（含单频点与战役 29 频点）推断正确。"""
        p = tmp_path / f"n{n_ports}.s{n_ports}p"
        _synth_touchstone(p, n_ports, n_freq)
        assert infer_touchstone_port_count(p) == n_ports

    def test_two_vs_four_port_disambiguation(self, tmp_path):
        """首行同为 9 值：2 端口（每行独立）与 4 端口（块 [9,8,8,8]）靠块行数消歧。"""
        p2 = tmp_path / "a.s2p"
        p4 = tmp_path / "b.s4p"
        _synth_touchstone(p2, 2, 7)
        _synth_touchstone(p4, 4, 7)
        assert infer_touchstone_port_count(p2) == 2
        assert infer_touchstone_port_count(p4) == 4

    def test_hfss_export_sample_is_one_port(self, tmp_path):
        """HFSS 2025.1 真机导出格式（MA、! 注释、# 选项行、!Freq 列头）→ 1 端口。"""
        assert infer_touchstone_port_count(_HFSS_S1P_SAMPLE) == 1
        p = tmp_path / "params.s2p"  # 扩展名故意写错：推断只看内容
        p.write_text(_HFSS_S1P_SAMPLE, encoding="utf-8")
        assert infer_touchstone_port_count(p) == 1

    def test_wrong_extension_does_not_matter(self, tmp_path):
        """扩展名 rank 与内容不符时推断以内容为准（原故障形态：1 端口写成 .s2p）。"""
        p = tmp_path / "params.s2p"
        _synth_touchstone(p.with_suffix(".s1p"), 1, 11)
        p.with_suffix(".s1p").replace(p)
        assert infer_touchstone_port_count(p) == 1

    def test_comments_only_returns_none(self):
        assert infer_touchstone_port_count("! c\n# GHz S MA R 50\n") is None

    def test_missing_file_returns_none(self, tmp_path):
        assert infer_touchstone_port_count(tmp_path / "nope.s2p") is None

    def test_unrecognized_structure_returns_none(self):
        """结构不匹配任何端口数（每行 5 值）→ None，不猜。"""
        assert infer_touchstone_port_count("# GHz S MA R 50\n1 0.1 0 0.2 0\n2 0.1 0 0.2 0\n") is None


# ─── touchstone_path_for_ports：扩展名按实际端口数纠正 ─────────────────────

class TestPathForPorts:
    def test_one_port_corrects_s2p(self):
        """原故障核心：1 端口也要修正（旧条件 n_ports >= 2 漏掉）。"""
        assert touchstone_path_for_ports(Path("r/params.s2p"), 1) == Path("r/params.s1p")

    def test_three_port_corrects_s2p(self):
        assert touchstone_path_for_ports(Path("r/params.s2p"), 3) == Path("r/params.s3p")

    def test_matching_suffix_unchanged(self):
        assert touchstone_path_for_ports(Path("r/params.s2p"), 2) == Path("r/params.s2p")
        assert touchstone_path_for_ports(Path("r/PARAMS.S1P"), 1) == Path("r/PARAMS.S1P")

    def test_unknown_ports_unchanged(self):
        assert touchstone_path_for_ports(Path("r/params.s2p"), None) == Path("r/params.s2p")
        assert touchstone_path_for_ports(Path("r/params.s2p"), 0) == Path("r/params.s2p")


# ─── contract_for_port_count：契约按实际端口数适配（z0 校验保留） ────────────

class TestContractForPortCount:
    def test_two_port_contract_adapts_to_one_port(self):
        tc = AdsExchangeContract.for_n_ports(2).touchstone
        out = contract_for_port_count(tc, 1)
        assert isinstance(out, TouchstoneContract)
        assert out.port_order == ["input"]
        assert out.renormalization_ohm == tc.renormalization_ohm
        assert out.frequency_unit == tc.frequency_unit

    def test_adapts_to_more_ports_keeps_z0(self):
        tc = TouchstoneContract(renormalization_ohm=75.0, port_order=["input"])
        out = contract_for_port_count(tc, 3)
        assert out.port_order == ["input", "output_1", "output_2"]
        assert out.renormalization_ohm == 75.0

    def test_matching_returns_same_object(self):
        tc = AdsExchangeContract.for_n_ports(2).touchstone
        assert contract_for_port_count(tc, 2) is tc

    def test_unknown_or_none_passthrough(self):
        tc = AdsExchangeContract.for_n_ports(2).touchstone
        assert contract_for_port_count(tc, None) is tc
        assert contract_for_port_count(None, 1) is None

    def test_adapted_contract_is_valid_for_ads_exchange(self):
        """重建的 port_order 满足 AdsExchangeContract 形式化规则（input 唯一、递增）。"""
        tc = contract_for_port_count(AdsExchangeContract.for_n_ports(2).touchstone, 4)
        AdsExchangeContract(touchstone=tc)  # validator 不抛


# ─── export_touchstone / get_sparams 链路（mock PyAEDT） ────────────────────

class _FakeSimProfile:
    def __init__(self, status: str):
        self.status = status


class _FakeProfiles(dict):
    pass


class _FakeSetup:
    is_solved = True

    def get_profile(self):
        return None


class _FakeHfss:
    """模拟 Hfss 会话：健康 profile + 可配置端口列表（或查询抛错）。

    R4-1 扩展：可选 boundaries（BoundaryObject 形状，含 props["Modes"]）
    供多模波端口 Σ模数计数钉；不传则保持旧形状（无 boundaries 属性）。
    """

    def __init__(self, ports, *, ports_raise: bool = False,
                 boundaries=None, boundaries_raise: bool = False):
        self._ports = list(ports)
        self._ports_raise = ports_raise
        self._boundaries = boundaries
        self._boundaries_raise = boundaries_raise
        self.osolution = object()
        self.working_directory = None
        self.project_path = None
        self.project_name = "proj"
        self.design_name = "d"

    @property
    def ports(self):
        if self._ports_raise:
            raise RuntimeError("gRPC blip")
        return self._ports

    @property
    def boundaries(self):
        if self._boundaries_raise:
            raise RuntimeError("gRPC blip")
        return list(self._boundaries or [])

    are_there_simulations_running = False

    def get_profile(self, name):
        return _FakeProfiles({"s1": _FakeSimProfile("Normal Completion")})

    def get_setup(self, name):
        return _FakeSetup()

    def get_setups(self):
        return ["Setup1"]

    def get_sweeps(self, name):
        return ["Sweep1"]


@pytest.fixture()
def adapter(monkeypatch):
    monkeypatch.delenv("RFAUTO_HFSS_SOLVE_TIMEOUT_S", raising=False)
    HfssSession.reset()
    a = HfssAdapter()
    yield a
    HfssSession.reset()


def _patch_direct_export(monkeypatch, n_ports: int, n_freq: int = 29, *, z0: float = 50.0):
    """把 ExportNetworkData 换成"按设计端口数写合成 Touchstone 到请求路径"。"""
    calls: list[Path] = []

    def _fake_export(hfss, setup_name, sweep_name, path):
        calls.append(Path(path))
        _synth_touchstone(Path(path), n_ports, n_freq, z0=z0)

    monkeypatch.setattr(HfssAdapter, "_direct_export_touchstone", staticmethod(_fake_export))
    return calls


class TestExportTouchstonePortGeneralization:
    def test_one_port_design_with_two_port_contract_regression(self, adapter, monkeypatch, tmp_path):
        """原故障：1 端口设计 + run_once 按插件契约请求 params.s2p + 2 端口契约
        → 现在返回 params.s1p、skrf 可读 1 端口、契约按实际端口数校验通过。"""
        adapter.session.hfss = _FakeHfss(["P1"])
        calls = _patch_direct_export(monkeypatch, n_ports=1, n_freq=29)
        contract = AdsExchangeContract.for_n_ports(2)
        (tmp_path / "results").mkdir()  # run_once 在调用前 mkdir(parents=True)

        out = adapter.export_touchstone(tmp_path / "results" / "params.s2p", contract)

        assert out == tmp_path / "results" / "params.s1p"
        assert out.exists()
        assert calls == [out], "HFSS 应直接导出到修正后的 .s1p 路径"
        net = rf.Network(str(out))
        assert net.nports == 1
        assert net.frequency.npoints == 29

    def test_two_port_design_unchanged(self, adapter, monkeypatch, tmp_path):
        """2 端口设计 + .s2p 请求 + 2 端口契约：既有行为不变。"""
        adapter.session.hfss = _FakeHfss(["P1", "P2"])
        _patch_direct_export(monkeypatch, n_ports=2)
        out = adapter.export_touchstone(tmp_path / "params.s2p", AdsExchangeContract.for_n_ports(2))
        assert out == tmp_path / "params.s2p"
        assert rf.Network(str(out)).nports == 2

    def test_three_port_design_corrects_suffix(self, adapter, monkeypatch, tmp_path):
        """3 端口设计 + .s2p 请求：修正为 .s3p（既有多端口行为保留）。"""
        adapter.session.hfss = _FakeHfss(["P1", "P2", "P3"])
        _patch_direct_export(monkeypatch, n_ports=3)
        out = adapter.export_touchstone(tmp_path / "params.s2p", AdsExchangeContract.for_n_ports(3))
        assert out == tmp_path / "params.s3p"
        assert rf.Network(str(out)).nports == 3

    def test_ports_query_fails_falls_back_to_file_inference(self, adapter, monkeypatch, tmp_path):
        """hfss.ports 查询抛错（n_ports 未知）：先按请求路径导出，再由文件数据
        行结构推断 1 端口并重命名为 .s1p（无需重导出）。"""
        adapter.session.hfss = _FakeHfss(["P1"], ports_raise=True)
        calls = _patch_direct_export(monkeypatch, n_ports=1, n_freq=11)
        out = adapter.export_touchstone(tmp_path / "params.s2p", AdsExchangeContract.for_n_ports(2))
        assert calls == [tmp_path / "params.s2p"]
        assert out == tmp_path / "params.s1p"
        assert out.exists()
        assert not (tmp_path / "params.s2p").exists()
        assert rf.Network(str(out)).nports == 1

    def test_contract_impedance_still_enforced(self, adapter, monkeypatch, tmp_path):
        """端口数适配不绕过契约：参考阻抗不符仍抛 ContractViolationError（不凑绿）。"""
        adapter.session.hfss = _FakeHfss(["P1"])
        _patch_direct_export(monkeypatch, n_ports=1, z0=75.0)
        with pytest.raises(ContractViolationError, match="参考阻抗"):
            adapter.export_touchstone(tmp_path / "params.s2p", AdsExchangeContract.for_n_ports(2))

    def test_no_contract_one_port(self, adapter, monkeypatch, tmp_path):
        """无契约（get_sparams 路径）：1 端口 .s2p 请求同样修正为 .s1p。"""
        adapter.session.hfss = _FakeHfss(["P1"])
        _patch_direct_export(monkeypatch, n_ports=1)
        out = adapter.export_touchstone(tmp_path / "tmp.s2p")
        assert out.suffix == ".s1p"


class TestGetSparamsOnePort:
    def test_get_sparams_one_port_network(self, adapter, monkeypatch):
        """get_sparams 的 .s2p 临时占位在 1 端口设计下得到 1 端口网络，临时文件清理。"""
        adapter.session.hfss = _FakeHfss(["P1"])
        calls = _patch_direct_export(monkeypatch, n_ports=1, n_freq=29)
        net = adapter.get_sparams()
        assert net.nports == 1
        assert net.frequency.npoints == 29
        assert len(calls) == 1 and calls[0].suffix == ".s1p"
        assert not calls[0].exists(), "导出的临时 .s1p 须清理"
        assert not calls[0].with_suffix(".s2p").exists(), "占位 .s2p 须清理"


# ─── R4-1 多模波端口 Σ模数计数（审查批 2026-10-04，#309 先例升主路径） ──────

class _FakeBoundary:
    """BoundaryObject 形状最小仿真：name + props（含 Modes）。"""

    def __init__(self, name: str, modes=None):
        self.name = name
        self.props = {} if modes is None else {"Modes": modes}


class TestDesignPortCountSumModes:
    def test_two_ports_two_modes_each_sums_to_four(self):
        """2 波端口×2 模（#307/#309 hairpin 锚形态）→ Σ模数=4，非边界数 2。"""
        hfss = _FakeHfss(
            ["P1sheetP", "P2sheetP"],
            boundaries=[_FakeBoundary("P1sheetP", 2), _FakeBoundary("P2sheetP", 2)])
        assert HfssAdapter._design_port_count(hfss) == 4

    def test_lumped_port_without_modes_counts_one(self):
        """集总端口无 Modes 键按 1 模；混排按逐端口累加。"""
        hfss = _FakeHfss(
            ["W1", "L1"],
            boundaries=[_FakeBoundary("W1", 3), _FakeBoundary("L1")])
        assert HfssAdapter._design_port_count(hfss) == 4

    def test_boundaries_query_fails_falls_back_to_boundary_count(self):
        """boundaries 查询抛错：退回端口边界数口径（旧行为，单模设计逐位一致）。"""
        hfss = _FakeHfss(["P1", "P2"], boundaries_raise=True)
        assert HfssAdapter._design_port_count(hfss) == 2

    def test_no_boundaries_attribute_old_fake_shape(self):
        """旧 _FakeHfss 形状（无 boundaries 属性）→ 边界数口径，不炸。"""
        assert HfssAdapter._design_port_count(_FakeHfss(["P1", "P2"])) == 2

    def test_ports_query_fails_returns_none(self):
        assert HfssAdapter._design_port_count(_FakeHfss(["P1"], ports_raise=True)) is None


class TestMultimodeExportS4p:
    def test_two_port_two_mode_design_exports_s4p(self, adapter, monkeypatch, tmp_path):
        """回归钉（R4-1/#248 复发面）：2 端口×2 模设计请求 .s2p → 按 Σ模数=4
        修正为 .s4p，skrf 按扩展名读出 4 端口网络（旧径把 4×4 模态数据改名
        .s2p → skrf reshape IndexError）。"""
        hfss = _FakeHfss(
            ["P1sheetP", "P2sheetP"],
            boundaries=[_FakeBoundary("P1sheetP", 2), _FakeBoundary("P2sheetP", 2)])
        adapter.session.hfss = hfss
        calls = _patch_direct_export(monkeypatch, n_ports=4)
        out = adapter.export_touchstone(tmp_path / "params.s2p")
        assert out == tmp_path / "params.s4p"
        assert calls == [out], "应直接导出到 Σ模数修正后的 .s4p 路径"
        assert rf.Network(str(out)).nports == 4


class TestPatchPluginContractOnePort:
    """0da followUp② 收口回归钉：patch 插件契约 1 端口与三通道一致。

    wp34 GT 战役根因的另一半：插件契约 n_ports=2 与单馈 patch 设计实际
    1 端口不一致（导出侧 contract_for_port_count 每点重建+告警兜底）。
    契约改 1 后三通道（插件/TEMPLATE_META/docs meta.yaml）逐位一致，
    HFSS 导出路径不再触发重建告警。
    """

    @staticmethod
    def _repo() -> Path:
        return Path(__file__).resolve().parents[2]

    def test_plugin_n_ports_matches_single_feed(self):
        from rfauto.models.registry import get
        assert get("patch_antenna").n_ports == 1

    def test_three_channel_port_count_consistency(self):
        import yaml

        from rfauto.adapters.openems_templates import TEMPLATE_META
        from rfauto.models.registry import get
        plugin = int(get("patch_antenna").n_ports)
        oe_meta = int(TEMPLATE_META["patch"]["n_ports"])
        docs = yaml.safe_load(
            (self._repo() / "docs" / "templates" / "patch" / "meta.yaml")
            .read_text(encoding="utf-8"))
        assert plugin == oe_meta == int(docs["n_ports"]) == 1

    def test_run_once_patch_contract_matches_fake_network(self, tmp_path, monkeypatch):
        """run_once(fake) 全链：契约 1 端口 × fake 网络 1 端口一致——
        FakeAdapter.export_touchstone 的契约校验不再可能触发
        ContractViolationError（旧 2 端口形状残留已删）。"""
        monkeypatch.chdir(tmp_path)
        recipe = self._repo() / "recipes" / "patch_antenna_v1.yaml"
        from rfauto.service.api import run_once
        result = run_once(recipe)
        assert result["ok"], result.get("errors")
        s1p = list((Path(result["run_dir"]) / "results").glob("params.s1p"))
        assert s1p, "契约 1 端口 → 请求扩展名应为 .s1p"
