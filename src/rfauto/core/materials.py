"""materials.yaml 单点发现/加载器（AU-5：材料加载上移）。

背景：材料表 ``configs/materials.yaml`` 的路径发现逻辑原本散落多处
（core/synthesis.py ``Stackup.from_materials_yaml`` 的 parent×4、
core/dispersion.py ``_materials_path`` 的同款、service/fab_service.py
``_materials_path`` 的 parents[3]、mcp_server ``materials_resource``
的 cwd 相对 ``open("configs/materials.yaml")``）——四处各自拼路径，
env 覆盖无处生效。本模块收敛为单点，其余位置一律薄委托。

发现顺序（resolve_materials_yaml_path）：
1. **显式入参**（调用方 ``materials_path``；公开签名语义不变，优先级最高，
   压过 env——显式参数是代码级意图）。
2. **``RFAUTO_MATERIALS_YAML`` 环境变量**显式路径。设置即信：路径不存在
   直接 FileNotFoundError（**不静默回退**——显式 env 意图被兜底吞掉会把
   错配置伪装成正常）；空串（含纯空白，``strip()`` 后为空）视同未设置。
3. **锚点向上找** ``configs/materials.yaml``：canonical = 本模块 parent×4
   （``src/rfauto/core/`` → 仓根，与原 core/synthesis.py 推导逐位一致，
   同一工作区解析到同一文件）；canonical 未命中再逐级向上（editable 安装/
   嵌套布局兜底），到盘根止。
4. 全部未命中 → 返回 canonical 缺省路径——由调用方按既有文案
   ``FileNotFoundError(f"materials.yaml 不存在: {path}")`` 报错，错误里
   的路径与上移前逐位相同（行为零变化）。

分层论证：import-linter（.importlinter）里 core 是分层叶子，service/
infra 不得被 core 反向依赖——单点加载器必须落 core 层，core/synthesis
（约 80 处 ``Stackup.from_materials_yaml`` 调用的汇聚口）与 core/dispersion
才能零反向依赖地复用；service 层（fab_service/dispersion_service）只做
薄转发保持原函数名与调用方零改动。载入（yaml.safe_load）与路径发现同点
收敛，映射（Stackup/DjordjevicSarkar 构造）留在各域——那是域语义不是发现。

行为不变铁律（AU-5 验收）：env 未设置时，同一工作区解析到与改前相同的
文件路径；材料表内容零变化（tests/unit/test_materials_loader.py 三钉）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "MATERIALS_YAML_ENV",
    "default_materials_yaml_path",
    "load_materials_yaml",
    "resolve_materials_yaml_path",
]

#: 材料表路径覆盖环境变量（设置即信；空串含纯空白视同未设置）。
MATERIALS_YAML_ENV = "RFAUTO_MATERIALS_YAML"

#: canonical 缺省：core/materials.py 位于 <root>/src/rfauto/core/，
#: parents[3] = 仓根（与原 synthesis/dispersion 的 parent×4 同推导）。
_CANONICAL_PARENT_DEPTH = 3

_DEFAULT_RELPATH = Path("configs") / "materials.yaml"


def _anchor() -> Path:
    """发现锚点（本模块文件绝对路径）。"""
    return Path(__file__).resolve()


def _upward_candidates(anchor: Path) -> list[Path]:
    """锚点向上一族的候选路径（canonical 先行，逐级向上到盘根；纯函数）。

    首个元素恒为 canonical（parents[3]，与上移前 synthesis 缺省逐位一致），
    其后是更上层的兜底候选——命中顺序即优先级。
    """
    parents = anchor.parents
    depth = min(_CANONICAL_PARENT_DEPTH, max(len(parents) - 1, 0))
    return [parents[i] / _DEFAULT_RELPATH for i in range(depth, len(parents))]


def default_materials_yaml_path() -> Path:
    """canonical 缺省路径（<root>/configs/materials.yaml；不检查存在性）。"""
    anchor = _anchor()
    return anchor.parents[_CANONICAL_PARENT_DEPTH] / _DEFAULT_RELPATH


def resolve_materials_yaml_path(
    explicit: str | Path | None = None,
) -> Path:
    """按发现顺序解析 materials.yaml 路径（见模块 docstring 顺序 1-4）。

    Args:
        explicit: 调用方显式路径（``None`` 走 env → 向上发现）。

    Returns:
        解析到的路径。全部候选未命中时返回 canonical 缺省路径（调用方
        报 FileNotFoundError 时文案与上移前一致）。
    """
    if explicit is not None:
        return Path(explicit)

    env_path = os.environ.get(MATERIALS_YAML_ENV, "").strip()
    if env_path:
        return Path(env_path)

    candidates = _upward_candidates(_anchor())
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # 全部未命中：回 canonical（错误文案路径与上移前逐位一致）
    return candidates[0] if candidates else default_materials_yaml_path()


def load_materials_yaml(explicit: str | Path | None = None) -> dict[str, Any]:
    """单点加载 materials.yaml 全文档（缺文件抛 FileNotFoundError）。

    Args:
        explicit: 显式路径（``None`` 走 :func:`resolve_materials_yaml_path`）。

    Returns:
        YAML 全文档 dict（空文档为 ``{}``）。

    Raises:
        FileNotFoundError: 解析到的路径不存在（文案
            ``materials.yaml 不存在: <path>``，与上移前一致）。
    """
    path = resolve_materials_yaml_path(explicit)
    if not path.exists():
        raise FileNotFoundError(f"materials.yaml 不存在: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
