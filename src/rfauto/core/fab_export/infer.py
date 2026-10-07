"""从变量名自动推断角色/公差类（减少人工配置）.

已知局限（审查项 R12，如实记录不静默修）：``r\\d`` 规则会把含
``r<数字>`` 子串的名字（如 ``wr90_len``）判为 free——金样 WR90 变量
显式给 roles/tol_classes 时不受影响；要精确请显式配置。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# 名称 → (role, tol_class) 优先序：精确 → 前缀/包含
_EXACT = {
    "a": ("rf_critical", "WG_AB"),
    "b": ("rf_critical", "WG_AB"),
    "iris_w": ("rf_critical", "IRIS"),
    "iris_t": ("rf_critical", "IRIS"),
    "iris_h": ("rf_critical", "IRIS"),
    "h_cavity": ("rf_critical", "CAV_H"),
    "h_iris": ("rf_critical", "IRIS"),
    "w_iris": ("rf_critical", "IRIS"),
    "t_iris": ("rf_critical", "IRIS"),
    "l": ("assembly", "FREE"),
    "length": ("assembly", "FREE"),
    "wall": ("free", "FREE"),
    "t_wall": ("free", "FREE"),
}

_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"^a$|^b$|_a$|_b$|waveguide|wg_", re.I), "rf_critical", "WG_AB"),
    (re.compile(r"iris|coupl|window|膜|耦合", re.I), "rf_critical", "IRIS"),
    (re.compile(r"cavity|h_cav|reson", re.I), "rf_critical", "CAV_H"),
    (re.compile(r"thz|w_?thz", re.I), "rf_critical", "THz"),
    (re.compile(r"pin|dowel|定位销", re.I), "assembly", "PIN_H7"),
    (re.compile(r"flange|法兰", re.I), "assembly", "FLAT_FLANGE"),
    (re.compile(r"thread|m\d|螺纹", re.I), "assembly", "THD"),
    (re.compile(r"^l$|^w$|^h$|length|width|height|len|总长|总宽|总高", re.I), "assembly", "FREE"),
    (re.compile(r"wall|thk|thick|厚", re.I), "free", "FREE"),
    (re.compile(r"r\d|fillet|round|圆角|倒角", re.I), "free", "FREE"),
]


def infer_role_and_tol(name: str) -> tuple[str, str]:
    key = name.strip()
    low = key.lower()
    if low in _EXACT:
        return _EXACT[low]
    for pat, role, tol in _RULES:
        if pat.search(low) or pat.search(key):
            return role, tol
    return "free", "FREE"


def infer_mapping(names: Iterable[str]) -> dict[str, tuple[str, str]]:
    return {n: infer_role_and_tol(n) for n in names}


def split_mapping(names: Iterable[str]) -> tuple[dict[str, str], dict[str, str]]:
    roles: dict[str, str] = {}
    tols: dict[str, str] = {}
    for n, (r, t) in infer_mapping(names).items():
        roles[n] = r
        tols[n] = t
    return roles, tols
