"""双引擎对照曲线服务+端点测试（aurora_i R3 设计 M3，W3-S1 席 2026-10-19）。

数据面：runs/ 证据湖真实数据对（b2a 批 wilkinson 同栅对 + branchline
单引擎 + ratrace 4 端口 S41 schema + slotline 7 列 resid schema）——
runs/ 是 gitignored 证据区，干净 clone/CI 缺盘时**诚实 skip**（conftest
real-machine 同款纪律），注册表/空信封面不依赖证据恒可跑。

解析红线自证（R3 §5）：掩码载体优先（#314，OE 只对直接测量元素出线）、
同栅 ulp 判定（#287）、异栅最近邻（#294）、4 端口 S41 schema 分派
（render_ratrace_cyl 写出契约——既有 masked 解析器 ≥9 列分支会把它
按 3 端口 S23 误读，本钉防回退）。
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNS = _REPO_ROOT / "runs"

#: 真实数据对证据在盘探针（分族独立 skipif——各证据目录生命周期不同）。
_E_WILKINSON = _RUNS / "hfss_window_b2a/wilkinson/hfss_side/rung3.s3p"
_E_BRANCLINE = _RUNS / "hfss_window_b2a/branchline/hfss_side/rung3.s4p"
_E_RATRACE_H = _RUNS / "ratrace_arbitration/hfss_ratrace.s4p"
_E_RATRACE_O = _RUNS / "ratrace_arbitration/mesh_0p2mm/p1/sparams.csv"
_E_SLOT_H = _RUNS / "slotline_transitions/hfss/hfss_trans.s2p"
_E_SLOT_O = _RUNS / "slotline_transitions/trans/sparams.csv"

_skip_no = "runs/ 证据湖产物不在盘（干净 clone/CI）——真实数据对诚实 skip"


def _freq_strictly_increasing(payload: dict) -> bool:
    f = payload["freq_ghz"]
    return len(f) > 1 and all(hi > lo for lo, hi in pairwise(f))


class TestCredibilityCurvesService:
    """service 层（真实 runs/ 数据对 + 注册表面）。"""

    def test_overview_registry_surface(self):
        """总览面：注册 9 族、5 配对、4 单引擎（R3 清单+本席在盘复核口径
        ——此断言钉注册表代码，不依赖证据在盘）。"""
        from rfauto.service import credibility_curves_service as c

        ov = c.credibility_curves()
        assert ov["ok"] is True
        assert ov["count"] == 9
        # 配对态=双引擎曲线证据对（runs/ 湖在盘才可判 paired）——公开树无
        # 证据湖，paired 诚实归零；单引擎计数随配对态联动（9-0）。
        runs_lake = Path(__file__).resolve().parents[2] / "runs"
        has_lake = (runs_lake / "hairpin_calib").is_dir()
        assert ov["n_paired"] == (5 if has_lake else 0)
        assert ov["n_single_engine"] == (4 if has_lake else 9)
        templates = {f["template"] for f in ov["families"]}
        assert {"wilkinson", "branchline", "ratrace",
                "slotline_transitions"} <= templates
        for f in ov["families"]:
            assert f["pairing_state"] in ("paired", "single_engine")

    def test_registered_families_listing(self):
        from rfauto.service import credibility_curves_service as c

        assert c.registered_families()[0] == "wilkinson"
        assert len(c.registered_families()) == 9

    @pytest.mark.skipif(not _E_WILKINSON.is_file(), reason=_skip_no)
    def test_wilkinson_paired_same_grid(self):
        """wilkinson 真实双引擎对：曲线非空/频轴单调/双引擎同栅/掩码出线。"""
        from rfauto.service import credibility_curves_service as c

        r = c.credibility_curves("wilkinson")
        assert r["ok"] is True
        hfss, oe = r["engines"]["hfss"], r["engines"]["openems"]
        # 曲线非空 + 频率轴单调（3 端口全矩阵 9 线 vs OE 掩码 4 线）
        assert hfss["available"] and oe["available"]
        assert hfss["n_ports"] == 3 and len(hfss["curves"]) == 9
        assert _freq_strictly_increasing(hfss)
        assert _freq_strictly_increasing(oe)
        assert hfss["n_points"] == oe["n_points"] == 401
        # 双引擎同栅（b2a 口径：2.0–3.0GHz 同栅，#287 ulp 判定）
        assert r["pairing"]["state"] == "paired"
        assert r["pairing"]["same_grid"] is True
        assert r["pairing"]["n_matched"] == 401
        # 掩码载体优先（#314）：OE 只出直接测量元素，补齐元素如实落
        # omitted_filled 不冒充测量值
        oe_names = {cu["name"] for cu in oe["curves"]}
        assert {"S11", "S21", "S23", "S31"} <= oe_names
        assert "S12" not in oe_names and "S22" not in oe_names
        assert set(oe["omitted_filled"]) >= {"S12", "S22"}
        assert oe["mask_note"]
        # 偏差注记覆盖双引擎交集 S 名，且 provenance 指针在位
        dev = r["pairing"]["max_dev_db"]
        assert {"S11", "S21", "S31", "S23"} <= set(dev)
        for v in dev.values():
            assert v["max_dev_db"] >= 0.0
        assert r["provenance"]["hfss"].startswith("runs/")
        assert r["verdict"]["counts"]["total"] == 5
        assert r["verdict"]["counts"]["agree"] == 5

    @pytest.mark.skipif(
        not (_E_WILKINSON.is_file()
             and (_RUNS / "hfss_window_b2a/stepped_impedance/hfss_side"
                  / "rung3.s2p").is_file()),
        reason=_skip_no)
    def test_stepped_impedance_nearest_neighbor(self):
        """异栅族（OE 子窗 1.92–2.88 vs HFSS 1.5–3.5）：最近邻配对，
        n_matched/重叠带如实（#294——不插值不假装同栅）。"""
        from rfauto.service import credibility_curves_service as c

        r = c.credibility_curves("stepped_impedance")
        assert r["ok"] is True
        p = r["pairing"]
        assert p["state"] == "paired"
        assert p["same_grid"] is False
        assert "最近邻" in p["match_rule"]
        assert p["n_matched"] > 0
        lo, hi = p["overlap_ghz"]
        assert lo >= 1.92 and hi <= 2.881
        # verdict DISAGREE 如实透传（#122 不凑绿）
        assert r["verdict"]["counts"]["disagree"] == 2
        assert any("DISAGREE" in n for n in r["notes"])

    @pytest.mark.skipif(
        not (_E_RATRACE_H.is_file() and _E_RATRACE_O.is_file()),
        reason=_skip_no)
    def test_ratrace_four_port_s41_schema_dispatch(self):
        """ratrace 4 端口 S41 schema：header 分派直读（回归钉——走既有
        masked 3 端口分支会把 S41 数据错标 S23，本钉防回退）。"""
        from rfauto.service import credibility_curves_service as c

        r = c.credibility_curves("ratrace")
        assert r["ok"] is True
        oe = r["engines"]["openems"]
        assert oe["available"] and oe["n_ports"] == 4
        assert [cu["name"] for cu in oe["curves"]] == [
            "S11", "S21", "S31", "S41"]
        assert oe["omitted_filled"] == []
        # HFSS 侧 4 端口全矩阵（#309 多模 .s4p 命名兼容面走 skrf 链）
        hfss = r["engines"]["hfss"]
        assert hfss["available"] and hfss["n_ports"] == 4
        assert len(hfss["curves"]) == 16
        # 配对交集=S41 在内（最近邻：HFSS 2.5MHz vs OE 1.25MHz 子窗）
        p = r["pairing"]
        assert p["state"] == "paired" and p["same_grid"] is False
        assert "S41" in p["max_dev_db"]
        assert p["n_matched"] == 201

    @pytest.mark.skipif(
        not (_E_SLOT_H.is_file() and _E_SLOT_O.is_file()), reason=_skip_no)
    def test_slotline_resid_schema_via_existing_chain(self):
        """slotline 7 列（带 S21_resid 列）：既有 masked 2 端口分支正确
        消费（resid 列忽略，S11/S21 出线）。"""
        from rfauto.service import credibility_curves_service as c

        r = c.credibility_curves("slotline_transitions")
        assert r["ok"] is True
        oe = r["engines"]["openems"]
        assert oe["available"] and oe["n_points"] == 201
        assert [cu["name"] for cu in oe["curves"]] == ["S11", "S21"]
        assert set(oe["omitted_filled"]) == {"S12", "S22"}
        assert r["pairing"]["state"] == "paired"

    @pytest.mark.skipif(not _E_BRANCLINE.is_file(), reason=_skip_no)
    def test_branchline_single_engine_honest_note(self):
        """branchline 单引擎（OE rerun 目录无 sparams.csv）：HFSS 曲线
        齐备 + openEMS 侧如实 note，不虚构第二根线。"""
        from rfauto.service import credibility_curves_service as c

        r = c.credibility_curves("branchline")
        assert r["ok"] is True
        hfss, oe = r["engines"]["hfss"], r["engines"]["openems"]
        assert hfss["available"] and hfss["n_ports"] == 4
        assert len(hfss["curves"]) == 16
        assert _freq_strictly_increasing(hfss)
        assert oe["available"] is False and oe["curves"] == []
        assert r["pairing"]["state"] == "single_engine"
        assert any("openEMS 侧不可用" in n for n in r["notes"])

    def test_unknown_template_honest_empty_envelope(self):
        """未注册模板=诚实空信封（ok=True+engines 空+可用族引导），
        不是 error（"暂无数据"是如实态）；乱名不触盘零穿越面。"""
        from rfauto.service import credibility_curves_service as c

        r = c.credibility_curves("no_such_template")
        assert r["ok"] is True
        assert r["engines"] == {}
        assert r["count"] == 0
        assert "wilkinson" in r["available_templates"]
        assert r["notes"] and "无对照曲线注册数据" in r["notes"][0]


class TestModelAliasNormalization:
    """存量 run 旧模型名别名映射（aurora_j W1-S2 席 2026-10-23）。

    差异面证据：P0–P6 时代模型插件恰三族（git 851614e8
    models/registry.py 实测）→ v3 模板库（936a8e8e 2026-09-01）起改用
    现行短名；runs/ 湖 meta.model 旧名存量实测在盘
    （wilkinson_power_divider×~1290/branchline_coupler×~77/
    patch_antenna×4，2026-10-23 抽样 1819 份 meta.json）。
    本类全部确定性零 runs/ 证据依赖（命中面断言信封结构与回显名，
    引擎负载可用性与证据在盘无关）；证据同负载恒等钉 skipif 门控。
    """

    def test_alias_hit_resolves_current_family(self):
        """旧名命中现行族：model 回显=现行名（信封 hit 路径
        entry["template"]），走引擎解析面（engines 双键在，非诚实空态
        ——available 与否是证据在盘问题，与名字解析正交）。
        patch_antenna→patch 归一命中现行模板名，但 patch 不在本服务
        9 族对照注册表（_FAMILIES）→ 与直查 "patch" 同样的诚实空态
        （别名只做名字归一，不虚构曲线注册）。"""
        from rfauto.service import credibility_curves_service as c

        for old, cur in (("wilkinson_power_divider", "wilkinson"),
                         ("branchline_coupler", "branchline")):
            r = c.credibility_curves(old)
            assert r["ok"] is True
            assert r["model"] == cur
            assert set(r["engines"]) == {"hfss", "openems"}
            assert "available_templates" not in r

    def test_patch_antenna_alias_resolves_but_unregistered_honest(self):
        """patch_antenna 归一到现行 patch 族：归一层命中（纯函数钉），
        信封层与直查现行名 "patch" 同构诚实空态（数据负载逐键恒等；
        model/notes 回显用户输入原样是既有契约——别名不虚构注册数据）。"""
        from rfauto.service import credibility_curves_service as c

        assert c._normalize_model_alias("patch_antenna") == "patch"
        ro = c.credibility_curves("patch_antenna")
        rc = c.credibility_curves("patch")
        assert ro["ok"] is True and rc["ok"] is True
        assert ro["engines"] == rc["engines"] == {}
        assert ro["count"] == rc["count"] == 0
        assert ro["available_templates"] == rc["available_templates"]
        assert ro["model"] == "patch_antenna"  # 回显输入原样（既有契约）

    def test_alias_case_and_whitespace_normalized(self):
        """strip+lower 归一在查表前（大小写/空白混杂的旧名同样命中）。"""
        from rfauto.service import credibility_curves_service as c

        r = c.credibility_curves("  Wilkinson_Power_Divider  ")
        assert r["ok"] is True
        assert r["model"] == "wilkinson"

    def test_no_fuzzy_or_prefix_match_honest_empty(self):
        """前缀/模糊名不命中（诚实降级红线钉）：旧名前缀截断
        （wilkinson_power）与子串（power_divider）都走诚实空态，
        不制造假对照。"""
        from rfauto.service import credibility_curves_service as c

        for fuzzy in ("wilkinson_power", "power_divider",
                      "wilkinson_power_divider_v2"):
            r = c.credibility_curves(fuzzy)
            assert r["engines"] == {}, fuzzy
            assert "wilkinson" in r["available_templates"]

    def test_current_and_unknown_names_unchanged(self):
        """现行名/未知名零行为变化（别名只加不改：现行名命中现行族、
        未知名诚实空态+model 回显用户输入原样）。"""
        from rfauto.service import credibility_curves_service as c

        cur = c.credibility_curves("wilkinson")
        assert cur["ok"] is True and cur["model"] == "wilkinson"
        miss = c.credibility_curves("no_such_template")
        assert miss["engines"] == {}
        assert miss["model"] == "no_such_template"

    def test_normalize_function_unit(self):
        """纯函数单点：命中换现行名/现行名恒等/未知名 strip+lower 原样。"""
        from rfauto.service import credibility_curves_service as c

        assert c._normalize_model_alias(
            "wilkinson_power_divider") == "wilkinson"
        assert c._normalize_model_alias("  BranchLine_Coupler ") \
            == "branchline"
        assert c._normalize_model_alias("cpw") == "cpw"  # 现行名恒等
        assert c._normalize_model_alias("  Ghost_Family ") == "ghost_family"

    def test_empty_alias_table_zero_behavior(self, monkeypatch):
        """空表零行为变化（常量 docstring 契约钉）：旧名退回诚实空态，
        现行名解析不受影响。"""
        from rfauto.service import credibility_curves_service as c

        monkeypatch.setattr(c, "_MODEL_ALIASES", {})
        miss = c.credibility_curves("wilkinson_power_divider")
        assert miss["engines"] == {}
        assert "wilkinson" in miss["available_templates"]
        cur = c.credibility_curves("wilkinson")
        assert cur["ok"] is True and cur["model"] == "wilkinson"

    @pytest.mark.skipif(not _E_WILKINSON.is_file(), reason=_skip_no)
    def test_alias_hit_payload_identical_to_current_name(self):
        """证据在盘时：旧名与现行名同族同负载（整信封恒等——别名只
        改名字解析，不触曲线/配对/判读任何字段）。"""
        from rfauto.service import credibility_curves_service as c

        assert c.credibility_curves("wilkinson_power_divider") \
            == c.credibility_curves("wilkinson")


class TestCredibilityCurvesEndpoint:
    """REST 面（照 test_metric_glossary_ui.py 先例：TestClient+真仓只读）。"""

    @pytest.fixture()
    def client(self):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        return TestClient(create_ui_app())

    def test_overview_ok_envelope(self, client):
        r = client.get("/api/credibility/curves")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["count"] == 9
        assert body["schema_version"] == "1.0"
        assert any(f["template"] == "wilkinson" for f in body["families"])

    @pytest.mark.skipif(not _E_WILKINSON.is_file(), reason=_skip_no)
    def test_template_query_ok_envelope(self, client):
        r = client.get("/api/credibility/curves?template=wilkinson")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["model"] == "wilkinson"
        assert body["engines"]["hfss"]["available"] is True
        assert body["engines"]["hfss"]["curves"]
        assert body["pairing"]["state"] == "paired"
        assert body["provenance"]["hfss"].startswith("runs/")

    def test_unknown_template_honest_empty(self, client):
        r = client.get("/api/credibility/curves?template=does_not_exist")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["engines"] == {}
        assert "wilkinson" in body["available_templates"]

    def test_route_registered_once(self):
        """路由面单注册（重复注册=星装多匹配歧义面，照 metric-glossary 钉）。"""
        import inspect

        from rfauto.ui import server as ui_server

        src = inspect.getsource(ui_server)
        assert src.count('"/api/credibility/curves"') == 1
