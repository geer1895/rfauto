"""激励盒内缩守卫（#253 单源 raise 型，审查 R4-2）。

背景（#253，2026-09-17 排空六轮二批）：openEMS 激励盒跨满吸收边界截面 →
"Excitation inside Mur-ABC" 延迟开启瞬态激起零模 DC 漂移（15ns 内涨到信号
10 倍）——激励盒/激励面到吸收边界的内缩必须 ≥2·BASE。

R4-2 缺口：该口径此前无统一 raise 型守卫——slotline 族只有起跑审计记录键
（render_slotline marchand2 脚本 ``excite_inset_ge2base`` 落 audit_mesh.json，
靠下游消费），metasurface/siw 是字面量口径（λ0/16、16·BASE 注释）。新模板
接入若照抄缺省可能静默内缩不足。本模块 = 单源判定（不足即 ValueError，
带两值与 #253 引用，#347/#266 渲染期守卫先例）。

约定：本守卫只做校验、不改几何（渲染面字节不变性）；内缩本就不足的模板
接入后如实 FAIL——这正是守卫意义。
"""

from __future__ import annotations

#: #253 内缩下界系数（×BASE）
EXCITATION_INSET_MIN_BASE = 2.0


def assert_excitation_inset(inset_m: float, base_m: float, *,
                            label: str = "激励盒") -> None:
    """校验激励盒/激励面到吸收边界的内缩 ≥2·BASE，不足即 ValueError。

    Args:
        inset_m: 激励面/盒沿激励轴到最近吸收边界（MUR/PML）的内缩距离（米）。
        base_m: 网格 BASE 尺度（米，与渲染脚本同参单源）。
        label: 守卫位置描述（进报错文本，便于定位模板/通道）。

    Raises:
        ValueError: inset < 2·BASE（含两值与 #253 引用）。
    """
    floor_m = EXCITATION_INSET_MIN_BASE * base_m
    if not (float(inset_m) >= floor_m):
        raise ValueError(
            f"{label}: 激励盒内缩 {float(inset_m) * 1e3:.4g}mm < "
            f"{EXCITATION_INSET_MIN_BASE:g}·BASE={floor_m * 1e3:.4g}mm"
            f"（BASE={float(base_m) * 1e3:.4g}mm，#253：激励盒跨满吸收边界"
            "截面会激起 Mur-ABC 延迟开启零模 DC 漂移）——加大内缩或加密网格")
