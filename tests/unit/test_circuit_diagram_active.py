"""M3 增补两族上图钉（aurora_p A2 席，2026-11-01）。

语境钉死：runs/aurora_o/design_specs/T-O4_ADS_UX_SPEC.md §八 遗留 1
（M3 增补位）+ 设计定稿 runs/aurora_p/a2/M3_DESIGN.md。T-O4 既有 43 钉
（test_circuit_sim_service.py）零改动——本文件只钉新族面：

1. 白名单自证（#231 家法参数版）：ACTIVE_PARAM_KEYS == 渲染器签名关键参集
   （集合差恰=显式例外键：active_chain 的 match_snp=数据文件位参；loadpull
   的 z_load_re/z_load_im 成对 ↔ z_load complex）；== core 布局表键集；
2. 出图读回往返：p_/unit_/src_ 三件组在档、承载卡归属、byte-identical、
   mxGraph 官方九条（T-O1 家法）；
3. 读回-渲染等价（spec 钉 2 复刻）：J2 改图值 → 网表文本逐字变化；不改值
   时网表 == 渲染器直调逐字节（零格式化逻辑证明钉）；
4. 三态优先级 + sweep 兜底（频扫=两 Touchstone 交集 source=touchstone）；
5. 负例：未知族/家族不匹配/白名单外 p_ 键 warn 忽略/图缺必带键 fail loud/
   空串 error/match_snp 文件缺失/非 2 端口出图即拒；
6. 指标单源 + 对拍卡形态（dB 域）+ provenance 图版 + 反标注幂等
   byte-identical（spec 钉 5/6/7 复刻）；
7. ADS 段失败降级 error 头卡不虚构指标（#105/#122）；
8. 确定性（同图同 runner 两跑逐字节）+ 信封写面（原图只读/ASCII 无 BOM）。

离线纪律：全链 ads_runner 注入（#139——配置存在也不许单测真打 ADS）；
真机冒烟由 runs/aurora_p/a2/ 冒烟脚本承载（solo，#246）。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
import skrf

from rfauto.core.active_chain import DEFAULT_Z0
from rfauto.core.circuit_diagram import (
    _FAMILY_KEYS,
    ANNOT_LAYER_ID,
    family_param_keys,
    parse_effective_params,
    read_circuit_params,
)
from rfauto.linkage import ads_active_chain as aac
from rfauto.service.circuit_sim_service import (
    _METRIC_UNITS,
    ACTIVE_METRIC_NAMES,
    ACTIVE_PARAM_KEYS,
    PARAM_KEYS,
    _family_defaults,
    annotate_circuit_diagram,
    circuit_sim_run,
    generate_circuit_diagram,
)
from rfauto.service.report_render import fmt_value

F0_HZ = 2.0e9
MATCH_LOSS_DB, DEV_LOSS_DB = 1.0, 3.0


# --------------------------------------------------------------------------- #
# 离线替身（匹配衰减器 2 端口——S11=S22=0 恒匹配，指标闭式可精确断言）
# --------------------------------------------------------------------------- #

def _attenuator_snp(path: Path, loss_db: float, n_points: int = 41,
                    band=(1.8e9, 2.2e9)) -> Path:
    freqs = np.linspace(band[0], band[1], n_points)
    a = 10 ** (-loss_db / 20)
    s = np.zeros((freqs.size, 2, 2), dtype=complex)
    s[:, 0, 1] = a
    s[:, 1, 0] = a
    net = skrf.Network(frequency=skrf.Frequency.from_f(freqs, unit="Hz"), s=s, z0=50)
    net.write_touchstone(str(path), form="ri")
    return path


def _payload_from_network(net: skrf.Network) -> dict:
    n = net.nports
    s = {}
    for i in range(n):
        for j in range(n):
            s[f"{i + 1}_{j + 1}"] = [[float(v.real), float(v.imag)] for v in net.s[:, i, j]]
    return {
        "ok": True, "key": "SP1.SP", "frequency_hz": [float(f) for f in net.f], "s": s,
        "port_names": [f"P{k + 1}" for k in range(n)], "port_z": [[50.0, 0.0]] * n,
    }


def _chain_runner(match: Path, device: Path, *, perturb_db: float = 0.0):
    _, _, cascade = aac.chain_manual_reference(match, device)
    payload = _payload_from_network(cascade)
    if perturb_db:
        for row in payload["s"]["2_1"]:
            mag = np.hypot(row[0], row[1]) * 10 ** (perturb_db / 20)
            ang = np.arctan2(row[1], row[0])
            row[0], row[1] = float(mag * np.cos(ang)), float(mag * np.sin(ang))

    def run(_netlist: Path) -> dict:
        return payload
    return run


def _hb_payload(device_snp: Path, f0_hz: float, power_dbm: float, z_load: complex) -> dict:
    """离线 HB 替身（test_ads_active_chain 波代数家法同构——独立于内核
    transducer_gain_db 的第三方口径）。"""
    net = skrf.Network(str(device_snp))
    idx = int(np.argmin(np.abs(net.f - f0_hz)))
    s = net.s[idx]
    z0 = 50.0
    gl = (z_load - z0) / (z_load + z0)
    a1 = np.sqrt(10 ** (power_dbm / 10) * 1e-3)
    b2 = s[1, 0] * a1 / (1 - s[1, 1] * gl)
    v_peak = np.sqrt(2) * np.sqrt(z0) * b2 * (1 + gl)
    p_w = abs(b2) ** 2 * (1 - abs(gl) ** 2)
    harmonics = [{"freq_hz": 0.0, "mix": 0, "nodes": {"N_IN": [0.0, 0.0], "N_OUT": [0.0, 0.0]}},
                 {"freq_hz": f0_hz, "mix": 1,
                  "nodes": {"N_IN": [1.0, 0.0], "N_OUT": [float(v_peak.real), float(v_peak.imag)]}}]
    harmonics += [{"freq_hz": f0_hz * k, "mix": k,
                   "nodes": {"N_IN": [0.0, 0.0], "N_OUT": [0.0, 0.0]}}
                  for k in range(2, 6)]
    p_dbm = 10 * np.log10(p_w * 1e3)
    meas = {"Pout_W": float(p_w), "Pout_dBm": float(p_dbm),
            "Gain_dB": float(p_dbm - power_dbm)}
    return {"ok": True, "key": "HB1.HB", "harmonics": harmonics,
            "measurements": meas,
            "keys": ["HB1.HB"] + [f"aele_{i}.HB1.HB" for i in range(3)]}


def _hb_runner(device_snp: Path, power_dbm: float = 20.0, z_load: complex = 15 + 8.5j):
    def run(_netlist: Path) -> dict:
        return _hb_payload(device_snp, F0_HZ, power_dbm, z_load)
    return run


def _loadpull_params(**over) -> dict:
    params = {"f0_hz": 2.0e9, "power_dbm": 20.0, "z_load_re": 15.0, "z_load_im": 8.5}
    params.update(over)
    return params


def _edit_diagram_param(diagram: Path, attr: str, new_text: str) -> Path:
    """J2 模拟：draw.io Edit Data 改 p_* 属性 → 另存新图（原图不动）。"""
    tree = ET.parse(diagram)
    hit = False
    for uo in tree.getroot().iter("UserObject"):
        if uo.get(attr) is not None:
            uo.set(attr, new_text)
            hit = True
    assert hit, f"图中无属性 {attr}（出图面缺键？）"
    out = diagram.with_name(diagram.stem + f"_edit_{attr}.drawio")
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out


def _drop_diagram_param(diagram: Path, attr: str) -> Path:
    tree = ET.parse(diagram)
    hit = False
    for uo in tree.getroot().iter("UserObject"):
        if uo.get(attr) is not None:
            del uo.attrib[attr]
            hit = True
    assert hit, f"图中无属性 {attr}"
    out = diagram.with_name(diagram.stem + f"_drop_{attr}.drawio")
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out


def _cell_id_set(xml_text: str) -> set[str]:
    root = ET.fromstring(xml_text)
    return {el.get("id") for el in root.iter() if el.get("id")}


def _attrs_by_id(xml_text: str) -> dict[str, dict[str, str]]:
    root = ET.fromstring(xml_text)
    return {el.get("id"): dict(el.attrib)
            for el in root.iter() if el.get("id") is not None}


@pytest.fixture()
def chain_files(tmp_path: Path) -> dict[str, Path]:
    return {
        "match": _attenuator_snp(tmp_path / "match.s2p", MATCH_LOSS_DB),
        "device": _attenuator_snp(tmp_path / "device.s2p", DEV_LOSS_DB),
    }


@pytest.fixture()
def chain_gen(chain_files: dict[str, Path], tmp_path: Path) -> Path:
    env = generate_circuit_diagram(
        "active_chain_sparam", chain_files["device"], tmp_path / "chain.drawio",
        params={"match_snp": str(chain_files["match"])})
    assert env["ok"], env.get("errors")
    return tmp_path / "chain.drawio"


@pytest.fixture()
def loadpull_gen(chain_files: dict[str, Path], tmp_path: Path) -> Path:
    env = generate_circuit_diagram(
        "loadpull_hb", chain_files["device"], tmp_path / "loadpull.drawio",
        params=_loadpull_params())
    assert env["ok"], env.get("errors")
    return tmp_path / "loadpull.drawio"


# --------------------------------------------------------------------------- #
# 钉 1：白名单自证（#231 家法参数版——渲染器签名演化忘同步即红）
# --------------------------------------------------------------------------- #

class TestActiveWhitelistSelfCert:
    @staticmethod
    def _signature_kw(renderer) -> set[str]:
        sig = inspect.signature(renderer)
        # 排除位：template_path=内核内部路由（同 MVP 家法）；match_snp/
        # device_snp/output_path=数据文件与产物路径位参（数据面，非可调电参数）
        data_args = {"template_path", "match_snp", "device_snp", "output_path"}
        return {name for name, p in sig.parameters.items()
                if p.kind in (p.KEYWORD_ONLY, p.POSITIONAL_OR_KEYWORD)
                and name not in data_args}

    def test_chain_param_keys_match_renderer_signature(self):
        kw = self._signature_kw(aac.render_chain_netlist)
        keys = set(ACTIVE_PARAM_KEYS["active_chain_sparam"])
        assert kw - keys == set(), f"渲染器新参 {sorted(kw - keys)} 未上图（白名单忘同步）"
        # match_snp=数据文件位参上图（device 走 run --snp——同 MVP snp_path
        # 排除语义的显式例外，集合差恰此一键）
        assert keys - kw == {"match_snp"}, (
            f"白名单外出键 {sorted(keys - kw)}——只允许 match_snp 数据文件例外")

    def test_loadpull_param_keys_match_renderer_signature(self):
        kw = self._signature_kw(aac.render_loadpull_netlist)
        keys = set(ACTIVE_PARAM_KEYS["loadpull_hb"])
        assert kw - keys == {"z_load"}, (
            f"渲染器新参 {sorted(kw - keys)} 未上图——z_load 例外应恰一键")
        assert keys - kw == {"z_load_re", "z_load_im"}, (
            "z_load: complex ↔ z_load_re/z_load_im 成对是唯一例外（service 组装）")
        # 缺省值同源钉：harmonic_order/z0 图缺省 == 渲染器签名缺省（漂移即红）
        sig = inspect.signature(aac.render_loadpull_netlist)
        defaults = _family_defaults("loadpull_hb")
        assert sig.parameters["harmonic_order"].default == defaults["harmonic_order"]
        assert sig.parameters["z0"].default == pytest.approx(defaults["z0"])

    def test_core_layout_tables_match_active_registry(self):
        for family in ACTIVE_PARAM_KEYS:
            assert set(family_param_keys(family)) == set(ACTIVE_PARAM_KEYS[family]), family

    def test_registry_union_covers_core_families_exactly(self):
        assert set(_FAMILY_KEYS) == set(PARAM_KEYS) | set(ACTIVE_PARAM_KEYS), (
            "core 布局表族集 == MVP ∪ ACTIVE 两注册表并集（双表面一致）")

    def test_metric_names_covered_by_unit_table(self):
        for family, names in ACTIVE_METRIC_NAMES.items():
            for name in names:
                assert name in _METRIC_UNITS, f"{family} 指标 {name} 缺单位表项"

    def test_loadpull_required_keys_have_no_default(self):
        defaults = _family_defaults("loadpull_hb")
        for key in ("f0_hz", "power_dbm", "z_load_re", "z_load_im"):
            assert defaults[key] is None, f"{key} 必给键不得有臆造缺省（铁律 7）"
        assert defaults["harmonic_order"] == 5
        assert defaults["z0"] == pytest.approx(DEFAULT_Z0)


# --------------------------------------------------------------------------- #
# 钉 2：出图读回往返（三件组/承载卡归属/byte-identical/官方九条）
# --------------------------------------------------------------------------- #

class TestActiveDiagramGeneration:
    def test_chain_roundtrip_and_card_ownership(self, chain_files, chain_gen):
        info = read_circuit_params(chain_gen.read_text(encoding="utf-8"))
        assert info["family"] == "active_chain_sparam"
        assert set(info["raw"]) == set(ACTIVE_PARAM_KEYS["active_chain_sparam"])
        assert info["cells"]["match_snp"] == "uobj_mn"
        assert info["cells"]["npoints"] == "uobj_setup"
        assert info["units"]["z0"] == "Ohm" and info["units"]["match_snp"] == "path"
        assert info["units"]["npoints"] == "1" and info["units"]["frequency_unit"] == "GHz"
        assert all(v == "input" for v in info["srcs"].values())
        assert parse_effective_params(info["raw"])["npoints"] == 41
        xml_text = chain_gen.read_text(encoding="utf-8")
        assert "%p_match_snp%" in xml_text
        root = ET.fromstring(xml_text)
        ids = [el.get("id") for el in root.iter() if el.get("id")]
        assert len(ids) == len(set(ids)), "id 必须唯一"
        assert {"0", "1"} <= {c.get("id") for c in root.iter("mxCell")}
        for uo in root.iter("UserObject"):
            assert uo.get("placeholders") == "1"
            assert uo.find("mxCell").find("mxGeometry") is not None
        assert "base64" not in xml_text

    def test_loadpull_roundtrip_and_card_ownership(self, loadpull_gen):
        info = read_circuit_params(loadpull_gen.read_text(encoding="utf-8"))
        assert info["family"] == "loadpull_hb"
        assert set(info["raw"]) == set(ACTIVE_PARAM_KEYS["loadpull_hb"])
        for key in ("f0_hz", "power_dbm", "harmonic_order", "z0"):
            assert info["cells"][key] == "uobj_hb"
        assert info["cells"]["z_load_re"] == "uobj_load"
        assert info["cells"]["z_load_im"] == "uobj_load"
        assert info["units"]["power_dbm"] == "dBm"
        assert info["units"]["z_load_re"] == "Ohm"
        assert "%p_z_load_re%+j*(%p_z_load_im%)" in loadpull_gen.read_text(encoding="utf-8"), (
            "负载卡复数形态（#293 负虚部括号语义）上图可见")

    def test_generation_deterministic_bytes(self, chain_files, tmp_path):
        kw = dict(params={"match_snp": str(chain_files["match"])})
        x1 = generate_circuit_diagram(
            "active_chain_sparam", chain_files["device"], tmp_path / "a.drawio", **kw)
        x2 = generate_circuit_diagram(
            "active_chain_sparam", chain_files["device"], tmp_path / "b.drawio", **kw)
        assert x1["ok"] and x2["ok"]
        assert (tmp_path / "a.drawio").read_bytes() == (tmp_path / "b.drawio").read_bytes()

    def test_chain_npoints_default_is_min_of_both_files(self, chain_files, tmp_path):
        dev21 = _attenuator_snp(tmp_path / "dev21.s2p", DEV_LOSS_DB, n_points=21,
                                band=(1.9e9, 2.5e9))
        env = generate_circuit_diagram(
            "active_chain_sparam", dev21, tmp_path / "c.drawio",
            params={"match_snp": str(chain_files["match"])})
        assert env["ok"]
        assert env["values"]["npoints"] == {"value": 21, "source": "default"}

    def test_generation_negatives(self, chain_files, tmp_path):
        dev = chain_files["device"]
        r = generate_circuit_diagram("mystery", dev, tmp_path / "a.drawio")
        assert r["ok"] is False and any("未知模板族" in e for e in r["errors"])
        r = generate_circuit_diagram(
            "active_chain_sparam", dev, tmp_path / "b.drawio")  # 缺 match_snp
        assert r["ok"] is False and any("match_snp" in e for e in r["errors"])
        r = generate_circuit_diagram(
            "active_chain_sparam", dev, tmp_path / "c.drawio",
            params={"match_snp": str(tmp_path / "no.s2p")})
        assert r["ok"] is False and any("不存在" in e for e in r["errors"])
        r = generate_circuit_diagram(
            "loadpull_hb", dev, tmp_path / "d.drawio")  # 缺全部必给键
        assert r["ok"] is False and any("缺必给参数" in e for e in r["errors"])
        r = generate_circuit_diagram(
            "loadpull_hb", dev, tmp_path / "e.drawio", params={"z0": True})
        assert r["ok"] is False and any("bool" in e for e in r["errors"])

    def test_non_2port_rejected_at_generation(self, chain_files, tmp_path):
        net = skrf.Network(frequency=skrf.Frequency(1.8, 2.2, 41, "GHz"),
                           s=np.zeros((41, 4, 4), dtype=complex), z0=50)
        p4 = tmp_path / "four.s4p"
        net.write_touchstone(str(p4), form="ri")
        r = generate_circuit_diagram(
            "active_chain_sparam", p4, tmp_path / "f.drawio",
            params={"match_snp": str(chain_files["match"])})
        assert r["ok"] is False and any("2 端口" in e for e in r["errors"])
        r = generate_circuit_diagram(
            "loadpull_hb", p4, tmp_path / "g.drawio", params=_loadpull_params())
        assert r["ok"] is False and any("2 端口" in e for e in r["errors"])


# --------------------------------------------------------------------------- #
# 钉 3：读回-渲染等价（J2 改图值 → 网表逐字；不改值 == 直调逐字节）
# --------------------------------------------------------------------------- #

class TestActiveReadRenderEquivalence:
    def test_chain_edited_z0_reaches_netlist_verbatim(
            self, chain_files, chain_gen, tmp_path):
        edited = _edit_diagram_param(chain_gen, "p_z0", "65")
        result = circuit_sim_run(
            edited, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_chain_runner(chain_files["match"], chain_files["device"]))
        assert result["ok"], result.get("errors")
        text = Path(result["netlist_path"]).read_text(encoding="ascii")
        assert "Z=65 Ohm" in text, "J2 改 z0 50→65 必须逐字进网表（Port Z=）"
        assert "Z=50 Ohm" not in text
        assert result["effective"]["z0"] == {"value": 65.0, "source": "diagram"}
        assert f'File="{chain_files["match"].resolve()}"' in text, (
            "MN 卡 match_snp 路径逐字进 SnP File=")

    def test_chain_unedited_renders_byte_identical_to_direct_call(
            self, chain_files, chain_gen, tmp_path):
        result = circuit_sim_run(
            chain_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_chain_runner(chain_files["match"], chain_files["device"]))
        assert result["ok"]
        via_diagram = Path(result["netlist_path"]).read_bytes()
        direct = aac.render_chain_netlist(
            chain_files["match"], chain_files["device"], tmp_path / "direct.txt",
            frequency_unit="GHz", npoints=41, z0=50.0)
        assert via_diagram == Path(direct).read_bytes(), (
            "图→合参→渲染 == 渲染器直调（本席零格式化逻辑证明钉）")

    def test_loadpull_edited_power_reaches_netlist_verbatim(
            self, chain_files, loadpull_gen, tmp_path):
        edited = _edit_diagram_param(loadpull_gen, "p_power_dbm", "25")
        result = circuit_sim_run(
            edited, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_hb_runner(chain_files["device"], power_dbm=25.0))
        assert result["ok"], result.get("errors")
        text = Path(result["netlist_path"]).read_text(encoding="ascii")
        assert "dbmtow(25)" in text, "J2 改功率 20→25 必须逐字进 P[1]=dbmtow()"
        assert "dbmtow(20)" not in text
        assert "Z=15+j*(8.5)" in text, "负载复数形态逐字（#293 括号语义位）"
        assert result["effective"]["power_dbm"] == {"value": 25.0, "source": "diagram"}

    def test_loadpull_unedited_renders_byte_identical_to_direct_call(
            self, chain_files, loadpull_gen, tmp_path):
        result = circuit_sim_run(
            loadpull_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_hb_runner(chain_files["device"]))
        assert result["ok"]
        via_diagram = Path(result["netlist_path"]).read_bytes()
        direct = aac.render_loadpull_netlist(
            chain_files["device"], tmp_path / "direct.txt",
            f0_hz=2.0e9, power_dbm=20.0, z_load=complex(15.0, 8.5))
        assert via_diagram == Path(direct).read_bytes()


# --------------------------------------------------------------------------- #
# 钉 4：三态优先级 + sweep 兜底（频扫=两 Touchstone 交集）
# --------------------------------------------------------------------------- #

class TestActiveThreeState:
    def test_json_beats_diagram(self, chain_files, loadpull_gen, tmp_path):
        result = circuit_sim_run(
            loadpull_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            params_override={"power_dbm": 18},
            runner=_hb_runner(chain_files["device"], power_dbm=18.0))
        assert result["ok"]
        assert result["effective"]["power_dbm"] == {"value": 18.0, "source": "input-json"}
        assert "dbmtow(18)" in Path(result["netlist_path"]).read_text(encoding="ascii")

    def test_chain_override_match_and_npoints(self, chain_files, chain_gen, tmp_path):
        other = _attenuator_snp(tmp_path / "other.s2p", 6.0)
        result = circuit_sim_run(
            chain_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            params_override={"match_snp": str(other), "npoints": 11},
            runner=_chain_runner(other, chain_files["device"]))
        assert result["ok"]
        assert result["effective"]["match_snp"] == {
            "value": str(other), "source": "input-json"}
        assert result["effective"]["npoints"] == {"value": 11, "source": "input-json"}
        text = Path(result["netlist_path"]).read_text(encoding="ascii")
        assert f'File="{other.resolve()}"' in text
        assert "Lin=11" in text

    def test_chain_sweep_is_touchstone_intersection(self, chain_files, tmp_path):
        dev21 = _attenuator_snp(tmp_path / "dev21.s2p", DEV_LOSS_DB, n_points=21,
                                band=(1.9e9, 2.5e9))
        env = generate_circuit_diagram(
            "active_chain_sparam", dev21, tmp_path / "c.drawio",
            params={"match_snp": str(chain_files["match"])})
        assert env["ok"]
        result = circuit_sim_run(
            tmp_path / "c.drawio", snp_path=dev21, out_dir=tmp_path / "run",
            runner=_chain_runner(chain_files["match"], dev21))
        assert result["ok"]
        assert result["sweep"]["source"] == "touchstone", "频扫=两数据文件交集"
        assert result["sweep"]["fstart"] == pytest.approx(1.9)
        assert result["sweep"]["fstop"] == pytest.approx(2.2)
        assert result["sweep"]["npoints"] == 21
        assert result["effective"]["npoints"] == {"value": 21, "source": "diagram"}

    def test_loadpull_has_no_sweep(self, chain_files, loadpull_gen, tmp_path):
        result = circuit_sim_run(
            loadpull_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_hb_runner(chain_files["device"]))
        assert result["ok"]
        assert result["sweep"] is None, "HB 单点无频扫（如实 None）"

    def test_missing_required_key_fails_loud(self, chain_files, loadpull_gen, tmp_path):
        dropped = _drop_diagram_param(loadpull_gen, "p_f0_hz")
        result = circuit_sim_run(
            dropped, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_hb_runner(chain_files["device"]))
        assert result["ok"] is False
        assert any("图缺必带参数键 'f0_hz'" in e and "uobj_hb" in e
                   for e in result["errors"])

    def test_empty_non_sweep_value_fails_loud(self, chain_files, loadpull_gen, tmp_path):
        emptied = _edit_diagram_param(loadpull_gen, "p_power_dbm", "")
        result = circuit_sim_run(
            emptied, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_hb_runner(chain_files["device"]))
        assert result["ok"] is False
        assert any("值为空" in e for e in result["errors"])

    def test_match_snp_missing_file_fails_envelope(self, chain_files, chain_gen, tmp_path):
        edited = _edit_diagram_param(chain_gen, "p_match_snp", str(tmp_path / "gone.s2p"))
        result = circuit_sim_run(
            edited, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_chain_runner(chain_files["match"], chain_files["device"]))
        assert result["ok"] is False
        assert result["ads"]["status"] == "error"
        assert "不存在" in result["ads"]["error"], "match_snp 缺文件如实降级 error"

    def test_whitelist_external_key_warned_and_ignored(
            self, chain_files, chain_gen, tmp_path):
        tree = ET.parse(chain_gen)
        for uo in tree.getroot().iter("UserObject"):
            if uo.get("kind") == "SNP":
                uo.set("p_my_note", "自用注记")
        noted = chain_gen.with_name("noted.drawio")
        tree.write(noted, encoding="utf-8", xml_declaration=True)
        result = circuit_sim_run(
            noted, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_chain_runner(chain_files["match"], chain_files["device"]))
        assert result["ok"], "白名单外键 warnings 忽略不报错（spec §2.3）"
        assert any("my_note" in w for w in result["warnings"])

    def test_family_mismatch_explicit_arg(self, chain_files, chain_gen, tmp_path):
        result = circuit_sim_run(
            chain_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            family="loadpull_hb",
            runner=_chain_runner(chain_files["match"], chain_files["device"]))
        assert result["ok"] is False
        assert any("不一致" in e for e in result["errors"])


# --------------------------------------------------------------------------- #
# 钉 6+7：指标单源（闭式精确）+ 对拍卡形态（dB 域）+ provenance
# --------------------------------------------------------------------------- #

class TestActiveMetricsAndCompare:
    def test_chain_metrics_closed_form_exact(self, chain_files, chain_gen, tmp_path):
        """恒匹配衰减器链：gain=-(1+3) dB 精确、VSWR=1 精确（闭式对照 #118）。"""
        result = circuit_sim_run(
            chain_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_chain_runner(chain_files["match"], chain_files["device"]))
        assert result["ok"]
        assert result["metrics"]["system_gain_db"] == pytest.approx(
            -(MATCH_LOSS_DB + DEV_LOSS_DB), abs=1e-9)
        assert result["metrics"]["input_vswr"] == pytest.approx(1.0, abs=1e-9)
        assert result["compare"]["gate_ok"] is True
        assert result["compare"]["max_abs_db"] < 1e-6

    def test_chain_gate_fail_renders_red_card(self, chain_files, chain_gen, tmp_path):
        result = circuit_sim_run(
            chain_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_chain_runner(chain_files["match"], chain_files["device"],
                                 perturb_db=0.5))
        assert result["ok"] is False, "对拍炸=ok False（不凑绿）"
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        assert "gate_ok=false" in annotated
        assert "fillColor=#f8cecc" in annotated

    def test_loadpull_metrics_single_source_closed_form(
            self, chain_files, loadpull_gen, tmp_path):
        z_load = 15 + 8.5j
        payload = _hb_payload(chain_files["device"], F0_HZ, 20.0, z_load)
        result = circuit_sim_run(
            loadpull_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=lambda _p: payload)
        assert result["ok"]
        ref = aac.loadpull_point_closed_form(
            chain_files["device"], f0_hz=F0_HZ, power_dbm=20.0, z_load=z_load)
        assert result["metrics"]["pout_dbm"] == pytest.approx(ref["pout_dbm"], abs=1e-9)
        assert result["metrics"]["gain_db"] == pytest.approx(ref["gt_db"], abs=1e-9)
        # 指标单源：同 payload 重调 hb_payload_to_point 同值（spec 钉 7）
        point = aac.hb_payload_to_point(payload, z_load=z_load, power_dbm=20.0)
        assert result["metrics"] == {
            name: point[name] for name in ACTIVE_METRIC_NAMES["loadpull_hb"]}
        assert result["compare"]["gate_ok"] is True

    def test_compare_cards_carry_provenance_and_tol(
            self, chain_files, chain_gen, loadpull_gen, tmp_path):
        r_chain = circuit_sim_run(
            chain_gen, snp_path=chain_files["device"], out_dir=tmp_path / "rc",
            runner=_chain_runner(chain_files["match"], chain_files["device"]),
            gate=1e-6)
        r_lp = circuit_sim_run(
            loadpull_gen, snp_path=chain_files["device"], out_dir=tmp_path / "rl",
            runner=_hb_runner(chain_files["device"]), gate=0.5)
        assert r_chain["ok"] and r_lp["ok"]
        assert r_chain["compare"]["tol_db"] == pytest.approx(1e-6), "gate→tol_db 透传"
        assert r_lp["compare"]["tol_db"] == pytest.approx(0.5)
        for result, source in (
                (r_chain, "rfauto.linkage.ads_active_chain.compare_chain_with_manual"),
                (r_lp, "rfauto.linkage.ads_active_chain.compare_loadpull_point")):
            annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
            root = ET.fromstring(annotated)
            cards = {el.get("id"): el for el in root.iter("UserObject")
                     if (el.get("id") or "").startswith("sim_")}
            assert source in cards["sim_c"].get("source"), "对拍卡 source 钉对拍函数"
            for card in cards.values():
                assert card.get("source") and card.get("sim_ref") is not None
                assert card.get("unit") is not None, "每卡 source/sim_ref/unit 三件组"
            metric_cards = [c for cid, c in cards.items() if cid.startswith("sim_m")]
            assert len(metric_cards) == len(ACTIVE_METRIC_NAMES[result["family"]])
            for card in metric_cards:
                assert card.get("value") == fmt_value(float(card.get("value"))), ".6g 同函数"

    def test_compare_skipped_card(self, chain_files, chain_gen, tmp_path):
        result = circuit_sim_run(
            chain_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            compare=False,
            runner=_chain_runner(chain_files["match"], chain_files["device"]))
        assert result["ok"], "compare 关闭时 ok 不被对拍位翻转"
        assert result["compare"] == {"status": "skipped"}
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        assert "对拍：skipped" in annotated


# --------------------------------------------------------------------------- #
# 钉 5（反标注幂等）+ ADS 失败降级 + 确定性 + 信封写面
# --------------------------------------------------------------------------- #

class TestActiveAnnotationAndEnvelope:
    @pytest.mark.parametrize("family", ["active_chain_sparam", "loadpull_hb"])
    def test_annotate_idempotent_bytes_and_original_untouched(
            self, chain_files, tmp_path, family):
        device = chain_files["device"]
        if family == "active_chain_sparam":
            gen = generate_circuit_diagram(
                family, device, tmp_path / "ckt.drawio",
                params={"match_snp": str(chain_files["match"])})
            runner = _chain_runner(chain_files["match"], device)
        else:
            gen = generate_circuit_diagram(
                family, device, tmp_path / "ckt.drawio", params=_loadpull_params())
            runner = _hb_runner(device)
        assert gen["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=device,
                                 out_dir=tmp_path / "run", runner=runner)
        assert result["ok"]
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        original = (tmp_path / "ckt.drawio").read_text(encoding="utf-8")
        ids_before, ids_after = _cell_id_set(original), _cell_id_set(annotated)
        added = ids_after - ids_before
        assert added == {ANNOT_LAYER_ID, "sim_h", "sim_m0", "sim_m1", "sim_c"}
        before, after = _attrs_by_id(original), _attrs_by_id(annotated)
        for cell_id, attrs in before.items():
            assert after[cell_id] == attrs, f"原 cell {cell_id} 被改动（零改动纪律）"
        result_json = tmp_path / "run" / f"{family}_circuit_result.json"
        out2 = tmp_path / "re" / "again.drawio"
        out2.parent.mkdir(parents=True, exist_ok=True)
        env2 = annotate_circuit_diagram(
            Path(result["annotated_diagram_path"]), result_json, out2)
        assert env2["ok"]
        assert out2.read_bytes() == Path(result["annotated_diagram_path"]).read_bytes(), (
            "annotate(annotate(x))==annotate(x) 三方逐字节（验收 C）")

    def test_ads_failure_degrades_to_error_head_card(self, chain_files, chain_gen, tmp_path):
        def boom(_p):
            raise RuntimeError("Linear features are not licensed (0 tokens)")

        result = circuit_sim_run(
            chain_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=boom)
        assert result["ok"] is False
        assert result["ads"]["status"] == "error"
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        assert "status=error" in annotated
        assert "not licensed" in annotated, "错误尾巴引注在卡（#105 溯源）"
        assert "sim_m0" not in annotated, "ADS 段失败不出指标卡（不虚构指标）"
        out = tmp_path / "degraded.drawio"
        env2 = annotate_circuit_diagram(
            chain_gen, tmp_path / "run" / "active_chain_sparam_circuit_result.json", out)
        assert env2["ok"] and out.exists(), "失败 result 也能离线 annotate（降级头卡）"

    def test_original_diagram_readonly_hash(self, chain_files, chain_gen, tmp_path):
        before = hashlib.sha256(chain_gen.read_bytes()).hexdigest()
        result = circuit_sim_run(
            chain_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=_chain_runner(chain_files["match"], chain_files["device"]))
        assert result["ok"]
        after = hashlib.sha256(chain_gen.read_bytes()).hexdigest()
        assert before == after, "--diagram 只读（原稿是模板）"

    def test_same_run_twice_byte_identical_j5_loop(self, chain_files, loadpull_gen, tmp_path):
        runner = _hb_runner(chain_files["device"])
        r1 = circuit_sim_run(loadpull_gen, snp_path=chain_files["device"],
                             out_dir=tmp_path / "run", runner=runner)
        netlist_1 = Path(r1["netlist_path"]).read_bytes()
        diagram_1 = Path(r1["annotated_diagram_path"]).read_bytes()
        result_1 = (tmp_path / "run" / "loadpull_hb_circuit_result.json").read_bytes()
        r2 = circuit_sim_run(loadpull_gen, snp_path=chain_files["device"],
                             out_dir=tmp_path / "run", runner=runner)
        assert Path(r2["netlist_path"]).read_bytes() == netlist_1
        assert Path(r2["annotated_diagram_path"]).read_bytes() == diagram_1
        assert (tmp_path / "run" / "loadpull_hb_circuit_result.json").read_bytes() == result_1
        assert r1["metrics"] == r2["metrics"]

    def test_netlist_ascii_no_bom(self, chain_files, chain_gen, loadpull_gen, tmp_path):
        r1 = circuit_sim_run(chain_gen, snp_path=chain_files["device"],
                             out_dir=tmp_path / "r1",
                             runner=_chain_runner(chain_files["match"], chain_files["device"]))
        r2 = circuit_sim_run(loadpull_gen, snp_path=chain_files["device"],
                             out_dir=tmp_path / "r2", runner=_hb_runner(chain_files["device"]))
        for result in (r1, r2):
            raw = Path(result["netlist_path"]).read_bytes()
            assert not raw.startswith(b"\xef\xbb\xbf"), "无 BOM"
            raw.decode("ascii")

    def test_loadpull_point_and_reference_in_result(
            self, chain_files, loadpull_gen, tmp_path):
        z_load = 15 + 8.5j
        result = circuit_sim_run(
            loadpull_gen, snp_path=chain_files["device"], out_dir=tmp_path / "run",
            runner=lambda _p: _hb_payload(chain_files["device"], F0_HZ, 20.0, z_load))
        assert result["ok"]
        result_json = json.loads(
            (tmp_path / "run" / "loadpull_hb_circuit_result.json").read_text(encoding="utf-8"))
        circuit = result_json["circuit"]
        assert circuit["point"]["z_load"] == {"re": 15.0, "im": 8.5}
        assert circuit["reference"]["pout_dbm"] == pytest.approx(
            result["metrics"]["pout_dbm"], abs=1e-9)
        assert circuit["metric_source"] == (
            "rfauto.linkage.ads_active_chain.hb_payload_to_point")
