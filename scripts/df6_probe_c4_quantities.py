"""对已解的 c4 项目清点 Modal Solution Data 真实量名（零重解探针）。"""
from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
VERSION = "2025.1"
OUT = REPO / "runs" / "df6_hfss_track" / "c4_quantity_probe.json"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def probe(design: str) -> dict:
    from ansys.aedt.core import Hfss

    proj = REPO / "runs" / "df6_hfss_track" / f"c4_{design}.aedt"
    h = Hfss(project=str(proj), design=f"c4_{design}",
             solution_type="DrivenModal", version=VERSION,
             non_graphical=True, new_desktop=True)
    out: dict = {}
    try:
        sol_name = "Setup1 : LastAdaptive"
        cats = h.post.available_quantities_categories(
            report_category="Modal Solution Data", solution=sol_name)
        out["categories"] = sorted({str(c) for c in (cats or [])})
        out["quantities"] = {}
        for cat in out["categories"]:
            with contextlib.suppress(Exception):
                qs = h.post.available_report_quantities(
                    report_category="Modal Solution Data", solution=sol_name,
                    quantities_category=cat)
                if qs:
                    out["quantities"][cat] = sorted({str(q) for q in qs})
        # 按候选量名直读一次，验证 get_solution_data 通路
        want = []
        for cat in ("Z Parameter", "Port Zo", "S Parameter", "Gamma"):
            want.extend(out["quantities"].get(cat, [])[:12])
        if want:
            sol = h.post.get_solution_data(
                expressions=want, setup_sweep_name=sol_name,
                report_category="Modal Solution Data")
            out["readback"] = {}
            if sol is not None:
                for q in want:
                    with contextlib.suppress(Exception):
                        _x, re_ = sol.get_expression_data(q, formula="real")
                        _x, im_ = sol.get_expression_data(q, formula="imag")
                        out["readback"][q] = [float(next(iter(re_))),
                                              float(next(iter(im_)))]
            else:
                out["readback_error"] = "get_solution_data None"
        return out
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


def main() -> int:
    result: dict = {}
    for design in ("microstrip", "slotline_neg"):
        log(f"probe {design}")
        try:
            result[design] = probe(design)
        except Exception as exc:
            result[design] = {"error": repr(exc)}
        OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    log("probe done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
