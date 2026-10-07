"""zenodo_service —— PR-11 DOI 与引用闭环：Zenodo 元数据导出器+校验器。

规格=研究扩充 round16 §四 PR-11："填 CITATION.cff+
Zenodo 集成（.zenodo.json+概念 DOI，release 自动归档）"。本模块承担**纯元
数据面**：

- :func:`export_zenodo_metadata`：读 CITATION.cff（Citation File Format
  1.2.0，YAML）→ 组装 Zenodo deposit 元数据 dict（upload_type=software、
  access_right、creators、keywords、repository-code→related_identifiers），
  可选落盘 JSON（公开仓 release 面把它放仓根 ``.zenodo.json`` 即被 Zenodo
  release 工作流自动拾取）。
- :func:`validate_citation_metadata`：CITATION.cff 必填字段校验（缺=errors）
  + 与 pyproject ``[project] version`` 同步校验（错位=errors，release
  readiness H1 节同语义）+ 如实 warnings（repository-code 待补填、概念 DOI
  未铸造——**不编造**）。

**零网络铁律**：本模块**永不真实上传**——纯本地文件解析与组装，概念
DOI 只能由 Zenodo 侧首次发布后回填，本面只做元数据导出与一致性校验
（零 push 铁律，上传动作永远由用户在 release 面显式执行）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tomllib
import yaml

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "CFF_REQUIRED_FIELDS",
    "SUPPORTED_CFF_VERSION",
    "export_zenodo_metadata",
    "validate_citation_metadata",
]

#: 支持的 Citation File Format 版本（本仓 CITATION.cff 钉 1.2.0）。
SUPPORTED_CFF_VERSION = "1.2.0"

#: CITATION.cff 必填字段（缺任一=校验 errors； Zenodo/CFF 规范最小集）。
CFF_REQUIRED_FIELDS = (
    "cff-version",
    "title",
    "type",
    "authors",
    "version",
    "license",
    "abstract",
)

# 仓库根（本文件 src/rfauto/service/zenodo_service.py → parents[3]=仓根，
# #140：入参一律先 Path() 收敛）。
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_cff(citation_path: str | Path) -> tuple[dict[str, Any] | None, list[str]]:
    """读 CITATION.cff（YAML）；损坏/缺失返回 (None, errors)。"""
    path = Path(citation_path)
    if not path.exists():
        return None, [f"CITATION.cff 不存在: {path}"]
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        return None, [f"CITATION.cff 读取/解析失败: {exc}"]
    if not isinstance(data, dict):
        return None, [f"{path} 不是合法 CFF 映射文档"]
    return data, []


def _authors_zenodo(authors: Any) -> list[dict[str, str]]:
    """CFF authors → Zenodo creators（name 形态优先，family/given 拼接）。"""
    out: list[dict[str, str]] = []
    for a in authors or []:
        if not isinstance(a, dict):
            continue
        if a.get("name"):
            out.append({"name": str(a["name"])})
        elif a.get("family"):
            name = str(a["family"])
            if a.get("given"):
                name += ", " + str(a["given"])
            out.append({"name": name})
    return out


def _related_identifiers(cff: dict[str, Any]) -> list[dict[str, str]]:
    """repository-code → Zenodo related_identifiers（isSupplementTo/url）。

    概念 DOI 未铸造时**留空不编造**——DOI 概念号由 Zenodo 首次发布后回填。
    """
    repo = str(cff.get("repository-code") or "").strip()
    if not repo:
        return []
    return [{"identifier": repo, "relation": "isSupplementTo", "scheme": "url"}]


def export_zenodo_metadata(
    citation_path: str | Path | None = None,
    *,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """CITATION.cff → Zenodo deposit 元数据（导出器，零网络）。

    Args:
        citation_path: CFF 源（None=仓根 CITATION.cff）。
        out_path: 落盘路径（None=只组装不落盘；公开仓 release 面惯用
            仓根 ``.zenodo.json``）。

    Returns
    -------
    dict
        ok 信封：``metadata``（Zenodo deposit 元数据 dict）+ ``written``
        （是否落盘）+ ``out_path``；CFF 缺失/损坏走 error 信封。
    """
    cff, errors = _load_cff(citation_path or _REPO_ROOT / "CITATION.cff")
    if cff is None:
        return error_envelope(errors)
    description = " ".join(str(cff.get("abstract") or "").split())
    metadata: dict[str, Any] = {
        "title": str(cff.get("title") or ""),
        "upload_type": "software",
        "creators": _authors_zenodo(cff.get("authors")),
        "description": description,
        "version": str(cff.get("version") or ""),
        "license": str(cff.get("license") or ""),
        "keywords": [str(k) for k in (cff.get("keywords") or [])],
        "access_right": "open",
        "related_identifiers": _related_identifiers(cff),
    }
    written = False
    out: str | None = None
    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        written = True
        out = str(p)
    return ok_envelope(metadata=metadata, written=written, out_path=out)


def validate_citation_metadata(
    citation_path: str | Path | None = None,
    *,
    pyproject_path: str | Path | None = None,
) -> dict[str, Any]:
    """CITATION.cff 校验器（必填字段+pyproject 版本同步；零网络）。

    Args:
        citation_path: CFF 源（None=仓根 CITATION.cff）。
        pyproject_path: 对照 pyproject（None=仓根；``[project] version``
            与 CFF ``version`` 错位=errors——release readiness H1 同语义）。

    Returns
    -------
    dict
        ok 信封：``warnings``（repository-code 待补填、概念 DOI 未铸造等
        如实登记，不判失败）+ ``checked``（逐项检查摘要）；缺字段/版本
        错位走 error 信封（errors 恒 list[str]）。
    """
    cff, errors = _load_cff(citation_path or _REPO_ROOT / "CITATION.cff")
    if cff is None:
        return error_envelope(errors)

    for key in CFF_REQUIRED_FIELDS:
        v = cff.get(key)
        if v is None or (isinstance(v, str) and not v.strip()) or v == []:
            errors.append(f"CITATION.cff 缺必填字段: {key}")
    if errors:
        return error_envelope(errors, warnings=[], checked={})

    warnings: list[str] = []
    checked: dict[str, Any] = {}

    if str(cff.get("cff-version")) != SUPPORTED_CFF_VERSION:
        errors.append(
            f"cff-version={cff.get('cff-version')} 不受支持"
            f"（本面钉 {SUPPORTED_CFF_VERSION}）")
    if str(cff.get("type")) != "software":
        errors.append(f"type={cff.get('type')!r} 应为 'software'")
    if not _authors_zenodo(cff.get("authors")):
        errors.append("authors 为空或无可解析姓名（name 或 family/given）")
    checked["cff_version"] = str(cff.get("cff-version"))
    checked["type"] = str(cff.get("type"))
    checked["n_authors"] = len(_authors_zenodo(cff.get("authors")))

    repo = str(cff.get("repository-code") or "").strip()
    checked["repository_code"] = repo or None
    if not repo:
        # 如实登记待补填状态，不编造 URL（不判失败——首次发布前允许空）
        warnings.append(
            "repository-code 未填：公开仓库 URL 就绪后补填"
            "（与 pyproject project.urls 同步），概念 DOI 归档依赖它")

    pp = Path(pyproject_path) if pyproject_path is not None \
        else _REPO_ROOT / "pyproject.toml"
    if pp.exists():
        try:
            with open(pp, "rb") as f:
                proj = tomllib.load(f).get("project") or {}
            py_ver = str(proj.get("version") or "")
            checked["pyproject_version"] = py_ver
            if py_ver and py_ver != str(cff.get("version")):
                errors.append(
                    f"版本错位：CITATION.cff version={cff.get('version')!r}"
                    f" vs pyproject [project] version={py_ver!r}"
                    "（release readiness H1 同语义，两处一起改）")
        except (OSError, tomllib.TOMLDecodeError) as exc:
            warnings.append(f"pyproject 读取失败（跳过版本同步校验）: {exc}")
    else:
        warnings.append(f"pyproject 不存在（跳过版本同步校验）: {pp}")

    if errors:
        return error_envelope(errors, warnings=warnings, checked=checked)
    return ok_envelope(warnings=warnings, checked=checked)
