"""Q-X49（aurora_q）——LVS 网表对照器单测（服务全链 + CLI 叶钉）。

覆盖面：
- 归一化钉：格式 auto 判定、接地别名归一（0/gnd/GND!/1'b0 → 0）、
  SPICE 大小写不敏感、verilog 内置门级解析（family/value/params/
  向量与命名连接 warning）；
- 图同构钉：relay 重命名重排 MATCH、镜像角色交换（r1↔r2 强制换名
  映射——iso 不绑定名）、对称族引脚翻转 vs 极性族（diode）翻转、
  missing/extra、同构预算耗尽 undecidable（monkeypatch 预算参数）；
- 参数容差：出窗 PARTIAL / 容差内 MATCH / 双表达式 raw 比对；
- RF 特化钉：端口数量/序号/阻抗、传输线 series/shunt/coupled 分类、
  --rf 关闭时不判端口；
- 对照报告钉：schema/verdict 词表/score ∈[0,1]/差异三分类 taxonomy/
  score 单调性/summary 计数自洽；
- CLI 叶：--json 信封正负例（tmp fixture 零 runs/ 湖写入零网络——#144
  家法）、verdict 拦截退出码（MATCH=0/其余=1）、usage 错 exit 2
  （#ge1㉙ 契约）、help 卫生（#305 家族）、click 树注册面 + 计数链
  grep 字面钉（#304 家法——本席落树时点 live=316，字面随并发席合流
  笔收敛；稳定断言=lvs 域恰 1 叶+sum 分型互证）。

零网络零真机零新依赖（纯离线结构比对——铁律 7：解析不仿真）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.cli.main import app
from rfauto.service.lvs_compare_service import (
    DEFAULT_TOLERANCE,
    LVS_COMPARE_SCHEMA,
    LVS_VERDICTS,
    compare_netlist_files,
    compare_netlist_texts,
    detect_netlist_format,
)

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_numbers.py"
_SPEC = importlib.util.spec_from_file_location("check_numbers_gate_lvs",
                                               _SCRIPT)
check_numbers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_numbers)

#: RC 梯形 + RF 端口（P 元件显式 port/z0 参数 → 端口化，不进元件清单）。
_SPICE_RC = """RC ladder with RF port
P1 in 0 port=1 z0=50
R1 in n1 1k
C1 n1 0 2p
R2 n1 out 500
C2 out 0 1p
.end
"""

#: 同电路 relay 命名（重命名网络+换名元件+数值书写形变 1k↔1000）。
_SPICE_RC_RENAMED = """same circuit relay names
P9 vin vss port=1 z0=50
r7 vin mid 1000
c3 mid vss 2e-12
r5 mid vout 0.5k
c8 vout vss 1p
.end
"""

#: schematic 缺 R2（layout 侧出 extra）。
_SPICE_RC_NO_R2 = _SPICE_RC.replace("R2 n1 out 500\n", "")

#: R2 参数出窗（500 → 550，相对 10% > 缺省 1%）。
_SPICE_RC_PARAM_OFF = _SPICE_RC.replace("R2 n1 out 500", "R2 n1 out 550")

#: R2 参数容差内（500 → 505，相对 1% == 缺省容差边界内）。
_SPICE_RC_PARAM_NEAR = _SPICE_RC.replace("R2 n1 out 500", "R2 n1 out 505")

#: pi 网络 layout（角色镜像 schematic 的参照侧）。
_SPICE_PI = """pi network layout
R1 a b 1k
R2 b c 2k
C1 a 0 1p
C2 c 0 2p
.end
"""

#: pi 镜像（C 挪位——同构成立但元件值随角色互换：结构 MATCH 值出窗）。
_SPICE_PI_MIRROR = """pi network mirror
R1 c b 2k
R2 b a 1k
C1 c 0 2p
C2 a 0 1p
.end
"""

#: 双电阻链+端接电容（同名映射被电容落点否决——唯一合法同构必须换名
#: 映射 r1→r2/r2→r1：iso 不绑定名的强钉；值沿角色对齐保 MATCH 纯度）。
_SPICE_CHAIN_A = """chain layout
R1 a b 1k
R2 b c 2k
C1 a 0 1p
.end
"""

_SPICE_CHAIN_B = """chain schematic mirrored
R1 c b 2k
R2 b a 1k
C1 a 0 1p
.end
"""

#: 二极管极性族（引脚序不可翻转——翻转=结构 MISMATCH）。
_SPICE_DIODE = """diode polarity layout
D1 a b dmod
R1 b 0 1k
.end
"""

_SPICE_DIODE_FLIP = """diode polarity flipped
D1 b a dmod
R1 b 0 1k
.end
"""

#: 接地别名三态（gnd/GND!/0 归一）。
_SPICE_GND = """ground alias layout
R1 in out 1k
C1 out gnd 2p
.end
"""

_SPICE_GND_B = """ground alias schematic
R1 in out 1k
C1 out GND! 2p
.end
"""

#: 耦合电感对 + 短路枝（RF 分类：coupled vs isolated / shunt stub）。
_SPICE_TL_COUPLED = """coupled pair layout
T1 a 0 b 0 td=1n
K1 L1 L2 0.9
L1 p1 p2 1n
L2 p3 p4 1n
.end
"""

_SPICE_TL_OPEN = """uncoupled pair schematic
T1 a 0 b 0 td=1n
L1 p1 p2 1n
L2 p3 p4 1n
.end
"""

#: 传输线 series vs shunt（同元件清单，shunt=单网络短路枝 T a 0 0 0——
#: 分类按非地网络去重数：==1 → shunt，>=2 → series）。
_SPICE_TL_SERIES = """tline series layout
T1 a b c d td=1n
R1 a 0 50
R2 d 0 50
.end
"""

_SPICE_TL_SHUNT = """tline shunt schematic
T1 a 0 0 0 td=1n
R1 a 0 50
R2 a 0 50
.end
"""

#: 端口阻抗出窗（z0 50 → 75）。
_SPICE_RC_Z0_OFF = _SPICE_RC.replace("z0=50", "z0=75")

#: 端口数量不齐（schematic 加 P2）。
_SPICE_RC_PORT2 = _SPICE_RC + "P2 out 0 port=2 z0=50\n"

#: 门级 Verilog 同一 RC 电路（跨格式归一互证）。
_VERILOG_RC = """module rc_ladder (in, out);
  input in;
  output out;
  wire n1;
  resistor #(.r(1000)) R1 (in, n1);
  capacitor #(.c(2e-12)) C1 (n1, gnd);
  resistor #(.r(500)) R2 (n1, out);
  capacitor #(.c(1e-12)) C2 (out, gnd);
endmodule
"""

#: verilog 向量 + 命名连接（warning 面钉）。
_VERILOG_VECTOR = """module vec (data, out);
  input [3:0] data;
  output out;
  not g1 (.a(out), .b(data));
endmodule
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _invoke(*args: str):
    return CliRunner().invoke(app, args)


def _diff_types(env: dict) -> list[str]:
    return [d["type"] for d in env.get("differences") or []]


# --------------------------------------------------------------------------- #
# 归一化钉
# --------------------------------------------------------------------------- #


class TestNormalization:
    def test_detect_format_auto_and_explicit(self):
        assert detect_netlist_format(_SPICE_RC) == "spice"
        assert detect_netlist_format(_VERILOG_RC) == "verilog"
        # 显式覆盖：verilog 文本按 spice 解析走 core 解析器（解析面如实
        # 出结构化误差不炸——fail-soft 契约）
        env = compare_netlist_texts(_VERILOG_RC, _VERILOG_RC, fmt="spice")
        assert env["ok"] is True

    def test_format_vocabulary_rejected(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC, fmt="vhdl")
        assert env["ok"] is False
        assert any("vhdl" in e for e in env["errors"])

    def test_ground_aliases_unified(self):
        env = compare_netlist_texts(_SPICE_GND, _SPICE_GND_B)
        assert env["ok"] is True
        assert env["verdict"] == "MATCH"
        assert env["score"] == 1.0

    def test_spice_case_insensitive_names(self):
        # relay 命名夹具本身即小写化+换名——同构映射跨大小写与名（双钉）
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC_RENAMED)
        assert env["verdict"] == "MATCH"
        mapping = env["iso"]["element_mapping"]
        assert mapping == {"c1": "c3", "c2": "c8", "r1": "r7", "r2": "r5"}
        assert env["iso"]["net_mapping"] == {
            "0": "vss", "in": "vin", "n1": "mid", "out": "vout"}

    def test_port_element_excluded_from_inventory(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC)
        assert env["layout"]["n_elements"] == 4  # P1 端口化不进元件清单
        assert env["layout"]["n_ports"] == 1
        port = env["layout"]["ports"][0]
        assert port["index"] == 1
        assert port["z0"] == 50.0
        assert port["element"] == "p1"

    def test_coax_p_without_port_param_not_a_port(self):
        text = """coax no port param
T1 a 0 b 0 td=1n
P1 a 0 50
.end
"""
        env = compare_netlist_texts(text, text)
        assert env["ok"] is True
        assert env["layout"]["n_ports"] == 0  # 无显式端口参数 → 非端口
        assert env["layout"]["n_elements"] == 2

    def test_verilog_core_parser_preferred(self):
        # Q-X47 verilog_netlist_parser 已落树（parse_verilog）——只读消费
        # 单点切换（verilog_parser_source=core 如实披露；schema 不识时
        # 兜底内置器，切换非静默）
        env = compare_netlist_texts(_VERILOG_RC, _VERILOG_RC)
        assert env["ok"] is True
        assert env["verdict"] == "MATCH"
        assert env["layout"]["format"] == "verilog"
        assert env["layout"]["verilog_parser_source"] == "core"
        assert env["layout"]["n_elements"] == 4

    def test_verilog_builtin_fallback_path(self):
        # 内置最小归一器兜底面直钉（core 探测不中/schema 不识时的兜底）：
        # 直接调内置解析+归一（绕过 core 优先分派）
        from rfauto.service.lvs_compare_service import (
            _normalize_verilog_graph,
            _parse_verilog_netlist_text,
        )

        parsed = _parse_verilog_netlist_text(_VERILOG_RC)
        graph = _normalize_verilog_graph(parsed)
        assert graph["format"] == "verilog"
        assert graph["n_elements"] == 4
        families = {el["name"]: el["family"] for el in graph["elements"]}
        assert families == {"R1": "resistor", "C1": "capacitor",
                            "R2": "resistor", "C2": "capacitor"}
        assert graph["ports"] == [
            {"index": 1, "element": None, "net": "in", "z0": None},
            {"index": 2, "element": None, "net": "out", "z0": None},
        ]

    def test_verilog_vector_and_named_conn_warnings(self):
        env = compare_netlist_texts(_VERILOG_VECTOR, _VERILOG_VECTOR)
        assert env["ok"] is True
        warns = "\n".join(env["warnings"])
        assert "向量" in warns  # [3:0] 位级展开超 MVP 如实警示
        assert "命名端口" in warns  # .a(x) 命名连接摊平如实警示

    def test_cross_format_spice_vs_verilog_match(self):
        env = compare_netlist_texts(_SPICE_RC, _VERILOG_RC)
        assert env["ok"] is True
        assert env["verdict"] == "MATCH"
        assert env["score"] == 1.0
        assert env["layout"]["format"] == "spice"
        assert env["schematic"]["format"] == "verilog"


# --------------------------------------------------------------------------- #
# 图同构钉
# --------------------------------------------------------------------------- #


class TestIsomorphism:
    def test_identical_match(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC)
        assert env["verdict"] == "MATCH"
        assert env["score"] == 1.0
        assert env["summary"]["matched_element_pairs"] == 4
        assert env["iso"]["matched"] is True

    def test_relay_names_isomorphic_match(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC_RENAMED)
        assert env["verdict"] == "MATCH"
        assert len(env["iso"]["element_mapping"]) == 4

    def test_forced_rename_mapping_chain_mirror(self):
        # 链两端镜像：同构不绑定名——唯一合法映射 r1→r2/r2→r1（强钉；
        # c1 落点同名但 r 对必须换名——映射逐对断言非名字自映射）
        env = compare_netlist_texts(_SPICE_CHAIN_A, _SPICE_CHAIN_B)
        assert env["ok"] is True
        assert env["verdict"] == "MATCH"
        assert env["iso"]["element_mapping"] == {
            "c1": "c1", "r1": "r2", "r2": "r1"}

    def test_missing_element_structural_mismatch(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC_NO_R2)
        assert env["verdict"] == "MISMATCH"
        assert "extra_element" in _diff_types(env)  # layout 独有 r2
        extra = [d for d in env["differences"]
                 if d["type"] == "extra_element"]
        assert extra[0]["element"] == "r2"
        assert extra[0]["category"] == "extra"
        assert env["summary"]["matched_element_pairs"] == 0

    def test_missing_side_semantics_schematic_only(self):
        # missing=schematic 独有（layout 缺）——方向语义钉
        env = compare_netlist_texts(_SPICE_RC_NO_R2, _SPICE_RC)
        assert env["verdict"] == "MISMATCH"
        missing = [d for d in env["differences"]
                   if d["type"] == "missing_element"]
        assert missing[0]["side"] == "schematic"
        assert missing[0]["element"] == "r2"

    def test_param_mismatch_beyond_tolerance_partial(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC_PARAM_OFF)
        assert env["verdict"] == "PARTIAL"  # 结构一致值级出窗
        assert "param_mismatch" in _diff_types(env)
        assert 0.0 < env["score"] < 1.0
        assert env["iso"]["matched"] is True

    def test_param_within_tolerance_match(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC_PARAM_NEAR,
                                    tolerance=0.02)
        assert env["verdict"] == "MATCH"
        assert env["score"] == 1.0
        # 同一 1% 出窗：505/500 恰 1% 边界——缺省容差判定为一致（<=）
        env_def = compare_netlist_texts(_SPICE_RC, _SPICE_RC_PARAM_NEAR)
        assert env_def["verdict"] == "MATCH"

    def test_polar_pin_flip_mismatch(self):
        env = compare_netlist_texts(_SPICE_DIODE, _SPICE_DIODE_FLIP)
        assert env["verdict"] == "MISMATCH"
        assert "topology_mismatch" in _diff_types(env)
        # 同型不翻转 = MATCH（排除法钉极性序语义）
        env_same = compare_netlist_texts(_SPICE_DIODE, _SPICE_DIODE)
        assert env_same["verdict"] == "MATCH"

    def test_mirror_structure_match_values_partial(self):
        # pi 镜像：结构同构成立（net a↔c 换位），值随角色互换 → PARTIAL
        env = compare_netlist_texts(_SPICE_PI, _SPICE_PI_MIRROR)
        assert env["ok"] is True
        assert env["verdict"] == "PARTIAL"
        assert env["iso"]["matched"] is True
        assert len(_diff_types(env)) == 4  # 四个元件值全出窗

    def test_budget_exceeded_undecidable_partial(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC_RENAMED,
                                    iso_step_budget=0)
        assert env["verdict"] == "PARTIAL"  # 不可判定≠判定不一致
        assert "undecidable" in _diff_types(env)
        assert env["iso"]["budget_exceeded"] is True
        assert env["summary"]["budget_exceeded"] is True
        assert env["score"] == 0.0  # 未验证同构=零已证一致（如实）

    def test_element_count_unequal_skips_iso_with_warning(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC_NO_R2)
        assert env["verdict"] == "MISMATCH"
        assert env["iso"]["attempted"] is False
        assert any("元件数不等" in w for w in env["warnings"])


# --------------------------------------------------------------------------- #
# 对照报告钉
# --------------------------------------------------------------------------- #


class TestReport:
    def test_report_schema_keys(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC)
        assert env["schema"] == LVS_COMPARE_SCHEMA
        assert env["verdict"] in LVS_VERDICTS
        assert isinstance(env["score"], float)
        assert 0.0 <= env["score"] <= 1.0
        assert isinstance(env["differences"], list)
        for key in ("verdict", "verdict_reason", "n_missing", "n_extra",
                    "n_mismatched", "n_differences",
                    "n_elements_layout", "n_elements_schematic",
                    "matched_element_pairs", "budget_exceeded"):
            assert key in env["summary"], key
        for key in ("layout", "schematic", "iso", "rf", "params",
                    "warnings"):
            assert key in env, key
        assert env["params"]["tolerance"] == DEFAULT_TOLERANCE

    def test_difference_taxonomy(self):
        env = compare_netlist_texts(_SPICE_RC_NO_R2, _SPICE_RC)
        env2 = compare_netlist_texts(_SPICE_RC, _SPICE_RC_PARAM_OFF)
        for source in (env, env2):
            for d in source["differences"]:
                assert d["category"] in ("missing", "extra", "mismatched")
                assert d["type"] in (
                    "missing_element", "extra_element",
                    "param_mismatch", "topology_mismatch", "undecidable",
                    "port_mismatch", "impedance_mismatch",
                    "tline_class_mismatch")
                assert isinstance(d["detail"], str) and d["detail"]

    def test_score_monotonic_in_differences(self):
        env_param = compare_netlist_texts(_SPICE_RC, _SPICE_RC_PARAM_OFF)
        env_missing = compare_netlist_texts(_SPICE_RC, _SPICE_RC_NO_R2)
        assert env_missing["score"] < env_param["score"]

    def test_summary_counts_self_consistent(self):
        env = compare_netlist_texts(_SPICE_RC_NO_R2, _SPICE_RC)
        s = env["summary"]
        assert s["n_missing"] + s["n_extra"] + s["n_mismatched"] \
            == s["n_differences"] == len(env["differences"])
        env_match = compare_netlist_texts(_SPICE_RC, _SPICE_RC)
        assert env_match["summary"]["n_differences"] == 0
        assert env_match["score"] == 1.0

    def test_file_entry_same_as_text_entry(self, tmp_path):
        p1 = _write(tmp_path, "layout.cir", _SPICE_RC)
        p2 = _write(tmp_path, "schematic.cir", _SPICE_RC_PARAM_OFF)
        env_f = compare_netlist_files(p1, p2)
        env_t = compare_netlist_texts(_SPICE_RC, _SPICE_RC_PARAM_OFF)
        assert env_f["verdict"] == env_t["verdict"] == "PARTIAL"
        assert env_f["score"] == env_t["score"]
        assert env_f["layout"]["path"] == str(p1)
        assert env_t["layout"]["path"] is None

    def test_error_envelope_missing_file(self, tmp_path):
        env = compare_netlist_files(tmp_path / "nope.cir",
                                    tmp_path / "nope2.cir")
        assert env["ok"] is False
        assert len(env["errors"]) == 2  # 两侧归属如实
        assert any("layout" in e for e in env["errors"])
        assert any("schematic" in e for e in env["errors"])

    def test_negative_tolerance_rejected(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC, tolerance=-0.1)
        assert env["ok"] is False


# --------------------------------------------------------------------------- #
# RF 特化钉
# --------------------------------------------------------------------------- #


class TestRf:
    def test_rf_match_ports_and_z0(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC, rf=True)
        assert env["verdict"] == "MATCH"
        assert env["rf"]["n_ports_layout"] == 1
        assert env["rf"]["n_ports_schematic"] == 1
        assert env["rf"]["z0_compared"] == 1

    def test_rf_port_count_mismatch(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC_PORT2, rf=True)
        assert env["verdict"] == "MISMATCH"
        assert "port_mismatch" in _diff_types(env)

    def test_rf_z0_beyond_tolerance_partial(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC_Z0_OFF, rf=True)
        assert env["verdict"] == "PARTIAL"  # 结构一致阻抗出窗
        assert "impedance_mismatch" in _diff_types(env)

    def test_rf_off_ignores_port_differences(self):
        env = compare_netlist_texts(_SPICE_RC, _SPICE_RC_PORT2)
        assert env["verdict"] == "MATCH"  # 无 --rf 端口面不判
        assert env["rf"] is None

    def test_rf_tline_series_vs_shunt(self):
        env = compare_netlist_texts(_SPICE_TL_SERIES, _SPICE_TL_SHUNT,
                                    rf=True)
        assert env["verdict"] == "MISMATCH"
        assert "tline_class_mismatch" in _diff_types(env)
        cls = env["rf"]["tline_class_layout"]
        assert cls.get("tline/series") == 1
        assert env["rf"]["tline_class_schematic"].get("tline/shunt") == 1

    def test_rf_coupled_vs_uncoupled(self):
        env = compare_netlist_texts(_SPICE_TL_COUPLED, _SPICE_TL_OPEN,
                                    rf=True)
        assert env["verdict"] == "MISMATCH"
        assert "tline_class_mismatch" in _diff_types(env)
        cls_l = env["rf"]["tline_class_layout"]
        assert cls_l.get("inductor/coupled") == 2  # K1 引用归组
        assert env["rf"]["tline_class_schematic"].get(
            "inductor/isolated") == 2

    def test_rf_coupled_identical_match(self):
        env = compare_netlist_texts(_SPICE_TL_COUPLED, _SPICE_TL_COUPLED,
                                    rf=True)
        assert env["verdict"] == "MATCH"


# --------------------------------------------------------------------------- #
# CLI 叶 + 注册面 + 计数链
# --------------------------------------------------------------------------- #


class TestLvsCompareCli:
    def test_help_constructs_no_bare_percent(self):
        result = _invoke("lvs", "compare", "--help")
        assert result.exit_code == 0, result.output
        assert "%" not in result.output  # #305 家族：裸 % 让 --help 炸

    def test_json_envelope_match_exit0(self, tmp_path):
        p1 = _write(tmp_path, "layout.cir", _SPICE_RC)
        p2 = _write(tmp_path, "schematic.cir", _SPICE_RC_RENAMED)
        result = _invoke("lvs", "compare", str(p1), str(p2), "--json")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)  # stdout 纯 JSON 不污染
        assert payload["ok"] is True
        assert payload["verdict"] == "MATCH"
        assert payload["schema"] == LVS_COMPARE_SCHEMA
        assert payload["layout"]["path"] == str(p1)

    def test_json_envelope_mismatch_exit1(self, tmp_path):
        p1 = _write(tmp_path, "layout.cir", _SPICE_RC)
        p2 = _write(tmp_path, "schematic.cir", _SPICE_RC_NO_R2)
        result = _invoke("lvs", "compare", str(p1), str(p2), "--json")
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["verdict"] == "MISMATCH"
        assert payload["summary"]["n_extra"] == 1

    def test_json_envelope_partial_exit1(self, tmp_path):
        p1 = _write(tmp_path, "layout.cir", _SPICE_RC)
        p2 = _write(tmp_path, "schematic.cir", _SPICE_RC_PARAM_OFF)
        result = _invoke("lvs", "compare", str(p1), str(p2), "--json")
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["verdict"] == "PARTIAL"

    def test_cli_tolerance_flag_plumbing(self, tmp_path):
        p1 = _write(tmp_path, "layout.cir", _SPICE_RC)
        p2 = _write(tmp_path, "schematic.cir", _SPICE_RC_PARAM_OFF)
        result = _invoke("lvs", "compare", str(p1), str(p2),
                         "--tolerance", "0.2", "--json")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["verdict"] == "MATCH"
        assert payload["params"]["tolerance"] == 0.2

    def test_cli_rf_flag_plumbing(self, tmp_path):
        p1 = _write(tmp_path, "layout.cir", _SPICE_RC)
        p2 = _write(tmp_path, "schematic.cir", _SPICE_RC_Z0_OFF)
        result = _invoke("lvs", "compare", str(p1), str(p2), "--rf",
                         "--json")
        payload = json.loads(result.output)
        assert result.exit_code == 1
        assert payload["verdict"] == "PARTIAL"
        # --no-rf 三态：显式关闭（#277 typer 陷阱家法）
        result2 = _invoke("lvs", "compare", str(p1), str(p2), "--no-rf",
                          "--json")
        assert result2.exit_code == 0, result2.output
        payload2 = json.loads(result2.output)
        assert payload2["verdict"] == "MATCH"
        assert payload2["rf"] is None

    def test_usage_error_tolerance_non_numeric_exit2(self, tmp_path):
        p1 = _write(tmp_path, "layout.cir", _SPICE_RC)
        result = _invoke("lvs", "compare", str(p1), str(p1),
                         "--tolerance", "abc", "--json")
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["ok"] is False

    def test_usage_error_tolerance_negative_exit2(self, tmp_path):
        p1 = _write(tmp_path, "layout.cir", _SPICE_RC)
        result = _invoke("lvs", "compare", str(p1), str(p1),
                         "--tolerance", "-0.5", "--json")
        assert result.exit_code == 2

    def test_usage_error_format_exit2(self, tmp_path):
        p1 = _write(tmp_path, "layout.cir", _SPICE_RC)
        result = _invoke("lvs", "compare", str(p1), str(p1),
                         "--format", "vhdl", "--json")
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert "vhdl" in payload["errors"][0]

    def test_service_error_missing_file_exit1(self, tmp_path):
        result = _invoke("lvs", "compare", str(tmp_path / "no.cir"),
                         str(tmp_path / "no2.cir"), "--json")
        assert result.exit_code == 1  # service 信封失败 exit 1（≠usage 2）
        payload = json.loads(result.output)
        assert payload["ok"] is False

    def test_human_output_smoke(self, tmp_path):
        p1 = _write(tmp_path, "layout.cir", _SPICE_RC)
        p2 = _write(tmp_path, "schematic.cir", _SPICE_RC_NO_R2)
        result = _invoke("lvs", "compare", str(p1), str(p2))
        assert result.exit_code == 1
        assert "MISMATCH" in result.output
        assert "LVS_FLAG" in result.output  # 拦截语义红字


class TestRegistrationAndCountChain:
    """注册面 + 计数链（#304 家法：新叶必须同笔钉全部消费面）。"""

    def test_lvs_compare_leaf_in_click_tree(self):
        from typer.main import get_command

        cmd = get_command(app)
        lvs_group = cmd.commands.get("lvs")
        assert lvs_group is not None, "lvs 域未注册"
        assert "compare" in lvs_group.commands
        # --json 旗标在位（W2-C 棘轮：新命令必须带 --json）
        compare_params = [p.name
                          for p in lvs_group.commands["compare"].params]
        assert "json_output" in compare_params
        assert "tolerance" in compare_params
        assert "rf" in compare_params
        assert "fmt" in compare_params

    def test_lvs_domain_exactly_one_leaf(self):
        from typer.main import get_command

        cmd = get_command(app)
        assert len(cmd.commands["lvs"].commands) == 1

    def test_no_shadow_with_layout_lvs(self):
        # layout lvs（几何 flag 级）与本域 lvs compare（全图同构）零撞名
        from typer.main import get_command

        cmd = get_command(app)
        assert "lvs" in cmd.commands  # 本席顶层组
        assert "layout" in cmd.commands  # 近名域独立在位
        layout_cmds = cmd.commands["layout"].commands
        assert "lvs" in layout_cmds  # 近名叶语义不同域不同组——零 shadow

    def test_count_chain_cli_live(self):
        """CLI 322（live 口径：本席开工基线 315 + 本席 lvs compare 1 +
        并发席在树增量（drc 2/ibis 2/verilog 侧其他 +2）——#304 家法
        grep 字面钉，字面随并发席合流笔收敛（Q-X33 spice 先例：落树
        时点 live 实测收口，Q-X46 合流笔实收 320→322）；本席稳定断言
        =lvs 域恰 1 叶 + sum 分型互证（不受后续席位数漂移影响）。"""
        assert check_numbers.count_cli() == 358  # aurora_r M-6 终合流 2026-11-10 统一重钉到终值（原 354；锚历史链见 test_cli/test_check_numbers 主锚）
        counts = check_numbers.cli_leaf_counts()
        assert counts["lvs"] == 1
        assert sum(counts.values()) == check_numbers.count_cli()
