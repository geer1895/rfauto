"""G15 物理不变量·通用不变量面（continuation-plan §10.7 G15 / §10.19 第 5 条）。

目标：给确定性内核建"零外部参考的物理预言机"——不依赖任何外部参考数值，
只用**不变量**判真伪。本件承载 **registry 驱动的通用不变量面**：

1. **计算器全键覆盖**：CALCULATOR_REGISTRY 的每个注册键都被实际执行，断言
   通用不变量（ok/有限/逐字节确定/缺参·未知参显式报错）。参数化列表直接取
   注册表，**新增注册键若未补输入表则本测试失败**（输入表+域错误表本体在
   _invariants_helpers，#231"每键输入表"钉点不变）。
2. **越界域守卫**：DOMAIN_ERROR_CASES 逐用例断言显式 ok=False+error。
3. **标量扫描契约**：物理域内任取标量，ok=True 且有限、确定。
4. **S 面分类封闭**：S 面白名单 ∪ skip 清单 == 注册表全集（新键未归类即
   fail）+ reciprocal=False 豁免清单封闭。

aurora_h W2-S4 拆分批（R1 立项 #7）：原 4581 行单件按域拆四——电长度元变
（Maxwell 尺度律/频移等价）见 test_physics_invariants_tl.py；端口网络对称
元变（镜像/置换/互易扫描/叠加/无源）见 test_physics_invariants_rf.py；
预言机自证可失败见 test_physics_invariants_meas.py。拆分铁律：collect 计数
逐位不变（函数名与 parametrize 集合逐位搬移，不改一行断言）。

确定性口径（任务硬约束 4）：Hypothesis 一律 derandomize=True（固定种子），
禁网络、禁真机；本文件只跑 fake/闭式内核。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator
from tests.unit._invariants_helpers import (
    _NO_S_PLANE_KEYS,
    _RECIPROCITY_EXEMPT,
    DOMAIN_ERROR_CASES,
    G15,
    S_PLANE_CALCULATOR_KEYS,
    SCALAR_SWEEPS,
    _calculator_inputs,
    _reciprocity_exempt_names,
    assert_service_result_contract,
)


@pytest.mark.parametrize(
    "name", CALCULATOR_REGISTRY.names(include_experimental=True))
def test_every_registered_calculator_generic_invariants(name: str) -> None:
    """全键覆盖：每个注册键被实际执行并断言通用不变量。

    参数化列表取注册表本身（含实验键）→ 新增键自动进入；输入表缺失即失败，
    保证没有任何注册键"没被执行到"。实验键经 allow_experimental=True 放行——
    本测试裁判的是确定性内核的通用不变量，开关策略由
    test_experimental_calculators.py 单独钉住。
    """
    inputs = _calculator_inputs()
    assert name in inputs, (
        f"注册键 {name!r} 未在 G15 输入表 _calculator_inputs() 中声明——"
        "补输入后每个键才被实际执行（G15 要求全键覆盖）"
    )
    params = dict(inputs[name])

    first = run_calculator(name, params, allow_experimental=True)
    assert_service_result_contract(first)

    # 重复调用逐字节一致（确定性核）
    second = run_calculator(name, params, allow_experimental=True)
    assert json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(
        second, sort_keys=True, allow_nan=False
    ), f"{name} 重复调用结果不一致（非确定性内核）"

    # 非法输入显式报错：未知参数名 → TypeError 被翻译成 ok=False
    bogus = dict(params)
    bogus["g15_bogus_kw"] = 1
    err = run_calculator(name, bogus, allow_experimental=True)
    assert err["ok"] is False and err.get("error"), (
        f"{name} 对未知参数未显式报错: {err!r}"
    )

    # 非法输入显式报错：缺必需参数 → ok=False（service 缺少参数分支）
    spec = CALCULATOR_REGISTRY.get(name)
    if spec.required:
        missing = dict(params)
        missing.pop(spec.required[0])
        err2 = run_calculator(name, missing, allow_experimental=True)
        assert err2["ok"] is False and err2.get("error"), (
            f"{name} 缺必需参数 {spec.required[0]} 未显式报错: {err2!r}"
        )


def test_input_table_covers_registry_bidirectionally() -> None:
    """输入表与注册表双向一致：注册键不多不少（防陈旧行/漏键）。"""
    assert set(_calculator_inputs()) == set(
        CALCULATOR_REGISTRY.names(include_experimental=True))


@pytest.mark.parametrize("name,params", DOMAIN_ERROR_CASES)
def test_domain_errors_are_explicit(name: str, params: dict[str, Any]) -> None:
    """越界输入必须 ok=False + error，不得返回 NaN/异常上抛。"""
    out = run_calculator(name, params, allow_experimental=True)
    assert out["ok"] is False, f"{name} 对越界输入未报错: {out!r}"
    assert out.get("error"), f"{name} 报错缺 error 字段: {out!r}"


@pytest.mark.parametrize("name,param,lo,hi", SCALAR_SWEEPS)
@G15
@given(data=st.data())
def test_scalar_sweep_preserves_contract(
    name: str, param: str, lo: float, hi: float, data: st.DataObject
) -> None:
    """物理域内任取标量：ok=True 且有限、确定（Hypothesis 固定种子）。"""
    value = data.draw(
        st.floats(min_value=lo, max_value=hi, allow_nan=False,
                  allow_infinity=False)
    )
    params = dict(_calculator_inputs()[name])
    params[param] = value
    out = run_calculator(name, params)
    if not out["ok"]:
        pytest.fail(f"{name}({param}={value!r}) 物理域内意外失败: {out!r}")
    assert_service_result_contract(out)


def test_s_plane_classification_covers_registry() -> None:
    """skip 清单封闭：白名单 ∪ skip 清单 == 注册表全集（新键未归类即 fail）。

    新增注册键（含实验键）若既不在 S 面白名单、也不在本 skip 清单，本断言
    即红——开发者必须显式归类：产出 S/ABCD → 进白名单受互易扫描裁判；
    标量/无 S 面 → 进 skip 清单。误把 S 面键放进 skip 清单属审查遗漏，
    由互易全键扫描（白名单键逐键实调）与代码评审共同兜底。
    """
    all_names = set(CALCULATOR_REGISTRY.names(include_experimental=True))
    assert not (S_PLANE_CALCULATOR_KEYS & _NO_S_PLANE_KEYS), (
        "白名单与 skip 清单相交（归类矛盾）")
    assert all_names == S_PLANE_CALCULATOR_KEYS | _NO_S_PLANE_KEYS, (
        f"未归类注册键: "
        f"{sorted(all_names - S_PLANE_CALCULATOR_KEYS - _NO_S_PLANE_KEYS)}；"
        f"已消失键: "
        f"{sorted((S_PLANE_CALCULATOR_KEYS | _NO_S_PLANE_KEYS) - all_names)}"
    )


def test_reciprocal_exemption_list_is_closed() -> None:
    """豁免清单封闭：reciprocal=False 的键必须与钉死清单逐键一致。

    机制（§D-7）：spec.reciprocal 缺省 True → 新 S 面键自动进互易扫描；
    铁氧体类键须显式 reciprocal=False → 本断言即红，强制把新豁免键写进
    _RECIPROCITY_EXEMPT（豁免是有意识的决定，不是缺省）。
    """
    exempt = _reciprocity_exempt_names(CALCULATOR_REGISTRY)
    assert exempt == set(_RECIPROCITY_EXEMPT), (
        f"reciprocal=False 豁免键 {sorted(exempt)} 与封闭清单 "
        f"{sorted(_RECIPROCITY_EXEMPT)} 不一致——新增豁免键必须同步本清单"
    )
