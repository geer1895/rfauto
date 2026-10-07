"""标准尺寸库：WR/BJ 波导、法兰、嘉立创配合公差、Kerr 规则（L0 纯数据）.

数值来源见原型 docs/调研附录.md（O=公开产品表，K=行业共识，合同前核实）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WaveguideSpec:
    name: str
    bj: str
    iec: str
    a: float  # 内宽 mm
    b: float  # 内高 mm
    r1: float  # 内圆角
    A: float  # 外宽
    B: float  # 外高
    t: float  # 壁厚
    freq_ghz: tuple[float, float]
    evidence: str = "O"
    r2: tuple[float, float] = (0.65, 1.15)  # 外圆角范围（细则 §1.1，管材典型）

    def outer_loop_params(self) -> tuple[float, float, float]:
        """(A, B, t)."""
        return self.A, self.B, self.t


# 全系列可按需扩展；WR-90/BJ100 为金样默认
WAVEGUIDES: dict[str, WaveguideSpec] = {
    "WR-90": WaveguideSpec("WR-90", "BJ100", "R100", 22.86, 10.16, 0.8, 25.4, 12.7, 1.27, (8.2, 12.5)),
    "BJ100": WaveguideSpec("WR-90", "BJ100", "R100", 22.86, 10.16, 0.8, 25.4, 12.7, 1.27, (8.2, 12.5)),
    "WR-112": WaveguideSpec("WR-112", "BJ84", "R84", 28.499, 12.624, 0.8, 31.75, 15.88, 1.27, (7.05, 10.0)),
    "BJ84": WaveguideSpec("WR-112", "BJ84", "R84", 28.499, 12.624, 0.8, 31.75, 15.88, 1.27, (7.05, 10.0)),
    "WR-28": WaveguideSpec("WR-28", "BJ320", "R320", 7.112, 3.556, 0.5, 8.51, 4.75, 0.64, (26.5, 40.0)),
}


@dataclass(frozen=True)
class FlangeSpec:
    name: str
    family: str
    outer: float
    thickness: float
    bolt_count: int
    bolt_dia: float
    bolt_pcd_x: float
    bolt_pcd_y: float
    pin_dia: float
    pin_count: int
    flatness: float
    evidence: str = "K"
    note: str = ""
    perpendicularity: float = 0.05  # 对轴线垂直度 mm/100mm（细则 §1.1b [K]）


FLANGES: dict[str, FlangeSpec] = {
    # 孔系为行业典型 [K]，发图前对照厂家图
    "FBP100": FlangeSpec(
        "FBP100", "B-square-flat", 30.0, 6.0, 4, 3.2, 25.4, 25.4, 2.5, 2, 0.03,
        note="UBR100 方形平法兰",
    ),
    "UG-39": FlangeSpec(
        "UG-39/U", "cover-square", 30.0, 6.0, 4, 3.2, 25.4, 25.4, 2.5, 2, 0.02,
        note="方盖；发前核 TD-00077",
    ),
    "UG-84": FlangeSpec(
        "UG-84/U", "choke", 30.0, 6.0, 4, 3.2, 25.4, 25.4, 2.5, 2, 0.02,
        note="扼流槽 ≈ λg/4",
    ),
}

# 嘉立创公开配合带（参考，非 RF 专属）
FIT_BANDS_MM: dict[str, tuple[float, float]] = {
    "press_interference": (-0.02, -0.01),
    "location": (0.0, 0.01),
    "plug": (0.02, 0.05),
    "clearance_general": (0.05, 0.10),
    "slide_or_large": (0.05, 0.20),
}

FINISH_ONE_SIDE_MM: dict[str, tuple[float, float]] = {
    "anodize": (0.005, 0.008),
    "hard_anodize": (0.02, 0.04),
    "paint": (0.03, 0.10),
}

KERR_RULES = {
    "linear_tol_pct": 0.5,
    "corner_r_max_frac_of_a": 0.10,
    "flange_misalign_pct": 3.0,
    "flange_misalign_deg": 6.0,
}

DEFAULT_PROCESS_TAGS = {
    "iris": "WEDM",
    "deep_slot": "WEDM",
    "pocket": "3-axis",
    "thread": "tap",
}


def get_waveguide(name: str) -> WaveguideSpec:
    key = name.strip().upper().replace(" ", "")
    if key not in WAVEGUIDES:
        raise KeyError(f"unknown waveguide {name!r}; known: {sorted(WAVEGUIDES)}")
    return WAVEGUIDES[key]


def get_flange(name: str) -> FlangeSpec:
    key = name.strip()
    for k, v in FLANGES.items():
        if key.upper() == k.upper() or key.upper() in v.name.upper():
            return v
    raise KeyError(f"unknown flange {name!r}")


def catalog_tables() -> dict[str, Any]:
    return {
        "waveguides": {
            k: {
                "bj": v.bj,
                "a": v.a,
                "b": v.b,
                "A": v.A,
                "B": v.B,
                "t": v.t,
                "freq_ghz": v.freq_ghz,
                "evidence": v.evidence,
                "r1": v.r1,
                "r2": v.r2,
            }
            for k, v in WAVEGUIDES.items()
        },
        "flanges": {
            k: {
                "outer": v.outer,
                "thickness": v.thickness,
                "bolt": f"{v.bolt_count}x{v.bolt_dia} pcd {v.bolt_pcd_x}x{v.bolt_pcd_y}",
                "pin": f"{v.pin_count}x{v.pin_dia}",
                "flatness": v.flatness,
                "perpendicularity_mm_per_100": v.perpendicularity,
                "evidence": v.evidence,
            }
            for k, v in FLANGES.items()
        },
        "fit_bands_mm": FIT_BANDS_MM,
        "finish_one_side_mm": FINISH_ONE_SIDE_MM,
        "kerr": KERR_RULES,
    }
