"""KD-10 出版级图表规范+Zenodo 清单测试（round16 P3，J 流）。

锚树：
- IEEE rcParams 门：字号/刻度/线宽/dpi/图宽逐门 PASS-FAIL 边界；
  缺键与命名尺寸=UNKNOWN 不翻总门（测量与报告面，非清零运动 #122）；
  target=column(≤3.5in)/full(≤7.16in) 两档；词表外 target 拒绝；
- rcparams_from_matplotlib：matplotlib 缺失时 RuntimeError 诚实降级
  （纯函数面不受影响）；
- Zenodo 清单：必备字段齐备/upload_type 与 access_right 词表/
  open-embargoed 须 license/restricted 须 access_conditions/creators
  非空含 name/DOI 占位符（自引循环）FAIL；
- 确定性：同输入两次 JSON 逐位一致。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

from rfauto.core.publication_standards import (
    GATE_FAIL,
    GATE_PASS,
    GATE_UNKNOWN,
    IEEE_COLUMNWIDTH_IN,
    IEEE_MIN_DPI,
    IEEE_MIN_FONT_PT,
    IEEE_MIN_LINEWIDTH_PT,
    check_ieee_rcparams,
    rcparams_from_matplotlib,
    zenodo_checklist,
)


def _good_rc(target: str = "column") -> dict:
    return {"font.size": 8, "xtick.labelsize": 8, "ytick.labelsize": 8,
            "lines.linewidth": 1.0, "savefig.dpi": 300,
            "figure.figsize": [IEEE_COLUMNWIDTH_IN, 2.5]}


class TestIeeeRcparams:
    def test_compliant_params_pass(self):
        r = check_ieee_rcparams(_good_rc())
        assert r["verdict"] == GATE_PASS and r["ok"]
        assert all(rule["gate"] == GATE_PASS for rule in r["rules"])

    def test_small_font_fails(self):
        rc = _good_rc()
        rc["font.size"] = 6
        r = check_ieee_rcparams(rc)
        assert r["verdict"] == GATE_FAIL
        assert any(r_["rule"] == "font_size" and r_["gate"] == GATE_FAIL
                   for r_ in r["rules"])

    def test_thin_line_fails(self):
        rc = _good_rc()
        rc["lines.linewidth"] = 0.2
        assert check_ieee_rcparams(rc)["verdict"] == GATE_FAIL

    def test_low_dpi_fails(self):
        rc = _good_rc()
        rc["savefig.dpi"] = 72
        r = check_ieee_rcparams(rc)
        assert any(r_["rule"] == "dpi" and r_["gate"] == GATE_FAIL
                   for r_ in r["rules"])
        assert r["verdict"] == GATE_FAIL

    def test_oversized_column_figure_fails_but_full_passes(self):
        rc = _good_rc()
        rc["figure.figsize"] = [5.0, 3.0]
        assert check_ieee_rcparams(rc, target="column")["verdict"] == GATE_FAIL
        assert check_ieee_rcparams(rc, target="full")["verdict"] == GATE_PASS

    def test_named_font_size_is_unknown_not_fail(self):
        rc = _good_rc()
        rc["font.size"] = "small"  # matplotlib 命名尺寸——跨版本映射漂移，不猜
        r = check_ieee_rcparams(rc)
        font_rule = next(r_ for r_ in r["rules"] if r_["rule"] == "font_size")
        assert font_rule["gate"] == GATE_UNKNOWN
        assert r["verdict"] == GATE_PASS  # UNKNOWN 不翻总门

    def test_missing_keys_are_unknown(self):
        r = check_ieee_rcparams({})
        assert all(rule["gate"] == GATE_UNKNOWN for rule in r["rules"])
        assert r["verdict"] == GATE_PASS  # 测量与报告：无 FAIL 即 PASS

    def test_boundary_values_exact_pass(self):
        rc = _good_rc()
        rc["font.size"] = IEEE_MIN_FONT_PT
        rc["lines.linewidth"] = IEEE_MIN_LINEWIDTH_PT
        rc["savefig.dpi"] = IEEE_MIN_DPI
        rc["figure.figsize"] = [IEEE_COLUMNWIDTH_IN, 2.0]
        assert check_ieee_rcparams(rc)["verdict"] == GATE_PASS

    def test_invalid_target_rejected(self):
        r = check_ieee_rcparams(_good_rc(), target="poster")
        assert not r["ok"] and "column" in r["issues"][0]

    def test_deterministic(self):
        a = json.dumps(check_ieee_rcparams(_good_rc()), sort_keys=True)
        b = json.dumps(check_ieee_rcparams(_good_rc()), sort_keys=True)
        assert a == b

    def test_matplotlib_adapter_honest_when_missing(self):
        try:
            import matplotlib  # noqa: F401
            has_mpl = True
        except ImportError:
            has_mpl = False
        if has_mpl:
            vals = rcparams_from_matplotlib()
            assert "font.size" in vals
        else:
            with pytest.raises(RuntimeError, match="matplotlib"):
                rcparams_from_matplotlib()


def _good_zenodo() -> dict:
    return {"title": "RF dataset X",
            "creators": [{"name": "Zhang, San"}],
            "description": "Open RF measurement dataset.",
            "upload_type": "dataset",
            "access_right": "open",
            "license": "CC-BY-4.0",
            "keywords": ["RF", "microstrip"]}


class TestZenodoChecklist:
    def test_compliant_metadata_passes(self):
        r = zenodo_checklist(_good_zenodo())
        assert r["verdict"] == GATE_PASS and r["ok"]
        assert all(c["gate"] == GATE_PASS for c in r["checks"])

    def test_missing_required_field_fails(self):
        md = _good_zenodo()
        del md["description"]
        r = zenodo_checklist(md)
        assert r["verdict"] == GATE_FAIL
        assert any("description" in s for s in r["issues"])

    def test_nc_license_note_on_open_access_is_fine_here(self):
        # 门只判 license 存在性；NC 禁分发铁律在 external_dataset_service
        # 许可门（KD-8）——两层分工，本清单不重复裁决
        md = _good_zenodo()
        md["license"] = "CC-BY-NC-4.0"
        assert zenodo_checklist(md)["verdict"] == GATE_PASS

    def test_restricted_without_conditions_fails(self):
        md = _good_zenodo()
        md["access_right"] = "restricted"
        md["license"] = "none"
        r = zenodo_checklist(md)
        assert r["verdict"] == GATE_FAIL
        assert any("access_conditions" in s for s in r["issues"])

    def test_restricted_with_conditions_passes(self):
        md = _good_zenodo()
        md["access_right"] = "restricted"
        md["access_conditions"] = "_request"
        del md["license"]  # restricted 不强制 license
        r = zenodo_checklist(md)
        assert r["verdict"] == GATE_PASS

    def test_empty_creators_fails(self):
        md = _good_zenodo()
        md["creators"] = []
        assert zenodo_checklist(md)["verdict"] == GATE_FAIL
        md["creators"] = [{"affiliation": "X"}]  # 缺 name
        assert zenodo_checklist(md)["verdict"] == GATE_FAIL

    def test_doi_placeholder_self_citation_fails(self):
        md = _good_zenodo()
        md["doi"] = "10.0000/zenodo.12345"
        r = zenodo_checklist(md)
        assert r["verdict"] == GATE_FAIL
        assert any("占位" in s for s in r["issues"])

    def test_upload_type_out_of_vocabulary_fails(self):
        md = _good_zenodo()
        md["upload_type"] = "meme"
        assert zenodo_checklist(md)["verdict"] == GATE_FAIL

    def test_deterministic(self):
        a = json.dumps(zenodo_checklist(_good_zenodo()), sort_keys=True)
        b = json.dumps(zenodo_checklist(_good_zenodo()), sort_keys=True)
        assert a == b
