"""AU-5 材料加载上移行为钉（core/materials 单点发现/加载）。

三钉（批任务书验收）＋辅助钉：
1. env 优先：``RFAUTO_MATERIALS_YAML`` 压过缺省发现；
2. parent 兜底命中与未命中回退：canonical（parent×4）先行、逐级向上、
   全部未命中回 canonical（错误路径与上移前逐位一致）；
3. 缺省零变化：env 未设置时同一工作区解析到与改前相同的文件
   （<repo>/configs/materials.yaml），材料表内容零变化。

辅助钉：显式入参压过 env、env 缺失不静默回退（设置即信）、
core/dispersion 与 service/fab_service 薄委托同点、
mcp_server materials_resource 去 cwd 依赖。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.core import materials as core_materials
from rfauto.core.materials import (
    MATERIALS_YAML_ENV,
    default_materials_yaml_path,
    load_materials_yaml,
    resolve_materials_yaml_path,
)
from rfauto.core.synthesis import Stackup

REPO = Path(__file__).resolve().parents[2]
REPO_MATERIALS = REPO / "configs" / "materials.yaml"

_TMP_YAML = """\
materials:
  rogers4350b_h0.508:
    epsilon_r: 4.4
    thickness_mm: 9.9
    loss_tangent: 0.111
"""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    """每钉默认清空 env（确定性：不依赖外机是否设置过覆盖）。"""
    monkeypatch.delenv(MATERIALS_YAML_ENV, raising=False)


def _write_tmp_yaml(directory: Path, name: str = "materials.yaml") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_text(_TMP_YAML, encoding="utf-8")
    return p


# ─── 钉 3：缺省零变化 ─────────────────────────────────────────────────────────

class TestDefaultZeroChange:
    """env 未设置：同一工作区解析到与上移前相同的文件/内容。"""

    def test_resolve_equals_repo_configs(self):
        assert resolve_materials_yaml_path() == REPO_MATERIALS
        assert resolve_materials_yaml_path().is_file()

    def test_default_path_matches_old_parent4_formula(self):
        # 改前公式（core/synthesis.py 内联）：parent×4 / configs / materials.yaml
        # core/materials.py 与 core/synthesis.py 同目录（src/rfauto/core），
        # 同深度推导必须逐位相等。
        old = (Path(core_materials.__file__).resolve()
               .parent.parent.parent.parent / "configs" / "materials.yaml")
        assert default_materials_yaml_path() == old == REPO_MATERIALS

    def test_stackup_content_unchanged(self):
        s = Stackup.from_materials_yaml("rogers4350b_h0.508")
        assert s.epsilon_r == 3.66
        assert s.thickness_mm == 0.508

    def test_load_full_document(self):
        data = load_materials_yaml()
        assert "materials" in data
        assert "rogers4350b_h0.508" in data["materials"]


# ─── 钉 1：env 优先 ──────────────────────────────────────────────────────────

class TestEnvPriority:
    """RFAUTO_MATERIALS_YAML 设置即信，压过缺省发现。"""

    def test_env_overrides_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        tmp_yaml = _write_tmp_yaml(tmp_path)
        monkeypatch.setenv(MATERIALS_YAML_ENV, str(tmp_yaml))

        assert resolve_materials_yaml_path() == tmp_yaml
        # 缺省文件里同样存在该键——值取 env 文件即证 env 赢了
        s = Stackup.from_materials_yaml("rogers4350b_h0.508")
        assert s.thickness_mm == 9.9
        assert s.epsilon_r == 4.4

    def test_env_empty_string_ignored(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(MATERIALS_YAML_ENV, "")
        assert resolve_materials_yaml_path() == REPO_MATERIALS

    def test_explicit_arg_beats_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        env_yaml = _write_tmp_yaml(tmp_path / "env_dir")
        explicit_yaml = _write_tmp_yaml(tmp_path / "explicit_dir")
        monkeypatch.setenv(MATERIALS_YAML_ENV, str(env_yaml))

        assert resolve_materials_yaml_path(explicit_yaml) == explicit_yaml
        assert load_materials_yaml(explicit_yaml)["materials"]

    def test_env_missing_raises_no_silent_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        missing = tmp_path / "nope" / "materials.yaml"
        monkeypatch.setenv(MATERIALS_YAML_ENV, str(missing))

        # 设置即信：env 路径不存在直接报错（报错点名 env 路径），不静默回退
        with pytest.raises(FileNotFoundError) as ei:
            load_materials_yaml()
        assert str(missing) in str(ei.value)


# ─── 钉 2：parent 兜底命中与未命中回退 ───────────────────────────────────────

class TestUpwardWalk:
    """向上发现：canonical 先行，逐级向上，未命中回 canonical。"""

    def test_candidates_canonical_first_and_ascending(self, tmp_path: Path):
        # 假锚点：tmp/base/x/y/anchor.py，parents = [y, x, base, tmp, ...]
        anchor = tmp_path / "base" / "x" / "y" / "anchor.py"
        cands = core_materials._upward_candidates(anchor)
        assert cands[0] == tmp_path / "configs" / "materials.yaml"  # canonical
        # 逐级向上：路径父数单调减（越走越靠近盘根）
        depths = [len(c.parents) for c in cands]
        assert depths == sorted(depths, reverse=True)
        # 最后一候可选到盘根
        assert cands[-1] == anchor.parents[-1] / "configs" / "materials.yaml"

    def test_walk_hit_at_canonical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        hit = _write_tmp_yaml(tmp_path / "configs")
        # 3 级中间目录：parents[3] 恰为 tmp（对齐 core 文件 src/rfauto/core/×4）
        monkeypatch.setattr(core_materials, "_anchor",
                            lambda: tmp_path / "x" / "y" / "z" / "a.py")

        assert resolve_materials_yaml_path() == hit
        assert load_materials_yaml()["materials"]["rogers4350b_h0.508"][
            "thickness_mm"] == 9.9

    def test_walk_hit_beyond_canonical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # canonical（parents[3]=walk_base）未命中，更上层（tmp）命中
        upper = _write_tmp_yaml(tmp_path / "configs")
        walk_base = tmp_path / "base"
        monkeypatch.setattr(core_materials, "_anchor",
                            lambda: walk_base / "x" / "y" / "z" / "a.py")

        assert resolve_materials_yaml_path() == upper

    def test_walk_miss_falls_back_to_canonical_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # 全树无 configs/materials.yaml：返回 canonical（错误路径与改前一致）
        walk_base = tmp_path / "base"
        monkeypatch.setattr(core_materials, "_anchor",
                            lambda: walk_base / "x" / "y" / "z" / "a.py")
        canonical = walk_base / "configs" / "materials.yaml"

        assert resolve_materials_yaml_path() == canonical
        with pytest.raises(FileNotFoundError, match=r"materials\.yaml 不存在"):
            load_materials_yaml()


# ─── 辅助钉：各收敛点同源 ─────────────────────────────────────────────────────

class TestDelegationPins:
    """散落点薄委托同一单点（env 生效即证同源）。"""

    def test_core_dispersion_delegates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from rfauto.core import dispersion

        assert dispersion._materials_path(None) == REPO_MATERIALS
        tmp_yaml = _write_tmp_yaml(tmp_path / "env_dir")
        monkeypatch.setenv(MATERIALS_YAML_ENV, str(tmp_yaml))
        assert dispersion._materials_path(None) == tmp_yaml

    def test_fab_service_delegates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from rfauto.service import fab_service

        assert fab_service._materials_path() == REPO_MATERIALS
        tmp_yaml = _write_tmp_yaml(tmp_path / "env_dir")
        monkeypatch.setenv(MATERIALS_YAML_ENV, str(tmp_yaml))
        assert fab_service._materials_path() == tmp_yaml

    def test_mcp_resource_cwd_independent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from rfauto.mcp_server import materials_resource

        monkeypatch.chdir(tmp_path)  # 仓外 cwd：改前 FileNotFoundError
        data = materials_resource()
        assert "materials" in data
        assert "rogers4350b_h0.508" in data["materials"]
