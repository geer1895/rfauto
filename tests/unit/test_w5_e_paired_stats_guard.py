"""T15-B10 配对实验统计守卫钉（scripts/paired_stats_guard.py，Z-9 并档）。

判据（SPECS3 §3.1 ①-④，预声明）：

- ① 金样例三档各≥1：tests/gold/paired_stats_cases/ 四例——#294 形 ulp 差
  →not_assertable；#281 形平台内漂移+broad MDE→below_mde；注入真效应
  →assertable；边界例 CI 恰含 0→not_assertable（判据②同钉）；
- ③ bootstrap seed 固定：同输入两次运行逐字节一致（确定性）；
- ④ MDE 缺省拒绝：CI 不含 0 而未传 MDE → ValueError（宁可拒跑）。

本文件为 W5-E 席自建测试（批纪律命名 test_w5_e_*；spec 原名
test_paired_stats_guard.py 并档记录见 runs/w5_phase5/w5e/REPORT.md）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
GOLD = REPO / "tests" / "gold" / "paired_stats_cases"


def _load_guard():
    spec = importlib.util.spec_from_file_location(
        "paired_stats_guard", SCRIPTS / "paired_stats_guard.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


psg = _load_guard()

GOLD_CASES = [
    "case_not_assertable_ulp",
    "case_below_mde_plateau",
    "case_assertable_effect",
    "case_boundary_ci_zero",
]


def _case_text(name: str) -> str:
    return (GOLD / name / "case.csv").read_text(encoding="utf-8")


def _expected(name: str) -> dict:
    return json.loads((GOLD / name / "expected.json").read_text(
        encoding="utf-8"))


class TestGoldCases:
    @pytest.mark.parametrize("name", GOLD_CASES)
    def test_gold_case_three_tiers_and_boundary(self, name):
        """判据①+②：金样例三档各≥1；CI 恰含 0 边界例判 not_assertable。"""
        exp = _expected(name)
        report = psg.guard_csv_text(_case_text(name), exp["mde"])
        assert report["verdict"] == exp["expect_verdict"]
        assert report["verdict"] in psg.VERDICTS
        assert report["n_pairs"] == exp["n_pairs"]
        assert report["bootstrap"]["n_boot"] == 10_000
        assert report["bootstrap"]["seed"] == 0

    def test_boundary_case_mean_diff_exactly_zero(self):
        """判据②：边界例 mean_diff 恰为 0.0 且 CI 恰含 0（非近似）。"""
        report = psg.guard_csv_text(_case_text("case_boundary_ci_zero"), None)
        assert report["mean_diff"] == 0.0
        assert report["ci95_low"] <= 0.0 <= report["ci95_high"]

    def test_ulp_case_not_assertable_even_with_mde(self):
        """判据①：CI 含 0 时 MDE 不参与判读（传 MDE 判读不变）。"""
        rep_no = psg.guard_csv_text(_case_text("case_not_assertable_ulp"), None)
        rep_with = psg.guard_csv_text(
            _case_text("case_not_assertable_ulp"), 1e-9)
        assert rep_no["verdict"] == "not_assertable"
        assert rep_with["verdict"] == "not_assertable"


class TestDeterminism:
    def test_two_runs_bitwise_identical(self):
        """判据③：bootstrap seed 固定，两次运行逐字节一致。"""
        text = _case_text("case_below_mde_plateau")
        one = json.dumps(psg.guard_csv_text(text, 0.5), ensure_ascii=False)
        two = json.dumps(psg.guard_csv_text(text, 0.5), ensure_ascii=False)
        assert one == two

    def test_cli_json_out_deterministic(self, tmp_path):
        text = _case_text("case_assertable_effect")
        one = psg.guard_csv_text(text, 1.0)
        two = psg.guard_csv_text(text, 1.0)
        assert json.dumps(one, sort_keys=True) == json.dumps(
            two, sort_keys=True)


class TestMdePredeclared:
    def test_missing_mde_with_ci_excluding_zero_rejects(self):
        """判据④：CI 不含 0 而未传 MDE → ValueError（宁可拒跑）。"""
        text = _case_text("case_below_mde_plateau")
        with pytest.raises(ValueError, match="MDE"):
            psg.guard_csv_text(text, None)

    def test_mde_must_be_positive(self):
        text = _case_text("case_assertable_effect")
        with pytest.raises(ValueError, match="MDE"):
            psg.guard_csv_text(text, 0.0)


class TestKernelEdges:
    def test_constant_zero_diffs_not_assertable(self):
        rep = psg.paired_stats_guard([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], 0.5)
        assert rep["verdict"] == "not_assertable"
        assert rep["mean_diff"] == 0.0
        assert rep["effect_size"] is None

    def test_constant_nonzero_diffs_requires_investigation(self):
        """sd=0 常数非零差：effect_size/snr 记 None 不虚构；verdict=
        requires_investigation（审查 P1-1 修：旧断言把"可断言"固化=旁路
        MDE 门的 #294/#287 族形态，2026-10-05 契约变更）。"""
        rep = psg.paired_stats_guard([2.0, 3.0, 4.0], [1.0, 2.0, 3.0], 0.5)
        assert rep["verdict"] == "requires_investigation"
        assert rep["effect_size"] is None
        assert rep["snr"] is None
        assert rep["ci95_low"] == rep["ci95_high"] == 1.0
        assert any("sd(diff)=0" in note for note in rep["notes"])

    def test_constant_nonzero_diffs_missing_mde_rejects(self):
        with pytest.raises(ValueError, match="MDE"):
            psg.paired_stats_guard([2.0, 3.0], [1.0, 2.0], None)

    def test_unequal_arms_rejected(self):
        with pytest.raises(ValueError, match="配对语义"):
            psg.paired_stats_guard([1.0, 2.0], [1.0, 2.0, 3.0], 0.5)

    def test_single_pair_rejected(self):
        with pytest.raises(ValueError, match="n=1"):
            psg.paired_stats_guard([1.0], [2.0], 0.5)


class TestCsvParsing:
    def test_missing_header_columns_rejected(self):
        with pytest.raises(ValueError, match="表头"):
            psg.parse_paired_csv("a,1.0\nb,2.0\n")

    def test_non_float_value_rejected(self):
        with pytest.raises(ValueError, match="float"):
            psg.parse_paired_csv("arm,value\narm_a,abc\narm_b,1.0\n")

    def test_three_arms_rejected(self):
        text = ("arm,value\n"
                "arm_a,1.0\narm_a,2.0\n"
                "arm_b,1.5\narm_b,2.5\n"
                "arm_c,0.5\narm_c,0.5\n")
        with pytest.raises(ValueError, match="两臂"):
            psg.parse_paired_csv(text)

    def test_unequal_arm_rows_rejected(self):
        text = "arm,value\narm_a,1.0\narm_a,2.0\narm_b,1.5\n"
        with pytest.raises(ValueError, match="行数不等"):
            psg.parse_paired_csv(text)

    def test_seed_column_parsed_but_not_pairing_semantics(self):
        text = ("arm,value,seed\n"
                "arm_a,1.0,7\narm_b,2.0,7\n"
                "arm_a,3.0,8\narm_b,2.0,8\n")
        parsed = psg.parse_paired_csv(text)
        assert parsed["n_pairs"] == 2
        rep = psg.paired_stats_guard(parsed["values_a"], parsed["values_b"],
                                     10.0)
        assert rep["verdict"] == "not_assertable"

    def test_explicit_arm_selection(self):
        text = ("arm,value\n"
                "treated,3.0\ntreated,4.0\n"
                "control,1.0\ncontrol,2.0\n")
        parsed = psg.parse_paired_csv(text, arm_a="treated", arm_b="control")
        assert parsed["arm_a"] == "treated"
        assert parsed["arm_b"] == "control"
        rep = psg.paired_stats_guard(parsed["values_a"], parsed["values_b"],
                                     0.5)
        assert rep["mean_diff"] == 2.0
        # 常数差（sd=0）：审查 P1-1 修后=requires_investigation（同上契约）
        assert rep["verdict"] == "requires_investigation"

    def test_arm_selection_missing_arm_rejected(self):
        with pytest.raises(ValueError, match="不在 CSV 臂集合"):
            psg.parse_paired_csv("arm,value\narm_a,1.0\narm_b,2.0\n",
                                 arm_a="arm_a", arm_b="ghost")


class TestCli:
    def test_cli_happy_path_json_out(self, tmp_path, capsys):
        out = tmp_path / "guard_out.json"
        rc = psg.main(["--csv", str(GOLD / "case_assertable_effect"
                                       / "case.csv"),
                       "--mde", "1.0", "--json-out", str(out)])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["verdict"] == "assertable"
        assert json.loads(out.read_text(encoding="utf-8")) == payload

    def test_cli_missing_mde_rejects_rc2(self, capsys):
        rc = psg.main(["--csv", str(GOLD / "case_below_mde_plateau"
                                       / "case.csv")])
        assert rc == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert "MDE" in payload["error"]

    def test_cli_help_no_bracket_no_percent(self, capsys):
        """批纪律：自写 help 文本禁 [ 与 % 字符（#305 同型防再犯）。

        扫描对象=本脚本自写的 description 与各 help= 串（argparse 自动
        生成的 usage 行自带方括号样板，不属自写文本）；真跑 --help 钉
        百分号格式崩溃路径。
        """
        parser = psg._build_parser()
        own_texts = [parser.description or ""]
        own_texts += [act.help or "" for act in parser._actions if act.help]
        assert own_texts, "自写 help 文本面为空——扫描面失效"
        for text in own_texts:
            assert "[" not in text, f"help 文本含左方括号：{text!r}"
            assert "%" not in text, f"help 文本含百分号：{text!r}"
        with pytest.raises(SystemExit) as exc:
            psg.main(["--help"])
        assert exc.value.code == 0
        capsys.readouterr()

    def test_cli_deterministic_stdout(self, capsys):
        argv = ["--csv", str(GOLD / "case_not_assertable_ulp" / "case.csv")]
        psg.main(argv)
        one = capsys.readouterr().out
        psg.main(argv)
        two = capsys.readouterr().out
        assert one == two


class TestConstantDiffBranch:
    """常数差三分支钉（审查 P1-1，2026-10-05）：sd=0 非零差不得落 assertable。"""

    def test_const_nonzero_is_requires_investigation(self):
        import json
        from pathlib import Path
        gold = json.loads(
            (Path(__file__).parent.parent / "gold" / "paired_stats_cases"
             / "const_nonzero.json").read_text(encoding="utf-8"))
        assert gold["verdict"] == "requires_investigation"
        assert "非零常数" in gold["reason"]
        assert gold["effect_size"] is None

    def test_const_zero_gold_consistent(self):
        import json
        from pathlib import Path
        gold = json.loads(
            (Path(__file__).parent.parent / "gold" / "paired_stats_cases"
             / "const_zero.json").read_text(encoding="utf-8"))
        assert gold["verdict"] in ("not_assertable", "assertable")

    def test_nonzero_constant_direct(self):
        from scripts.paired_stats_guard import paired_stats_guard
        out = paired_stats_guard([2.0] * 20, [1.0] * 20, mde=0.5)
        assert out["verdict"] == "requires_investigation"
        assert "ulp" in out["reason"] or "系统偏移" in out["reason"]
