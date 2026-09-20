"""V2 验证：poly_ridge vs NN（物理增广）在同一真采样集上的 LOOCV ρ 对比。

用法：python scripts/compare_surrogates.py runs/<rid>/calibration/samples.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from rfauto.core.objectives import Objective, SpecEvaluator
from rfauto.optimization.surrogate import PolyRidgeSurrogate, loocv_rho
from rfauto.optimization.surrogate.nn_model import NNSurrogate


def main(samples_path: str) -> None:
    data = json.loads(Path(samples_path).read_text(encoding="utf-8"))
    samples = data["samples"]
    objectives = [Objective(**o) for o in (data.get("objectives") or [])]
    bounds = {k: tuple(v) for k, v in (data.get("bounds") or {}).items()}
    assert samples and objectives and bounds, "samples.json 不完整"

    def cost(s: dict) -> float:
        return SpecEvaluator.evaluate_objectives(s["metrics"], objectives)

    def make_ridge():
        return PolyRidgeSurrogate(config={"bounds": bounds, "order": 2,
                                          "ridge_lambda": 0.1})

    def make_nn():
        return NNSurrogate(config={"bounds": bounds, "epochs": 1200,
                                   "n_ensemble": 5, "augmenter": "wilkinson_rf"})

    r_ridge = loocv_rho(samples, cost, make_ridge)
    r_nn = loocv_rho(samples, cost, make_nn)

    lines = [
        "# 代理对比（同一真采样集）",
        f"- 样本：{samples_path}（{len(samples)} 点）",
        f"- poly_ridge(2阶)：LOOCV ρ = {r_ridge.get('rho')}",
        f"- nn(wilkinson_rf 物理增广)：LOOCV ρ = {r_nn.get('rho')}",
    ]
    out = Path(samples_path).parent / "surrogate_compare.md"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("COMPARE_DONE")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1])
