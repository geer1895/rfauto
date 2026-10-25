"""fs_list / recipe_view 文件面围栏单测（S-1/S-3，code_audit_slice6 审查修复批 B）。

钉住：
1. fs_list 根围栏（cwd + RFAUTO_FS_ROOT，os.path.normcase 比较 #318）——
   相对穿越（../）、绝对路径越根、盘符逃逸（D:\\x）一律 ok=False 且错误
   指明允许根；RFAUTO_FS_ROOT（os.pathsep 多根）显式放行；
2. 敏感面过滤——configs 目录项、*.local.yaml、chat_settings.yaml 不进
   entries；target 位于 configs（含就是 configs 目录）直接拒；
3. 空 path = cwd（返回形状 ok/path/parent/entries 不变）；
4. /api/fs/list 路由信封原样透传（错误信息能到前端）；
5. recipe_view 同一围栏（errors 列表形状；allow_outside_roots 只放宽根
   围栏、不放宽敏感过滤）；
6. get_system_prompt 公开访问口（F-4：外部消费面不再穿透私有名）。

全部 chdir tmp_path（#144 隔离口径），不读真实文件面、不污染真实 runs/。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
import yaml

from rfauto.service.r3_services import fs_list, get_system_prompt
from rfauto.service.ui_service import recipe_view


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch, isolated):
    # 围栏根只认 cwd + 显式 RFAUTO_FS_ROOT——防本机 set 的该 env 串味
    #（确定性测试要清空同名前缀的整个环境变量集合，内核立规注记 踩坑速查）
    monkeypatch.delenv("RFAUTO_FS_ROOT", raising=False)
    (tmp_path / "runs").mkdir(exist_ok=True)
    yield


# ─── 1. 根围栏（S-1）──────────────────────────────────────────────────────────

class TestFsListRootFence:
    def test_empty_path_lists_cwd(self, tmp_path: Path) -> None:
        (tmp_path / "proj.aedt").write_bytes(b"x")
        d = fs_list("")
        assert d["ok"] and d["path"] == str(tmp_path)
        assert d["parent"] == str(tmp_path.parent)
        assert [e["name"] for e in d["entries"]] == ["runs", "proj.aedt"]  # 目录在前

    def test_relative_traversal_rejected(self) -> None:
        d = fs_list("../..")
        assert d["ok"] is False
        assert "路径越界" in d["error"]
        assert str(Path.cwd()) in d["error"]  # 错误指明允许根
        assert "RFAUTO_FS_ROOT" in d["error"]  # 并给出放行出口

    def test_absolute_outside_root_rejected(self, tmp_path: Path) -> None:
        d = fs_list(str(tmp_path.parent))
        assert d["ok"] is False and "路径越界" in d["error"]
        # R3 弱测试 #20 加固：安全面拒绝必须回显越界路径与允许根（错误
        # 可行动——调用方一眼看出"拒的是谁、允许的是哪"）
        assert str(tmp_path.parent) in d["error"]
        assert str(tmp_path) in d["error"]  # 允许根
        assert "RFAUTO_FS_ROOT" in d["error"]  # 放行出口同信封

    def test_drive_escape_rejected(self, tmp_path: Path) -> None:
        # 盘符逃逸（围栏先于存在性判定：无论 D:\x 是否存在都拒，不外探磁盘）
        d = fs_list("D:\\x")
        assert d["ok"] is False and "路径越界" in d["error"]
        # R3 弱测试 #21 加固：越界路径逐字回显（围栏对盘符逃逸的拒绝
        # 理由与根围栏同源，不做存在性外探）
        assert "D:\\x" in d["error"]
        assert str(tmp_path) in d["error"]

    def test_missing_within_root_reports_not_exist(self, tmp_path: Path) -> None:
        d = fs_list("no_such_dir")
        assert d["ok"] is False and "目录不存在" in d["error"]

    def test_env_root_allows_outside(self, tmp_path, monkeypatch) -> None:
        work = tmp_path / "work"
        work.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        monkeypatch.chdir(work)  # cwd 收窄：outside 成真正的根外路径
        # R3 弱测试 #22 加固：注入对照——先证无 env 时真拒（放行语义
        # 有对照物），再证设 env 后放行+路径回显
        d0 = fs_list(str(outside))
        assert d0["ok"] is False and "路径越界" in d0["error"]
        monkeypatch.setenv("RFAUTO_FS_ROOT", str(outside))
        d = fs_list(str(outside))
        assert d["ok"] and d["path"] == str(outside)

    def test_env_root_multiple_segments(self, tmp_path, monkeypatch) -> None:
        # 多根（os.pathsep 分隔）+ 空段容忍；cwd 根始终在场
        work = tmp_path / "work"
        work.mkdir()
        root_a = tmp_path / "root_a"
        root_b = tmp_path / "root_b"
        root_a.mkdir()
        root_b.mkdir()
        monkeypatch.chdir(work)
        # 空段（首尾/连续分隔符）被跳过，不产生空串根
        monkeypatch.setenv("RFAUTO_FS_ROOT",
                           f"{os.pathsep}{root_a}{os.pathsep}{os.pathsep}{root_b}")
        assert fs_list(str(root_a))["ok"]
        assert fs_list(str(root_b))["ok"]
        # cwd（work）仍是根
        assert fs_list("")["ok"]
        # cwd 的父目录不在任何根内 → 拒
        assert fs_list(str(tmp_path))["ok"] is False

    def test_normcase_boundary_no_prefix_confusion(self, tmp_path) -> None:
        # 根边界判定：C:\ab 不是 C:\a 的子路径（前缀串扰防，#318 normcase 口径）
        sibling = tmp_path.parent / (tmp_path.name + "x")
        d = fs_list(str(sibling))
        assert d["ok"] is False
        # R3 弱测试 #23 加固：语义+回显双钉——拒绝理由是围栏语义（非
        # 存在性/敏感面误拦），且被拒路径=兄弟目录本身（#318 前缀串扰
        # 的直接证据面：tmp+x 整路径被拒，而非 tmp 被误放行后的次生错误）
        assert "路径越界" in d["error"]
        assert str(sibling) in d["error"]


# ─── 2. 敏感面过滤（S-1）──────────────────────────────────────────────────────

class TestFsListSensitiveFilter:
    @pytest.fixture
    def seeded(self, tmp_path: Path) -> Path:
        cfg = tmp_path / "configs"
        cfg.mkdir()
        (cfg / "chat_settings.yaml").write_text("api_key: x", encoding="utf-8")
        (cfg / "remote_machines.local.yaml").write_text("host: x", encoding="utf-8")
        (tmp_path / "chat_settings.yaml").write_text("api_key: y", encoding="utf-8")
        (tmp_path / "remote_machines.local.yaml").write_text(
            "host: y", encoding="utf-8")
        (tmp_path / "ok.yaml").write_text("model: m", encoding="utf-8")
        (tmp_path / "recipes").mkdir()
        return tmp_path

    def test_sensitive_entries_never_listed(self, seeded: Path) -> None:
        d = fs_list("")
        names = [e["name"] for e in d["entries"]]
        assert d["ok"]
        assert "configs" not in names
        assert "chat_settings.yaml" not in names
        assert "remote_machines.local.yaml" not in names
        assert "ok.yaml" in names and "recipes" in names

    def test_target_inside_configs_rejected(self) -> None:
        d = fs_list("configs")
        assert d["ok"] is False and "configs" in d["error"]
        d2 = fs_list("configs/sub")
        assert d2["ok"] is False and "configs" in d2["error"]

    def test_envelope_shape_unchanged(self, seeded: Path) -> None:
        d = fs_list("")
        assert set(d) == {"ok", "path", "parent", "entries"}
        for e in d["entries"]:
            assert set(e) == {"name", "path", "kind"}


# ─── 3. 路由信封透传 ──────────────────────────────────────────────────────────

class TestRoutePassthrough:
    def test_fs_list_route_forwards_error_envelope(self) -> None:
        from starlette.requests import Request

        from rfauto.ui.server import api_fs_list

        request = Request({"type": "http", "method": "GET",
                           "query_string": b"path=..%2F..%2F.."})
        resp = asyncio.run(api_fs_list(request))
        body = json.loads(resp.body)
        assert body["ok"] is False
        assert "路径越界" in body["error"]
        assert resp.status_code == 200  # 信封语义在 body，不改 HTTP 状态


# ─── 4. recipe_view 读围栏（S-3）──────────────────────────────────────────────

def _write_recipe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
    }, allow_unicode=True), encoding="utf-8")
    return path


class TestRecipeViewFence:
    def test_within_cwd_ok(self, tmp_path: Path) -> None:
        v = recipe_view(_write_recipe(tmp_path / "r.yaml"))
        assert v["ok"] and v["model"] == "wilkinson_power_divider"

    def test_outside_cwd_rejected_then_env_root_allows(
            self, tmp_path, monkeypatch) -> None:
        work = tmp_path / "work"
        work.mkdir()
        outside = _write_recipe(tmp_path / "outside" / "r.yaml")
        monkeypatch.chdir(work)  # cwd 收窄：tmp_path 根下的 outside 成越界
        d = recipe_view(str(outside))
        assert d["ok"] is False and "路径越界" in d["errors"][0]
        assert d["errors"][0].endswith("）")  # 错误带允许根信息
        monkeypatch.setenv("RFAUTO_FS_ROOT", str(tmp_path))
        assert recipe_view(str(outside))["ok"]

    def test_allow_outside_roots_relaxes_roots_only(
            self, tmp_path, monkeypatch) -> None:
        work = tmp_path / "work"
        work.mkdir()
        outside = _write_recipe(tmp_path / "outside" / "r.yaml")
        monkeypatch.chdir(work)
        v = recipe_view(str(outside), allow_outside_roots=True)
        assert v["ok"] and v["model"] == "wilkinson_power_divider"

    def test_sensitive_paths_rejected_even_with_allow_flag(self) -> None:
        for p in ("configs/a.yaml", "secret.local.yaml", "chat_settings.yaml"):
            d = recipe_view(p, allow_outside_roots=True)
            assert d["ok"] is False, p
            assert ("敏感目录" in d["errors"][0]
                    or "敏感文件" in d["errors"][0]), p

    def test_sensitive_configs_file_never_read_even_inside_root(self) -> None:
        # 敏感过滤与根围栏正交：根内的 configs/ 同样拒
        d = recipe_view("configs/remote.yaml")
        assert d["ok"] is False and "敏感目录" in d["errors"][0]


# ─── 5. F-4 公开访问口 ────────────────────────────────────────────────────────

class TestSystemPromptAccess:
    def test_get_system_prompt_returns_private_constant(self) -> None:
        from rfauto.service import r3_services

        prompt = get_system_prompt()
        assert isinstance(prompt, str) and "rfauto" in prompt
        assert prompt == r3_services._SYSTEM_PROMPT  # 同一单源，私有名保留

    def test_server_no_longer_touches_private_name(self) -> None:
        # aurora_d UI-R1 拆分后扫描面=ui 包全 .py（server.py 装配壳 +
        # routes/* 分域 + csp.py）：私有名任何 UI 模块都不得触碰。
        from pathlib import Path as _P

        import rfauto.ui as ui_pkg

        ui_dir = _P(ui_pkg.__file__).parent
        joined = "\n".join(
            p.read_text(encoding="utf-8") for p in sorted(ui_dir.rglob("*.py")))
        assert "_SYSTEM_PROMPT" not in joined  # UI 面只走 get_system_prompt()
        assert "get_system_prompt" in joined
