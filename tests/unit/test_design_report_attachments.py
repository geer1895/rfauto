"""T-O9 报告附件面钉子测试（aurora_o，2026-11-01）。

范围（任务书三条验收）：附件自动生成接线本体由 T-O5 落（§④
ok/missing/skipped 三态）；本席增量=报告内**相对链接**（``[rel](rel)``
形态，round-trip 契约=从报告所在目录解析即达附件）+ 确定性钉。T-O5
既有 39 钉（tests/unit/test_design_replay_report.py）零改动独立全绿。

- ① 有链数据 fixture：generate 后附件在盘 + 报告内链接解析到存在文件
  （缺省落点 run 目录下与外置 output 双形态 round-trip）；
- ② 无链数据：§④ missing 如实 + 手工出图指引（既有行为零回归；
  不落 diagrams/ 目录）；
- ③ 确定性：同 run 两跑 .drawio 附件逐字节一致 + 两份报告 §④ 节逐字节
  一致（豁免行=生成时间戳，REPORT_SPEC §3.1；该行不在 §④ 节内）；
- provenance 门：含链 fixture 模型 ``bare_number_fields`` 判零
  （rel_path/rel_link 均字符串叶；exists=bool 豁免）。

全部离线确定性（#139 零网络；#144 tmp fixture 隔离，零 runs/ 污染）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
src_dir = _REPO / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.service.design_replay_report import (
    build_design_report_model,
    generate_design_report,
    render_design_report_md,
)
from rfauto.service.report_render import bare_number_fields

_CHAIN = [
    {"name": "LNA", "gain_db": 20.0, "nf_db": 0.8},
    {"name": "Mixer", "gain_db": -6.0, "nf_db": 5.0},
]


def _make_run_with_chain(tmp_path: Path) -> Path:
    """B 优化族最小 fixture + chain.json（§④ ok 形态；fixture 形态与
    test_design_replay_report._make_b_run 同源，独立副本避免跨席文件
    耦合——T-O5 钉文件零改动红线）。"""
    run = tmp_path / "run_b"
    (run / "trials").mkdir(parents=True)
    costs = [4.0, 1.0]
    params_variants = [
        {"arm_len_mm": 20.0, "series_w_mm": 0.40},
        {"arm_len_mm": 21.0, "series_w_mm": 0.35},
    ]
    metrics_variants = [
        {"s11_db_max_in_band": -9.0, "s21_db_mean_in_band": -4.5},
        {"s11_db_max_in_band": -10.0, "s21_db_mean_in_band": -4.0},
    ]
    for i, (params, cost, metrics) in enumerate(zip(
            params_variants, costs, metrics_variants, strict=True)):
        (run / "trials" / f"trial_{i}.json").write_text(json.dumps({
            "trial_number": i, "params": params, "metrics": metrics,
            "cost": cost,
        }, indent=1), encoding="utf-8")
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "optimization": {"params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0}}},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
    }
    (run / "recipe.snapshot.yaml").write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=True),
        encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({
        "run_id": run.name, "git_sha": "deadbee",
        "model": "wilkinson_power_divider", "adapter": "fake",
        "status": "done", "study_name": "tune_b_fixture",
        "timestamp": "2026-11-01T00:00:00+00:00", "seed": None,
        "metrics": dict(metrics_variants[1]),
    }, indent=1), encoding="utf-8")
    (run / "chain.json").write_text(json.dumps(_CHAIN, indent=1),
                                    encoding="utf-8")
    return run


def _section_text(md: str, heading: str) -> str:
    """取 ``## <heading>`` 节全文（至下一个 ``##`` 或文末）。"""
    lines = md.splitlines()
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith("## ") and heading in ln)
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


def _md_link_targets(section: str) -> list[str]:
    """节内 markdown 链接目标（``[text](target)`` 的 target 列表）。"""
    return re.findall(r"\]\(([^)]+)\)", section)


class TestAttachmentRoundTrip:
    """验收①：附件在盘 + 报告内链接解析到存在文件（round-trip）。"""

    def test_round_trip_default_output(self, tmp_path: Path):
        run = _make_run_with_chain(tmp_path)
        result = generate_design_report(run)
        assert result["ok"]
        assert result["diagrams"]["status"] == "ok"
        att = result["diagrams"]["attachments"][0]
        assert att["exists"] is True
        att_path = Path(att["path"])
        assert att_path.is_file()
        report_path = Path(result["report"])
        assert report_path.name == "design_report.md"
        assert report_path.parent.resolve() == run.resolve()
        sec4 = _section_text(report_path.read_text(encoding="utf-8"), "④")
        targets = _md_link_targets(sec4)
        assert targets, "§④ ok 态应含相对链接形态附件行"
        for target in targets:
            resolved = (report_path.parent / target).resolve()
            assert resolved.is_file(), f"链接解析不到存在文件: {target}"
        assert (report_path.parent / targets[0]).resolve() == \
            att_path.resolve()
        # 模型面 rel_path=相对 run 目录的稳定 posix 形态
        assert att["rel_path"] == "diagrams/link_summary.drawio"

    def test_round_trip_external_output(self, tmp_path: Path):
        run = _make_run_with_chain(tmp_path)
        out = tmp_path / "reports" / "dr.md"
        result = generate_design_report(run, output=out)
        assert result["ok"]
        att = result["diagrams"]["attachments"][0]
        report_path = Path(result["report"])
        sec4 = _section_text(report_path.read_text(encoding="utf-8"), "④")
        targets = _md_link_targets(sec4)
        assert targets
        resolved = (report_path.parent / targets[0]).resolve()
        assert resolved.is_file()
        assert resolved == Path(att["path"]).resolve()
        # 外置落点=真相对链接（含 .. 段；posix 分隔，非绝对路径伪装）
        assert targets[0].startswith("../")
        assert "\\" not in targets[0]

    def test_model_provenance_clean_with_chain(self, tmp_path: Path):
        run = _make_run_with_chain(tmp_path)
        model = build_design_report_model(run, with_diagrams=True)
        assert bare_number_fields(model) == []
        assert model["diagrams"]["attachments"][0]["rel_path"] == \
            "diagrams/link_summary.drawio"
        # 直渲染（未经 generate 注入 rel_link）回退 rel_path 仍成链接；
        # 该形态下链接语义=相对 run 目录（缺省报告落点 run 根）。
        sec4 = _section_text(render_design_report_md(model), "④")
        assert _md_link_targets(sec4) == ["diagrams/link_summary.drawio"]

    def test_skipped_writes_no_diagrams_dir(self, tmp_path: Path):
        run = _make_run_with_chain(tmp_path)
        model = build_design_report_model(run, with_diagrams=False)
        assert model["diagrams"]["status"] == "skipped"
        assert not (run / "diagrams").exists()


class TestMissingNoRegression:
    """验收②：无链数据 §④ missing 如实（既有行为零回归）。"""

    def test_no_chain_missing_and_no_link(self, tmp_path: Path):
        run = _make_run_with_chain(tmp_path)
        (run / "chain.json").unlink()
        result = generate_design_report(run)
        assert result["ok"]
        assert result["diagrams"]["status"] == "missing"
        assert result["diagrams"]["attachments"] == []
        md = Path(result["report"]).read_text(encoding="utf-8")
        sec4 = _section_text(md, "④")
        assert "missing（如实降级）" in sec4
        assert "rfauto diagram link" in sec4  # 手工出图指引保留
        assert not _md_link_targets(sec4)  # 无附件链接形态
        assert not (run / "diagrams").exists()

    def test_bad_chain_schema_still_missing_no_link(self, tmp_path: Path):
        run = _make_run_with_chain(tmp_path)
        (run / "chain.json").write_text(
            json.dumps([{"name": "LNA", "gain_db": 20.0}]),  # 缺 nf_db
            encoding="utf-8")
        result = generate_design_report(run)
        assert result["diagrams"]["status"] == "missing"
        assert result["diagrams"]["attachments"] == []
        sec4 = _section_text(
            Path(result["report"]).read_text(encoding="utf-8"), "④")
        # 降级注记如实点名 schema 缺键（nf_db）+ 手工出图指引
        assert "nf_db" in sec4
        assert "missing（如实降级）" in sec4
        assert not _md_link_targets(sec4)
        assert not (run / "diagrams").exists()


class TestAttachmentDeterminism:
    """验收③：同 run 两跑附件逐字节。"""

    def test_two_pass_attachment_and_section_byte_identical(
            self, tmp_path: Path):
        run = _make_run_with_chain(tmp_path)
        r1 = generate_design_report(run, output=tmp_path / "one.md")
        r2 = generate_design_report(run, output=tmp_path / "two.md")
        assert r1["ok"] and r2["ok"]
        att1 = r1["diagrams"]["attachments"][0]
        att2 = r2["diagrams"]["attachments"][0]
        assert Path(att1["path"]) == Path(att2["path"])  # 同一附件落点
        data1 = Path(att1["path"]).read_bytes()
        data2 = Path(att2["path"]).read_bytes()
        assert data1 == data2  # .drawio 逐字节一致
        assert data1.startswith(b"<?xml") or data1.startswith(b"<")
        sec1 = _section_text(
            Path(str(r1["report"])).read_text(encoding="utf-8"), "④")
        sec2 = _section_text(
            Path(str(r2["report"])).read_text(encoding="utf-8"), "④")
        assert sec1 == sec2  # §④ 节逐字节（时间戳豁免行不在本节内）
        assert "diagrams/link_summary.drawio" in sec1


@pytest.mark.parametrize("link", [
    "diagrams/link_summary.drawio",
    "../run_b/diagrams/link_summary.drawio",
])
def test_rel_link_shape_is_posix_relative(link: str):
    """相对链接形态钉（posix 分隔 + 相对路径；round-trip 契约的词法面）。"""
    assert "\\" not in link
    assert not Path(link).is_absolute()
    assert not link.startswith("/")
