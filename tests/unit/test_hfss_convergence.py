"""P2-D6 测试——SolveReport 收敛真值提取（pyaedt 1.4.0 get_profile API）。

pyaedt 不在 .venv，用纯 Python mock 模拟 Profiles/SimulationProfile/ProfileStep
结构（依据 pyaedt-main/src/ansys/aedt/core/modules/profile.py 源码）。
真机验证留 -m real_edt。
"""

import sys
from pathlib import Path

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.hfss_adapter import HfssAdapter

# ─── mock 工具（模拟 pyaedt profile 结构） ──────────────────────────────────

class _FakeStep:
    """模拟 ProfileStep：含 delta_s_max 属性。"""
    def __init__(self, delta_s_max):
        self.delta_s_max = delta_s_max


class _FakeAdaptivePass:
    """模拟 SimulationProfile.adaptive_pass（ProfileStep）。"""
    def __init__(self, pass_deltas: dict[str, float]):
        self.steps = {k: _FakeStep(v) for k, v in pass_deltas.items()}
        self.process_steps = list(pass_deltas.keys())


class _FakeSimProfile:
    """模拟 SimulationProfile。"""
    def __init__(self, num_passes: int, pass_deltas: dict | None = None):
        self.num_adaptive_passes = num_passes
        self.adaptive_pass = _FakeAdaptivePass(pass_deltas) if pass_deltas else None


class _FakeProfiles:
    """模拟 Profiles（Mapping）。"""
    def __init__(self, sim_profile):
        self._d = {"setup1": sim_profile}
    def keys(self): return self._d.keys()
    def __iter__(self): return iter(self._d)
    def __getitem__(self, k): return self._d[k]
    def __len__(self): return len(self._d)


class _FakeSetup:
    """模拟 hfss.get_setup() 返回的 setup 对象。"""
    def __init__(self, profiles=None, get_profile_raises=False):
        self._profiles = profiles
        self._raises = get_profile_raises
    def get_profile(self):
        if self._raises:
            raise RuntimeError("AEDT not connected")
        return self._profiles


class TestExtractConvergence:
    """_extract_convergence 从 get_profile() 提取 (passes, delta_s_final)。"""

    def test_normal_3_passes(self):
        """3 个 adaptive pass，末次 delta_s=0.015。"""
        sim = _FakeSimProfile(
            3,
            {"Pass 1": 0.12, "Pass 2": 0.04, "Pass 3": 0.015},
        )
        setup = _FakeSetup(_FakeProfiles(sim))
        passes, delta_s = HfssAdapter._extract_convergence(setup)
        assert passes == 3
        assert abs(delta_s - 0.015) < 1e-9

    def test_single_pass(self):
        sim = _FakeSimProfile(1, {"Pass 1": 0.08})
        setup = _FakeSetup(_FakeProfiles(sim))
        passes, delta_s = HfssAdapter._extract_convergence(setup)
        assert passes == 1
        assert abs(delta_s - 0.08) < 1e-9

    def test_no_adaptive_pass(self):
        """adaptive_pass 为 None → (0, 0.0)。"""
        sim = _FakeSimProfile(0, None)
        setup = _FakeSetup(_FakeProfiles(sim))
        passes, delta_s = HfssAdapter._extract_convergence(setup)
        assert passes == 0
        assert delta_s == 0.0

    def test_get_profile_raises(self):
        """get_profile() 异常 → (0, 0.0)，不穿透。"""
        setup = _FakeSetup(get_profile_raises=True)
        passes, delta_s = HfssAdapter._extract_convergence(setup)
        assert passes == 0
        assert delta_s == 0.0

    def test_empty_profiles(self):
        """Profiles 为空（空 Mapping）→ (0, 0.0)。"""
        setup = _FakeSetup({})  # 空 dict 是空 Mapping，not {} → True
        passes, delta_s = HfssAdapter._extract_convergence(setup)
        assert passes == 0
        assert delta_s == 0.0

    def test_none_profiles(self):
        """get_profile() 返回 None → (0, 0.0)。"""
        setup = _FakeSetup(None)
        passes, delta_s = HfssAdapter._extract_convergence(setup)
        assert passes == 0
        assert delta_s == 0.0

    def test_missing_delta_s_max_attr(self):
        """末次 pass 缺 delta_s_max 属性 → delta_s=0.0（getattr fallback）。"""
        sim = _FakeSimProfile(2, {"Pass 1": 0.1, "Pass 2": None})
        # 让 Pass 2 的 delta_s_max 是 None → float(None or 0.0) = 0.0
        setup = _FakeSetup(_FakeProfiles(sim))
        passes, delta_s = HfssAdapter._extract_convergence(setup)
        assert passes == 2
        assert delta_s == 0.0

    def test_picks_last_pass_not_first(self):
        """确认取的是最后一个 Pass 的 delta_s，而非第一个。"""
        sim = _FakeSimProfile(
            4,
            {"Pass 1": 0.5, "Pass 2": 0.2, "Pass 3": 0.05, "Pass 4": 0.01},
        )
        setup = _FakeSetup(_FakeProfiles(sim))
        passes, delta_s = HfssAdapter._extract_convergence(setup)
        assert passes == 4
        assert abs(delta_s - 0.01) < 1e-9, "应取末次 Pass 4 的 delta_s=0.01"
