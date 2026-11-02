"""物理先验 NN 代理（v2，纯 numpy 实现——零重依赖，接口对齐 torch 可换后端）。

设计要点（docs/surrogate_calibration_design.md §v2 + 法动比赛实战沉淀）：
- 小样本（9~30 点）场景： MLP(24,24) + bagging 集成（bootstrap K 份），
  集成 std 即不确定度（MC-Dropout 的廉价替代）。
- 物理先验 = 特征增广层（PHYSICS_AUGMENTERS 注册表）：原始参数之外补充
  领域特征（如 wilkinson 的线阻抗失配 Γ、λ/4 电长度比），让网络学残差
  而不是从零学物理。默认 polynomial_cross（二阶交叉项），可按模板注册。
- 确定性：全链路固定种子（初始化/bootstrap/训练顺序），同配置同结果。
- 迁移学习 warm-start（T-N16，aurora_n W2；opt-in——config["warm_start"]
  缺省 None=既有路径零改动）：注册表 champion 资产（model_registry blob
  反序列化的 NNSurrogate）的 _MLP 权重经 mlp_state/mlp_load_state 载入
  作集成初始化，微调起步；负迁移门（LOOCV ρ 同 seed 对照）不达标自动
  回退从零并如实标记（详见 fit 与 _negative_transfer_gate docstring）。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np

from .base import SurrogateModel, surrogate_registry

# ─── 物理特征增广注册表 ──────────────────────────────────────────────────────
# 签名 fn(params: dict[str, float], bounds: dict[str, tuple]) -> dict[str, float]
# 返回"增广特征名 → 值"（与原始参数合并后进网络）。注册键 = 模板名。


def _polynomial_cross(params: dict[str, float],
                      bounds: dict[str, tuple]) -> dict[str, float]:
    """通用二阶交叉项（无领域知识时的默认增广）。"""
    keys = sorted(params)
    out: dict[str, float] = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            out[f"cross__{a}__{b}"] = float(params[a]) * float(params[b])
    return out


def _wilkinson_rf(params: dict[str, float],
                  bounds: dict[str, tuple]) -> dict[str, float]:
    """wilkinson 物理特征：线阻抗失配 Γ_s/Γ_sh 与臂电长度比（v0 口径复用）。

    全部由 core.synthesis 的物理函数计算（optimization→core 合法依赖），
    网络在物理特征之上学残差，而不是从零拟合谐振行为。
    """
    from rfauto.core.synthesis import Stackup, forward_z0

    series_w = float(params.get("series_w_mm", 0.33))
    shunt_w = float(params.get("shunt_w_mm", 1.10))
    arm_len = float(params.get("arm_len_mm", 20.5))
    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    z0 = 50.0
    zt = z0 * math.sqrt(2)
    z_s, eps_s = forward_z0(series_w, 2.4, stackup)
    z_sh, _ = forward_z0(shunt_w, 2.4, stackup)
    gamma_s = abs((z_s - zt) / (z_s + zt))
    gamma_sh = abs((z_sh - z0) / (z_sh + z0))
    lambda_quarter_mm = 0.25 * 3e8 / 2.4e9 / math.sqrt(eps_s) * 1e3
    return {
        "gamma_series": gamma_s,
        "gamma_shunt": gamma_sh,
        "arm_elec_ratio": arm_len / lambda_quarter_mm,
    }


PHYSICS_AUGMENTERS: dict[str, Callable[[dict[str, float], dict[str, tuple]],
                                       dict[str, float]]] = {
    "polynomial_cross": _polynomial_cross,
    "wilkinson_rf": _wilkinson_rf,
}


# ─── numpy 小型 MLP ──────────────────────────────────────────────────────────

class _MLP:
    """两层全连接（tanh），Adam，L2。仅覆盖小样本回归需要的最小功能面。"""

    def __init__(self, n_in: int, n_out: int, hidden: int, seed: int):
        rng = np.random.default_rng(seed)
        self.w1 = rng.normal(0, math.sqrt(2.0 / n_in), (n_in, hidden))
        self.b1 = np.zeros(hidden)
        self.w2 = rng.normal(0, math.sqrt(2.0 / hidden), (hidden, hidden))
        self.b2 = np.zeros(hidden)
        self.w3 = rng.normal(0, math.sqrt(2.0 / hidden), (hidden, n_out))
        self.b3 = np.zeros(n_out)
        self._params = [self.w1, self.b1, self.w2, self.b2, self.w3, self.b3]
        self._m = [np.zeros_like(p) for p in self._params]
        self._v = [np.zeros_like(p) for p in self._params]
        self._t = 0

    def forward(self, x: np.ndarray) -> np.ndarray:
        h1 = np.tanh(x @ self.w1 + self.b1)
        h2 = np.tanh(h1 @ self.w2 + self.b2)
        return h2 @ self.w3 + self.b3

    def _grads(self, x: np.ndarray, y: np.ndarray, wd: float,
               sample_w: np.ndarray | None = None):
        n = len(x)
        h1 = np.tanh(x @ self.w1 + self.b1)
        h2 = np.tanh(h1 @ self.w2 + self.b2)
        out = h2 @ self.w3 + self.b3
        # 缺省路径（sample_w=None，逐字节等价基线）=等权均方损失 2(out−y)/n；
        # 置信度加权（T-N2）：L=Σw_i‖out_i−y_i‖²/Σw_i——全 1 权重时
        # Σw=n 与旧路径逐位一致。
        d_out = (2.0 * (out - y) / n if sample_w is None else
                 2.0 * sample_w[:, None] * (out - y) / sample_w.sum())
        g = [None] * 6
        g[5] = d_out.sum(0)
        g[4] = h2.T @ d_out + wd * self.w3
        d_h2 = (d_out @ self.w3.T) * (1 - h2 ** 2)
        g[3] = d_h2.sum(0)
        g[2] = h1.T @ d_h2 + wd * self.w2
        d_h1 = (d_h2 @ self.w2.T) * (1 - h1 ** 2)
        g[1] = d_h1.sum(0)
        g[0] = x.T @ d_h1 + wd * self.w1
        return g

    def adam_step(self, x, y, wd, lr, betas=(0.9, 0.999), eps=1e-8,
                  sample_w: np.ndarray | None = None) -> None:
        g = self._grads(x, y, wd, sample_w=sample_w)
        self._t += 1
        for p, gi, mi, vi in zip(self._params, g, self._m, self._v, strict=False):
            mi *= betas[0]
            mi += (1 - betas[0]) * gi
            vi *= betas[1]
            vi += (1 - betas[1]) * gi * gi
            m_hat = mi / (1 - betas[0] ** self._t)
            v_hat = vi / (1 - betas[1] ** self._t)
            p -= lr * m_hat / (np.sqrt(v_hat) + eps)


# ─── 迁移学习权重状态（T-N16，aurora_n W2）───────────────────────────────────

#: warm-start 权重状态格式版本（版本兼容键——消费端 mlp_load_state 校验，
#: 未来字段演进=升版本号，旧状态被显式拒绝而非静默错载）。
WARM_STATE_FORMAT_VERSION = 1

#: _MLP 可迁移参数键（顺序即快照 canonical 序）。
_MLP_STATE_KEYS: tuple[str, ...] = ("w1", "b1", "w2", "b2", "w3", "b3")


def mlp_state(net: _MLP) -> dict[str, Any]:
    """_MLP 权重快照（深拷贝 numpy 数组 + format_version 兼容键）。"""
    state: dict[str, Any] = {"format_version": WARM_STATE_FORMAT_VERSION}
    for key in _MLP_STATE_KEYS:
        state[key] = np.array(getattr(net, key), copy=True)
    return state


def mlp_load_state(net: _MLP, state: dict[str, Any]) -> None:
    """把权重快照写进 _MLP（架构不匹配/版本不兼容显式报错——负例契约）。

    - 原位覆盖（``arr[...] = val``）保持 ``net._params`` 别名有效——Adam
      更新走 ``self._params`` 引用，重绑定属性会静默脱钩（#116 名字绑定
      家族）；
    - Adam 一/二阶矩与步数清零：微调=新优化器轨迹（同 seed 确定性）。
    """
    if not isinstance(state, dict):
        raise ValueError(
            f"mlp_load_state：state 须为 dict，得 {type(state).__name__}")
    ver = state.get("format_version")
    if ver != WARM_STATE_FORMAT_VERSION:
        raise ValueError(
            f"mlp_load_state：权重格式版本 {ver!r} 不兼容"
            f"（支持 {WARM_STATE_FORMAT_VERSION}）——旧资产显式拒绝不静默错载")
    missing = [k for k in _MLP_STATE_KEYS if k not in state]
    if missing:
        raise ValueError(f"mlp_load_state：state 缺键 {missing}")
    for key in _MLP_STATE_KEYS:
        cur = getattr(net, key)
        val = np.asarray(state[key], dtype=float)
        if val.shape != cur.shape:
            raise ValueError(
                f"mlp_load_state：架构不匹配——{key} 形状 {val.shape} vs "
                f"目标 {cur.shape}（资产与目标网络不同构，显式报错不静默）")
    for key in _MLP_STATE_KEYS:
        getattr(net, key)[...] = np.asarray(state[key], dtype=float)
    net._m = [np.zeros_like(p) for p in net._params]
    net._v = [np.zeros_like(p) for p in net._params]
    net._t = 0


def augmenter_transfer_verdict(
    source_augmenter: str | None,
    source_feature_names: list[str] | None,
    target_augmenter: str,
    target_feature_names: list[str],
) -> dict[str, Any]:
    """特征增广迁移语义一致性校验（T-N16②；PHYSICS_AUGMENTERS 面）。

    权重迁移的前提=两端特征空间同构：增广器名一致（同名同实现，进程内
    注册表语义）且特征名序逐位一致（参数键并集+增广特征名的实际布局）。
    任一可判维度不一致即 ``ok=False``（reason=augmenter_mismatch /
    feature_names_mismatch）；两端信息皆缺（手工权重直灌）不判——形状
    门（mlp_load_state）仍是底线。
    """
    tgt_names = [str(n) for n in (target_feature_names or [])]
    problems: list[dict[str, Any]] = []
    if source_augmenter is not None \
            and str(source_augmenter) != str(target_augmenter):
        problems.append({
            "reason": "augmenter_mismatch",
            "source": str(source_augmenter),
            "target": str(target_augmenter)})
    if source_feature_names is not None:
        src_names = [str(n) for n in source_feature_names]
        if src_names != tgt_names:
            problems.append({
                "reason": "feature_names_mismatch",
                "source": src_names, "target": tgt_names})
    if problems:
        return {"ok": False, "reason": problems[0]["reason"],
                "problems": problems}
    return {"ok": True, "augmenter": str(target_augmenter),
            "n_features": len(tgt_names)}


#: warm_start 旋钮合法键（未知键显式拒绝——拼错旋钮静默失效是数据事故面）
_WARM_START_KNOBS = frozenset({
    "weights", "fine_tune_epochs", "meta", "gate", "gate_metric",
    "gate_eps", "gate_epochs"})


@surrogate_registry.register("nn")
class NNSurrogate(SurrogateModel):
    """物理特征增广 + bagging 集成的小样本 NN 代理（numpy 后端）。

    config 除下方既有旋钮外（T-N2）：``sample_weight_key``——样本字典顶层
    置信度权重键名（缺省 None=不消费权重，训练路径逐字节等价；给定后
    加权损失 L=Σw_i‖·‖²/Σw——按权重质量归一，uniform 置信重缩放不变量，
    与 poly_ridge 质量守恒归一同哲学；与 virtual_samples.VIRTUAL_WEIGHT_KEY
    对齐，缺键样本=1.0 真实锚点全可信语义）。

    config 迁移学习旋钮（T-N16，opt-in）：``warm_start``（缺省 None=既有
    路径零改动）——dict 形态：
        weights: 集成成员权重状态列表（mlp_state 快照；成员数须
            == n_ensemble，format_version 兼容键须=当前版本，违者显式报错）；
        fine_tune_epochs: 微调轮数（缺省 None=用 epochs）；
        meta: 资产元信息（extract_nn_warm_start 产出的 augmenter_name/
            feature_names）——给出即触发特征增广语义一致性终校验，不一致
            显式 ValueError（跨增广器/跨特征面权重迁移拒绝）；
        gate: 负迁移门开关（缺省 True）：fit 前先在同 seed 同小样本上跑
            warm vs 从零双臂 LOOCV ρ 对照（裁判单源 loocv_rho），ρ_transfer
            ≥ ρ_scratch−gate_eps 才采用迁移；不达标自动回退从零训练并
            fit_info 标 negative_transfer=True（预声明门，不凑绿）；
        gate_metric: ρ 裁判指标键（缺省 None=字典序首个指标键，确定性）；
        gate_eps: 采纳容差（缺省 0.0）；
        gate_epochs: 门内双臂训练轮数（缺省 None=同 fine_tune_epochs）。
    fit_info 扩展（仅 warm_start 给出时加键）：``warm_start``（门数字与
    adopted/fallback）与 ``negative_transfer``（bool）。
    """

    KIND = "nn"

    def __init__(self, config: dict[str, Any]):
        self.config = dict(config)
        self.bounds = {k: (float(v[0]), float(v[1]))
                       for k, v in (config.get("bounds") or {}).items()}
        self.hidden = int(config.get("hidden", 24))
        # 默认值来自 run2 真采样超参扫（2026-09-04，LOOCV ρ 最优组合）：
        # epochs=4000 / wd=1e-3 / n_ensemble=3；增广器在 n=9 上
        # polynomial_cross(ρ=0.52) 与 wilkinson_rf(ρ=0.47) 同档——
        # 默认保 wilkinson_rf（物理先验语义），追平性能靠样本量。
        self.epochs = int(config.get("epochs", 4000))
        self.lr = float(config.get("lr", 5e-3))
        self.wd = float(config.get("weight_decay", 1e-3))
        self.n_ensemble = int(config.get("n_ensemble", 3))
        self.seed = int(config.get("seed", 42))
        augmenter = str(config.get("augmenter", "wilkinson_rf"))
        self.augmenter_name = augmenter
        self.augmenter = PHYSICS_AUGMENTERS.get(
            augmenter, _polynomial_cross)
        # 样本置信度加权通道（T-N2，opt-in）：缺省 None=不消费权重（旧路径
        # 逐字节等价）；给定键名时逐样本读该顶层键（缺键=1.0 真实锚点全
        # 可信），与 virtual_samples.VIRTUAL_WEIGHT_KEY 消费对齐。
        self.sample_weight_key: str | None = config.get("sample_weight_key")
        # 迁移学习 warm-start（T-N16，opt-in）：缺省 None=既有路径零改动。
        # 此处只做结构早校验（类型/成员数/版本键）；形状级架构校验在
        # mlp_load_state（fit 期，n_in/n_out 依赖样本特征面方可判定）。
        warm_start_cfg = config.get("warm_start")
        if warm_start_cfg is not None and not isinstance(warm_start_cfg, dict):
            raise ValueError(
                f"NNSurrogate：warm_start 须为 dict 或 None，得 "
                f"{type(warm_start_cfg).__name__}")
        if warm_start_cfg is not None:
            unknown = sorted(
                str(k) for k in warm_start_cfg if str(k) not in _WARM_START_KNOBS)
            if unknown:
                raise ValueError(
                    f"NNSurrogate：warm_start 未知键 {unknown}（允许键 "
                    f"{sorted(_WARM_START_KNOBS)}）——拼错旋钮会静默失效，"
                    "显式拒绝")
        self.warm_start_config: dict[str, Any] | None = (
            dict(warm_start_cfg) if warm_start_cfg is not None else None)
        self._warm_states: list[dict[str, Any]] | None = None
        if self.warm_start_config is not None:
            weights = self.warm_start_config.get("weights")
            if not isinstance(weights, (list, tuple)) or not weights:
                raise ValueError(
                    "NNSurrogate：warm_start.weights 须为非空列表"
                    "（每集成成员一份 mlp_state 快照 dict）")
            states: list[dict[str, Any]] = []
            for i, w in enumerate(weights):
                if not isinstance(w, dict):
                    raise ValueError(
                        f"NNSurrogate：warm_start.weights[{i}] 须为 "
                        f"_MLP 状态 dict，得 {type(w).__name__}")
                ver = w.get("format_version")
                if ver != WARM_STATE_FORMAT_VERSION:
                    raise ValueError(
                        f"NNSurrogate：warm_start.weights[{i}] 格式版本 "
                        f"{ver!r} 不兼容（支持 "
                        f"{WARM_STATE_FORMAT_VERSION}）——显式报错不静默错载")
                states.append(w)
            if len(states) != self.n_ensemble:
                raise ValueError(
                    f"NNSurrogate：warm_start 权重成员数 {len(states)} 与 "
                    f"n_ensemble={self.n_ensemble} 不一致"
                    f"（显式报错，不静默截断/复制）")
            self._warm_states = states
        self._models: list[_MLP] = []
        self._xs: np.ndarray | None = None
        self._ys: np.ndarray | None = None
        self.metric_keys: list[str] = []

    # ── 特征化 ──
    def _feature_names(self, sample_params: dict[str, float]) -> list[str]:
        base = sorted(self.bounds.keys() | sample_params.keys())
        aug = sorted(self.augmenter(
            {k: float(sample_params.get(k, np.mean(self.bounds.get(k, (0, 0)))))
             for k in base}, self.bounds))
        return base + aug

    def _vectorize(self, params: dict[str, float],
                   names: list[str]) -> np.ndarray:
        full = dict(params)
        for k in self.bounds:
            full.setdefault(k, sum(self.bounds[k]) / 2.0)
        aug = self.augmenter({k: float(full.get(k, 0.0)) for k in sorted(full)},
                             self.bounds)
        full |= aug
        return np.array([float(full.get(k, 0.0)) for k in names])

    # ── SurrogateModel 契约 ──
    def fit(self, samples: list[dict[str, Any]]) -> None:
        if not samples:
            raise ValueError("NNSurrogate.fit：无样本")
        names = self._feature_names(samples[0]["params"])
        x = np.vstack([self._vectorize(s["params"], names) for s in samples])
        keys = sorted({k for s in samples
                       for k, v in s["metrics"].items()
                       if isinstance(v, (int, float))})
        y = np.array([[float(s["metrics"].get(k, np.nan)) for k in keys]
                      for s in samples])
        ok = ~np.isnan(y).any(axis=1)
        x, y = x[ok], y[ok]
        # 置信度权重抽取（T-N2）：与 ok 掩码同行过滤；非法值显式报错
        #（#316 多报不放过），有效权重全 0 显式报错不静默退化。
        if self.sample_weight_key is None:
            self._sw: np.ndarray | None = None
        else:
            w_all: list[float] = []
            for idx, s in enumerate(samples):
                if self.sample_weight_key not in s:
                    w_all.append(1.0)
                    continue
                try:
                    wv = float(s[self.sample_weight_key])
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"NNSurrogate.fit：样本 {idx} 权重键 "
                        f"{self.sample_weight_key!r} 值 "
                        f"{s[self.sample_weight_key]!r} 不可转 float") from exc
                if not np.isfinite(wv) or wv < 0.0:
                    raise ValueError(
                        f"NNSurrogate.fit：样本 {idx} 权重键 "
                        f"{self.sample_weight_key!r} 值 {wv!r} 非法"
                        f"（须非负有限）")
                w_all.append(wv)
            sw = np.array(w_all, dtype=float)[ok]
            if len(sw) and not sw.sum() > 0.0:
                raise ValueError(
                    f"NNSurrogate.fit：权重键 "
                    f"{self.sample_weight_key!r} 下全部有效样本权重为 0"
                    f"（显式报错不静默退化）")
            self._sw = sw
        self.metric_keys = keys
        self._x_names = names
        self._x_mean, self._x_std = x.mean(0), x.std(0) + 1e-12
        self._y_mean, self._y_std = y.mean(0), y.std(0) + 1e-12
        self._xs = (x - self._x_mean) / self._x_std
        self._ys = (y - self._y_mean) / self._y_std
        n = len(x)
        info = self._mark_fitted(n)
        if self._warm_states is None:
            self._fit_ensemble(n, epochs=self.epochs, use_warm=False)
            return info
        # 门裁判面只对有效样本（全指标键数值）留一——nan 行进折会把 ρ
        # 退化为 0（_spearman 常数退化口径），如实剔除后再判
        valid = [s for s, keep in zip(samples, ok, strict=True) if keep]
        return self._fit_with_warm_start(valid, info)

    # ── 迁移学习 warm-start（T-N16）──

    def _fine_tune_epochs(self) -> int:
        raw = (self.warm_start_config or {}).get("fine_tune_epochs")
        return self.epochs if raw is None else int(raw)

    def _fit_ensemble(self, n: int, *, epochs: int, use_warm: bool) -> None:
        """集成训练单源（缺省路径与旧实现逐位同序：bootstrap→初始化→Adam）。"""
        names = self._x_names
        keys = self.metric_keys
        self._models = []
        for k in range(self.n_ensemble):
            rng = np.random.default_rng(self.seed + k)
            idx = rng.integers(0, n, n)  # bootstrap
            net = _MLP(len(names), len(keys), self.hidden, self.seed + 1000 + k)
            if use_warm:
                mlp_load_state(net, self._warm_states[k])
            for _ in range(epochs):
                if self._sw is None:
                    net.adam_step(self._xs[idx], self._ys[idx], self.wd,
                                  self.lr)
                else:
                    net.adam_step(self._xs[idx], self._ys[idx], self.wd,
                                  self.lr, sample_w=self._sw[idx])
            self._models.append(net)

    def _fit_with_warm_start(
        self, valid_samples: list[dict[str, Any]], info: dict[str, Any],
    ) -> dict[str, Any]:
        """warm-start 拟合路径（opt-in；负迁移门预声明语义）。

        - meta 给出资产增广/特征面 → 语义一致性校验不过显式 ValueError
          （跨增广器/跨特征面权重迁移拒绝，不静默错载）；
        - gate=True（缺省）：warm vs 从零双臂 LOOCV ρ 同 seed 对照，
          ρ_transfer ≥ ρ_scratch−gate_eps 才采用；不达标自动回退从零，
          fit_info 标 negative_transfer=True + fallback=scratch（如实）；
        - gate=False：盲迁移（调用方自担），fit_info 仍带 adopted 键面。
        """
        ws = self.warm_start_config or {}
        meta = ws.get("meta") or {}
        if meta.get("augmenter_name") is not None \
                or meta.get("feature_names") is not None:
            verdict = augmenter_transfer_verdict(
                meta.get("augmenter_name"), meta.get("feature_names"),
                self.augmenter_name, list(self._x_names))
            if not verdict.get("ok"):
                raise ValueError(
                    "NNSurrogate.fit：特征增广迁移语义校验未过"
                    f"（{verdict.get('reason')}）——跨增广器/跨特征面权重"
                    "迁移显式拒绝；改用同增广器资产或从零训练")
        gate_on = ws.get("gate")
        gate_on = True if gate_on is None else bool(gate_on)
        if not gate_on:
            self._fit_ensemble(len(self._xs), epochs=self._fine_tune_epochs(),
                               use_warm=True)
            info["warm_start"] = {"adopted": True, "gate": False}
            return info
        gate = self._negative_transfer_gate(valid_samples)
        if not gate["adopt"]:
            self._fit_ensemble(len(self._xs), epochs=self.epochs,
                               use_warm=False)
            info["negative_transfer"] = True
            info["warm_start"] = {**gate, "adopted": False,
                                  "fallback": "scratch"}
            return info
        self._fit_ensemble(len(self._xs), epochs=self._fine_tune_epochs(),
                           use_warm=True)
        info["negative_transfer"] = False
        info["warm_start"] = {**gate, "adopted": True}
        return info

    def _negative_transfer_gate(
        self, valid_samples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """负迁移门内核（预声明）：双臂 LOOCV ρ 对照，裁判单源 loocv_rho。

        两臂同 seed 同折同轮数（gate_epochs，缺省同 fine_tune_epochs）；
        LOOCV 不可跑（有效样本 <4 等内核 ok=False 面）= 不可证实迁移收益
        → 如实拒绝采信（adopt=False + reason），回退从零（#122 不凑绿）。
        """
        from rfauto.optimization.surrogate.poly_ridge import loocv_rho

        ws = self.warm_start_config or {}
        metric = ws.get("gate_metric")
        if metric is None:
            if not self.metric_keys:
                return {"adopt": False, "reason": "gate_no_metric"}
            metric = sorted(self.metric_keys)[0]
        elif metric not in self.metric_keys:
            raise ValueError(
                f"NNSurrogate：gate_metric {metric!r} 不在指标键 "
                f"{self.metric_keys}")
        raw_eps = ws.get("gate_eps")
        eps = 0.0 if raw_eps is None else float(raw_eps)
        raw_ge = ws.get("gate_epochs")
        gate_epochs = self._fine_tune_epochs() if raw_ge is None else int(raw_ge)

        def cost_fn(s: dict[str, Any]) -> float:
            return float(s["metrics"][metric])

        def factory(use_warm: bool) -> NNSurrogate:
            cfg = dict(self.config)
            cfg["epochs"] = gate_epochs
            cfg["warm_start"] = (
                {"weights": list(self._warm_states or []), "gate": False}
                if use_warm else None)
            return NNSurrogate(config=cfg)

        rho_warm = loocv_rho(valid_samples, cost_fn, lambda: factory(True))
        rho_scratch = loocv_rho(valid_samples, cost_fn, lambda: factory(False))
        base = {"gate_metric": metric, "gate_eps": eps,
                "gate_epochs": gate_epochs,
                "rho_transfer_detail": rho_warm, "rho_scratch_detail": rho_scratch}
        if not (rho_warm.get("ok") and rho_scratch.get("ok")):
            return {"adopt": False, "reason": "gate_loocv_unavailable", **base}
        rho_t = float(rho_warm["rho"])
        rho_s = float(rho_scratch["rho"])
        return {"adopt": bool(rho_t >= rho_s - eps),
                "rho_transfer": rho_t, "rho_scratch": rho_s,
                "margin": rho_t - rho_s, "n_folds": rho_warm.get("n_folds"),
                "skipped": int(rho_warm.get("skipped") or 0)
                + int(rho_scratch.get("skipped") or 0),
                **base}

    def predict(self, params: dict[str, float]) -> dict[str, float]:
        if not self._models:
            raise RuntimeError("NNSurrogate.predict：先 fit")
        x = self._vectorize(params, self._x_names)
        x = (x - self._x_mean) / self._x_std
        outs = np.vstack([m.forward(x[None, :])[0] for m in self._models])
        mean = outs.mean(0) * self._y_std + self._y_mean
        return {k: float(v) for k, v in zip(self.metric_keys, mean, strict=False)}

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        if not self._models:
            raise RuntimeError("NNSurrogate.uncertainty：先 fit")
        x = self._vectorize(params, self._x_names)
        x = (x - self._x_mean) / self._x_std
        outs = np.vstack([m.forward(x[None, :])[0] for m in self._models])
        std = outs.std(0) * self._y_std
        return {k: float(v) for k, v in zip(self.metric_keys, std, strict=False)}
