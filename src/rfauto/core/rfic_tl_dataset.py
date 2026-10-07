"""PB-1 RFIC-TL 公开基准数据集 loader（外部对拍基准载体，纯读取零上游代码依赖）。

数据源（研究扩充 round5 §4.1 PB-1）：IMS 2024
「Transfer Learning Assisted Fast Design Migration Over Technology Nodes」
（arXiv:2502.18636；GitHub ChenhaoChu/RFIC-TL，Apache-2.0 含示例数据集）。
数据 = 1:1 片上变压器匹配网络的参数化 EM 扫描：输入 = 设计参数 x（匹配
电容 C1/C2 + 目标阻抗 Zin 实/虚部），输出 = 电路参数 y（Lp/Ls/k/SRF/Qp/Qs）
与物理参数 z（线圈宽度/半径/馈线几何）；按「工艺节点 × 金属选项 × 频率」
分目录（node）存放，频率是节点级标量（从目录名解析），非逐样本轴。

基准协议（跨节点迁移，本模块 docstring 契约）：训练集按节点整域排除测试
节点（source→target 迁移口径；论文核心主张 = 跨节点迁移 4× 降数据）。
train_test_split_by_node 保证 train/test 节点集交为空且由构造即无泄漏。
上游 train.py 的节点内随机 6:2:2 划分（utils.get_loader）是节点内口径，
与本基准的跨节点协议正交，勿混用。

provenance 诚实性（#122 不凑绿 / #331 观察不失真）：
- 数据是上游 README 声明的「虚构工艺（fictitious process NodeA/NodeB）
  示例数据」——真实 foundry PDK 训练数据不公开；本 loader 只作外部对拍
  基准载体，不做工艺真实性声明。
- 列序 caveat：上游 README 写 x 列为 [C1, C2, RealZin, ImageZin]，而生成
  发布 npy 的 preprocess.py:26 为 [C2, C1, RealZin, ImageZin]——C1/C2 量纲
  与范围相同（10~300），仅标签顺序上游自身不一致；本 loader 按
  preprocess.py（发布数据实际生成代码）口径标注，并在 provenance 记录
  该矛盾，消费者不得依赖 C1/C2 标签做语义区分。
- 单位：仅 SRF 上游声明为 GHz；k/Q 无量纲（物理定义）；其余列上游未声明
  单位，units 记 UNSTATED（量级推断写注释，不作权威口径）。

数据获取（工作区快照，gitignored 不入库）：本仓快照 =
``git clone --depth 1 https://github.com/ChenhaoChu/RFIC-TL.git
runs/pb1_rfic_tl/upstream``（2026-09-26 实测，commit 见
RFIC_TL_SNAPSHOT_COMMIT）；他机可重放同一命令。

消费方：
- tests/unit/test_rfic_tl_dataset.py（数据在盘时 schema 钉 + 按节点划分
  无泄漏钉 + numpy 岭回归跨节点最小基线；数据不在盘诚实 skip）
- surrogate_loop 公开基准 / GP 通道外部对拍接线留后续（service 层，本
  模块保持 core 纯函数、不进 calculators 注册表）。
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Sequence
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# provenance 常量（出处/许可/快照，2026-09-26 实测）
# ---------------------------------------------------------------------------

RFIC_TL_SOURCE_URL = "https://github.com/ChenhaoChu/RFIC-TL"
RFIC_TL_LICENSE = "Apache-2.0"
RFIC_TL_ARXIV = "arXiv:2502.18636"
RFIC_TL_CITATION = (
    "Chu, C., Mao, Y., Wang, H., 'Transfer Learning Assisted Fast Design "
    "Migration Over Technology Nodes: A Study on Transformer Matching "
    "Network', IMS 2024, pp. 188-191, doi:10.1109/IMS40175.2024.10600344"
)
RFIC_TL_SNAPSHOT_COMMIT = "41d8aac60913017ebe22fa0b472e2e8561f5f2f3"
RFIC_TL_SNAPSHOT_DATE = "2026-09-26"

# ---------------------------------------------------------------------------
# schema（列序按上游 preprocess.py:26-28 —— 发布 npy 的实际生成代码，非 README）
# ---------------------------------------------------------------------------

X_COLUMNS: tuple[str, ...] = ("C2", "C1", "RealZin", "ImageZin")
Y_COLUMNS: tuple[str, ...] = ("Lp", "Ls", "k", "SRF", "Qp", "Qs")
Z_COLUMNS: tuple[str, ...] = ("wlow", "wup", "r0", "r1", "xgnd", "lfeed")

EXPECTED_WIDTHS: dict[str, int] = {"x": 4, "y": 6, "z": 6}
BLOCK_COLUMNS: dict[str, tuple[str, ...]] = {"x": X_COLUMNS, "y": Y_COLUMNS, "z": Z_COLUMNS}

UNSTATED = "unstated_upstream"

# 单位口径（诚实标注：stated=上游声明；dimensionless=物理定义；其余 UNSTATED）
UNITS: dict[str, dict[str, str]] = {
    "x": {"C2": UNSTATED, "C1": UNSTATED, "RealZin": "ohm", "ImageZin": "ohm"},
    "y": {
        "Lp": UNSTATED,
        "Ls": UNSTATED,
        "k": "dimensionless",
        "SRF": "GHz",
        "Qp": "dimensionless",
        "Qs": "dimensionless",
    },
    "z": {c: UNSTATED for c in Z_COLUMNS},
}
UNIT_NOTES: dict[str, str] = {
    "C1_C2": (
        "上游未声明单位；数值范围 10~300，毫米波匹配电容的 fF 量级——"
        "量级推断，非权威口径"
    ),
    "Lp_Ls": (
        "上游未声明单位；数值范围 ~87~459，毫米波片上变压器线圈的 pH 量级——"
        "量级推断，非权威口径"
    ),
    "z_geometry": (
        "上游未声明单位；数值范围 2~100，版图几何长度的 um 量级——"
        "量级推断，非权威口径"
    ),
}

_NODE_RE = re.compile(
    r"^node(?P<process>[^_]+)_(?P<metal>[^_]+)_(?P<freq>\d+(?:\.\d+)?)GHz$"
)

_DATA_FILES = ("x_data.npy", "y_data.npy", "z_data.npy")


def parse_node_name(name: str) -> dict:
    """解析节点目录名 → {process, metal, frequency_ghz}。

    目录名格式（实测上游 5 个节点全符合）：
    ``node{process}_{metal}_{freq}GHz``，如 ``nodeB_GNVT_39GHz``。

    Raises
    ------
    ValueError
        目录名不符合上游命名格式（不猜测语义，如实报错）。
    """
    m = _NODE_RE.match(name)
    if m is None:
        raise ValueError(
            f"RFIC-TL 节点目录名 {name!r} 不符合 "
            "'node{process}_{metal}_{freq}GHz' 上游命名格式"
        )
    return {
        "process": f"node{m.group('process')}",
        "metal": m.group("metal"),
        "frequency_ghz": float(m.group("freq")),
    }


def _resolve_data_dir(root: str | Path) -> Path:
    """收敛入参为数据目录（#140：PathLike 入参第一行先 Path()）。

    接受三种形态：上游仓库根（含 data/ 子目录）、data/ 目录本身、
    或任何直接包含节点目录的目录。
    """
    root = Path(root)
    if (root / "data").is_dir():
        return root / "data"
    return root


def discover_nodes(root: str | Path) -> list[str]:
    """发现数据目录下的全部节点名（纯文件系统操作，不加载数组）。

    节点判定 = 子目录同时含 x/y/z_data.npy（.DS_Store 等噪声文件忽略）。
    返回排序后的节点名列表。
    """
    data_dir = _resolve_data_dir(root)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"RFIC-TL 数据目录不存在: {data_dir}")
    names = [
        p.name
        for p in sorted(data_dir.iterdir())
        if p.is_dir() and all((p / f).is_file() for f in _DATA_FILES)
    ]
    if not names:
        raise FileNotFoundError(f"RFIC-TL 数据目录下未发现节点目录: {data_dir}")
    return names


def _column_ranges(arr: np.ndarray, columns: tuple[str, ...]) -> dict[str, list]:
    """逐列 [min, max]（全 NaN 列如实记 [None, None]，不臆造数值）。"""
    ranges: dict[str, list] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # 全 NaN 列的 nanmin 告警
        for j, col in enumerate(columns):
            colvals = arr[:, j]
            if np.isnan(colvals).all():
                ranges[col] = [None, None]
            else:
                ranges[col] = [float(np.nanmin(colvals)), float(np.nanmax(colvals))]
    return ranges


def load_rfic_tl(root: str | Path, *, nodes: Sequence[str] | None = None) -> dict:
    """加载 RFIC-TL 公开基准数据集。

    Parameters
    ----------
    root : str | Path
        上游仓库根（含 ``data/``）或数据目录本身。典型取法
        ``<repo>/runs/pb1_rfic_tl/upstream``。
    nodes : Sequence[str] | None
        只加载指定节点（None = 全部）。未知节点名报 ValueError。

    Returns
    -------
    dict
        ``{"schema", "provenance", "summary", "nodes"}``。每个节点含
        x/y/z float32 数组（N×4 / N×6 / N×6）、n_samples、逐列 ranges、
        nan_counts 与从目录名解析的 process/metal/frequency_ghz。

    Raises
    ------
    ValueError
        x/y/z 形状不一致、列宽不符 schema、含非有限值（上游实测 0 NaN，
        出现即数据损坏，如实拒绝而非静默裁剪）。
    """
    data_dir = _resolve_data_dir(root)
    available = discover_nodes(data_dir)
    if nodes is None:
        selected = list(available)
    else:
        selected = list(nodes)
        unknown = [n for n in selected if n not in available]
        if unknown:
            raise ValueError(f"未知 RFIC-TL 节点: {unknown}；可用节点: {available}")

    loaded: dict[str, dict] = {}
    total = 0
    for name in selected:
        node_dir = data_dir / name
        arrays = {k: np.load(node_dir / f"{k}_data.npy") for k in ("x", "y", "z")}
        for k, arr in arrays.items():
            if arr.ndim != 2 or arr.shape[1] != EXPECTED_WIDTHS[k]:
                raise ValueError(
                    f"节点 {name} 的 {k}_data.npy 形状 {arr.shape} 不符 schema "
                    f"(N, {EXPECTED_WIDTHS[k]})"
                )
            n = int(arrays["x"].shape[0])
            if arr.shape[0] != n:
                raise ValueError(
                    f"节点 {name} 的 {k}_data.npy 行数 {arr.shape[0]} 与 x 行数 {n} 不一致"
                )
            nan_count = int((~np.isfinite(arr)).sum())
            if nan_count:
                raise ValueError(
                    f"节点 {name} 的 {k}_data.npy 含 {nan_count} 个非有限值"
                    "（上游实测 0 NaN，出现即数据损坏）"
                )
        meta = parse_node_name(name)
        loaded[name] = {
            "process": meta["process"],
            "metal": meta["metal"],
            "frequency_ghz": meta["frequency_ghz"],
            "x": arrays["x"],
            "y": arrays["y"],
            "z": arrays["z"],
            "n_samples": int(arrays["x"].shape[0]),
            "ranges": {
                k: _column_ranges(arrays[k], BLOCK_COLUMNS[k]) for k in ("x", "y", "z")
            },
        }
        total += loaded[name]["n_samples"]

    provenance = {
        "source_url": RFIC_TL_SOURCE_URL,
        "source_commit_snapshot": RFIC_TL_SNAPSHOT_COMMIT,
        "snapshot_date": RFIC_TL_SNAPSHOT_DATE,
        "license": RFIC_TL_LICENSE,
        "arxiv": RFIC_TL_ARXIV,
        "citation": RFIC_TL_CITATION,
        "data_release_note": (
            "上游 README 声明：真实 foundry PDK 训练数据为专有；本数据集为"
            "虚构工艺（fictitious process NodeA/NodeB）示例数据"
        ),
        "frequency_axis_note": (
            "频率是节点级标量（从目录名解析 frequency_ghz），"
            "本数据集无逐样本频率轴"
        ),
        "column_order_caveat": (
            "上游 README 写 x 列为 [C1, C2, RealZin, ImageZin]，而生成发布 "
            "npy 的 preprocess.py:26 为 [C2, C1, RealZin, ImageZin]——C1/C2 "
            "仅标签顺序上游自身不一致；本 loader 按 preprocess.py 口径标注，"
            "消费者不得依赖 C1/C2 标签做语义区分"
        ),
        "units": UNITS,
        "unit_notes": UNIT_NOTES,
    }
    schema = {
        "x_columns": list(X_COLUMNS),
        "y_columns": list(Y_COLUMNS),
        "z_columns": list(Z_COLUMNS),
        "dtype": "float32",
        "x_width": EXPECTED_WIDTHS["x"],
        "y_width": EXPECTED_WIDTHS["y"],
        "z_width": EXPECTED_WIDTHS["z"],
    }
    return {
        "schema": schema,
        "provenance": provenance,
        "summary": {
            "n_nodes": len(selected),
            "n_samples_total": total,
            "node_names": list(selected),
        },
        "nodes": loaded,
    }


def train_test_split_by_node(
    data: dict,
    test_nodes: Sequence[str],
    *,
    target: str = "y",
) -> dict:
    """按节点划分训练/测试集（跨节点迁移基准协议，构造级无泄漏）。

    协议（该基准的核心口径）：**训练集整域排除全部测试节点**——
    source→target 迁移评测中，测试节点（目标域）的任何样本都不得进入
    训练集；节点内随机划分（上游 train.py 口径）与本协议正交，混用即
    泄漏（同域信息流入目标域评测）。

    Parameters
    ----------
    data : dict
        :func:`load_rfic_tl` 的返回值（或同构 dict，含 "nodes" 键）。
    test_nodes : Sequence[str]
        作为测试域（目标节点）的节点名，须全部存在于 data["nodes"]。
    target : str
        回归目标块："y"（电路参数，默认）或 "z"（物理参数）。

    Returns
    -------
    dict
        ``{"x_train", "y_train", "x_test", "y_test", "train_nodes",
        "test_nodes", "target"}``；train/test 节点集交为空由构造保证
        （仍显式断言，防调用方传入被篡改的 data）。
    """
    all_nodes = data.get("nodes")
    if not isinstance(all_nodes, dict) or not all_nodes:
        raise ValueError("data 缺少非空 'nodes' 字典（须为 load_rfic_tl 返回值或同构）")
    if target not in ("y", "z"):
        raise ValueError(f"target 须为 'y' 或 'z'，收到 {target!r}")
    test_list = list(test_nodes)
    if not test_list:
        raise ValueError("test_nodes 不能为空（跨节点协议至少需要一个目标节点）")
    unknown = [n for n in test_list if n not in all_nodes]
    if unknown:
        raise ValueError(f"未知测试节点: {unknown}；可用节点: {list(all_nodes)}")

    train_names = [n for n in all_nodes if n not in set(test_list)]
    if not train_names:
        raise ValueError("全部节点都被划入测试集，训练集为空——跨节点协议不允许")

    def _stack(names: list[str], x_key: str, y_key: str) -> tuple[np.ndarray, np.ndarray]:
        xs = [all_nodes[n][x_key] for n in names]
        ys = [all_nodes[n][y_key] for n in names]
        return np.vstack(xs), np.vstack(ys)

    x_train, y_train = _stack(train_names, "x", target)
    x_test, y_test = _stack(test_list, "x", target)

    # 构造级无泄漏的显式断言（防上游 dict 被篡改后静默泄漏）
    assert not (set(train_names) & set(test_list)), "train/test 节点集交必须为空"

    return {
        "x_train": x_train,
        "y_train": y_train,
        "x_test": x_test,
        "y_test": y_test,
        "train_nodes": train_names,
        "test_nodes": test_list,
        "target": target,
    }
