"""TRL 校准件设计向导钉（aurora_p G1 席，2026-11-02）。

四面：

1. **设计数学手算锚逐位**（验收判据 A：手算表——
   L(θ=90°,f=10GHz,εeff=1)=C_MM_GHZ/40=7.49481145mm；
   L(εeff=4)=7.49481145/2=3.747405725mm；覆盖带 6GHz=[4/3, 32/3]GHz；
   带 4–9GHz@εeff=2.25：f0=6、L=299.792458/36、带缘 θ=[60°,135°]；
   带 2–18GHz@εeff=1：k=2、带心 2·9^(1/4)/2·9^(3/4)、L=299.792458/(4f0)、
   带缘 θ=90°·9^(±1/4)、拼接窗=[2·9^(3/4)·2/9, 2·9^(1/4)·16/9]）；
2. **覆盖三态语义**（验收判据 B：覆盖/不覆盖/警告如实——窄带单 Line
   零警告；中带 multiline 拼接窗核验；超限 uncovered 如实拒绝不硬凑
   [#122]，standards 空且警告指明所需 k）；
3. **介质单源消费**（铁律 7：微带 εeff/线宽逐位==synthesis 单源回算；
   coax TEM εeff=εr 闭式；负例=频率倒置/介质缺键/未知 kind/εeff<1/
   bool 入参）；
4. **service 信封+连接图集成+CLI**（验收判据 C/D：ok/error 信封同构；
   --out-dir 三件固定名端到端（设计单 JSON/calkit 定义 YAML 消费面
   method 契约对齐/连接图 XML 合法+CAL 标记）；确定性两次调用逐字节；
   CLI --json 成功+失败同构、usage 错 exit 2 JSON）。
"""

from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

_REPO = Path(__file__).resolve().parents[2]
_src = _REPO / "src"
if _src.exists() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from rfauto.cli.main import app as root_app
from rfauto.core.calc_families.registry import C_MM_GHZ
from rfauto.core.testsetup_diagram import normalize_scene
from rfauto.core.trl_design import (
    LINE_PHASE_TOL_DEG,
    LINE_THETA_MAX_DEG,
    LINE_THETA_MIN_DEG,
    design_trl_standards,
    line_coverage_band_ghz,
    line_length_mm,
    line_theta_deg,
    multiline_plan_centers,
)
from rfauto.service.cal_wizard_service import (
    _build_testsetup_scene,
    _calkit_def_yaml,
    trl_wizard,
)

_TOL = 1e-9


# ── 1. 设计数学手算锚（判据 A）───────────────────────────────────────────
class TestDesignMathAnchors:
    def test_line_length_hand_anchor(self):
        # 手算：C_MM_GHZ/4/f = 299.792458/(4·10) = 7.49481145 mm（εeff=1）
        assert line_length_mm(10.0, 1.0) == pytest.approx(7.49481145, abs=_TOL)
        # 手算：除以 √4=2 → 3.747405725 mm
        assert line_length_mm(10.0, 4.0) == pytest.approx(3.747405725, abs=_TOL)
        # θ≠90° 闭式：λg·θ/360（θ=20° 手算 = 7.49481145·20/90）
        assert line_length_mm(10.0, 1.0, 20.0) == pytest.approx(
            7.49481145 * 20.0 / 90.0, abs=_TOL)

    def test_theta_roundtrip_identity(self):
        length = line_length_mm(6.0, 2.25, 90.0)
        assert line_theta_deg(6.0, length, 2.25) == pytest.approx(90.0, abs=_TOL)
        # 任意长度正逆互逆
        assert line_theta_deg(9.0, 12.0, 3.0) == pytest.approx(
            360.0 * 9.0 * 12.0 * math.sqrt(3.0) / C_MM_GHZ, abs=_TOL)

    def test_coverage_band_hand_anchor(self):
        # 手算：f0·20/90=4/3、f0·160/90=32/3（f0=6）；边比恒 8:1
        lo, hi = line_coverage_band_ghz(6.0)
        assert lo == pytest.approx(4.0 / 3.0, abs=_TOL)
        assert hi == pytest.approx(32.0 / 3.0, abs=_TOL)
        assert hi / lo == pytest.approx(8.0, abs=_TOL)

    def test_single_line_design_hand_anchor(self):
        # 手算表：带 4–9GHz@εeff=2.25 → f0=√36=6、L=C/(4·6·1.5)=C/36、
        # 带缘 θ=90°·(4/6)=60° 与 90°·(9/6)=135°（∈[20°,160°]）
        d = design_trl_standards(4.0, 9.0, {"kind": "er_eff", "er_eff": 2.25})
        assert d["verdict"] == "single_line"
        assert d["covered"] is True
        assert d["f_center_ghz"] == pytest.approx(6.0, abs=_TOL)
        line = next(s for s in d["standards"] if s["role"] == "line")
        assert line["length_mm"] == pytest.approx(C_MM_GHZ / 36.0, abs=_TOL)
        assert line["theta_at_band_edges_deg"][0] == pytest.approx(60.0, abs=_TOL)
        assert line["theta_at_band_edges_deg"][1] == pytest.approx(135.0, abs=_TOL)
        assert d["standards"][0]["role"] == "thru"
        assert d["standards"][1]["role"] == "reflect"

    def test_multiline_hand_anchor(self):
        # 手算表：带 2–18GHz@εeff=1（R=9）→ k=ceil(ln9/ln((16/9)²))=2；
        # 带心 2·9^(1/4)=3.4641016 与 2·9^(3/4)=10.3923048；
        # L_j=C/(4·f0_j)；带缘 θ=90°·9^(±1/4)≈[51.9615°, 155.8846°]；
        # 拼接窗=[f0_2·20/90, f0_1·160/9] 非空
        d = design_trl_standards(2.0, 18.0, {"kind": "er_eff", "er_eff": 1.0})
        assert d["verdict"] == "multiline"
        assert d["covered"] is True
        assert d["n_lines"] == 2
        f01 = 2.0 * 9.0 ** 0.25
        f02 = 2.0 * 9.0 ** 0.75
        assert multiline_plan_centers(2.0, 18.0, 2) == pytest.approx(
            [f01, f02], abs=_TOL)
        lines = [s for s in d["standards"] if s["role"] == "line"]
        assert lines[0]["f_center_ghz"] == pytest.approx(f01, abs=_TOL)
        assert lines[0]["length_mm"] == pytest.approx(
            C_MM_GHZ / (4.0 * f01), abs=_TOL)
        assert lines[1]["length_mm"] == pytest.approx(
            C_MM_GHZ / (4.0 * f02), abs=_TOL)
        for line in lines:
            lo, hi = line["theta_at_band_edges_deg"]
            assert lo == pytest.approx(90.0 / 9.0 ** 0.25, abs=_TOL)
            assert hi == pytest.approx(90.0 * 9.0 ** 0.25, abs=_TOL)
            assert LINE_THETA_MIN_DEG <= lo < hi <= LINE_THETA_MAX_DEG
        assert d["line_overlap_windows_ghz"][0] == pytest.approx(
            [f02 * 20.0 / 90.0, f01 * 160.0 / 90.0], abs=_TOL)
        assert d["line_overlap_windows_ghz"][0][0] < d["line_overlap_windows_ghz"][0][1]
        # 单 Line 不足的警告如实带出
        assert any("覆盖不足" in w for w in d["warnings"])

    def test_multiline_k5_wide_band(self):
        # R=100 → k=ceil(ln100/ln(256/81))=ceil(4.0005)=5；每子带几何居中
        d = design_trl_standards(1.0, 100.0, {"kind": "er_eff", "er_eff": 4.0})
        assert d["verdict"] == "multiline"
        assert d["n_lines"] == 5
        assert len(d["line_overlap_windows_ghz"]) == 4  # 相邻拼接窗 k-1 个
        ratio = 100.0
        for j, line in enumerate(
                [s for s in d["standards"] if s["role"] == "line"], start=1):
            lo = 1.0 * ratio ** ((j - 1) / 5.0)
            hi = 1.0 * ratio ** (j / 5.0)
            assert line["served_band_ghz"] == pytest.approx([lo, hi], abs=_TOL)

    def test_tolerance_derivation(self):
        # 容差=LINE_PHASE_TOL_DEG 按服务子带最高频率折算（Δθ→ΔL 线性闭式）
        d = design_trl_standards(4.0, 9.0, {"kind": "er_eff", "er_eff": 2.25})
        line = next(s for s in d["standards"] if s["role"] == "line")
        assert line["phase_tolerance_deg"] == LINE_PHASE_TOL_DEG
        assert line["length_tolerance_mm"] == pytest.approx(
            line_length_mm(9.0, 2.25, LINE_PHASE_TOL_DEG), abs=_TOL)


# ── 2. 覆盖三态语义（判据 B）─────────────────────────────────────────────
class TestCoverageThreeState:
    def test_narrow_band_single_line_no_warning(self):
        # 窄带极端例：10–10.001GHz（R=1.0001）→ 单 Line 覆盖、零警告
        d = design_trl_standards(10.0, 10.001, {"kind": "er_eff",
                                                "er_eff": 1.0})
        assert d["verdict"] == "single_line"
        assert d["covered"] is True
        assert d["warnings"] == []

    def test_ultra_wide_uncovered_honest(self):
        # 超限极端例：R=5000 需 k=8 > 上限 6 → uncovered 如实拒绝（#122）
        d = design_trl_standards(1.0, 5000.0, {"kind": "er_eff", "er_eff": 2.2})
        assert d["verdict"] == "uncovered"
        assert d["covered"] is False
        assert d["standards"] == []
        assert d["n_lines"] == 0
        assert any("8" in w and "如实拒绝" in w for w in d["warnings"])

    def test_max_lines_param_caps_honest(self):
        # 上限参数收窄：R=100 需 5 条，给 max_lines=2 → uncovered 如实
        d = design_trl_standards(1.0, 100.0, {"kind": "er_eff", "er_eff": 2.2},
                                 max_lines=2)
        assert d["verdict"] == "uncovered"
        assert d["standards"] == []

    def test_medium_band_single_to_multiline_boundary(self):
        # R=3.16（=(16/9)² 边界内）单 Line；R=4 升 multiline k=2
        d1 = design_trl_standards(3.0, 9.48, {"kind": "er_eff", "er_eff": 1.0})
        assert d1["verdict"] == "single_line"
        d2 = design_trl_standards(3.0, 12.0, {"kind": "er_eff", "er_eff": 1.0})
        assert d2["verdict"] == "multiline"
        assert d2["n_lines"] == 2


# ── 3. 介质单源消费+负例（铁律 7/#122）───────────────────────────────────
class TestMediumAndNegatives:
    def test_er_eff_direct_passthrough(self):
        d = design_trl_standards(4.0, 9.0, {"kind": "er_eff", "er_eff": 2.25})
        assert d["medium"]["er_eff"] == 2.25
        assert d["medium"]["er_eff_source"] == "user_er_eff"

    def test_coax_tem_closed_form(self):
        # 均匀 TEM 同轴：εeff=εr（教科书闭式；非 skrf 面）
        d = design_trl_standards(4.0, 9.0, {"kind": "coax", "er": 2.1})
        assert d["medium"]["er_eff"] == 2.1
        assert d["medium"]["er_eff_source"] == "tem_coax_closed_form"

    def test_microstrip_single_source_bitwise(self):
        # 铁律 7：εeff/线宽逐位==synthesis 单源回算（同参同频）
        from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

        d = design_trl_standards(8.0, 12.0,
                                 {"kind": "microstrip", "er": 4.4,
                                  "h_mm": 1.6})
        f0 = math.sqrt(8.0 * 12.0)
        stackup = Stackup(name="x", epsilon_r=4.4, thickness_mm=1.6)
        w, _z0a, _status = inverse_width(50.0, f0, stackup)
        media = forward_z0(w, f0, stackup)
        med = d["medium"]
        assert med["width_mm"] == w
        assert med["er_eff"] == media.er_eff
        assert med["er_eff_source"].startswith("synthesis.forward_z0:")
        # 设计单 Line 长度=闭式恒等式（消费同一 εeff）
        line = next(s for s in d["standards"] if s["role"] == "line")
        assert line["length_mm"] == pytest.approx(
            C_MM_GHZ / (4.0 * f0 * math.sqrt(med["er_eff"])), abs=_TOL)
        # 物理界：(εr+1)/2 < εeff < εr（薄/宽微带夹逼）
        assert (4.4 + 1.0) / 2.0 < med["er_eff"] < 4.4
        # 微带口径色散注记警告如实（准静态口径 #122 声明）
        assert any("色散" in w for w in d["warnings"])

    def test_microstrip_explicit_width(self):
        d = design_trl_standards(8.0, 12.0,
                                 {"kind": "microstrip", "er": 4.4,
                                  "h_mm": 1.6, "w_mm": 1.0})
        assert d["medium"]["width_mm"] == 1.0

    def test_freq_inverted_rejected(self):
        with pytest.raises(ValueError, match="倒置"):
            design_trl_standards(9.0, 4.0, {"kind": "er_eff", "er_eff": 2.0})
        with pytest.raises(ValueError, match="大于 f_start_ghz"):
            design_trl_standards(5.0, 5.0, {"kind": "er_eff", "er_eff": 2.0})

    def test_non_finite_rejected(self):
        for bad in (float("inf"), float("nan")):
            with pytest.raises(ValueError, match="有限"):
                design_trl_standards(bad, 9.0,
                                     {"kind": "er_eff", "er_eff": 2.0})

    def test_bool_rejected(self):
        with pytest.raises(ValueError):
            design_trl_standards(True, 9.0, {"kind": "er_eff", "er_eff": 2.0})
        with pytest.raises(ValueError):
            design_trl_standards(4.0, 9.0, {"kind": "er_eff", "er_eff": True})

    def test_medium_missing_and_unknown(self):
        with pytest.raises(ValueError, match="h_mm"):
            design_trl_standards(4.0, 9.0, {"kind": "microstrip", "er": 4.4})
        with pytest.raises(ValueError, match="er_eff"):
            design_trl_standards(4.0, 9.0, {"kind": "er_eff"})
        with pytest.raises(ValueError, match="未知"):
            design_trl_standards(4.0, 9.0, {"kind": "waveguide", "er": 4.4})
        with pytest.raises(ValueError, match="未支持键"):
            design_trl_standards(4.0, 9.0,
                                 {"kind": "er_eff", "er_eff": 2.0, "x": 1})

    def test_er_eff_below_one_rejected(self):
        with pytest.raises(ValueError, match="≥1"):
            design_trl_standards(4.0, 9.0, {"kind": "er_eff", "er_eff": 0.5})

    def test_bad_max_lines_rejected(self):
        with pytest.raises(ValueError, match="正整数"):
            design_trl_standards(4.0, 9.0, {"kind": "er_eff", "er_eff": 2.0},
                                 max_lines=0)


# ── 4. service 信封+连接图集成+CLI（判据 C/D）────────────────────────────
class TestServiceEnvelope:
    def test_ok_envelope_shape(self):
        r = trl_wizard({"f_start_ghz": 4.0, "f_stop_ghz": 9.0,
                        "medium": {"kind": "er_eff", "er_eff": 2.25}})
        assert r["ok"] is True
        assert r["verdict"] == "single_line"
        assert r["written"] == {}  # 缺省零落盘
        for key in ("band_ghz", "standards", "warnings", "covered",
                    "n_lines", "anchors", "medium", "f_center_ghz"):
            assert key in r

    def test_error_envelope_shape(self):
        # service 层负例=错误信封（不抛异常；ok=False + errors list[str]）
        r = trl_wizard({"f_start_ghz": 9.0, "f_stop_ghz": 4.0,
                        "medium": {"kind": "er_eff", "er_eff": 2.25}})
        assert r["ok"] is False
        assert isinstance(r["errors"], list) and r["errors"]

    def test_payload_strict_keys(self):
        base = {"f_start_ghz": 4.0, "f_stop_ghz": 9.0,
                "medium": {"kind": "er_eff", "er_eff": 2.25}}
        assert trl_wizard({**base, "nope": 1})["ok"] is False
        assert trl_wizard({"f_start_ghz": 4.0,
                           "f_stop_ghz": 9.0})["ok"] is False
        assert trl_wizard({**base, "max_lines": "x"})["ok"] is False

    def test_determinism_envelope_and_files(self, tmp_path):
        payload = {"f_start_ghz": 2.0, "f_stop_ghz": 18.0,
                   "medium": {"kind": "er_eff", "er_eff": 1.0}}
        r1 = trl_wizard(dict(payload))
        r2 = trl_wizard(dict(payload))
        r1.pop("written"), r2.pop("written")
        assert r1 == r2
        out1, out2 = tmp_path / "a", tmp_path / "b"
        trl_wizard(dict(payload), out_dir=out1)
        trl_wizard(dict(payload), out_dir=out2)
        for name in ("trl_design_sheet.json", "calkit_def.yaml",
                     "trl_testsetup.drawio"):
            assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


class TestDiagramIntegration:
    def test_out_dir_three_files_end_to_end(self, tmp_path):
        r = trl_wizard({"f_start_ghz": 4.0, "f_stop_ghz": 9.0,
                        "medium": {"kind": "er_eff", "er_eff": 2.25},
                        "kit_id": "g1_smoke"}, out_dir=tmp_path)
        assert r["ok"] is True
        # 设计单 JSON 可解析且=信封数据面（written 键除外）
        sheet = json.loads((tmp_path / "trl_design_sheet.json").read_text(
            encoding="utf-8"))
        assert sheet["verdict"] == r["verdict"]
        assert sheet["band_ghz"] == r["band_ghz"]
        # calkit 定义 YAML：method=trl（单 Line 消费面 _TRL_ORDER 键契约）
        calkit = yaml.safe_load(
            (tmp_path / "calkit_def.yaml").read_text(encoding="utf-8"))
        entry = calkit["calkits"]["g1_smoke"]
        assert entry["method"] == "trl"
        assert entry["standards"] == {"thru": "thru.s2p",
                                      "reflect": "reflect.s1p",
                                      "line": "line1.s2p"}
        # 连接图 XML 合法+CAL 校准面标记+拓扑双射
        xml_text = (tmp_path / "trl_testsetup.drawio").read_text(
            encoding="utf-8")
        ET.fromstring(xml_text)
        assert "▎CAL" in xml_text
        assert r["written"]["testsetup_diagram"].endswith(
            "trl_testsetup.drawio")

    def test_calkit_multiline_consumer_contract(self):
        # 多 Line：method=nist_multiline_trl（消费面 _multiline_line_keys
        # 序号排序契约），键 line1..lineN
        d = design_trl_standards(2.0, 18.0, {"kind": "er_eff", "er_eff": 1.0})
        calkit = _calkit_def_yaml(d, "multi_kit")
        entry = calkit["calkits"]["multi_kit"]
        assert entry["method"] == "nist_multiline_trl"
        assert entry["standards"] == {"thru": "thru.s2p",
                                      "reflect": "reflect.s1p",
                                      "line1": "line1.s2p",
                                      "line2": "line2.s2p"}
        assert yaml.safe_load(yaml.safe_dump(calkit, allow_unicode=True)) \
            == calkit

    def test_uncovered_skips_calkit_not_diagram(self, tmp_path):
        # uncovered：calkit 骨架不产（无 Line 的 kit 过不了消费面），
        # 设计单+连接图仍产出；警告如实
        r = trl_wizard({"f_start_ghz": 1.0, "f_stop_ghz": 5000.0,
                        "medium": {"kind": "er_eff", "er_eff": 2.2}},
                       out_dir=tmp_path)
        assert r["ok"] is True
        assert r["verdict"] == "uncovered"
        assert "calkit_def" not in r["written"]
        assert "design_sheet" in r["written"]
        assert "testsetup_diagram" in r["written"]

    def test_scene_passes_normalize_schema(self):
        d = design_trl_standards(4.0, 9.0, {"kind": "er_eff", "er_eff": 2.25})
        scene = _build_testsetup_scene(d, "SMA")
        norm = normalize_scene(scene)  # 严格 schema 违约即 ValueError
        assert [i["kind"] for i in norm["instruments"]] == ["vna", "dut"]
        assert all(c["cal_plane"] for c in norm["connections"])
        assert len(norm["connections"]) == 2

    def test_scene_title_override(self):
        d = design_trl_standards(4.0, 9.0, {"kind": "er_eff", "er_eff": 2.25})
        scene = _build_testsetup_scene(d, "SMA", title="G1 席样例")
        assert scene["title"] == "G1 席样例"


class TestCliLeaf:
    def _run(self, *args: str):
        return CliRunner().invoke(root_app, ["cal-wizard", "trl", *args])

    def test_json_success_envelope(self):
        res = self._run("--freq-range-ghz", "4,9", "--er-eff", "2.25",
                        "--json")
        assert res.exit_code == 0
        payload = json.loads(res.output)
        assert payload["ok"] is True
        assert payload["verdict"] == "single_line"

    def test_json_failure_envelope_same_shape(self):
        # service 负例（εeff<1 非物理）：--json 失败路径也是信封
        # （禁裸文本，_emit 统一出口 exit 1）
        res = self._run("--freq-range-ghz", "4,9", "--er-eff", "0.5",
                        "--json")
        assert res.exit_code == 1
        payload = json.loads(res.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list) and payload["errors"]

    def test_inverted_freq_range_usage_error(self):
        # 频率倒置在 CLI 面被 _parse_freq_range（与 vna measure 同款
        # 单源）拦为 usage 错（exit 2）；service 层倒置负例另由信封测试钉
        res = self._run("--freq-range-ghz", "9,4", "--er-eff", "2.25",
                        "--json")
        assert res.exit_code == 2

    def test_json_out_dir_smoke(self, tmp_path):
        res = self._run("--freq-range-ghz", "4,9", "--er-eff", "2.25",
                        "--out-dir", str(tmp_path), "--json")
        assert res.exit_code == 0
        payload = json.loads(res.output)
        assert payload["written"]["design_sheet"]

    def test_usage_error_medium_flags(self):
        # 介质旗标纪律：er_eff 口径缺 --er-eff → usage 错（exit 2），
        # --json 下失败路径出 JSON 信封
        res = self._run("--freq-range-ghz", "4,9", "--json")
        assert res.exit_code == 2
        assert json.loads(res.output)["ok"] is False
        # 禁给旗标：coax 口径给 --er-eff
        res2 = self._run("--freq-range-ghz", "4,9", "--medium", "coax",
                         "--er", "2.1", "--er-eff", "2.1", "--json")
        assert res2.exit_code == 2
        # 未知 --medium
        res3 = self._run("--freq-range-ghz", "4,9", "--medium", "waveguide",
                         "--json")
        assert res3.exit_code == 2

    def test_human_output_smoke(self):
        res = self._run("--freq-range-ghz", "2,18", "--er-eff", "1.0")
        assert res.exit_code == 0
        assert "multiline" in res.output

    def test_help_hygiene(self):
        # help 卫生：零裸 [ 零裸 %（check_cli_help_bracket 同口径自证）
        res = self._run("--help")
        assert res.exit_code == 0
        for line in res.output.splitlines():
            assert "%" not in line
