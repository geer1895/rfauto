"""XN-8 零安装云沙箱接口面（round19 P3，ge8c 席C6）——Binder/Colab 一键体验面。

定位（round19 口径"Binder/Colab 一键体验面（计算器+画廊交互，零真机依赖）
——开源获客最低摩擦入口"；本席登记级交付=**接口面，零真云**）：

- **纯产物生成**（零网络）：repo 规格 → Binder/Colab 徽章与启动 URL
  （mybinder.org / colab.research.google.com 的公开 URL 形态）+ 最小
  environment.yml + 可执行 notebook 骨架（nbformat 4 JSON：markdown 导语
  + 代码单元引用 ``rfauto.core.calculators`` 闭式计算器——零真机依赖）；
- **URL 形态守卫**：仅 https；repo 必须 ``owner/name``；ref 字符白名单
  （URL 不安全字符拒绝，不静默编码——坏 ref 让上游改，不产出坏链接）；
- **probe（可选增强，注入通道）**：``http_get`` 注入式可达性探测（默认
  通道与 tool_intel 同款单点；**测试必注入**，本模块自身零真云调用发起
  方）。探测失败/非 2xx 如实 failed，不炸批次。

诚实边界：生成 artifacts ≠ 云上可用性；真实可达性只能由 probe/人工浏览器
确认，产物消费方据此如实标注。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

__all__ = [
    "SANDBOX_SCHEMA",
    "build_binder_url",
    "build_colab_url",
    "build_environment_yml",
    "build_notebook",
    "make_sandbox_bundle",
    "probe_bundle_urls",
]

#: 沙箱 bundle 契约版本。
SANDBOX_SCHEMA = "rfauto-cloud-sandbox-v1"

HttpGet = Callable[[str, float], bytes]

#: mybinder/colab 公开入口（URL 形态来源=两者官方首页文档口径）。
BINDER_BASE = "https://mybinder.org/v2/gh"
COLAB_BASE = "https://colab.research.google.com/github"

#: ref 白名单：分支/tag 名常见字符（git check-ref-format 宽包子集）。
_REF_RE = re.compile(r"^[A-Za-z0-9._\-/]{1,120}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")

#: environment.yml 最小依赖（与 pyproject 核心集对齐的体验面子集；
#: 版本下限钉仓内 pyproject 声明的主版本口径）。
ENV_DEPENDENCIES: tuple[str, ...] = (
    "python>=3.12",
    "numpy",
    "scipy",
    "pyyaml",
    "pydantic>=2",
    "scikit-rf",
    "optuna",
)


def _validate_repo(repo: str) -> str:
    r = str(repo).strip()
    if not _REPO_RE.match(r):
        raise ValueError(f"repo 必须 owner/name 且字符安全: {repo!r}")
    return r


def _validate_ref(ref: str) -> str:
    f = str(ref).strip()
    if not _REF_RE.match(f) or ".." in f:
        raise ValueError(f"ref 含不安全字符（拒绝产出坏链接）: {ref!r}")
    return f


def build_binder_url(repo: str, ref: str = "main",
                     filepath: str = "") -> str:
    """mybinder 启动 URL（纯字符串构造，零网络）。"""
    r, f = _validate_repo(repo), _validate_ref(ref)
    tail = f"?filepath={filepath}" if filepath else ""
    return f"{BINDER_BASE}/{r}/{f}{tail}"


def build_colab_url(repo: str, ref: str, notebook_path: str) -> str:
    """Colab 启动 URL（github 镜像形态；notebook 必须仓库内路径）。"""
    r, f = _validate_repo(repo), _validate_ref(ref)
    nb = str(notebook_path).lstrip("/")
    if not nb.endswith(".ipynb") or ".." in nb.split("/"):
        raise ValueError(f"notebook_path 必须是仓内 .ipynb 相对路径: "
                         f"{notebook_path!r}")
    return f"{COLAB_BASE}/{r}/{f}/{nb}"


def build_environment_yml(name: str = "rfauto-sandbox") -> str:
    """最小 environment.yml（依赖子集见 ENV_DEPENDENCIES）。"""
    lines = [f"name: {name}", "channels:", "  - conda-forge",
             "dependencies:"]
    lines += [f"  - {d}" for d in ENV_DEPENDENCIES]
    return "\n".join(lines) + "\n"


def build_notebook(repo: str, ref: str = "main") -> dict[str, Any]:
    """最小可执行 notebook 骨架（nbformat 4；代码单元零真机依赖）。

    代码单元只消费 ``rfauto.core.calculators`` 注册表闭式纯函数（铁律 7：
    数字只出确定性内核）；pip 安装单元用公开 PyPI 包名占位。
    """
    r = _validate_repo(repo)
    nb = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"# rfauto 零安装体验（{r}@{ref})\n",
                    "\n",
                    "本 notebook 消费 rfauto 闭式计算器（纯函数，零 EM 求解、",
                    "零真机依赖）；未配预览通道的能力如实不列。\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "%pip install -q rfauto\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "from rfauto.core.calculators import "
                    "CALCULATOR_REGISTRY as REG\n",
                    "names = REG.names()\n",
                    "print(f\"可用闭式计算器 {len(names)} 个（确定性内核）\")\n",
                    "print(names[:10])\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return nb


def make_sandbox_bundle(repo: str, ref: str = "main",
                        notebook_path: str = "notebooks/rfauto_intro.ipynb",
                        env_name: str = "rfauto-sandbox") -> dict[str, Any]:
    """沙箱 bundle：URL/环境/notebook 一揽子产物（零网络；JSON 进出）。"""
    try:
        binder = build_binder_url(repo, ref)
        colab = build_colab_url(repo, ref, notebook_path)
        nb = build_notebook(repo, ref)
    except ValueError as exc:
        from rfauto.service.envelope import error_envelope

        return error_envelope(str(exc))
    from rfauto.service.envelope import ok_envelope

    return ok_envelope(
        schema=SANDBOX_SCHEMA,
        repo=repo,
        ref=ref,
        urls={"binder": binder, "colab": colab},
        badges={
            "binder_md": f"[![Binder](https://mybinder.org/badge_logo.svg)]"
                         f"({binder})",
            "colab_md": f"[![Open In Colab](https://colab.research.google.com"
                        f"/assets/colab-badge.svg)]({colab})",
        },
        environment_yml=build_environment_yml(env_name),
        notebook=nb,
        notebook_path=notebook_path,
        note="产物生成 ≠ 云上可用性；真实可达性以 probe/人工确认为准（零真云）",
    )


def _default_http_get(url: str, timeout_s: float) -> bytes:
    """默认探测单点（与 tool_intel 同款；测试 monkeypatch/注入钉通道）。"""
    import urllib.request

    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "rfauto-sandbox"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


def probe_bundle_urls(
    urls: list[str],
    *,
    http_get: HttpGet | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    """bundle URL 可达性探测（注入通道；非 2xx/异常逐条如实 failed）。

    - ``http_get`` 注入即为离线 mock（#139：测试必注入，禁真网）；
    - 仅允许 https（非 https 直接拒——明文探测面不产出）。
    """
    from rfauto.service.envelope import error_envelope, ok_envelope

    get = http_get if http_get is not None else _default_http_get
    results: list[dict[str, Any]] = []
    for u in urls:
        if not str(u).startswith("https://"):
            return error_envelope(f"仅允许 https 探测: {u!r}")
        item: dict[str, Any] = {"url": u}
        try:
            get(str(u), timeout_s)
            item.update(ok=True, status="reachable")
        except Exception as exc:  # 网络/HTTP 错误逐条如实留痕
            item.update(ok=False, status="failed", reason=str(exc)[:300])
        results.append(item)
    n_ok = sum(1 for r in results if r["ok"])
    return ok_envelope(results=results, n_ok=n_ok, n_total=len(results),
                       note="probe 结果是时点快照；bundle 生成≠可用性")


def save_bundle(bundle: Mapping[str, Any], out_dir: str | Path) -> dict[str, Any]:
    """bundle 落盘（environment.yml + notebook ipynb + urls.json；只写本席产物）。"""
    from rfauto.service.envelope import error_envelope, ok_envelope

    if not bundle.get("ok"):
        return error_envelope("save_bundle requires ok bundle")
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "environment.yml").write_text(
        str(bundle["environment_yml"]), encoding="utf-8")
    (d / str(bundle.get("notebook_path") or "notebook.ipynb").split("/")[-1]) \
        .write_text(json.dumps(bundle["notebook"], ensure_ascii=False,
                               indent=1), encoding="utf-8")
    (d / "urls.json").write_text(
        json.dumps(bundle["urls"], ensure_ascii=False, indent=1),
        encoding="utf-8")
    return ok_envelope(out_dir=str(d),
                       files=["environment.yml",
                              str(bundle.get("notebook_path") or
                                  "notebook.ipynb").split("/")[-1],
                              "urls.json"])
