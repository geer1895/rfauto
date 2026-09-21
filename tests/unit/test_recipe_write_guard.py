"""recipes/ 原件写守卫回归（配方污染根修）。

取证背景：2026-09-17 17:18 UI「保存并运行」链把 recipes/branchline_coupler_v1.yaml
整文件重序列化（注释全丢/notes 引号丢/optimization 段被表单归一化整段替换，
diff 85 行留证），同刻触发 fake run_once。本文件钉住：

1. run_once（fake）本身不改配方原件字节（快照只落 runs/）；
2. 复现污染链（recipe_view → recipe_save → run_once）——原件字节不变，
   重序列化结果落 runs/recipe_workcopy/ 工作副本，运行消费副本；
3. 守卫三档语义（缺省抛 / redirect 工作副本 / explicit 原地）与 Windows
   大小写不敏感、chdir 后仓库原件仍受保护；
4. 显式保存入口边界仍可用（recipe migrate 原地升级、recipe_create 新建），
   但新建不得覆盖 recipes/ 既有原件；
5. 沙箱/快照等旁路写点被指到 recipes/ 时拒绝。

全部用例 chdir 到 tmp_path（#144：优化/run 类单测必须隔离，不污染真实 runs/）。
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

from rfauto.infra import recipe_guard as guard
from rfauto.infra.recipe_guard import RecipeWriteForbidden

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_BRANCHLINE = REPO_ROOT / "recipes" / "branchline_coupler_v1.yaml"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


@pytest.fixture
def recipes_dir(tmp_path) -> Path:
    d = tmp_path / "recipes"
    d.mkdir()
    return d


@pytest.fixture
def branchline_copy(recipes_dir) -> Path:
    """把真实原件按字节复制进隔离 recipes/（原件本身只读不动）。"""
    dst = recipes_dir / REAL_BRANCHLINE.name
    shutil.copyfile(REAL_BRANCHLINE, dst)
    return dst


# ─── 1. run_once 不改原件 ─────────────────────────────────────────────────────

class TestRunOnceKeepsOriginal:
    def test_run_once_fake_leaves_recipe_bytes_intact(self, branchline_copy, tmp_path):
        from rfauto.service.api import run_once

        before = _sha256(branchline_copy)
        assert b"#" in branchline_copy.read_bytes()  # 原件含人工注释（污染即丢）
        r = run_once("recipes/branchline_coupler_v1.yaml", adapter_name="fake")
        assert r["ok"], r.get("errors")
        assert _sha256(branchline_copy) == before
        # 快照只落 runs/<id>/，recipes/ 目录下仍只有那一个文件
        run_dir = tmp_path / "runs" / r["run_id"]
        assert (run_dir / "recipe.snapshot.yaml").exists()
        assert sorted(p.name for p in (tmp_path / "recipes").iterdir()) == [
            "branchline_coupler_v1.yaml"]


# ─── 2. 复现污染链：UI 保存并运行 ────────────────────────────────────────────

class TestUiSaveAndRunChain:
    def test_save_then_run_redirects_to_workcopy_and_keeps_original(
            self, branchline_copy, tmp_path):
        from rfauto.service.api import run_once
        from rfauto.service.ui_service import recipe_save, recipe_view

        before = _sha256(branchline_copy)
        view = recipe_view("recipes/branchline_coupler_v1.yaml")
        assert view["ok"]
        # 逐字复刻前端 saveRecipe 的 payload（表单归一化的 optimization 整段回写）
        updates = {
            "params": {p["name"]: p["value"] for p in view["params"]},
            "setup": view["setup"],
            "objectives": view["objectives"],
            "optimization": view["optimization"],
        }
        updates["params"]["arm_len_mm"] = 21.0
        r = recipe_save("recipes/branchline_coupler_v1.yaml", updates)
        assert r["ok"], r.get("errors")
        assert r["workcopy"] is True
        assert r["recipe_path"] == "runs/recipe_workcopy/branchline_coupler_v1.yaml"
        assert r["source_recipe"] == "recipes/branchline_coupler_v1.yaml"
        assert "原件受保护" in r["message"]

        # 原件逐字节不变；重序列化产物（含表单归一化的 sampler: tpe）只在副本里
        assert _sha256(branchline_copy) == before
        wc = tmp_path / "runs" / "recipe_workcopy" / "branchline_coupler_v1.yaml"
        assert wc.exists()
        wc_text = wc.read_text(encoding="utf-8")
        assert "sampler: tpe" in wc_text and "#" not in wc_text
        assert yaml.safe_load(wc_text)["params"]["arm_len_mm"]["value"] == 21.0
        # 临时文件不残留在任何目录
        assert not list((tmp_path / "recipes").glob("*.ui-tmp"))
        assert not list(wc.parent.glob("*.ui-tmp"))

        # 「并运行」消费回传路径 → 跑的是副本、原件仍不变
        run = run_once(r["recipe_path"], adapter_name="fake")
        assert run["ok"], run.get("errors")
        assert _sha256(branchline_copy) == before
        snap = yaml.safe_load(
            (tmp_path / "runs" / run["run_id"] / "recipe.snapshot.yaml").read_text(
                encoding="utf-8"))
        assert snap["params"]["arm_len_mm"]["value"] == 21.0

    def test_save_outside_recipes_stays_in_place(self, tmp_path):
        """非受保护路径（tmp/用户目录）行为不变：原地写、workcopy=False。"""
        from rfauto.service.ui_service import recipe_save

        path = tmp_path / "recipe.yaml"
        path.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        }), encoding="utf-8")
        r = recipe_save(path, {"params": {"arm_len_mm": 22.0}})
        assert r["ok"] and r["workcopy"] is False
        assert r["recipe_path"] == str(path).replace("\\", "/")
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["params"]["arm_len_mm"][
            "value"] == 22.0
        assert not (tmp_path / "runs" / "recipe_workcopy").exists()

    def test_save_with_numpy_scalar_payload_writes_clean_yaml(self, tmp_path):
        """numpy 标量复现钉：表单透传 np.float64/np.int64 payload 走
        recipe_save，落盘前套 sanitize_numpy_scalars——不抛 RepresenterError，
        写出文件可 yaml.safe_load 且零 numpy 残留（与 write_recipe_yaml 同口径）。"""
        import numpy as np

        from rfauto.service.ui_service import recipe_save

        path = tmp_path / "recipe_np.yaml"
        path.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        }), encoding="utf-8")
        r = recipe_save(path, {
            "params": {"arm_len_mm": np.float64(18.57)},
            "optimization": {
                "n_trials": np.int64(40),
                "sampler": "tpe",
                "params": {"arm_len_mm": {"low": np.float64(15.0),
                                          "high": np.float64(26.0)}},
            },
        })
        assert r["ok"], r.get("errors")
        assert r["workcopy"] is False
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        arm = data["params"]["arm_len_mm"]["value"]
        assert type(arm) is float and arm == 18.57
        assert data["optimization"]["n_trials"] == 40
        assert type(data["optimization"]["n_trials"]) is int
        assert data["optimization"]["params"]["arm_len_mm"] == {
            "low": 15.0, "high": 26.0}
        # 临时文件不残留（与守卫决策后目标同目录的 *.ui-tmp 已被 replace 消费）
        assert not list(tmp_path.glob("*.ui-tmp"))

    def test_second_save_on_workcopy_edits_workcopy_in_place(self, branchline_copy, tmp_path):
        from rfauto.service.ui_service import recipe_save

        r1 = recipe_save("recipes/branchline_coupler_v1.yaml",
                         {"params": {"arm_len_mm": 21.0}})
        r2 = recipe_save(r1["recipe_path"], {"params": {"arm_len_mm": 22.0}})
        assert r2["ok"] and r2["workcopy"] is False
        assert r2["recipe_path"] == r1["recipe_path"]
        wc = Path(r2["recipe_path"])
        assert yaml.safe_load(wc.read_text(encoding="utf-8"))["params"]["arm_len_mm"][
            "value"] == 22.0


# ─── 3. 守卫三档语义 ─────────────────────────────────────────────────────────

class TestGuardSemantics:
    def test_default_forbids_and_creates_nothing(self, recipes_dir):
        with pytest.raises(RecipeWriteForbidden):
            guard.resolve_recipe_write_target("recipes/x.yaml")
        with pytest.raises(RecipeWriteForbidden):
            guard.write_recipe_yaml("recipes/x.yaml", {"model": "m"})
        with pytest.raises(RecipeWriteForbidden):
            guard.write_recipe_text(recipes_dir / "y.yaml", "model: m\n")
        assert list(recipes_dir.iterdir()) == []

    def test_redirect_mirrors_relative_path_case_kept(self, recipes_dir, tmp_path):
        (recipes_dir / "examples").mkdir()
        target = guard.write_recipe_yaml("recipes/examples/Foo.yaml", {"notes": "中文"},
                                         redirect=True)
        assert target == Path("runs") / "recipe_workcopy" / "examples" / "Foo.yaml"
        assert target.exists()
        assert yaml.safe_load(target.read_text(encoding="utf-8")) == {"notes": "中文"}
        assert list((recipes_dir / "examples").iterdir()) == []

    def test_explicit_writes_in_place(self, recipes_dir):
        target = guard.write_recipe_yaml("recipes/new.yaml", {"model": "m"}, explicit=True)
        assert target == Path("recipes/new.yaml") and target.exists()

    def test_non_protected_paths_pass_through_unchanged(self, tmp_path):
        rel = Path("runs") / "agent_proposals" / "p.yaml"
        assert guard.resolve_recipe_write_target(rel) == rel
        absolute = tmp_path / "recipes_other" / "a.yaml"  # 前缀相似但非 recipes/
        assert guard.resolve_recipe_write_target(absolute) == absolute
        assert not guard.is_protected_recipe_path(absolute)

    @pytest.mark.skipif(not REAL_BRANCHLINE.exists(), reason="仓库 recipes/ 缺失")
    def test_repo_recipes_protected_even_after_chdir(self):
        """cwd 已切到 tmp，仓库自带 recipes/ 绝对路径仍受保护（进程 chdir 逃逸口）。"""
        roots = guard.protected_recipe_roots()
        assert len(roots) == 2
        assert guard.is_protected_recipe_path(REAL_BRANCHLINE)
        upper = Path(str(REAL_BRANCHLINE).upper())  # Windows 大小写不敏感
        assert guard.is_protected_recipe_path(upper)
        with pytest.raises(RecipeWriteForbidden):
            guard.check_recipe_write_target(REAL_BRANCHLINE)

    def test_recipes_root_itself_is_not_a_write_target(self, recipes_dir):
        assert guard.is_protected_recipe_path("recipes")
        with pytest.raises(RecipeWriteForbidden):
            guard.workcopy_path("recipes")
        with pytest.raises(RecipeWriteForbidden):
            guard.workcopy_path("runs/not_recipes.yaml")


# ─── 4. 显式保存入口边界 ─────────────────────────────────────────────────────

class TestExplicitEntriesBoundary:
    def test_recipe_migrate_cli_entry_still_upgrades_in_place(self, recipes_dir):
        """`rfauto recipe migrate <path>` 是用户显式入口：v0→v1 允许原地写。"""
        from rfauto.service.api import recipe_migrate

        p = recipes_dir / "legacy.yaml"
        p.write_text("model: wilkinson_power_divider\nparams: {}\n", encoding="utf-8")
        r = recipe_migrate(p)
        assert r["ok"] and r["changed"] and r["to_version"] == 1
        assert yaml.safe_load(p.read_text(encoding="utf-8"))["recipe_version"] == 1

    def test_recipe_migrate_noop_for_current_version(self, branchline_copy):
        from rfauto.service.api import recipe_migrate

        before = _sha256(branchline_copy)
        r = recipe_migrate(branchline_copy)
        assert r["ok"] and not r["changed"]
        assert _sha256(branchline_copy) == before

    def test_recipe_create_refuses_overwriting_original_but_allows_new(
            self, branchline_copy, recipes_dir):
        from rfauto.service.ui_service import recipe_create

        before = _sha256(branchline_copy)
        data = {"model": "wilkinson_power_divider", "params": {}}
        r = recipe_create(branchline_copy, data)
        assert not r["ok"] and any("受保护" in e for e in r["errors"])
        assert _sha256(branchline_copy) == before

        r2 = recipe_create(recipes_dir / "brand_new.yaml", data)
        assert r2["ok"]
        assert yaml.safe_load((recipes_dir / "brand_new.yaml").read_text(
            encoding="utf-8"))["model"] == "wilkinson_power_divider"

    def test_recipe_create_outside_recipes_unchanged(self, tmp_path):
        from rfauto.service.ui_service import recipe_create

        p = tmp_path / "wizard" / "new.yaml"
        p.parent.mkdir()
        p.write_text("model: old\n", encoding="utf-8")  # 非受保护路径允许整体覆盖
        r = recipe_create(p, {"model": "wilkinson_power_divider"})
        assert r["ok"]
        assert yaml.safe_load(p.read_text(encoding="utf-8"))["model"] == "wilkinson_power_divider"


# ─── 5. 旁路写点 ─────────────────────────────────────────────────────────────

class TestSideWritePoints:
    def test_snapshot_recipe_refuses_recipes_dir_as_run_dir(self, recipes_dir, tmp_path):
        from rfauto.infra.run_store import snapshot_recipe

        with pytest.raises(RecipeWriteForbidden):
            snapshot_recipe(recipes_dir, {"model": "m"})
        assert list(recipes_dir.iterdir()) == []
        dest = snapshot_recipe(tmp_path / "runs" / "r1", {"model": "m"})
        assert dest.exists() and dest.name == "recipe.snapshot.yaml"

    def test_sandbox_root_inside_recipes_is_refused(self, branchline_copy, recipes_dir):
        from rfauto.service.agent_sandbox import RecipeSandbox

        sb = RecipeSandbox(root=recipes_dir / "sb")
        with pytest.raises(RecipeWriteForbidden):
            sb.stage(branchline_copy)
        with pytest.raises(RecipeWriteForbidden):
            sb.write_yaml(branchline_copy, "model: m\n")
        assert sorted(p.name for p in recipes_dir.iterdir()) == ["branchline_coupler_v1.yaml"]

    def test_default_sandbox_still_writes_drafts(self, branchline_copy, tmp_path):
        from rfauto.service.agent_sandbox import RecipeSandbox

        r = RecipeSandbox().apply_param_edits(branchline_copy, {"arm_len_mm": 21.0})
        assert r["ok"]
        draft = Path(r["draft"])
        assert draft.exists() and "recipe_sandbox" in str(draft)
        assert yaml.safe_load(draft.read_text(encoding="utf-8"))["params"]["arm_len_mm"][
            "value"] == 21.0

    def test_tournament_variants_redirect_out_of_recipes(
            self, branchline_copy, recipes_dir, monkeypatch):
        """变体临时文件不得落 recipes/*_variantN.yaml；autotune_loop 消费重定向路径。"""
        from rfauto.service import autotune_service

        seen: list[Path] = []

        def fake_loop(variant_path, **_kw):
            p = Path(variant_path)
            seen.append(p)
            assert p.exists()
            return {"best": {"cost": float(len(seen))}, "run_id": f"r{len(seen)}",
                    "verdict": "PASS", "rounds_used": 1}

        monkeypatch.setattr(autotune_service, "autotune_loop", fake_loop)
        before = _sha256(branchline_copy)
        r = autotune_service.orchestrate_tournament(
            branchline_copy, [{"arm_len_mm": 19.0}, {"arm_len_mm": 21.0}])
        assert r["ok"] and r["n_variants"] == 2 and r["winner"]["variant_index"] == 0
        assert len(seen) == 2
        assert all(guard.WORKCOPY_SUBDIR[1] in p.parts for p in seen)
        assert not any(guard.is_protected_recipe_path(p) for p in seen)
        assert all(not p.exists() for p in seen)  # 用完即删
        assert _sha256(branchline_copy) == before
        assert sorted(p.name for p in recipes_dir.iterdir()) == ["branchline_coupler_v1.yaml"]

    def test_agent_apply_proposal_write_goes_to_runs(self, branchline_copy, tmp_path):
        """agent 提案落 runs/agent_proposals/（守卫出口缺省档，非受保护直通）。"""
        from rfauto.service.api import agent_apply, agent_propose

        before = _sha256(branchline_copy)
        prop = agent_propose(branchline_copy, {"arm_len_mm": 21.0}, adapter_name="fake")
        assert prop["ok"], prop
        applied = agent_apply(branchline_copy, prop["token"], {"arm_len_mm": 21.0},
                              adapter_name="fake")
        assert applied["ok"], applied
        assert Path(applied["proposal_recipe"]).exists()
        assert "agent_proposals" in applied["proposal_recipe"]
        assert _sha256(branchline_copy) == before


# ─── 6. 静态盘点：配方 YAML 写回点全部经守卫出口 ──────────────────────────────

class TestWriteBackInventory:
    """新增裸 yaml.safe_dump→recipes 写点时此测试亮红，提醒接守卫（#230 同源）。"""

    SRC = REPO_ROOT / "src" / "rfauto"
    GUARDED_MODULES = (
        "service/ui_service.py", "service/api.py", "service/autotune_service.py",
        "service/agent_sandbox.py", "service/v3_services.py",
        "service/kicad_em_service.py", "cli/main.py", "infra/run_store.py",
    )

    def test_known_recipe_writers_import_guard(self):
        for rel in self.GUARDED_MODULES:
            text = (self.SRC / rel).read_text(encoding="utf-8")
            assert "rfauto.infra.recipe_guard" in text, rel

    def test_ui_recipe_save_has_no_direct_replace_to_source(self):
        text = (self.SRC / "service" / "ui_service.py").read_text(encoding="utf-8")
        assert "tmp.replace(path)" not in text
        assert "tmp.replace(target)" in text


# ─── 7. explicit 覆盖既有受保护原件的 overwritten 标记 ──────────────────────

class TestExplicitOverwriteMarker:
    """explicit 档覆盖既有受保护原件必须可感知（消除与 recipe_create 拒覆盖
    的不对称盲写）：覆盖 → overwritten=True；新建 → False；非受保护路径
    不带标记（getattr 缺省 False，保持既有行为）。"""

    def test_explicit_overwrite_of_protected_original_marks_true(self, branchline_copy):
        assert guard.is_protected_recipe_path(branchline_copy)
        target = guard.write_recipe_yaml(
            "recipes/branchline_coupler_v1.yaml",
            {"model": "wilkinson_power_divider"}, explicit=True)
        assert target == Path("recipes/branchline_coupler_v1.yaml")
        assert getattr(target, "overwritten", False) is True

    def test_explicit_overwrite_text_variant_marks_true(self, branchline_copy):
        target = guard.write_recipe_text(
            "recipes/branchline_coupler_v1.yaml", "model: m\n", explicit=True)
        assert getattr(target, "overwritten", False) is True

    def test_explicit_new_protected_file_marks_false(self, recipes_dir):
        target = guard.write_recipe_yaml(
            "recipes/brand_new_r2d03.yaml", {"model": "m"}, explicit=True)
        assert target.exists()
        assert getattr(target, "overwritten", False) is False

    def test_non_protected_write_stays_unmarked_plain_path(self, tmp_path):
        target = guard.write_recipe_yaml(tmp_path / "elsewhere.yaml", {"model": "m"})
        assert not isinstance(target, guard.GuardedWritePath)
        assert getattr(target, "overwritten", False) is False

    def test_hfss_import_recipe_envelope_passes_overwritten_marker(
            self, branchline_copy, monkeypatch):
        import rfauto.adapters.hfss_import as hfss_import_mod
        from rfauto.service.v3_services import hfss_import_recipe

        monkeypatch.setattr(hfss_import_mod, "import_project_spec",
                            lambda *a, **k: {"ok": True})
        monkeypatch.setattr(hfss_import_mod, "spec_to_recipe_draft",
                            lambda *a, **k: {"recipe": {"model": "m"}})
        r = hfss_import_recipe("whatever.aedt",
                               out="recipes/branchline_coupler_v1.yaml")
        assert r["ok"] and r["recipe_path"].endswith("branchline_coupler_v1.yaml")
        assert r["overwritten"] is True
        r2 = hfss_import_recipe("whatever.aedt", out="recipes/fresh_r2d03.yaml")
        assert r2["ok"] and "overwritten" not in r2  # 新建不带键（既有信封形态）

    def test_kicad_autotune_recipe_envelope_passes_overwritten_marker(
            self, branchline_copy):
        from rfauto.service.kicad_em_service import autotune_recipe_from_extract

        payload = {"extract": {
            "ok": True,
            "board": {"stackup": {"dielectrics": [
                {"thickness_mm": 0.8, "er": 4.4}]}},
            "traces": [{"layer": "F.Cu", "width_mm": 1.0, "length_mm": 20.0,
                        "points_mm": [[0.0, 0.0], [20.0, 0.0]], "net": "RF"}],
            "zones": [{"net": "GND", "layer": "F.Cu", "clearance_mm": 0.3}],
        }}
        r = autotune_recipe_from_extract(payload,
                                         "recipes/branchline_coupler_v1.yaml")
        assert r["ok"], r.get("error")
        assert r["recipe_path"].endswith("branchline_coupler_v1.yaml")
        assert r["overwritten"] is True
        r2 = autotune_recipe_from_extract(payload, "recipes/brand_new_k2d03.yaml")
        assert r2["ok"] and "overwritten" not in r2


# ─── 8. numpy 标量泄漏的递归 sanitize ────────────────────────────────────────

class TestNumpyScalarSanitizer:
    """综合内核 np.float64 透传 recipe_draft → yaml.safe_dump RepresenterError
    （branchline arm_len_mm=18.57 实证）的根修钉：守卫统一写出出口
    （write_recipe_yaml → sanitize_numpy_scalars）递归转 Python 原生类型，
    值精确保留；单点出口覆盖 wstep/gysel/patch/ratrace/wilkinson 同类泄漏面。"""

    def test_scalar_and_nested_payload_types_and_values(self):
        import numpy as np

        payload = {
            "f": np.float64(18.57),
            "i": np.int64(401),
            "b": np.bool_(True),
            "arr": np.array([1.5, 2.5]),
            "params": {"arm_len_mm": {"value": np.float64(18.57)}},
            "band": [np.float64(1.68), np.float64(3.12)],
            "pair": (np.int64(1), np.int64(2)),
            "plain": {"keep": "as-is", "n": 3, "d": 0.5},
        }
        out = guard.sanitize_numpy_scalars(payload)
        assert type(out["f"]) is float and out["f"] == 18.57
        assert type(out["i"]) is int and out["i"] == 401
        assert type(out["b"]) is bool and out["b"] is True
        assert out["arr"] == [1.5, 2.5]
        assert type(out["params"]["arm_len_mm"]["value"]) is float
        assert out["params"]["arm_len_mm"]["value"] == 18.57
        assert all(type(v) is float
                   for v in out["band"])
        assert out["band"] == [1.68, 3.12]
        assert out["pair"] == (1, 2)
        assert out["plain"] == {"keep": "as-is", "n": 3, "d": 0.5}
        # 输入不被原地修改（sanitize 返回新容器）
        assert isinstance(payload["f"], np.float64)

    def test_numpy_scalar_dict_key_converted(self):
        import numpy as np

        out = guard.sanitize_numpy_scalars({np.int64(7): {"v": np.float64(1.0)}})
        keys = list(out)
        assert keys == [7] and type(keys[0]) is int
        assert out[7]["v"] == 1.0

    def test_write_recipe_yaml_accepts_numpy_payload(self, tmp_path):
        import numpy as np

        target = guard.write_recipe_yaml(tmp_path / "np_draft.yaml", {
            "model": "branchline_coupler",
            "params": {"arm_len_mm": {"value": np.float64(18.57)},
                       "points": np.int64(401)},
            "setup": {"freq_range_ghz": [np.float64(1.68), np.float64(3.12)]},
        })
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
        value = data["params"]["arm_len_mm"]["value"]
        assert type(value) is float and value == 18.57
        assert data["params"]["points"] == 401
        assert data["setup"]["freq_range_ghz"] == [1.68, 3.12]

    def test_branchline_draft_end_to_end_yaml_write(self):
        """真实复现路径回归：service 草稿（np 泄漏面）→ 守卫写出 → 可解析、值正确。"""
        from rfauto.service.template_spec_service import draft_recipe_from_spec

        r = draft_recipe_from_spec("branchline")
        assert r["ok"], r.get("error")
        target = guard.write_recipe_yaml("runs/tsdraft_fix/smoke.yaml",
                                         r["recipe_draft"])
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert data["model"] == "branchline_coupler"
        arm = data["params"]["arm_len_mm"]["value"]
        assert type(arm) is float and arm == pytest.approx(18.57, abs=0.01)


# ─── 9. UI 配方目录级写面钉（TODO C22 followUp：UI 配方目录守卫）──────────────

class TestDirectoryLevelWriteSurface:
    """C22 followUp：UI 面对配方的"目录级"操作（新建子目录/目录间移动/批量写）
    也必须走守卫（#317-#319 同源）。

    grep+AST 实证（2026-09-21）：UI 面（ui/server.py + service/ui_service.py +
    service/r3_services.py）**不存在** copytree/move/rmtree/rename/rmdir 类
    目录原语，也无不走守卫出口的 recipes/ 写点——UI 配方写面只有
    recipe_save（守卫 redirect + 同目录临时文件原子替换）与 recipe_create
    （explicit 向导入口 + 拒覆盖既有原件），其余 mkdir 均为 configs//runs/
    已知目标。本类钉两件事，防未来回归：

    ① 行为钉：UI 函数级目录行为——子目录配方的 redirect 镜像目录结构进
       工作副本、向导新建含子目录路径的配方走 explicit 边界；
    ② 静态盘点钉：UI 三模块的目录级写原语按（模块, 函数）白名单盘点，
       新增未接守卫的目录级写点即亮红（TestWriteBackInventory 目录级版）。"""

    SRC = REPO_ROOT / "src" / "rfauto"
    UI_SURFACE_MODULES = (
        SRC / "ui" / "server.py",
        SRC / "service" / "ui_service.py",
        SRC / "service" / "r3_services.py",
    )
    DIRECTORY_PRIMITIVES: ClassVar[set[str]] = {
        "mkdir", "makedirs", "copytree", "copy2", "copyfile", "move",
        "rmtree", "rename", "rmdir", "removedirs"}
    #: 现状盘点（模块文件名, 函数名）→ 允许的目录级写原语（写明理由）
    ALLOWED_SITES: ClassVar[dict[tuple[str, str], set[str]]] = {
        # 守卫决策后目标（工作副本/非受保护路径）建父目录；临时文件与目标
        # 同目录是原子替换前提（#319）
        ("ui_service.py", "recipe_save"): {"mkdir"},
        # CLI 专用渲染入口（--out 显式路径，缺省 runs/sparams_compare/）
        ("ui_service.py", "sparams_compare_png"): {"mkdir"},
        # configs/ 三个配置保存器的父目录创建（非 recipes/ 面）
        ("r3_services.py", "add_solver_to_config"): {"mkdir"},
        ("r3_services.py", "_apply_resource_capacity"): {"mkdir"},
        ("r3_services.py", "save_chat_settings"): {"mkdir"},
    }

    def test_ui_surface_directory_primitives_match_inventory(self):
        import ast

        found: set[tuple[str, str]] = set()
        for mod in self.UI_SURFACE_MODULES:
            tree = ast.parse(mod.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Call):
                        continue
                    if isinstance(sub.func, ast.Attribute):
                        name = sub.func.attr
                    elif isinstance(sub.func, ast.Name):
                        name = sub.func.id
                    else:
                        continue
                    if name in self.DIRECTORY_PRIMITIVES:
                        found.add((mod.name, node.name))
        assert found == {site for site, prims in self.ALLOWED_SITES.items()
                         if prims}, (
            f"UI 面目录级写原语盘点漂移（新增写点须接 recipe_guard 或更新"
            f"本白名单并写明理由）: 实际={sorted(found)}")

    def test_recipe_save_subdirectory_recipe_redirects_with_structure(
            self, recipes_dir, tmp_path):
        """子目录配方保存：守卫 redirect 把目录结构镜像进工作副本，原件字节不动
        （此前只有 guard.workcopy_path 函数级钉，UI 函数级目录行为此为首批）。"""
        from rfauto.service.ui_service import recipe_save

        nested = recipes_dir / "sub" / "family"
        nested.mkdir(parents=True)
        p = nested / "nested_recipe.yaml"
        p.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5}},
        }), encoding="utf-8")
        before = _sha256(p)
        r = recipe_save(p, {"params": {"arm_len_mm": 21.0}})
        assert r["ok"], r.get("errors")
        assert r["workcopy"] is True
        wc = tmp_path / "runs" / "recipe_workcopy" / "sub" / "family" / \
            "nested_recipe.yaml"
        assert wc.exists()
        assert yaml.safe_load(
            wc.read_text(encoding="utf-8"))["params"]["arm_len_mm"]["value"] == 21.0
        assert _sha256(p) == before
        # recipes/ 内不残留临时文件、不新增目录
        assert sorted(q.name for q in nested.iterdir()) == ["nested_recipe.yaml"]

    def test_recipe_create_new_subdirectory_under_recipes_explicit_boundary(
            self, recipes_dir):
        """向导新建含新子目录的路径：explicit 用户键入入口按本意原地创建
        （守卫边界如实），落盘走 write_recipe_yaml 守卫出口。"""
        from rfauto.service.ui_service import recipe_create

        r = recipe_create(recipes_dir / "newfam" / "wizard.yaml",
                          {"model": "wilkinson_power_divider", "params": {}})
        assert r["ok"], r.get("errors")
        p = recipes_dir / "newfam" / "wizard.yaml"
        assert p.exists()
        assert yaml.safe_load(
            p.read_text(encoding="utf-8"))["model"] == "wilkinson_power_divider"
