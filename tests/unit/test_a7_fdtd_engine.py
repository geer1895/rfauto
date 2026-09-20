"""A7 可微 FDTD 真引擎（fdtdx）CPU 接入单测 —— §10.18/§10.24 A7。

策略（如实门限）：
- fdtdx 未安装（未装 ``[diff-fdtd]`` extra）时 importorskip——skip 不算 FAIL，
  引擎是可选依赖（与 smt/dataset/comsol 同模式）；
- 已安装时跑最小 CPU 算例（38×38×3 体素、320 步、PEC 腔 TMz 型）：
  jax.grad 对介电潜参数求梯度，对照中心差分。实测（jax/jaxlib 0.11.1 CPU、
  fdtdx 0.6.2、float32）：grad=-5.4425e-01，FD(h=1e-2)=-5.4421e-01，
  rel_err≈6.2e-5；h-sweep 呈 O(h²) 收敛至 float32 底噪（≈3e-5）。
  门限 1e-3 = 实测值的 ~16 倍余量，仍能拦截量级级梯度错误。

P2⑮ 扩展（#30 a7-recorder-reversible-3d，既有 6 测断言逐字未动）：
- 子项 A：reversible（Recorder 可逆反传）PEC 腔走通，grad vs 中心差分及与
  checkpointed 同点对拍均 ≤1e-3（实测 PEC 腔 rev/ckpt 逐位一致）；
- 子项 B：2D PML 薄腔 recorder_k∈{1,2,4} 检查点/重算权衡量化——recording
  字节数随 k 单调下降、线性插值重建畸变随 k 增大（如实记录，不做 1e-3 硬门：
  开放腔梯度小（~8e-3），FD 底噪与插值畸变均超 1e-3，实测 k=1/2/4 对拍
  checkpointed 为 2.3e-3/1.9e-2/6.0e-2）；
- 子项 C：3D PEC 真腔（16×16×10 芯层=2560 体素 ≤4096 预算）checkpointed/
  reversible 各一测 ≤1e-3；fdtdx 0.6.2 可逆×PML 贴距 ≤2 格反传 nan 的实测
  局限以 validate 守卫钉住（gap≥3 格放行）。
"""

from __future__ import annotations

import pytest

from rfauto.adapters.fdtd_diff import CavitySpec, DiffCavity

# exc_type=ImportError：半残安装（依赖冲突 import 期炸）同样按 skip 处理，
# 只拦截"模块缺失"（ModuleNotFoundError）会让 broken install 变 collection ERROR
pytest.importorskip(
    "fdtdx",
    reason="fdtdx 不可用（可选依赖 extras [diff-fdtd] 未装或安装残缺），A7 引擎单测跳过",
    exc_type=ImportError,
)

# 梯度核对门限：实测 rel_err ≈ 6.2e-5（h=1e-2，float32），留一个量级余量
_REL_ERR_GATE = 1e-3


@pytest.fixture(scope="module")
def cavity() -> DiffCavity:
    return DiffCavity.build(CavitySpec())


def test_engine_importable_and_version():
    """引擎可导入即冒烟（版本探测不钉死，供 evidence 记录用）。"""
    import importlib.metadata

    ver = importlib.metadata.version("fdtdx")
    assert ver.count(".") >= 1


def test_cavity_spec_validation():
    """规模守卫：超 64×64 / 超 320 步 / 非正参数显式拒绝。"""
    with pytest.raises(ValueError, match="64"):
        CavitySpec(nx=65).validate()
    with pytest.raises(ValueError, match="320"):
        CavitySpec(steps=321).validate()
    with pytest.raises(ValueError, match="resolution"):
        CavitySpec(resolution=-1.0).validate()


def test_forward_energy_positive(cavity: DiffCavity):
    """前向物理性：末步能量有限且非退化（激励确实耦合进腔，#174 教训）。"""
    import math

    loss = cavity.loss_at(0.5)
    assert math.isfinite(loss)
    assert loss > 0.0


def test_eps_eff_interpolation():
    """等效介电插值与 inv-ε 线性插值一致（apply_params 连续分支口径）。"""
    spec = CavitySpec(eps_air=1.0, eps_diel=6.0)
    assert spec.eps_eff(0.0) == pytest.approx(1.0)
    assert spec.eps_eff(1.0) == pytest.approx(6.0)
    # p=0.5: 1/eps = 0.5*1 + 0.5*(1/6) → eps = 1.714285...
    assert spec.eps_eff(0.5) == pytest.approx(12.0 / 7.0)


def test_grad_matches_finite_difference(cavity: DiffCavity):
    """核心验收：jax.grad 穿 320 步 FDTD 与中心差分一致（rel_err < 1e-3）。"""
    chk = cavity.grad_fd_check(p=0.5, h=1e-2)
    # 梯度非退化（既不为 0 也不爆）
    assert chk.grad != 0.0
    assert abs(chk.grad) < 1e3
    # 损失为正有限
    assert 0.0 < chk.loss < 1e12
    # 一致性门限（实测 6.2e-5）
    assert chk.rel_err < _REL_ERR_GATE, (
        f"grad={chk.grad:.6e} fd={chk.finite_diff:.6e} rel_err={chk.rel_err:.3e} (gate {_REL_ERR_GATE})"
    )


def test_grad_deterministic(cavity: DiffCavity):
    """同点两次求梯度逐位一致（确定性内核数值纪律）。"""
    g1 = cavity.grad_at(0.5)
    g2 = cavity.grad_at(0.5)
    assert g1 == g2


# ==================== P2⑮ 子项 A：reversible 可逆反传（PEC 腔空 PML 界面走通） ====================


@pytest.fixture(scope="module")
def cavity_rev() -> DiffCavity:
    return DiffCavity.build(CavitySpec(gradient_method="reversible"))


def test_grad_reversible_matches_finite_difference(cavity: DiffCavity, cavity_rev: DiffCavity):
    """可逆反传验收（方案 §10.18 A7 门限）：grad vs 中心差分 ≤1e-3，且与
    checkpointed 同点对拍 ≤1e-3（PEC 腔空 PML 界面实测 rev/ckpt 逐位一致）。"""
    chk = cavity_rev.grad_fd_check(p=0.5, h=1e-2)
    # 梯度非退化（#174 门同款）
    assert chk.grad != 0.0
    assert abs(chk.grad) < 1e3
    assert 0.0 < chk.loss < 1e12
    assert chk.rel_err < _REL_ERR_GATE, (
        f"rev grad={chk.grad:.6e} fd={chk.finite_diff:.6e} rel_err={chk.rel_err:.3e} (gate {_REL_ERR_GATE})"
    )
    g_ckpt = cavity.grad_at(0.5)
    rel_cross = abs(chk.grad - g_ckpt) / max(abs(g_ckpt), 1e-30)
    assert rel_cross < _REL_ERR_GATE, (
        f"rev-vs-ckpt 对拍：rev={chk.grad:.6e} ckpt={g_ckpt:.6e} rel={rel_cross:.3e} (gate {_REL_ERR_GATE})"
    )


def test_grad_reversible_deterministic(cavity_rev: DiffCavity):
    """可逆反传同点两次求梯度逐位一致（确定性内核）。"""
    assert cavity_rev.grad_at(0.5) == cavity_rev.grad_at(0.5)


# ==================== P2⑮ 子项 B：检查点/重算权衡量化（2D PML 薄腔 k 扫描） ====================
# Recorder 只挂 PML 界面场（fdtd/initialization.py:769-784 从 objects.pml_objects 建形），
# PEC-only 腔无可记录数据，k 扫描必须 PML 边界承载；2D TMz 薄域（nz_core=1）z 向放不下
# PML（总高 3 格 < 2×thickness），fdtd_diff 已把 z 向钉 pec（Ez 为 z 壁法向场，物理不变）。

_K_SWEEP_SPEC = dict(nx=24, ny=24, steps=160, device_voxels=8, boundary="pml", boundary_thickness=2)


@pytest.fixture(scope="module")
def cavity_pml_ref() -> DiffCavity:
    """同几何 checkpointed 参考（无 Recorder，recording_bytes=0）。"""
    return DiffCavity.build(CavitySpec(gradient_method="checkpointed", **_K_SWEEP_SPEC))


def test_reversible_pml_proximity_guard():
    """fdtdx 0.6.2 可逆×PML 贴距守卫：贴距 ≤2 格拒绝（实测反传 nan），≥3 格放行。"""
    with pytest.raises(ValueError, match="贴距"):
        CavitySpec(nx=24, ny=24, steps=160, device_voxels=20, boundary="pml", boundary_thickness=2,
                   gradient_method="reversible").validate()  # gap=(22-20)/2=1
    CavitySpec(nx=24, ny=24, steps=160, device_voxels=8, boundary="pml", boundary_thickness=2,
               gradient_method="reversible").validate()  # gap=7 放行


def test_recorder_k_tradeoff_2d_pml(cavity_pml_ref: DiffCavity):
    """recorder_k∈{1,2,4}：recording 字节数随 k 单调下降；线性插值重建畸变随 k
    增大。如实记录不做 1e-3 硬门（开放腔梯度 ~8e-3，FD 底噪+插值畸变超 1e-3）；
    畸变有界性用幅度比对拍（|g_k| ∈ [0.5,2]×|g_ckpt|）+ 单调趋势钉住。"""
    assert cavity_pml_ref.recording_bytes() == 0  # checkpointed 无 recorder
    g_ref = cavity_pml_ref.grad_at(0.5)
    assert g_ref != 0.0
    rows = []
    for k in (1, 2, 4):
        cav = DiffCavity.build(CavitySpec(gradient_method="reversible", recorder_k=k, **_K_SWEEP_SPEC))
        b = cav.recording_bytes()
        chk = cav.grad_fd_check(p=0.5, h=1e-2)
        assert b > 0
        assert chk.grad != 0.0
        # 畸变有界：同点梯度幅度不跑出参考的一半到两倍
        ratio = abs(chk.grad) / abs(g_ref)
        assert 0.5 <= ratio <= 2.0, f"k={k} 幅度比 {ratio:.3f} 越界（grad={chk.grad:.3e} ref={g_ref:.3e}）"
        rows.append((k, b, chk.rel_err, abs(chk.grad - g_ref) / abs(g_ref)))
    # 字节数严格随 k 单调下降（latent 数 = 步数/k 向上取整，末步自动补）
    assert rows[0][1] > rows[1][1] > rows[2][1] > 0
    # 插值畸变趋势：k=4 的对拍误差显著大于 k=1（线性重建截断随 k 增大）
    assert rows[2][3] > rows[0][3]


# ==================== P2⑮ 子项 C：3D 真腔（PEC 封闭腔，16×16×10 芯层=2560 体素） ====================


def test_cavity_3d_voxel_budget_guard():
    """3D 体素预算守卫（4GB 内存信封）：芯层总体素 >4096 拒绝，预算内放行。"""
    with pytest.raises(ValueError, match="4096"):
        CavitySpec(nx=20, ny=20, nz_core=12).validate()  # 20*20*12=4800
    CavitySpec(nx=16, ny=16, nz_core=10, steps=160, device_voxels=6).validate()  # 2560 ≤ 4096


_3D_SPEC = dict(nx=16, ny=16, nz_core=10, steps=160, device_voxels=6)


@pytest.fixture(scope="module")
def cavity_3d() -> DiffCavity:
    return DiffCavity.build(CavitySpec(**_3D_SPEC))


@pytest.fixture(scope="module")
def cavity_3d_rev() -> DiffCavity:
    return DiffCavity.build(CavitySpec(gradient_method="reversible", **_3D_SPEC))


def test_grad_3d_cavity_checkpointed(cavity_3d: DiffCavity):
    """3D 真腔 checkpointed：grad vs 中心差分 ≤1e-3（方案 §10.18 A7 门限）。"""
    chk = cavity_3d.grad_fd_check(p=0.5, h=1e-2)
    assert 0.0 < chk.loss < 1e12
    assert chk.grad != 0.0
    assert abs(chk.grad) < 1e3
    assert chk.rel_err < _REL_ERR_GATE, (
        f"3d ckpt grad={chk.grad:.6e} fd={chk.finite_diff:.6e} rel_err={chk.rel_err:.3e} (gate {_REL_ERR_GATE})"
    )


def test_grad_3d_cavity_reversible(cavity_3d_rev: DiffCavity):
    """3D 真腔 reversible：grad vs 中心差分 ≤1e-3；PEC 腔空 PML 界面 → 无界面记录
    （recording_bytes=0），可逆性由 PEC 切向 E 清零投影的反向恒等保证。"""
    assert cavity_3d_rev.recording_bytes() == 0
    chk = cavity_3d_rev.grad_fd_check(p=0.5, h=1e-2)
    assert 0.0 < chk.loss < 1e12
    assert chk.grad != 0.0
    assert abs(chk.grad) < 1e3
    assert chk.rel_err < _REL_ERR_GATE, (
        f"3d rev grad={chk.grad:.6e} fd={chk.finite_diff:.6e} rel_err={chk.rel_err:.3e} (gate {_REL_ERR_GATE})"
    )
