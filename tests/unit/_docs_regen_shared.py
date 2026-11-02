"""再生器共享构建产物夹具单源（aurora_m W1-4）。

把 test_docs_site / test_check_docs_drift / test_kernel_cards 三消费面在
同一批跑里各自重复执行的 build_docs_pages.build_all / build_kernel_cards.build
（A 侧实测：三文件同门 docs_site 构建 11 次 + kernel_cards 2 次）收敛为
单次构建共享产物：

- 缓存域 = pytest tmp basetemp 下 ``regen_shared/<key>``（pytest tmp 域内，
  禁写 runs/ 与仓根——工作区摆放纪律 9）。单次 pytest invocation 内同 key
  只构建一次；xdist 多 worker 共享同一 basetemp，跨 worker 同样收敛；
  跨 invocation basetemp 轮换=天然过期，无陈旧复用面。
- 收敛机制 = 构建到同盘 staging 目录后 ``os.replace`` 原子改名进位；改名
  失败即他方（并发 worker/竞速进程）已构建完成，弃 staging 复用现存产物。
- manifest 与产物同笔缓存（先原子写 manifest 后改名，目录可见即 manifest
  必在；内容在同 invocation 内确定性一致，败者不覆写胜者已提交文件），
  消费者断言面零变化——manifest 仍来自真实 build_all 返回值。
- 共享产物**只读**：消费者一律经副本变异（test_check_docs_drift 既有
  _copy_ref 模式）或纯读（test_docs_site/test_kernel_cards 比对面）。

缺省行为不变红线：再生器/比对器脚本缺省 CLI 路径零改动（公开仓 CI
docs-drift job 消费同一脚本）；--from-dir 预构建消费口见各脚本 docstring。

aurora_m W1-3 追加跨段消费口：终门 v2 分段独立进程跨段无持久缓存（三
消费文件 5 段口径分属 seg1/seg2/seg3），wf_gate_full_v2 发射段前构建一次
产物落 ``gate_parts/<name>_regen/`` 并经 env ``RFAUTO_DOCREGEN_FROM`` 传
给段进程；夹具检测到该 env 直接消费预构建目录（跳过自身构建），同树同
生成器=与自建逐字节等价。目录/manifest 缺席=门 prebuild 契约破坏——
**如实红，不静默回退自建**（静默回退会把"每门 ≤1 次"契约悄悄变 3 次）；
env 未设（一切非门场景）走原路径，缺省行为不变。
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest

_REPO = Path(__file__).resolve().parents[2]

#: 门 prebuild 消费口环境变量（生产者=scripts/wf_gate_full_v2.py 的
#: REGEN_FROM_ENV——两处字面量必须一致，test 钉）。
REGEN_FROM_ENV = "RFAUTO_DOCREGEN_FROM"


class RegenBuild(NamedTuple):
    """单次共享构建的产物目录 + 构建期 manifest（测试同源锚）。"""

    directory: Path
    manifest: dict[str, Any]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御
        raise RuntimeError(f"无法装载 {path}")
    mod = importlib.util.module_from_spec(spec)
    # py3.12 dataclasses 解析 string 注解需先注册 sys.modules（同
    # test_docs_site._load_module：build_docs_pages 含 @dataclass CliNode）
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _read_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - 防御
        raise RuntimeError(
            f"共享构建产物 manifest 缺席/损坏: {manifest_path}（目录可见即 "
            "manifest 必在的提交序不变量被破坏）") from exc


def _atomic_shared_dir(base: Path, key: str,
                       build_fn: Callable[[Path], dict[str, Any]],
                       ) -> tuple[Path, dict[str, Any]]:
    """同 invocation 内同 key 只构建一次：staging 构建 → 原子改名进位。

    并发/xdist 多 worker 竞速时败者弃 staging 复用胜者产物（目录改名是
    提交点；manifest 原子写先于改名，目录可见即 manifest 完整）。
    """
    base.mkdir(parents=True, exist_ok=True)
    final = base / key
    manifest_path = base / f"{key}.manifest.json"
    if final.is_dir():
        return final, _read_manifest(manifest_path)
    staging = Path(tempfile.mkdtemp(prefix=f".staging-{key}-", dir=base))
    try:
        manifest = build_fn(staging)
        if final.is_dir():  # 构建期间他方已提交——弃 staging 复用（双检）
            shutil.rmtree(staging, ignore_errors=True)
            return final, _read_manifest(manifest_path)
        # manifest 原子写（tmp+os.replace）：败者与胜者内容确定性一致，
        # 原子替换保证读者只见完整文件，无半写撕裂窗
        manifest_tmp = base / f"{key}.manifest.json.{os.getpid()}.tmp"
        manifest_tmp.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
        os.replace(manifest_tmp, manifest_path)
        try:
            os.replace(staging, final)
        except OSError:
            if not final.is_dir():
                raise
            shutil.rmtree(staging, ignore_errors=True)  # 竞速败者复用胜者
            return final, _read_manifest(manifest_path)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)  # 失败不留半成品
        raise
    return final, manifest


def _maybe_prebuilt(key: str) -> RegenBuild | None:
    """门 prebuild 消费口（W1-3）：env 指向预构建根目录时返回其下 key 产物。

    env 未设 → None（走原构建路径，缺省行为不变）；env 设了但产物/manifest
    缺席 → RuntimeError（门契约破坏，如实红不静默自建）。manifest 读取与
    自建缓存同源（_read_manifest），消费者断言面零变化。"""
    root = os.environ.get(REGEN_FROM_ENV)
    if not root:
        return None
    base = Path(root)
    directory = base / key
    if not directory.is_dir():
        raise RuntimeError(
            f"{REGEN_FROM_ENV}={root} 缺 {key}/ 产物目录——门 prebuild 契约"
            "破坏（如实红，不静默回退自建）")
    return RegenBuild(directory=directory,
                      manifest=_read_manifest(base / f"{key}.manifest.json"))


def _docs_site_product(tmp_root: Path) -> RegenBuild:
    """docs_site 产物获取单源（夹具薄壳的实体；env 消费口优先，白盒可测）。"""
    pre = _maybe_prebuilt("docs_site")
    if pre is not None:
        return pre
    build_docs_pages = _load_module(
        "_regen_shared_build_docs_pages", _REPO / "scripts" / "build_docs_pages.py")

    def _build(out: Path) -> dict[str, Any]:
        return build_docs_pages.build_all(out)

    directory, manifest = _atomic_shared_dir(
        tmp_root / "regen_shared", "docs_site", _build)
    return RegenBuild(directory=directory, manifest=manifest)


def _kernel_cards_product(tmp_root: Path) -> RegenBuild:
    """kernel_cards 产物获取单源（夹具薄壳的实体；env 消费口优先）。"""
    pre = _maybe_prebuilt("kernel_cards")
    if pre is not None:
        return pre
    gen = _load_module(
        "_regen_shared_build_kernel_cards", _REPO / "scripts" / "build_kernel_cards.py")

    def _build(out: Path) -> dict[str, Any]:
        written = gen.build(out)
        return {"written": written}

    directory, manifest = _atomic_shared_dir(
        tmp_root / "regen_shared", "kernel_cards", _build)
    return RegenBuild(directory=directory, manifest=manifest)


@pytest.fixture(scope="session")
def docs_site_fresh(tmp_path_factory: pytest.TempPathFactory) -> RegenBuild:
    """docs_site 生成器产物（session 级单次构建，三消费文件共享）。

    manifest=build_all 真实返回值（计数同源锚，test_docs_site 消费）；
    产物目录只读（变异测试一律走副本）。env RFAUTO_DOCREGEN_FROM 在场时
    直接消费门 prebuild 产物（W1-3 跨段收敛，构建计数 0）。"""
    return _docs_site_product(tmp_path_factory.getbasetemp())


@pytest.fixture(scope="session")
def kernel_cards_fresh(tmp_path_factory: pytest.TempPathFactory) -> RegenBuild:
    """kernel_cards 生成器产物（session 级单次构建，三消费文件共享）。

    build_kernel_cards.build 内含 render_all()（构建期校验 validate_all
    随之执行一次）；产物目录只读，消费者纯读比对面。env
    RFAUTO_DOCREGEN_FROM 在场时直接消费门 prebuild 产物（构建计数 0）。"""
    return _kernel_cards_product(tmp_path_factory.getbasetemp())
