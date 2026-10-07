"""AI-5 公开数据集锚扩展锚测试（round14 :70，2026-10-02）。

锚口径（任务书预声明）：不联网下数据 → 落地形态=schema+加载器骨架+
UNVERIFIED 标注；round14 未给文献数值 → **零数值断言、不编数**——本
测试反过来钉"没有编数"（全锚 UNVERIFIED、literature_values 空、
dataset_id 只到 round 文档给到的精度）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.public_dataset_anchors import (
    PUBLIC_DATASET_ANCHORS,
    list_public_dataset_anchors,
    load_s11_table,
)

_ROUND14_KEYS = {"kaggle_patch_antenna", "mendeley_3gxr2vvd9n",
                 "ieee_dataport_s11"}


# ─── 注册面：round14 清单全量 + 不编数钉 ─────────────────────────────────

def test_registry_has_round14_three_anchors():
    assert set(PUBLIC_DATASET_ANCHORS) >= _ROUND14_KEYS
    assert set(PUBLIC_DATASET_ANCHORS) == _ROUND14_KEYS  # 登记面恰满


def test_all_anchors_unverified_and_value_free():
    """诚实纪律（#122）：round14 未给数值 → 全 UNVERIFIED、零占位数。"""
    for key, anchor in PUBLIC_DATASET_ANCHORS.items():
        assert anchor.status == "UNVERIFIED", key
        assert anchor.literature_values == (), (
            f"{key}: literature_values 非空=编数嫌疑（round14 未给值）")
        assert anchor.access_note, key  # 获取方式注记在（零下载口径）


def test_dataset_id_precision_is_honest():
    """dataset_id 只到 round14 给到的精度：mendeley 有 id，其余留空不猜。"""
    assert PUBLIC_DATASET_ANCHORS["mendeley_3gxr2vvd9n"].dataset_id \
        == "3gxr2vvd9n"
    assert PUBLIC_DATASET_ANCHORS["kaggle_patch_antenna"].dataset_id == ""
    assert PUBLIC_DATASET_ANCHORS["ieee_dataport_s11"].dataset_id == ""
    sources = {a.source for a in PUBLIC_DATASET_ANCHORS.values()}
    assert sources == {"kaggle", "mendeley", "ieee_dataport"}


def test_list_face_json_ready():
    listing = list_public_dataset_anchors()
    assert listing["ok"] is True
    assert listing["n_anchors"] == len(_ROUND14_KEYS)
    assert listing["n_verified"] == 0  # 升格路径未启用前的诚实计数
    json.dumps(listing, ensure_ascii=False, allow_nan=False)


# ─── 加载器骨架：本地 CSV 双方言 + 显式报错面 ────────────────────────────

def _write_csv(tmp_path: Path, name: str, lines: list[str]) -> str:
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def test_loader_cartesian_dialect(tmp_path):
    p = _write_csv(tmp_path, "s11_cart.csv", [
        "freq_hz,s11_re,s11_im",
        "2.4e9,-0.5,0.1",
        "2.401e9,-0.45,0.12",
    ])
    out = load_s11_table(p)
    assert out["dialect"] == "cartesian" and out["n_points"] == 2
    assert out["freq_hz"][0] == pytest.approx(2.4e9)
    assert out["s11_real"][0] == pytest.approx(-0.5)
    assert out["s11_imag"][0] == pytest.approx(0.1)


def test_loader_db_dialect_converts_amplitude(tmp_path):
    p = _write_csv(tmp_path, "s11_db.csv", [
        "freq_hz,s11_db",
        "1.0e9,-20.0",
        "2.0e9,-40.0",
    ])
    out = load_s11_table(p)
    assert out["dialect"] == "db"
    assert out["s11_real"][0] == pytest.approx(0.1)   # 10^(−20/20)
    assert out["s11_real"][1] == pytest.approx(0.01)  # 10^(−40/20)
    # dB 方言无相位 → imag 如实 None 路径（不伪造 0）
    assert all(v is None for v in out["s11_imag"])


def test_loader_validation_errors(tmp_path):
    with pytest.raises(FileNotFoundError, match="零下载"):
        load_s11_table(tmp_path / "nope.csv")
    bad_header = _write_csv(tmp_path, "bad_header.csv", [
        "f,s11", "1e9,0.1"])
    with pytest.raises(ValueError, match="表头不符"):
        load_s11_table(bad_header)
    ragged = _write_csv(tmp_path, "ragged.csv", [
        "freq_hz,s11_re,s11_im", "2.4e9,-0.5"])
    with pytest.raises(ValueError, match="残缺"):
        load_s11_table(ragged)
    nonfinite = _write_csv(tmp_path, "nan.csv", [
        "freq_hz,s11_re,s11_im", "2.4e9,nan,0.1"])
    with pytest.raises(ValueError, match="非有限"):
        load_s11_table(nonfinite)
    bad_freq = _write_csv(tmp_path, "freq.csv", [
        "freq_hz,s11_re,s11_im", "-1.0,-0.5,0.1"])
    with pytest.raises(ValueError, match="频点必须为正"):
        load_s11_table(bad_freq)
    empty = _write_csv(tmp_path, "empty.csv", [])
    with pytest.raises(ValueError, match="为空"):
        load_s11_table(empty)


def test_loader_zero_network_by_ast():
    """零网络面：AST 双查 Import 目标（#270 同源纪律）。"""
    src = (SRC / "rfauto" / "core" / "public_dataset_anchors.py").read_text(
        "utf-8")
    tree = ast.parse(src)
    banned = {"urllib", "requests", "http", "httpx", "socket"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] not in banned for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in banned
