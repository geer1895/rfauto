"""Q-X64（aurora_q）：Touchstone 解析内核 + 服务 + CLI 测试。

全离线零网络零真机、tmp_path 隔离零 run 湖写入（#144）：夹具内嵌小文本
（v1.0 2 端口 RI/MA + 1 端口 DB 错命名 .s2p 构造 #248 场景 + 4×4 模态
.s2p 命名构造 #309 场景 + 频率 ulp 噪声对构造 #287 场景 + v2.0 关键字
块/continuation/noise 段）。覆盖：嗅探逐规则、rank 三规则序与冲突
disagreement、三格式解码表驱动已知量、单位换算表、align_freq_axis 三态、
mode_data_shape 判定、skrf 桥往返、无源性统计、信封契约、CLI 计数链。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.cli.domains.touchstone import touchstone_app
from rfauto.core.touchstone_parser import (
    TouchstoneParseError,
    align_freq_axis,
    detect_mode_data_shape,
    matrix_health,
    parse_touchstone,
    sniff_touchstone,
    to_skrf_network,
)
from rfauto.service import touchstone_service
from rfauto.service.touchstone_service import (
    parse_touchstone_file,
    touchstone_info,
    touchstone_report,
)

runner = CliRunner()

# ── 夹具（内嵌小文本，写 tmp_path——零 run 湖写入，#144） ────────────────────

V1_2P_RI = """# GHZ S RI R 50
1.0 1 0 0 0 0.5 0.5 0.2 -0.1
2.0 0.8 0.1 -0.1 0.1 0.4 0.4 0.1 0.1
3.0 0.6 -0.2 0.2 0.1 0.3 0.3 0.05 0.05
"""

V1_2P_MA = """# MHz S MA R 50
100.0 0.7 45 0.6 -30 0.6 30 0.5 0
200.0 0.5 90 0.4 -60 0.4 60 0.3 10
"""

V1_1P_DB = """# MHz S DB R 50
100.0 -20.0 45.0
200.0 -40.0 -90.0
"""

V1_3P_MA = """# GHZ S MA R 50
1.0 1 0 0.5 90 0.5 -90
  0.4 45 0.3 0 0.2 10
  0.1 0 0.2 -10 0.3 0
"""

V1_4P_MA = """# GHZ S MA R 50
1.0 1 0 0.5 90 0.5 -90 0 0
  0 0 1 0 0.5 90 0.5 -90
  0 0 0.5 -90 1 0 0.5 90
  0 0 0.5 -90 0.5 90 1 0
2.0 0.9 10 0.4 80 0.4 -80 0 0
  0 0 0.9 10 0.4 80 0.4 -80
  0 0 0.4 -80 0.9 10 0.4 80
  0 0 0.4 -80 0.4 80 0.9 10
"""

V1_5P_MA = """# GHZ S MA R 50
1.0 1 0 0.5 90 0.4 45 0.3 0
  0.2 90
  0.3 0 0.4 10 0.2 20 0.1 30
  0.1 40
  0.2 0 0.3 10 0.4 20 0.1 30
  0.2 40
  0.1 0 0.2 10 0.3 20 0.4 30
  0.3 40
  0.4 0 0.1 10 0.2 20 0.3 30
  0.4 40
"""

V2_2P_CONT = """[Version] 2.0
# GHZ S RI R 50
[Number of Ports] 2
[Two-Port Data Order] rows_12_21
[Number of Frequencies] 2
[Reference] 50 50
[Matrix Format] Full
[Network Data]
1.0 1 0 0.2 0.1
  0.2 -0.1 0.5 0
2.0 0.8 0 0.1 0.1 0.1 -0.1 0.4 0
[End]
"""

V2_2P_LEGACY = V2_2P_CONT.replace("rows_12_21", "rows_21_12")

V2_4P = """[Version] 2.0
# GHZ S RI R 50
[Number of Ports] 4
[Number of Frequencies] 1
[Reference] 25 75 25 75
[Matrix Format] Full
[Network Data]
""" + " ".join(str(v) for v in [1.0, 1, 0, 0.5, 0, 0, 0, 0, 0,
                                0.5, 0, 1, 0, 0, 0, 0, 0,
                                0, 0, 0, 1, 0, 0, 0, 0,
                                0, 0, 0, 0, 1, 0, 0, 0]) + "\n"

V2_NOISE = V2_2P_CONT.replace(
    "[End]",
    "[Number of Noise Frequencies] 1\n[Noise Data]\n3.0 1.5 0.1 20.0 0.8\n[End]")

V2_UPPER = V2_2P_CONT.replace("[Matrix Format] Full", "[Matrix Format] Upper")

V2_CONFLICT_23 = """[Version] 2.0
# GHZ S RI R 50
[Number of Frequencies] 3
[Network Data]
1 1 0 0.5 0 0.5 0 0.5 0
2 1 0
3 0 1
"""

V2_CONFLICT_DECLARED = """[Version] 2.0
# GHZ S RI R 50
[Number of Ports] 4
[Number of Frequencies] 2
[Network Data]
1 1 0 0 0 0.5 0 0.5 0
2 1 0 0 0 0.4 0 0.4 0
"""

V1_NOISE_TAIL = V1_2P_RI + "4.0 1.5 0.2 45.0 0.8\n"

V1_BAD_ROW = """# GHZ S RI R 50
1.0 1 0 0 0 0.5 0.5
2.0 0.8 0.1 -0.1 0.1 0.4 0.4 0.1 0.1
"""

NO_OPTION_LINE = "! 只有注释\n1.0 1 0\n"

def _write(tmp_path: Path, text: str, name: str = "device.s2p") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p

# ── 嗅探（option line/版本/关键字块） ────────────────────────────────────────

class TestSniff:
    def test_option_line_quadruple(self, tmp_path: Path) -> None:
        s = sniff_touchstone(_write(tmp_path, V1_2P_RI))
        assert (s["freq_unit"], s["param_type"], s["data_format"],
                s["r_ref"]) == ("GHZ", "S", "RI", 50.0)
        assert s["option_line_raw"].startswith("# GHZ S RI R 50")
        assert s["version"] == "1.0" and s["version_source"] == "default"

    def test_unit_table_all_five(self, tmp_path: Path) -> None:
        # 表驱动单位换算：同一频率数值在不同单位下 → Hz 值 = 数值×倍率
        for unit, mult in (("HZ", 1.0), ("KHZ", 1e3), ("MHZ", 1e6),
                           ("GHZ", 1e9), ("THZ", 1e12)):
            text = f"# {unit} S RI R 50\n2.0 1 0\n"
            parsed = parse_touchstone(_write(tmp_path, text, f"u_{unit}.s1p"))
            assert parsed["freqs_hz"] == [2.0 * mult], unit

    def test_unit_lowercase_option_line(self, tmp_path: Path) -> None:
        s = sniff_touchstone(_write(tmp_path, "# ghz s ri r 50\n1 0 0\n"))
        assert (s["freq_unit"], s["data_format"]) == ("GHZ", "RI")

    def test_unit_missing_warns_default_ghz(self, tmp_path: Path) -> None:
        s = sniff_touchstone(_write(tmp_path, "# S RI R 50\n1 0 0\n"))
        assert s["freq_unit"] == "GHZ"
        assert any("非频率单位" in w for w in s["warnings"])

    def test_noise_flag_trailing_n(self, tmp_path: Path) -> None:
        s = sniff_touchstone(_write(tmp_path, "# GHZ S MA R 50 N\n1 1 0\n"))
        assert s["noise_flag"] is True

    def test_mixed_mode_il_rl_flag(self, tmp_path: Path) -> None:
        s = sniff_touchstone(_write(tmp_path, "# GHZ S IL RL R 50\n1 0 0\n"))
        assert s["mixed_mode"] is True
        assert s["param_type"] == "S"

    def test_version_keyword_2_0(self, tmp_path: Path) -> None:
        s = sniff_touchstone(_write(tmp_path, V2_2P_CONT))
        assert s["version"] == "2.0" and s["version_source"] == "keyword"
        v2 = s["v2"]
        assert v2["declared_n_ports"] == 2
        assert v2["declared_n_freqs"] == 2
        assert v2["two_port_order"] == "rows_12_21"
        assert v2["matrix_format"] == "full"
        assert v2["reference_tokens"] == ["50", "50"]
        assert v2["network_data_marker"] is True

    def test_version_structure_inference(self, tmp_path: Path) -> None:
        text = V2_2P_CONT.replace("[Version] 2.0\n", "")
        s = sniff_touchstone(_write(tmp_path, text))
        assert s["version"] == "2.0" and s["version_source"] == "structure"
        assert any("结构推断" in w for w in s["warnings"])

    def test_v2_unrecognized_keyword_honest(self, tmp_path: Path) -> None:
        text = V2_2P_CONT.replace(
            "[Network Data]",
            "[Future Keyword] 7\n[Network Data]")
        s = sniff_touchstone(_write(tmp_path, text))
        assert any("未识别 v2.0 关键字" in w for w in s["warnings"])
        assert "future keyword" in s["v2"]["other_keywords"]

    def test_public_sniff_json_safe(self, tmp_path: Path) -> None:
        s = sniff_touchstone(_write(tmp_path, V1_2P_RI))
        assert not any(k.startswith("_") for k in s)
        json.dumps({k: v for k, v in s.items() if k != "warnings"},
                   default=str, ensure_ascii=False)

    def test_missing_option_line_raises(self, tmp_path: Path) -> None:
        with pytest.raises(TouchstoneParseError, match="option line"):
            sniff_touchstone(_write(tmp_path, NO_OPTION_LINE))

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(TouchstoneParseError, match="为空"):
            sniff_touchstone(_write(tmp_path, "   \n  \n"))

    def test_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(TouchstoneParseError, match="不存在"):
            sniff_touchstone(tmp_path / "ghost.s2p")

# ── rank 三规则（①文件名 ②首行值数 ③块结构 + 共识/冲突） ────────────────────

class TestRankRules:
    def test_rule1_filename_trusted(self, tmp_path: Path) -> None:
        rank = sniff_touchstone(_write(tmp_path, V1_2P_RI))["rank"]
        assert rank["rule_filename"] == 2 and rank["rule_filename_trusted"] is True

    def test_rule1_filename_over9_untrusted(self, tmp_path: Path) -> None:
        # 12 端口 v2 形态（每频率一行 2n²+1=289 token）：文件名 N=12>9 不可信
        # 不进共识；内容规则②③独立成立 → n_ports 仍可解
        p = tmp_path / "big.s12p"
        p.write_text("[Version] 2.0\n# GHZ S RI R 50\n[Number of Ports] 12\n"
                     "[Number of Frequencies] 1\n[Network Data]\n"
                     "1.0 " + " ".join(["0", "0"] * 144) + "\n")
        rank = sniff_touchstone(p)["rank"]
        assert rank["rule_filename"] == 12
        assert rank["rule_filename_trusted"] is False
        assert rank["n_ports"] == 12  # 内容共识（v2 ②③）独立成立
        assert rank["rule_filename_note"] is not None

    def test_rule2_v1_first_line_9_ambiguous_set(self, tmp_path: Path) -> None:
        rank = sniff_touchstone(_write(tmp_path, V1_4P_MA))["rank"]
        cands = rank["rule_first_line"]["candidates"]
        assert rank["rule_first_line"]["value_count"] == 9
        assert 2 in cands and 4 in cands and 64 in cands  # 单规则不完备

    def test_rule2_v1_first_line_7_resolves_3(self, tmp_path: Path) -> None:
        rank = sniff_touchstone(_write(tmp_path, V1_3P_MA))["rank"]
        assert rank["rule_first_line"]["candidates"] == [3]

    def test_rule2_v2_direct_solve(self, tmp_path: Path) -> None:
        rank = sniff_touchstone(_write(tmp_path, V2_4P))["rank"]
        assert rank["rule_first_line"]["candidates"] == [4]

    def test_rule2_v2_continuation_split_honest(self, tmp_path: Path) -> None:
        # 首物理行被 continuation 截断 → 规则②缺证据（note 如实），③兜底
        rank = sniff_touchstone(_write(tmp_path, V2_2P_CONT))["rank"]
        assert rank["rule_first_line"]["candidates"] is None
        assert rank["rule_first_line"]["note"]
        assert rank["n_ports"] == 2 and rank["resolution"] == "content_consensus"

    def test_rule3_v1_block_2port_single_line(self, tmp_path: Path) -> None:
        rank = sniff_touchstone(_write(tmp_path, V1_2P_RI))["rank"]
        assert (rank["rule_block"]["block"],
                rank["rule_block"]["candidates"]) == (1, [2])

    def test_rule3_v1_block_4port_block4(self, tmp_path: Path) -> None:
        rank = sniff_touchstone(_write(tmp_path, V1_4P_MA))["rank"]
        assert (rank["rule_block"]["block"],
                rank["rule_block"]["candidates"]) == (4, [4])

    def test_rule3_v1_block_5port_block10_disambiguates(self, tmp_path: Path) -> None:
        # 5 端口首行同样 9 值——块行数 n·ceil(n/4)=10 与 2 端口（块 1）消歧
        rank = sniff_touchstone(_write(tmp_path, V1_5P_MA))["rank"]
        assert (rank["rule_block"]["block"],
                rank["rule_block"]["candidates"]) == (10, [5])
        assert rank["n_ports"] == 5

    def test_rule3_v2_token_stream(self, tmp_path: Path) -> None:
        rank = sniff_touchstone(_write(tmp_path, V2_4P))["rank"]
        assert rank["rule_block"]["candidates"] == [4]

    def test_consensus_conflict_honest_unknown(self, tmp_path: Path) -> None:
        # v2 规则②（首行 9 → [2]）与规则③（T=15/组 5 → [1]）无交集 →
        # 冲突如实 UNKNOWN，不猜
        p = _write(tmp_path, V2_CONFLICT_23)
        rank = sniff_touchstone(p)["rank"]
        assert rank["n_ports"] is None and rank["resolution"] == "conflict"
        assert any("无交集" in d for d in rank["disagreements"])
        parsed = parse_touchstone(p)
        assert parsed["n_ports"] is None and parsed["s_matrix"] is None

    def test_filename_conflict_content_wins_248(self, tmp_path: Path) -> None:
        # #248 场景：1 端口数据错命名 .s2p——内容为准 + disagreement 登记
        p = _write(tmp_path, V1_1P_DB, "misnamed.s2p")
        rank = sniff_touchstone(p)["rank"]
        assert rank["n_ports"] == 1
        assert rank["resolution"] == "content_consensus_filename_conflict"
        assert any("#248" in d for d in rank["disagreements"])

    def test_declared_keyword_conflict_content_wins(self, tmp_path: Path) -> None:
        # v2 [Number of Ports]=4 与内容推断 2 冲突——声明可错，数据不会
        rank = sniff_touchstone(_write(tmp_path, V2_CONFLICT_DECLARED))["rank"]
        assert rank["n_ports"] is None and rank["resolution"] == "conflict"
        assert any("[Number of Ports]=4" in d for d in rank["disagreements"])

    def test_declared_keyword_used_when_content_unresolvable(
            self, tmp_path: Path) -> None:
        # 内容规则全缺证据 → 退 declared 关键字采信（显式 resolution 态）
        p = _write(tmp_path, "[Version] 2.0\n# GHZ S RI R 50\n"
                   "[Number of Ports] 3\n[Network Data]\n", "declared.s3p")
        rank = sniff_touchstone(p)["rank"]
        assert rank["n_ports"] == 3
        assert rank["resolution"] == "declared_keyword_only"

# ── 三格式解码（表驱动已知量钉） ─────────────────────────────────────────────

class TestDecode:
    def test_ri_pair_exact(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V1_2P_RI))
        s = parsed["s_matrix"]
        assert s[0][0][0] == complex(1.0, 0.0)
        assert s[0][0][1] == complex(0.5, 0.5)      # S12（行主序 [0][1]）
        assert s[0][1][0] == complex(0.0, 0.0)      # S21（legacy 列序第 2 位）
        assert s[0][1][1] == complex(0.2, -0.1)

    def test_ma_known_values(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V1_2P_MA))
        s = parsed["s_matrix"]
        # 0.7∠45° → (0.7·cos45, 0.7·sin45)
        assert s[0][0][0] == pytest.approx(
            complex(0.7 * np.cos(np.pi / 4), 0.7 * np.sin(np.pi / 4)))
        assert s[1][1][1] == pytest.approx(
            complex(0.3 * np.cos(np.pi / 18), 0.3 * np.sin(np.pi / 18)))

    def test_db_minus20db_is_01_magnitude(self, tmp_path: Path) -> None:
        # 表驱动已知量：−20 dB → |S| = 10^(−20/20) = 0.1；∠45°
        parsed = parse_touchstone(_write(tmp_path, V1_1P_DB, "one.s1p"))
        s11 = parsed["s_matrix"][0][0][0]
        assert abs(s11) == pytest.approx(0.1)
        assert s11 == pytest.approx(
            complex(0.1 * np.cos(np.pi / 4), 0.1 * np.sin(np.pi / 4)))

    def test_db_minus40db_phase_minus90(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V1_1P_DB, "one.s1p"))
        s11 = parsed["s_matrix"][1][0][0]
        assert abs(s11) == pytest.approx(0.01)
        assert s11 == pytest.approx(complex(0.0, -0.01))

    def test_v1_2port_legacy_column_order_s11_s21_s12_s22(
            self, tmp_path: Path) -> None:
        # v1.0 2 端口单行 9 值列序 [S11, S21, S12, S22]——flat 第 2 对落
        # M[1,0]、第 3 对落 M[0,1]（与 skrf legacy 转置同口径）
        parsed = parse_touchstone(_write(tmp_path, V1_2P_RI))
        s = parsed["s_matrix"]
        assert s[1][0][0] == complex(0.8, 0.1)   # S11
        assert s[1][1][0] == complex(-0.1, 0.1)  # S21（flat 第 2 对）
        assert s[1][0][1] == complex(0.4, 0.4)   # S12（flat 第 3 对）

    def test_v1_3port_row_major(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V1_3P_MA, "tri.s3p"))
        s = parsed["s_matrix"]
        # 行主序：flat 序 [S11,S12,S13, S21,S22,S23, S31,S32,S33]
        assert s[0][0][0] == pytest.approx(complex(1.0, 0.0))
        assert s[0][0][1] == pytest.approx(0.5 * np.exp(1j * np.pi / 2))
        assert s[0][1][0] == pytest.approx(0.4 * np.exp(1j * np.pi / 4))

    def test_v1_4port_block_structure(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V1_4P_MA, "quad.s4p"))
        assert parsed["n_freqs"] == 2
        assert parsed["freqs_hz"] == [1e9, 2e9]
        assert parsed["s_matrix"].shape == (2, 4, 4)
        assert parsed["s_matrix"][1][1][1] == pytest.approx(
            0.9 * np.exp(1j * np.radians(10.0)))

    def test_v1_5port_two_line_row_groups(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V1_5P_MA, "penta.s5p"))
        assert parsed["n_ports"] == 5 and parsed["n_freqs"] == 1
        assert parsed["s_matrix"].shape == (1, 5, 5)
        assert parsed["s_matrix"][0][4][4] == pytest.approx(
            0.4 * np.exp(1j * np.radians(40.0)))  # S55 = 0.4∠40°

    def test_v2_rows_12_21_row_major(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V2_2P_CONT, "v2a.s2p"))
        s = parsed["s_matrix"]
        assert s[0][0][1] == complex(0.2, 0.1)   # S12（rows_12_21 第 2 对）
        assert s[0][1][0] == complex(0.2, -0.1)  # S21（第 3 对）

    def test_v2_rows_21_12_legacy_order(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V2_2P_LEGACY, "v2b.s2p"))
        s = parsed["s_matrix"]
        assert s[0][1][0] == complex(0.2, 0.1)   # S21 在 flat 第 2 位
        assert s[0][0][1] == complex(0.2, -0.1)

    def test_v2_continuation_accumulation(self, tmp_path: Path) -> None:
        # 首频率 9 token 跨两物理行——token 累积分组解码逐值正确
        parsed = parse_touchstone(_write(tmp_path, V2_2P_CONT, "v2c.s2p"))
        assert parsed["freqs_hz"] == [1e9, 2e9]
        assert parsed["s_matrix"][0][1][1] == complex(0.5, 0.0)

    def test_v2_4port_reference_per_port(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V2_4P, "v2d.s4p"))
        assert parsed["port_z"] == [25.0, 75.0, 25.0, 75.0]
        assert parsed["s_matrix"][0][1][0] == complex(0.5, 0.0)

    def test_structural_violation_fails_loud(self, tmp_path: Path) -> None:
        # v1 结构违规（2 端口应 9 值行实 7 值）：块结构不一致 → rank 宁
        # UNKNOWN（v1 ② 单规则不完备不可单独采信）→ 数据不解析不误判
        parsed = parse_touchstone(_write(tmp_path, V1_BAD_ROW, "bad.s2p"))
        assert parsed["n_ports"] is None
        assert parsed["s_matrix"] is None
        assert any("块结构" in w for w in parsed["warnings"])

    def test_structural_violation_fail_loud_when_rank_resolved(
            self, tmp_path: Path) -> None:
        # v2 rank 可解（② 2n²+1 直接解单独采信）+ token 总量不足声明组数
        # → 解码面 fail-loud（声明是结构契约，静默吞会错位）
        text = ("[Version] 2.0\n# GHZ S RI R 50\n[Number of Ports] 2\n"
                "[Number of Frequencies] 2\n[Network Data]\n"
                "1 1 0 0 0 0.5 0 0.5 0\n2 1 0 0 0 0.4 0\n")
        with pytest.raises(TouchstoneParseError, match="token"):
            parse_touchstone(_write(tmp_path, text, "short.s2p"))

    def test_v1_block_rows_not_multiple_fails(self, tmp_path: Path) -> None:
        text = V1_4P_MA.rsplit("\n", 2)[0] + "\n"  # 截去末块一行 → 行数 7
        with pytest.raises(TouchstoneParseError, match="整数倍"):
            parse_touchstone(_write(tmp_path, text, "trunc.s4p"))

# ── port_z / noise 段 ────────────────────────────────────────────────────────

class TestPortZAndNoise:
    def test_port_z_broadcast_r_ref(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V1_3P_MA, "tri.s3p"))
        assert parsed["port_z"] == [50.0, 50.0, 50.0]

    def test_v2_reference_single_value_broadcast(self, tmp_path: Path) -> None:
        text = V2_2P_CONT.replace("[Reference] 50 50", "[Reference] 75")
        parsed = parse_touchstone(_write(tmp_path, text, "v2r.s2p"))
        assert parsed["port_z"] == [75.0, 75.0]

    def test_v2_reference_count_mismatch_warns(self, tmp_path: Path) -> None:
        text = V2_2P_CONT.replace("[Reference] 50 50",
                                  "[Reference] 50 75 25")
        parsed = parse_touchstone(_write(tmp_path, text, "v2x.s2p"))
        assert parsed["port_z"] == [50.0, 50.0]  # 回落 r_ref 广播
        assert any("[Reference]" in w for w in parsed["warnings"])

    def test_v1_trailing_noise_registered(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V1_NOISE_TAIL))
        assert parsed["noise"]["present"] is True
        assert parsed["noise"]["n_points"] == 1
        assert parsed["noise"]["rows"] == [[4.0, 1.5, 0.2, 45.0, 0.8]]
        assert parsed["n_freqs"] == 3  # 矩阵数据不受 noise 段污染

    def test_v2_noise_marker_section(self, tmp_path: Path) -> None:
        parsed = parse_touchstone(_write(tmp_path, V2_NOISE, "v2n.s2p"))
        assert parsed["noise"]["present"] is True
        assert parsed["noise"]["n_points"] == 1
        assert parsed["noise"]["rows"] == [[3.0, 1.5, 0.1, 20.0, 0.8]]

    def test_noise_nonnumeric_token_nan_honest(self, tmp_path: Path) -> None:
        # noise 行含非数值 token → NaN 如实登记 + 警告（零静默丢弃）
        text = V1_2P_RI + "4.0 1.5 xx 45.0 0.8\n"
        parsed = parse_touchstone(_write(tmp_path, text))
        assert parsed["noise"]["present"] is True
        assert parsed["noise"]["rows"][0][2] != parsed["noise"]["rows"][0][2]  # NaN
        assert any("NaN" in w for w in parsed["warnings"])

    def test_v2_noise_declared_count_mismatch_noted(self, tmp_path: Path) -> None:
        text = V2_2P_CONT.replace(
            "[End]",
            "[Number of Noise Frequencies] 2\n[Noise Data]\n"
            "3.0 1.5 0.1 20.0 0.8\n[End]")
        parsed = parse_touchstone(_write(tmp_path, text, "v2m.s2p"))
        assert parsed["noise"]["present"] is True
        assert any("不一致" in w for w in parsed["warnings"])

# ── align_freq_axis（#287/#294 单源化三态） ─────────────────────────────────

class TestAlignFreqAxis:
    def test_same_grid_identity(self) -> None:
        res = align_freq_axis([1e9, 2e9, 3e9], [1e9, 2e9, 3e9])
        assert res["mode"] == "same_grid"
        assert res["indices_b"] == [0, 1, 2]
        assert res["n_matched"] == 3

    def test_ulp_noise_same_grid_287(self) -> None:
        # #287 场景：dB 写出/读回频率带 ~1e-7 Hz 浮点噪声 → 同栅直判
        a = [1e9, 2e9, 3e9]
        b = [1e9 + 1.3e-7, 2e9 - 0.9e-7, 3e9 + 2.1e-7]
        res = align_freq_axis(a, b, rtol=1e-9)
        assert res["mode"] == "same_grid"

    def test_nearest_interior_mapping(self) -> None:
        res = align_freq_axis([2e9, 3e9], [1e9 + 1.0, 2e9 + 2.0, 3e9 + 3.0],
                              rtol=1e-6)
        assert res["mode"] == "nearest"
        assert res["indices_b"] == [1, 2]

    def test_endpoint_ulp_within_tol_nearest(self) -> None:
        # 端点 ulp 容差（异栅路径）：a 端点略超 b 端点（1e-7 Hz@3e9）→
        # 最近邻匹配在 rtol 容差内（长度不等 → 非同栅路径）
        res = align_freq_axis([2e9, 3e9 + 1e-7], [1e9, 2e9, 3e9])
        assert res["mode"] == "nearest"
        assert res["indices_b"] == [1, 2]

    def test_out_of_band_dropped_when_extrap_false(self) -> None:
        res = align_freq_axis([1e9, 3.5e9], [1e9, 2e9, 3e9],
                              allow_endpoint_extrap=False)
        assert res["n_matched"] == 1
        assert res["unmatched_a"][0]["f"] == 3.5e9
        assert res["unmatched_a"][0]["kept_by"] is None
        assert res["unmatched_b"] == [2e9, 3e9]  # 未配对 b 点如实回显

    def test_out_of_band_kept_by_extrap_when_true(self) -> None:
        res = align_freq_axis([1e9, 3.5e9], [1e9, 2e9, 3e9],
                              allow_endpoint_extrap=True)
        assert res["n_matched"] == 2
        assert res["unmatched_a"][0]["kept_by"] == "endpoint_extrap"
        assert res["b_aligned"][-1] == 3e9

    def test_rtol_zero_strict(self) -> None:
        res = align_freq_axis([1e9], [1e9 + 1e-7], rtol=0.0,
                              allow_endpoint_extrap=False)
        assert res["n_matched"] == 0 and res["unmatched_a"]

    def test_empty_input_raises(self) -> None:
        with pytest.raises(TouchstoneParseError, match="为空"):
            align_freq_axis([], [1e9])
        with pytest.raises(TouchstoneParseError):
            align_freq_axis([1e9], [])

    def test_length_mismatch_nearest_extrap_false(self) -> None:
        res = align_freq_axis([1e9, 2e9], [1e9], allow_endpoint_extrap=False)
        assert res["mode"] == "nearest" and res["n_matched"] == 1

# ── Σ模数形状判定（#309/#248） ──────────────────────────────────────────────

class TestModeDataShape:
    def test_consistent(self, tmp_path: Path) -> None:
        res = detect_mode_data_shape(_write(tmp_path, V1_2P_RI), 2)
        assert res["verdict"] == "consistent"
        assert res["content_n"] == 2 and res["filename_n"] == 2

    def test_exceeds_suggests_s4p_309(self, tmp_path: Path) -> None:
        # #309 场景：4×4 模态数据按端口边界数命名 .s2p
        res = detect_mode_data_shape(_write(tmp_path, V1_4P_MA, "modal.s2p"), 2)
        assert res["verdict"] == "data_exceeds_filename"
        assert res["suggested_filename"] == ".s4p"
        assert any("#309" in w for w in res["warnings"])

    def test_below_suggests_s1p_248(self, tmp_path: Path) -> None:
        res = detect_mode_data_shape(
            _write(tmp_path, V1_1P_DB, "one.s2p"), 1)
        assert res["verdict"] == "data_below_filename"
        assert res["suggested_filename"] == ".s1p"
        assert any("#248" in w for w in res["warnings"])

    def test_declared_mode_mismatch_registered(self, tmp_path: Path) -> None:
        res = detect_mode_data_shape(_write(tmp_path, V1_4P_MA, "m.s4p"), 2)
        assert any("Σ模数口径" in d for d in res["disagreements"])

    def test_unknown_when_rank_unresolved(self, tmp_path: Path) -> None:
        res = detect_mode_data_shape(_write(tmp_path, V2_CONFLICT_23), 2)
        assert res["verdict"] == "unknown_data_shape"

    def test_filename_untrusted_verdict(self, tmp_path: Path) -> None:
        p = tmp_path / "big.s10p"
        p.write_text("[Version] 2.0\n# GHZ S RI R 50\n[Number of Ports] 2\n"
                     "[Number of Frequencies] 1\n[Network Data]\n"
                     "1.0 1 0 0 0 0 0 0 0\n")
        res = detect_mode_data_shape(p, 2)
        assert res["verdict"] == "filename_untrusted"
        assert res["filename_trusted"] is False

# ── 矩阵健康统计（无源性如实统计不做硬门） ──────────────────────────────────

class TestMatrixHealth:
    def test_identity_passive(self) -> None:
        s = np.array([[np.eye(2), np.eye(2) * 0.5]]).reshape(2, 2, 2)
        h = matrix_health(s)
        assert h["available"] is True
        assert h["max_eig_max"] == pytest.approx(1.0)
        assert h["n_passive_freqs"] == 2 and h["passive_ratio"] == 1.0

    def test_amplifier_non_passive_counted(self) -> None:
        s = np.zeros((2, 2, 2), dtype=complex)
        s[:, 1, 1] = 2.0  # 对角 |S22|=2 → 非无源（下三角 nilpotent 矩阵
        # 特征值恒 0，钉健康统计须用非三角结构）
        h = matrix_health(s)
        assert h["max_eig_max"] == pytest.approx(2.0)
        assert h["n_passive_freqs"] == 0

    def test_none_unavailable(self) -> None:
        h = matrix_health(None)
        assert h["available"] is False and h["note"]

    def test_bad_shape_unavailable(self) -> None:
        h = matrix_health(np.zeros((3, 2), dtype=complex))
        assert h["available"] is False

    def test_eps_threshold_custom(self) -> None:
        s = np.zeros((1, 2, 2), dtype=complex)
        s[0, 0, 0] = 1.0005
        assert matrix_health(s, eps=1e-3)["n_passive_freqs"] == 1
        assert matrix_health(s, eps=1e-4)["n_passive_freqs"] == 0

# ── skrf 桥往返 ─────────────────────────────────────────────────────────────

class TestSkrfBridge:
    def test_roundtrip_v1_2port_parity(self, tmp_path: Path) -> None:
        # 与 skrf.Network 直读同文件逐位对照（列序/解码/单位换算全链）
        import skrf
        p = _write(tmp_path, V1_2P_MA)
        net_mine = to_skrf_network(parse_touchstone(p))
        net_skrf = skrf.Network(str(p))
        assert np.allclose(net_mine.s, net_skrf.s)
        assert np.allclose(net_mine.f, net_skrf.f)

    def test_roundtrip_v1_3port_parity(self, tmp_path: Path) -> None:
        import skrf
        p = _write(tmp_path, V1_3P_MA, "tri.s3p")
        assert np.allclose(
            to_skrf_network(parse_touchstone(p)).s, skrf.Network(str(p)).s)

    def test_roundtrip_v2_rows_12_21_parity(self, tmp_path: Path) -> None:
        import skrf
        p = _write(tmp_path, V2_2P_CONT, "v2p.s2p")
        assert np.allclose(
            to_skrf_network(parse_touchstone(p)).s, skrf.Network(str(p)).s)

    def test_bridge_z0_per_port(self, tmp_path: Path) -> None:
        net = to_skrf_network(parse_touchstone(
            _write(tmp_path, V2_4P, "v2z.s4p")))
        z0 = np.asarray(net.z0)
        assert z0.shape[-1] == 4
        assert set(z0[0].tolist()) == {25.0, 75.0}

    def test_bridge_fails_loud_when_matrix_none(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="s_matrix"):
            to_skrf_network({"s_matrix": None, "freqs_hz": [1e9]})

    def test_bridge_fail_import_transparent(self, tmp_path: Path) -> None:
        # skrf 在仓内环境恒可用；本钉只验证桥面直通构建成功（fail-loud
        # 语义=ImportError 不被吞，环境缺 skrf 时自然透传）
        net = to_skrf_network(parse_touchstone(_write(tmp_path, V1_2P_RI)))
        assert net.nports == 2 and net.frequency.npoints == 3

# ── 服务信封（AU-2 构造器契约） ─────────────────────────────────────────────

class TestServiceEnvelopes:
    def test_info_ok_envelope_shape(self, tmp_path: Path) -> None:
        res = touchstone_info(_write(tmp_path, V1_2P_RI))
        assert res["ok"] is True
        for key in ("path", "format", "rank", "n_ports", "n_freqs",
                    "freqs_hz", "band"):
            assert key in res
        assert res["band"]["f_min_hz"] == 1e9 and res["band"]["f_max_hz"] == 3e9
        json.dumps(res, default=str, ensure_ascii=False)  # 信封 JSON 安全

    def test_info_error_missing_file(self, tmp_path: Path) -> None:
        res = touchstone_info(tmp_path / "no.s2p")
        assert res["ok"] is False
        assert isinstance(res["errors"], list) and res["errors"]

    def test_info_conflict_ok_carries_evidence(self, tmp_path: Path) -> None:
        # info 是查询面：rank 冲突=查询答案——ok=True 带全量证据+disagreements
        res = touchstone_info(_write(tmp_path, V2_CONFLICT_23))
        assert res["ok"] is True
        assert res["n_ports"] is None
        assert res["disagreements"]
        assert res["band"]["f_min_hz"] is None  # 冲突态无频段（不可解析）

    def test_info_structural_violation_honest_unknown(
            self, tmp_path: Path) -> None:
        # 结构违规文件：rank ③ 否决 + v1 ② 不可单独采信 → 宁 UNKNOWN；
        # info 查询面 ok=True 带全量证据（③ note 如实）
        res = touchstone_info(_write(tmp_path, V1_BAD_ROW, "bad.s2p"))
        assert res["ok"] is True
        assert res["n_ports"] is None
        assert res["rank"]["rule_block"]["note"] is not None
        assert "不一致" in res["rank"]["rule_block"]["note"]

    def test_parse_file_ok_full_shape(self, tmp_path: Path) -> None:
        res = parse_touchstone_file(_write(tmp_path, V1_2P_RI))
        assert res["ok"] is True
        assert res["n_ports"] == 2 and res["n_freqs"] == 3
        assert res["port_z"] == [50.0, 50.0]
        assert res["s_matrix"][0][0][0] == [1.0, 0.0]  # [re, im] 对
        assert res["s_matrix_truncated"] is False
        assert res["health"]["available"] is True
        assert res["noise"]["present"] is False

    def test_parse_file_error_no_option_line(self, tmp_path: Path) -> None:
        res = parse_touchstone_file(_write(tmp_path, NO_OPTION_LINE))
        assert res["ok"] is False
        assert any("option line" in e for e in res["errors"])

    def test_parse_file_error_rank_conflict(self, tmp_path: Path) -> None:
        res = parse_touchstone_file(_write(tmp_path, V2_CONFLICT_23))
        assert res["ok"] is False
        assert any("UNKNOWN" in e for e in res["errors"])
        assert "s_matrix" not in res

    def test_parse_file_s_matrix_cap_truncation(self, tmp_path: Path) -> None:
        # 4 端口 × 257 频点 = 4112 复杂值 > cap 4096 → 截断态如实
        # （v1.0 4 端口每频率 4 行块：首行 9 值 + 3 行 8 值）
        lines: list[str] = ["# GHZ S MA R 50"]
        for k in range(257):
            f = f"{1.0 + k * 0.001:.6f}"
            lines.append(f"{f} 1 0 " + " ".join(["0", "0"] * 3))
            for _ in range(3):
                lines.append(" ".join(["0", "0"] * 4))
        res = parse_touchstone_file(
            _write(tmp_path, "\n".join(lines) + "\n", "big.s4p"))
        assert res["ok"] is True
        assert res["s_matrix_truncated"] is True
        assert res["s_matrix"] is None
        assert len(res["s_matrix_preview"]) == 4
        assert res["n_freqs"] == 257

    def test_report_ok_summary_shape(self, tmp_path: Path) -> None:
        res = touchstone_report(_write(tmp_path, V1_2P_RI))
        assert res["ok"] is True
        assert res["n_ports"] == 2 and res["n_freqs"] == 3
        assert res["health"]["passive_ratio"] == 1.0
        assert res["freq_step"]["n_steps"] == 2
        assert res["band"]["f_min_hz"] == 1e9
        assert res["n_warnings"] == 0

    def test_report_error_conflict(self, tmp_path: Path) -> None:
        res = touchstone_report(_write(tmp_path, V2_CONFLICT_23))
        assert res["ok"] is False and res["errors"]

    def test_report_noise_summary_registered(self, tmp_path: Path) -> None:
        res = touchstone_report(_write(tmp_path, V1_NOISE_TAIL))
        assert res["ok"] is True
        assert res["noise"]["present"] is True and res["noise"]["n_points"] == 1

    def test_module_no_all_no_public_api_drift(self) -> None:
        # 本模块/内核不设 __all__（零金快照漂移——sdf 先例；docstring 提及
        # ``__all__`` 不算赋值，钉 "＝" 赋值形态不存在）
        import inspect
        src_core = inspect.getsource(
            sys.modules["rfauto.core.touchstone_parser"])
        src_svc = inspect.getsource(
            sys.modules["rfauto.service.touchstone_service"])
        assert "__all__ =" not in src_core
        assert "__all__ =" not in src_svc

# ── CLI（touchstone info --file [--json]） ──────────────────────────────────

class TestCli:
    def test_info_json_ok(self, tmp_path: Path) -> None:
        res = runner.invoke(touchstone_app,
                            ["info", "--file", str(_write(tmp_path, V1_2P_RI)),
                             "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["n_ports"] == 2

    def test_info_json_error_missing(self, tmp_path: Path) -> None:
        res = runner.invoke(
            touchstone_app,
            ["info", "--file", str(tmp_path / "no.s2p"), "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert isinstance(envelope["errors"], list)

    def test_info_human_output_rules(self, tmp_path: Path) -> None:
        res = runner.invoke(
            touchstone_app, ["info", "--file", str(_write(tmp_path, V1_4P_MA, "m.s4p"))])
        assert res.exit_code == 0, res.output
        for needle in ("规则①", "规则②", "规则③", "n_ports=4", "GHZ"):
            assert needle in res.output

    def test_info_human_conflict_shows_disagreement(self, tmp_path: Path) -> None:
        res = runner.invoke(
            touchstone_app,
            ["info", "--file", str(_write(tmp_path, V1_1P_DB, "x.s2p"))])
        assert res.exit_code == 0, res.output  # 内容共识成立 → 成功面
        assert "冲突" in res.output and ".s2p" in res.output

    def test_info_missing_file_flag_fails(self) -> None:
        res = runner.invoke(touchstone_app, ["info"])
        assert res.exit_code != 0

    def test_help_builds_no_bare_percent_305(self) -> None:
        # #305 家法：--help 真构建 + 零裸 %
        for argv in (["--help"], ["info", "--help"]):
            res = runner.invoke(touchstone_app, argv)
            assert res.exit_code == 0, res.output
            assert "%" not in res.output

    def test_cli_leaves_literal_pin(self) -> None:
        # 计数链钉：touchstone 域恰 1 叶、带 --json（新叶无 --json 即红）
        source = Path(touchstone_service.__file__).parent.parent.joinpath(
            "cli", "domains", "touchstone.py").read_text(encoding="utf-8")
        assert source.count('@touchstone_app.command("info")') == 1
        assert source.count("@touchstone_app.command(") == 1
        assert source.count("json_output: bool = typer.Option") == 1
        assert '--json", "-j"' in source
    def test_service_json_envelope_bare_ok_free(self, tmp_path: Path) -> None:
        # 服务面零裸 ok 字面（AU-2 契约：构造器单源——source 级 grep 钉）
        svc_src = Path(touchstone_service.__file__).read_text(encoding="utf-8")
        assert '{"ok"' not in svc_src
