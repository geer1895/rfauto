"""T-Q14 模板→配方通路端到端钉（aurora_q Q-W1-1 席）。

钉面（对应外部用户反馈①：模板注册表 75 族（Q-X6 批 2 layered_stack 注册后 76）与 models 注册表 4 模型名字
空间断裂，`model: pifa` 必入"未知模型"死胡同）：

- 映射表：76/76 覆盖 + 幂等（两次调用 JSON 逐字节同）+ model 族恰好
  四对 + null 族带"openEMS 模板直跑"边界标注；
- 导出：pifa=template 形态 / mline=model 形态；参数值逐键等于
  TEMPLATE_NOMINAL 注册表归档值（铁律 7：通路零物理数值生产）；
- validate：template 形态 PASS（export 产物端到端）；未知族/未知参数/
  model+template 互斥三态 error；`model: pifa` 复现形态前缀逐字节保留
  + 出口指引新条目；
- run：pifa template 配方 run_once fake 通道全绿（monkeypatch.chdir
  隔离——#144 家族：run 目录解析在调用时取 cwd）；族无 fake 前向模型
  如实报错并指引 openEMS 通道；
- CLI：templates export-recipe 叶信封（--json 归一兼容位）。

openEMS 真机通道（--adapter openems）单测禁真机——离线可复跑脚本
scripts/ 证据区（runs/aurora_q/qw11_smoke/），真跑验证由主代理复核执行。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from rfauto.cli.domains._core import app as cli_app
from rfauto.service.api.run_core import dry_run, run_once, validate_recipe
from rfauto.service.template_recipe_service import (
    build_template_recipe,
    export_template_recipe,
    template_model_mapping,
)

runner = CliRunner()

# 域注册触发（templates 域模块级 add_typer 自注册进 _core.app——
# 单跑本文件时也保证 "templates" 子应用在树）
from rfauto.cli.domains import templates as _templates_domain  # noqa: F401

# ─── 1. 76 族映射表 ──────────────────────────────────────────────────────────


class TestTemplateModelMapping:
    def test_full_coverage_75(self):
        from rfauto.adapters.oe_templates.registry import TEMPLATE_META

        result = template_model_mapping()
        assert result["ok"] is True
        assert result["total"] == 76
        assert [r["family"] for r in result["mapping"]] == list(TEMPLATE_META)

    def test_model_families_exact_four_pairs(self):
        """映射判定钉：TemplateSpec.hfss_plugin 三对 + models 同名 mline 一对。"""
        from rfauto.models.registry import list_models

        result = template_model_mapping()
        with_model = {r["family"]: r["model"] for r in result["mapping"]
                      if r["model"] is not None}
        assert with_model == {
            "wilkinson": "wilkinson_power_divider",
            "branchline": "branchline_coupler",
            "patch": "patch_antenna",
            "mline": "mline",
        }
        assert result["n_with_model"] == 4
        assert result["n_template_direct"] == 72
        # model 值全部真在 models 注册表（映射不产幻名）
        registry = set(list_models())
        assert all(m in registry for m in with_model.values())

    def test_idempotent_two_runs_byte_identical(self):
        a = json.dumps(template_model_mapping(), ensure_ascii=False,
                       sort_keys=True)
        b = json.dumps(template_model_mapping(), ensure_ascii=False,
                       sort_keys=True)
        assert a == b

    def test_null_rows_carry_boundary_semantics(self):
        """null 族 rationale 必须带"openEMS 模板直跑"边界标注（任务书文案定稿）。"""
        result = template_model_mapping()
        null_rows = [r for r in result["mapping"] if r["model"] is None]
        assert len(null_rows) == 72
        for row in null_rows:
            assert "openEMS 模板直跑" in row["rationale"]
            assert row["mapping_source"] == "none"
        # model 族 rationale 带判定出处（TemplateSpec.hfss_plugin /
        # models.registry 同名匹配二源之一）
        for row in (r for r in result["mapping"] if r["model"] is not None):
            assert ("TemplateSpec" in row["rationale"]
                    or "同名" in row["rationale"])


# ─── 2. 导出（确定性源组装） ─────────────────────────────────────────────────


class TestExportTemplateRecipe:
    def test_pifa_template_form_params_from_nominal(self):
        from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL

        result = export_template_recipe("pifa")
        assert result["ok"] is True
        assert result["form"] == "template"
        assert result["model"] is None
        recipe = result["recipe"]
        assert recipe["template"] == "pifa"
        assert "model" not in recipe
        # 参数值逐键=TEMPLATE_NOMINAL 归档值（零新数字，铁律 7）
        assert recipe["params"] == dict(TEMPLATE_NOMINAL["pifa"])
        # setup 频带由 meta f0 确定性派生（单端口族宽带 0.70 口径=专利
        # Fix3：窄带下真谐振落带外致“整带无谷”——2026-11-05 实证）
        f0 = 2.4
        assert recipe["setup"]["freq_range_ghz"] == [
            round(f0 * 0.70, 6), round(f0 / 0.70, 6)]
        assert recipe["setup"]["points"] == 401
        assert recipe["setup"]["solver"] == "openEMS"
        # yaml 文本与 recipe dict 可逆
        assert yaml.safe_load(result["yaml"]) == recipe

    def test_mline_model_form(self):
        result = export_template_recipe("mline")
        assert result["ok"] is True
        assert result["form"] == "model"
        assert result["model"] == "mline"
        assert result["recipe"]["model"] == "mline"

    def test_build_pure_idempotent(self):
        a = json.dumps(build_template_recipe("pifa"), ensure_ascii=False,
                       sort_keys=True)
        b = json.dumps(build_template_recipe("pifa"), ensure_ascii=False,
                       sort_keys=True)
        assert a == b

    def test_export_to_file_and_overwrite_guard(self, tmp_path,
                                                monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")
        assert result["ok"] is True
        assert Path(result["path"]).exists()
        # 防覆盖：已存在缺省拒绝
        again = export_template_recipe("pifa", "pifa.yaml")
        assert again["ok"] is False
        assert "--force" in again["errors"][0]
        # 显式覆盖：ok（非保护根无 overwritten 标记=缺省 False）
        forced = export_template_recipe("pifa", "pifa.yaml", overwrite=True)
        assert forced["ok"] is True

    def test_overwrite_marker_on_protected_recipes_root(
            self, tmp_path, monkeypatch):
        """recipes/ 受保护根 explicit 覆盖：GuardedWritePath.overwritten 标记
        透传进信封（R2-D-03 口径）。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "recipes").mkdir()
        first = export_template_recipe("pifa", "recipes/pifa.yaml")
        assert first["ok"] is True
        assert first["overwritten"] is False  # 新建
        forced = export_template_recipe("pifa", "recipes/pifa.yaml",
                                        overwrite=True)
        assert forced["ok"] is True
        assert forced["overwritten"] is True  # 覆盖既有原件

    def test_export_into_recipes_explicit_path(self, tmp_path, monkeypatch):
        """recipes/ 受保护根：CLI --out 属 explicit 显式保存档，原地写出。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "recipes").mkdir()
        result = export_template_recipe("pifa", "recipes/pifa.yaml")
        assert result["ok"] is True
        assert Path(result["path"]).exists()

    def test_unknown_family_did_you_mean(self):
        result = export_template_recipe("pifaX")
        assert result["ok"] is False
        assert "未知模板族: pifaX" in result["errors"][0]
        assert "'pifa'" in result["errors"][0]


# ─── 3. validate 打通 ────────────────────────────────────────────────────────


class TestValidateTemplateForm:
    def _write(self, tmp_path, data: dict) -> Path:
        p = tmp_path / "recipe.yaml"
        p.write_text(yaml.safe_dump(data, allow_unicode=True),
                     encoding="utf-8")
        return p

    def test_exported_pifa_validates_pass(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")
        v = validate_recipe(result["path"])
        assert v["ok"] is True, v.get("errors")

    def test_unknown_template_family_error(self, tmp_path):
        p = self._write(tmp_path, {"template": "pifaX", "params": {}})
        v = validate_recipe(p)
        assert v["ok"] is False
        assert any("未知模板族: pifaX" in e and "'pifa'" in e
                   for e in v["errors"])

    def test_unknown_param_in_template_form(self, tmp_path):
        p = self._write(tmp_path, {"template": "pifa",
                                   "params": {"pifa_l_mm_typo": 1.0}})
        v = validate_recipe(p)
        assert v["ok"] is False
        assert any("params 未知参数: pifa_l_mm_typo" in e for e in v["errors"])

    def test_model_and_template_mutually_exclusive(self, tmp_path):
        p = self._write(tmp_path, {"model": "mline", "template": "pifa",
                                   "params": {}})
        v = validate_recipe(p)
        assert v["ok"] is False
        assert any("二选一" in e for e in v["errors"])

    def test_user_repro_model_pifa_prefix_and_hint(self, tmp_path):
        """用户复现形态（model: pifa）：前缀逐字节保留 + 出口指引独立条目。"""
        repro = yaml.safe_load(
            (Path(__file__).resolve().parents[2] / "runs" / "aurora_q"
             / "feedback_repro" / "pifa_codex.yaml").read_text(
                 encoding="utf-8"))
        p = self._write(tmp_path, repro)
        v = validate_recipe(p)
        assert v["ok"] is False
        # 原文案前缀逐字节（aurora_n 人性化批子串钉安全）
        assert any(e.startswith("未知模型: pifa") for e in v["errors"])
        # T-Q14 出口指引：指到 template 形态与 export-recipe 一键生成
        assert any("template: pifa" in e
                   and "templates export-recipe pifa" in e
                   for e in v["errors"])

    def test_model_form_without_template_unchanged(self, tmp_path):
        """model 形态既有面零回归：缺 model 仍报原文案。"""
        p = self._write(tmp_path, {"params": {}})
        v = validate_recipe(p)
        assert v["ok"] is False
        assert "缺少 'model' 字段" in v["errors"]


# ─── 4. dry-run 简化计划面 ───────────────────────────────────────────────────


class TestDryRunTemplate:
    def test_dry_run_template_plan(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")
        plan = dry_run(result["path"])
        assert plan["ok"] is True
        assert plan["template"] == "pifa"
        assert plan["plugin_version"] == "template-direct"
        assert "缓存" in plan["note"]


# ─── 5. run 链（fake 通道离线；openEMS 真机禁入单测）────────────────────────


class TestRunTemplateFake:
    def test_run_once_pifa_fake_end_to_end(self, tmp_path, monkeypatch):
        """export → run_once(fake) 全绿：run 目录随 cwd 隔离（#144 家族）。"""
        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")
        res = run_once(result["path"], adapter_name="fake")
        assert res["ok"] is True, res.get("errors")
        run_dir = Path(res["run_dir"])
        assert run_dir.is_dir()
        assert (run_dir / "results" / "params.s1p").exists()
        assert (run_dir / "report.md").exists()
        meta = json.loads(
            (run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["template"] == "pifa"
        assert meta["status"] == "done"
        # 模板链缓存面如实标注（不冒充命中语义）
        assert res["cache"]["provenance"] == "not_applicable"

    def test_run_once_pifa_fake_s11_dip_at_design_f0(self, tmp_path,
                                                     monkeypatch):
        """ANT2 分派真触发：设计式精确逆 f0 → S11 谷落在 2.4GHz 设计点。"""
        import numpy as np
        import skrf

        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")
        res = run_once(result["path"], adapter_name="fake")
        assert res["ok"] is True
        ntw = skrf.Network(res["touchstone"])
        s11_db = 20 * np.log10(np.abs(ntw.s[:, 0, 0]) + 1e-15)
        assert float(s11_db.min()) < -5.0
        f_min_ghz = float(ntw.frequency.f[int(np.argmin(s11_db))]) / 1e9
        assert abs(f_min_ghz - 2.4) < 0.05

    def test_run_once_with_objectives_metrics_and_cost(self, tmp_path,
                                                       monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")
        recipe = dict(result["recipe"])
        recipe["objectives"] = [{"metric": "s11_db_min",
                                 "band": [2.35, 2.45],
                                 "op": "max_below", "value": -10.0}]
        p = tmp_path / "pifa_obj.yaml"
        p.write_text(yaml.safe_dump(recipe, allow_unicode=True),
                     encoding="utf-8")
        v = validate_recipe(p)
        assert v["ok"] is True, v.get("errors")
        res = run_once(p, adapter_name="fake")
        assert res["ok"] is True, res.get("errors")
        assert res["metrics"], "带目标时 metrics 非空"
        assert "s11_db_min" in "".join(res["metrics"].keys()) or \
            res["cost"] is not None

    def test_fake_channel_unsupported_family_honest_error(
            self, tmp_path, monkeypatch):
        """族无 fake 前向模型（TemplateSpec.fake_model=None）：如实报错并
        指引 openEMS 通道，不冒充求解成功。"""
        monkeypatch.chdir(tmp_path)
        recipe = build_template_recipe("schiffman")  # fake_model=None 族
        p = tmp_path / "schiffman.yaml"
        p.write_text(yaml.safe_dump(recipe, allow_unicode=True),
                     encoding="utf-8")
        res = run_once(p, adapter_name="fake")
        assert res["ok"] is False
        assert any("fake 通道不支持模板族 'schiffman'" in e
                   and "openems" in e for e in res["errors"])

    def test_unknown_adapter_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")
        res = run_once(result["path"], adapter_name="hfss")
        assert res["ok"] is False
        assert any("未知适配器: hfss" in e for e in res["errors"])

    def test_openems_channel_wiring_offline(self, tmp_path, monkeypatch):
        """openEMS 通道接线离线钉（monkeypatch 求解器，零真机——真跑验证由
        主代理按 runs/aurora_q/qw11_smoke/openems_real_run_check.py 执行）：
        模板几何 dict/频带透传/结果网络换算/落盘面。"""
        import numpy as np

        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")

        captured: dict = {}

        class _FakeResult:
            success = True
            freq_ghz = np.linspace(round(2.4 * 0.70, 6),
                                   round(2.4 / 0.70, 6), 41)
            s_params = None
            wall_time_s = 1.0
            message = "injected"

            def __init__(self) -> None:
                n = len(self.freq_ghz)
                s = np.ones((n, 1, 1), dtype=complex) * 0.1
                s[:, 0, 0] = 0.3
                self.s_params = s

        class _FakeSolver:
            def __init__(self, config) -> None:
                captured["freq_range"] = config.freq_range_ghz
                captured["mesh"] = config.mesh_resolution_mm

            def connect(self) -> bool:
                return True

            def build_geometry(self, geometry: dict) -> bool:
                captured["geometry"] = geometry
                return True

            def solve(self):
                return _FakeResult()

        import rfauto.service.template_recipe_service as svc_mod

        monkeypatch.setattr(
            "rfauto.adapters.openems_solver.OpenEMSSolver", _FakeSolver)
        # resolve_openems_exe 在被测函数体内 from em_solver_base 取用——
        # 补丁必须打在来源模块（svc_mod 打点无效，调用时按源模块解析）
        monkeypatch.setattr(
            "rfauto.adapters.em_solver_base.resolve_openems_exe",
            lambda: "openEMS-injected")
        assert svc_mod is not None  # import 面自证（守卫：被测链在位）
        res = run_once(result["path"], adapter_name="openems")
        assert res["ok"] is True, res.get("errors")
        assert captured["geometry"]["template"] == "pifa"
        assert captured["geometry"]["params"]["pifa_l_mm"] == 17.0785
        assert captured["freq_range"] == (
            round(2.4 * 0.70, 6), round(2.4 / 0.70, 6))  # 单端口宽带（Fix3）
        assert res["adapter"] == "openems"
        assert Path(res["touchstone"]).exists()


# ─── 6. CLI 叶 ───────────────────────────────────────────────────────────────

_REPO_RECIPES = Path(__file__).resolve().parents[2] / "recipes"


class TestRecipePresets:
    """recipes/ 预置件防腐钉（T-Q18 部分提前：pifa/monopole/mline v1）。"""

    @pytest.mark.parametrize(
        "name", ["pifa_v1.yaml", "monopole_v1.yaml", "mline_v1.yaml"])
    def test_preset_validates_and_fake_runs(self, name, tmp_path,
                                            monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _REPO_RECIPES / name
        assert src.exists(), f"预置配方缺失: {src}"
        target = tmp_path / name
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        v = validate_recipe(target)
        assert v["ok"] is True, (name, v.get("errors"))
        r = run_once(target, adapter_name="fake")
        assert r["ok"] is True, (name, r.get("errors"))

    def test_preset_params_equal_registry_nominal(self):
        """预置件参数值逐键=TEMPLATE_NOMINAL（铁律 7：零手拍数字）。"""
        import yaml

        from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL

        pairs = {"pifa_v1.yaml": "pifa", "monopole_v1.yaml": "monopole",
                 "mline_v1.yaml": "mline"}
        for fname, family in pairs.items():
            data = yaml.safe_load(
                (_REPO_RECIPES / fname).read_text(encoding="utf-8"))
            assert data["params"] == dict(TEMPLATE_NOMINAL[family]), fname


class TestExportRecipeCliLeaf:
    def test_leaf_registered(self):
        from rfauto.cli.domains.templates import templates_app

        assert any(c.name == "export-recipe"
                   for c in templates_app.registered_commands)

    def test_cli_json_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r = runner.invoke(cli_app, ["templates", "export-recipe", "pifa",
                                    "--json"])
        assert r.exit_code == 0, r.output[:400]
        payload = json.JSONDecoder().raw_decode(
            r.output[r.output.index("{"):])[0]
        assert payload["ok"] is True
        assert payload["form"] == "template"

    def test_cli_out_and_force(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "recipes").mkdir()  # 保护根内覆盖才有 overwritten 标记
        r1 = runner.invoke(cli_app, ["templates", "export-recipe", "pifa",
                                     "--out", "recipes/pifa.yaml"])
        assert r1.exit_code == 0, r1.output[:400]
        assert Path("recipes/pifa.yaml").exists()
        # 已存在缺省拒绝（防覆盖），exit 1
        r2 = runner.invoke(cli_app, ["templates", "export-recipe", "pifa",
                                     "--out", "recipes/pifa.yaml"])
        assert r2.exit_code == 1
        # --force 覆盖成功（受保护根 explicit 覆盖 → overwritten 标记透传）
        r3 = runner.invoke(cli_app, ["templates", "export-recipe", "pifa",
                                     "--out", "recipes/pifa.yaml", "--force"])
        assert r3.exit_code == 0, r3.output[:400]
        payload = json.JSONDecoder().raw_decode(
            r3.output[r3.output.index("{"):])[0]
        assert payload["overwritten"] is True

    def test_cli_unknown_family_exit_1(self):
        r = runner.invoke(cli_app, ["templates", "export-recipe", "pifaX"])
        assert r.exit_code == 1
        payload = json.JSONDecoder().raw_decode(
            r.output[r.output.index("{"):])[0]
        assert payload["ok"] is False
        assert "未知模板族" in payload["errors"][0]

    def test_cli_json_flag_accepted(self):
        r = runner.invoke(cli_app, ["templates", "export-recipe", "cpw",
                                    "--json"])
        assert r.exit_code == 0, r.output[:400]


# ─── 6. Touchstone 导出秩契约（#248 家族回归钉，2026-11-05 主代理）───────────


class TestTouchstoneExportRank:
    def test_openems_filled_matrix_exports_rank_named_file(
            self, tmp_path, monkeypatch):
        """openEMS 通道回填 2×2（名义 1 端口模板）→ 文件名随 network 实际
        秩（.s2p）+skrf 回读可读+meta 记录名义/导出双端口数（#314 掩码
        语义）。真跑实证 2026-11-05：按名义命名 .s1p 使 skrf 回读广播炸。"""
        import numpy as np
        import skrf

        monkeypatch.chdir(tmp_path)
        result = export_template_recipe("pifa", "pifa.yaml")
        assert result["ok"] is True, result.get("errors")

        freq = skrf.Frequency(1.0, 3.0, 11, unit="ghz")
        s2 = np.zeros((11, 2, 2), dtype=complex)
        s2[:, 0, 0] = 0.3 - 0.1j
        s2[:, 1, 0] = 0.3 - 0.1j  # 对称填充形态（fix-g11 家族语义）
        s2[:, 0, 1] = 0.3 - 0.1j
        s2[:, 1, 1] = 0.3 - 0.1j

        class _FakeFilledSolver:
            def __init__(self, config):
                pass

            def connect(self):
                return True

            def build_geometry(self, spec):
                return True

            def solve(self):
                from rfauto.adapters.em_solver_base import EMSolverResult

                return EMSolverResult(
                    success=True, freq_ghz=[float(f) for f in freq.f],
                    s_params=s2, wall_time_s=0.1, message="stub")

        monkeypatch.setattr(
            "rfauto.adapters.openems_solver.OpenEMSSolver",
            _FakeFilledSolver)
        monkeypatch.setattr(
            "rfauto.adapters.em_solver_base.resolve_openems_exe",
            lambda: "stub.exe")

        res = run_once(result["path"], adapter_name="openems")
        assert res["ok"] is True, res.get("errors")
        run_dir = Path(res["run_dir"])
        # 文件名=network 实际秩 2（非名义 1）
        assert (run_dir / "results" / "params.s2p").exists()
        assert not (run_dir / "results" / "params.s1p").exists()
        # skrf 回读可读（扩展名与数据秩一致）
        net = skrf.Network(str(run_dir / "results" / "params.s2p"))
        assert net.s.shape == (11, 2, 2)
        # meta 双端口记录（#314 掩码语义：名义 vs 导出）
        meta = json.loads(
            (run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["nominal_n_ports"] == 1
        assert meta["exported_n_ports"] == 2
        # Fix2（专利4）：filled_ports 布尔+s2p 头注（外部工具读头即识别）
        assert meta["filled_ports"] is True
        s2p_head = (run_dir / "results" / "params.s2p").read_text(
            encoding="utf-8").splitlines()[0]
        assert "single-port template result filled" in s2p_head
        # Fix4a：solve_report wall_time_s=harness 真墙钟（>0，非引擎 0.0）
        assert res["solve_report"]["wall_time_s"] > 0.0
        # Fix4c：solver_versions 溯源面在位（best-effort dict）
        assert isinstance(meta.get("solver_versions"), dict)
