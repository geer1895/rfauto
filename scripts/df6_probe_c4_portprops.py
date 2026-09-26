"""探测 c4_microstrip 项目端口边界 props（IntLine/CharImp 实况）。"""
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
VERSION = "2025.1"
OUT = REPO / "runs" / "df6_hfss_track" / "c4_portprops_probe.json"


def main() -> int:
    from ansys.aedt.core import Hfss

    proj = REPO / "runs" / "df6_hfss_track" / "c4_microstrip.aedt"
    h = Hfss(project=str(proj), design="c4_microstrip",
             solution_type="DrivenModal", version=VERSION,
             non_graphical=True, new_desktop=True)
    out: dict = {}
    try:
        for b in h.boundaries:
            out[str(b.name)] = {"type": str(b.type),
                                "props": json.loads(json.dumps(
                                    b.props, default=str))}
        OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print("props dumped")
        return 0
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


if __name__ == "__main__":
    sys.exit(main())
