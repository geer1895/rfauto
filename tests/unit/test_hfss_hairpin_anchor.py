"""hfss_hairpin_anchor.analyze_line_modes 换算改道 core 单源钉（ge8e W1 A2）。

背景：#307 换算链（Z0e=2·Zc、Z0o=Zd/2，偶模=εeff 较高者）此前在脚本
analyze_line_modes 内联两行（与 core/coupled_mode_z 双轨，审查 R4-4）；
本批改道 core 单源——行为逐位不变，用 runs/hairpin_hfss_anchor 归档读数
回代钉（#118 独立来源回收：归档=真机判读产物，零改写只读）。

脚本经 importlib 直载（test_hfss_hairpin_anchor_c8 先例；main 有
__main__ 守卫，导入零副作用）；analyze_line_modes 是纯函数（port_data
dict 进、dict 出，零 pyaedt 触碰）。注：analyze_line2t_modes 的 Zvi 重构
（Z0e=2·Zvi_even、Z0o=Zvi_odd）是端子级基准（#356⑤），不属本换算链，
本批保持内联不动——不在本测试钉程内。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "_hfss_hairpin_anchor", str(_REPO / "scripts" / "hfss_hairpin_anchor.py"))
assert _SPEC is not None and _SPEC.loader is not None
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

# ── runs/hairpin_hfss_anchor/hairpin_anchor.json verdict.points[gap].
#    line_default_zpi.per_port 归档读数（逐位字面量）→ 原始 port_data 量形
#    重构：Gamma=[alpha_np_m, beta_rad_m]、Zo=[zo_re, zo_im]（脚本解析口径
#    "Gamma(P1sheetP:1)" / "Zo(P1sheetP:1)"，模 3=倏逝框模由传播过滤排除）。──
PORT_DATA_G05 = {
    "P1sheetP": {
        "Gamma(P1sheetP:1)": [0.1565811592553951, 91.45991345615401],
        "Zo(P1sheetP:1)": [29.29093452847607, 0.04904948549050266],
        "Gamma(P1sheetP:2)": [0.1314909821692715, 84.32910765303932],
        "Zo(P1sheetP:2)": [96.74287999125424, 0.1523943472579421],
        "Gamma(P1sheetP:3)": [56.38388849530666, 0.003775814391574193],
        "Zo(P1sheetP:3)": [0.01962605218569626, 50.52912312564224],
    },
    "P2sheetP": {
        "Gamma(P2sheetP:1)": [0.156143085533231, 91.34813651010874],
        "Zo(P2sheetP:1)": [29.00270532574976, 0.04859498329119073],
        "Gamma(P2sheetP:2)": [0.1316388125327364, 84.36726690676056],
        "Zo(P2sheetP:2)": [95.33134104673856, 0.1503381367926255],
        "Gamma(P2sheetP:3)": [56.38586275275318, 0.003768128809137763],
        "Zo(P2sheetP:3)": [0.01867053328342473, 50.46852797407927],
    },
}
ARCHIVED_G05 = {
    "z0e_ohm": 58.29372163361394,
    "z0o_ohm": 48.01861490241117,
    "k_z": 0.09665018252816722,
    "eps_eff_even": 3.04321373136262,
    "eps_eff_odd": 2.5915117440736584,
    "even_mode_index": 1,
    "odd_mode_index": 2,
}

PORT_DATA_G22 = {
    "P1sheetP": {
        "Gamma(P1sheetP:1)": [0.1497995113775095, 89.62322780380404],
        "Zo(P1sheetP:1)": [27.16984110892694, 0.04437635803259227],
        "Gamma(P1sheetP:2)": [0.1423042758342005, 87.48730616618724],
        "Zo(P1sheetP:2)": [105.5037031244552, 0.1711558835552129],
        "Gamma(P1sheetP:3)": [56.36806481140079, 0.003838701925986698],
        "Zo(P1sheetP:3)": [0.02004632536461183, 50.63646480367605],
    },
    "P2sheetP": {
        "Gamma(P2sheetP:1)": [0.1499147817060367, 89.64744761660674],
        "Zo(P2sheetP:1)": [27.13833291467868, 0.04425830282648135],
        "Gamma(P2sheetP:2)": [0.1424449676644115, 87.52572275458387],
        "Zo(P2sheetP:2)": [105.2833796406045, 0.1706199466998454],
        "Gamma(P2sheetP:3)": [56.36834399149543, 0.003837626736979696],
        "Zo(P2sheetP:3)": [0.01980663752521029, 50.62772797285771],
    },
}
ARCHIVED_G22 = {
    "z0e_ohm": 54.30824635251793,
    "z0o_ohm": 52.69683996180072,
    "k_z": 0.015059156963659092,
    "eps_eff_even": 2.9265785007983656,
    "eps_eff_odd": 2.7892178999861628,
    "even_mode_index": 1,
    "odd_mode_index": 2,
}


def _assert_bitwise(out: dict, archived: dict) -> None:
    assert out["ok"] is True
    for key, want in archived.items():
        assert out[key] == want, key  # 逐位（float 恒等，非 approx）


def test_line_modes_replays_archived_g0500_bitwise() -> None:
    _assert_bitwise(mod.analyze_line_modes(PORT_DATA_G05, 0.5), ARCHIVED_G05)


def test_line_modes_replays_archived_g2200_bitwise() -> None:
    _assert_bitwise(mod.analyze_line_modes(PORT_DATA_G22, 2.2), ARCHIVED_G22)


def test_line_modes_routes_through_core(monkeypatch: pytest.MonkeyPatch) -> None:
    """改道钉：analyze_line_modes 经模块级 core 单源符号换算（恰一次调用）。"""
    calls: list[tuple[dict, dict]] = []
    real = mod.dual_conductor_mode_impedances

    def spy(zo_by_mode, eps_eff_by_mode):
        calls.append((dict(zo_by_mode), dict(eps_eff_by_mode)))
        return real(zo_by_mode, eps_eff_by_mode)

    monkeypatch.setattr(mod, "dual_conductor_mode_impedances", spy)
    out = mod.analyze_line_modes(PORT_DATA_G05, 0.5)
    assert out["ok"] is True
    assert len(calls) == 1
    zo, _eps = calls[0]
    assert set(zo) == {1, 2}  # 传播 TEM 对（模 3 倏逝已被过滤）


def test_line_modes_single_tem_mode_rejected_unchanged() -> None:
    """传播 TEM 模数不足 → ok=False 拒判（改道前后行为不变的守卫面）。"""
    broken = {
        pn: {k: v for k, v in qs.items() if not k.endswith(":2)")}
        for pn, qs in PORT_DATA_G05.items()
    }
    out = mod.analyze_line_modes(broken, 0.5)
    assert out["ok"] is False
    assert "传播 TEM 模数" in out["error"]


def test_line_modes_eps_tie_now_rejected_honestly() -> None:
    """εeff 并列：改道后经 core 显式拒绝（此前静默同模双算，拒绝面更诚实）。

    构造：两模 Gamma 同相速（εeff 并列）且均过传播/εeff 窗——换算拒绝，
    走脚本既有 ok=False 误差字典形态（不抛穿）。
    """
    tied = {
        "P1sheetP": {
            "Gamma(P1sheetP:1)": [0.15, 84.0],
            "Zo(P1sheetP:1)": [29.0, 0.0],
            "Gamma(P1sheetP:2)": [0.14, 84.0],
            "Zo(P1sheetP:2)": [96.0, 0.0],
        },
        "P2sheetP": {
            "Gamma(P2sheetP:1)": [0.15, 84.0],
            "Zo(P2sheetP:1)": [29.0, 0.0],
            "Gamma(P2sheetP:2)": [0.14, 84.0],
            "Zo(P2sheetP:2)": [96.0, 0.0],
        },
    }
    out = mod.analyze_line_modes(tied, 0.5)
    assert out["ok"] is False
    assert "换算拒绝" in out["error"]
