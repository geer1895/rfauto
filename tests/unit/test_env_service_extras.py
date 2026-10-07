"""doctor_extras（UX-A1）回归钉——extras 安装状态面板的 service 面。

数据面用 tmp 假 pyproject 隔离（不依赖本机安装态）；探测面对
"必装发行名"（numpy）与"必缺发行名"（伪造名）双钉。
"""

from __future__ import annotations

from pathlib import Path

from rfauto.service.env_service import EXTRA_SCENES, _requirement_name, doctor_extras

_FAKE_MISSING = "rfauto-definitely-not-installed-xyz"


def _write_pyproject(root: Path, groups: dict[str, list[str]]) -> Path:
    p = root / "pyproject.toml"
    lines = ["[project]", 'name = "x"', 'version = "0"', "[project.optional-dependencies]"]
    for g, reqs in groups.items():
        lines.append(f"{g} = [")
        for r in reqs:
            lines.append(f'    "{r}",')
        lines.append("]")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class TestRequirementName:
    def test_version_markers_and_extras_stripped(self) -> None:
        assert _requirement_name("scikit-rf>=2.0,<3") == "scikit-rf"
        assert _requirement_name("pytest[xdist]>=7") == "pytest"
        assert _requirement_name("some-pkg; python_version >= '3.10'") == "some-pkg"

    def test_fallback_path(self) -> None:
        # packaging 解析失败（非法串）回退轻量切分不抛异常。
        assert isinstance(_requirement_name("weird==1"), str)


class TestDoctorExtras:
    def test_fake_pyproject_structure_and_probe(self, tmp_path: Path) -> None:
        p = _write_pyproject(
            tmp_path,
            {
                "mcp": ["numpy>=1.20"],            # 必装 → 全装组
                "gnn": ["numpy", _FAKE_MISSING],   # 一缺 → partial 组
            },
        )
        result = doctor_extras(p)
        by_name = {g["name"]: g for g in result["groups"]}
        assert by_name["mcp"] == {"name": "mcp", "n_reqs": 1, "n_installed": 1, "missing": []}
        assert by_name["gnn"]["n_installed"] == 1
        assert by_name["gnn"]["missing"] == [_FAKE_MISSING]
        assert result["summary"]["n_groups"] == 2
        assert result["summary"]["fully_installed"] == 1
        # 场景面：EXTRA_SCENES 中 "MCP/agent" 含 mcp → ready；"优化与代理" 含 gnn → partial
        scenes = {s["scene"]: s for s in result["scenes"]}
        assert scenes["MCP/agent"]["ready"] is True
        assert scenes["优化与代理"]["ready"] is False
        assert scenes["优化与代理"]["partial"] == ["gnn"]

    def test_bad_pyproject_returns_empty_not_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "pyproject.toml"
        bad.write_text("not [ valid toml =", encoding="utf-8")
        result = doctor_extras(bad)
        assert result["groups"] == [] and result["summary"]["n_groups"] == 0

    def test_real_repo_pyproject_groups_nonempty(self) -> None:
        """真仓 pyproject：32 组基线（组数漂移时此钉提醒同步场景表）。"""
        result = doctor_extras()
        assert result["summary"]["n_groups"] >= 30
        assert {s["scene"] for s in result["scenes"]} == set(EXTRA_SCENES)


def test_cli_doctor_has_extras_flag() -> None:
    """CLI 注册面：doctor 带 --extras 选项（信息性恒 exit 0 语义在 docstring）。"""
    import inspect

    from rfauto.cli.domains.system import doctor

    sig = inspect.signature(doctor)
    assert "extras" in sig.parameters
