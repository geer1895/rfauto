"""COMSOL RF 通道正式探针（WP4.4c；runs/comsol_probe/_probe_*.py 的正式版）。

口径（#215/#217 实证，docs/comsol_references.md §2/§5）：
- ``mph.start(version="6.3")`` 显式钉版本——MPh 自动探测选最新=6.4（license 过期）；
- RF 频域接口类型串是 ``ElectromagneticWaves``（tag emw）——
  ``ElectromagneticWavesFrequencyDomain`` 可创建但**无 LumpedPort 特征**；
- license 判据 = emw 接口上成功创建 LumpedPort 特征（需 RF Module 运行时）；
- 一 Python 进程一 Client（JPype 单 JVM）；进程退出即释放，license 席位串行。

用法（git-bash，工作区根目录）：
    .venv/Scripts/python.exe scripts/comsol_probe.py
    .venv/Scripts/python.exe scripts/comsol_probe.py --version 6.4   # 预期 FAIL
    .venv/Scripts/python.exe scripts/comsol_probe.py --dump-api     # 追加 API 口径 dump

退出码：0=PROBE PASS；2=RF license/接口判据 FAIL。
--dump-api 把 emw 接口全属性 + study/Parametric 步属性落 JSON（API 对文档用，
不影响 PASS/FAIL 判定，best-effort #105）。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DUMP = REPO / "runs" / "comsol_tail" / "probe_api_dump.json"

# #217①：RF 模块频域接口正确类型串（ewfd 变体无 LumpedPort，仅早期 license
# 探针误用——license 结论成立、建模口径作废）
PHYSICS_TYPE = "ElectromagneticWaves"
PHYSICS_TAG = "emw"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default="6.3",
                        help="COMSOL 版本钉扎（默认 6.3；6.4 预期 FAIL）")
    parser.add_argument("--cores", type=int, default=2)
    parser.add_argument("--dump-api", action="store_true",
                        help="追加 dump emw 接口/study 步全属性（API 核对用）")
    parser.add_argument("--dump-path", default=str(DEFAULT_DUMP))
    args = parser.parse_args()

    import mph

    t0 = time.time()
    client = mph.start(version=args.version, cores=args.cores)
    print(f"[{args.version}] server up ({time.time() - t0:.0f}s)", flush=True)

    model = client.create(f"rf_probe_{int(time.time())}")
    try:
        j = model.java
        j.component().create("comp1", True)
        comp = j.component("comp1")
        geom = comp.geom().create("geom1", 3)
        geom.lengthUnit("mm")
        geom.create("blk1", "Block")
        geom.feature("blk1").set("size", ["20", "6", "1"])
        geom.run()
        # #217①：RF 接口必须 ElectromagneticWaves（emw）
        phys = comp.physics().create(PHYSICS_TAG, PHYSICS_TYPE, "geom1")
        print(f"[{args.version}] physics {PHYSICS_TYPE} OK", flush=True)
        # license 判据：RF Module 运行时才有 LumpedPort 特征
        port = phys.create("lport1", "LumpedPort", 2)
        port.set("PortName", "1")
        print(f"[{args.version}] LumpedPort OK -> RF 模块 license 通过", flush=True)

        if args.dump_api:
            _dump_api(model, Path(args.dump_path))
        print(f"[{args.version}] PROBE PASS", flush=True)
        return 0
    except Exception as exc:
        print(f"[{args.version}] PROBE FAILED: {exc}", flush=True)
        return 2
    finally:
        with contextlib.suppress(Exception):  # 观测性清理 best-effort（#105）
            client.remove(model)


def _dump_api(model: object, path: Path) -> None:
    """dump emw 接口全属性 + study 步属性（API 对文档用；best-effort）。

    属性名/取值来自本机 COMSOL 6.3 自报（MPh Node.properties()，§4 树
    API；Java 物理接口对象无 properties()——实测 AttributeError），是对
    官方手册的机器级核对——禁止凭想象写 API 的落地手段。
    """
    dump: dict = {}
    try:
        # MPh Node API：model/'physics' 下钻（Java 对象无接口级 properties()）
        dump["physics_nodes"] = [str(n.name()) for n in model / "physics"]
        emw_node = model / "physics" / PHYSICS_TAG
        dump["emw_properties"] = _safe_node_properties(emw_node)
        # study 步属性：Frequency 步（#217②）+ Parametric 步（port sweep 用）
        j = model.java
        j.study().create("std1")
        j.study("std1").create("freq", "Frequency")
        j.study("std1").create("param", "Parametric")
        std1 = model / "study" / "std1"
        dump["study_children"] = [str(n.name()) for n in std1]
        for child in std1:
            dump[f"step_properties::{child.name()}"] = _safe_node_properties(child)
        # 候选开放边界特征类型串（COMSOL 自校验：能创建=合法，报错=非法）
        dump["feature_type_probe"] = _probe_feature_types(j)
    except Exception as exc:
        dump["error"] = repr(exc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dump, ensure_ascii=False, indent=1, default=str),
                    encoding="utf-8")
    print(f"API dump -> {path}", flush=True)


def _safe_node_properties(node: object) -> dict:
    """MPh Node.properties() → 纯 JSON dict（best-effort，值截断）。"""
    try:
        raw = node.properties()
    except Exception as exc:
        return {"<properties() error>": repr(exc)}
    out = {}
    for key, value in dict(raw).items():
        try:
            text = str(value) if value is not None else None
            out[str(key)] = text if len(text or "") < 200 else (text[:200] + "...")
        except Exception as exc:
            out[str(key)] = f"<err {exc!r}>"
    return out


def _safe_properties(node: object) -> dict:
    """Node.properties() → 纯 JSON dict（JPype 值转字符串；失败给 repr）。"""
    try:
        raw = node.properties()
    except Exception as exc:
        return {"<properties() error>": repr(exc)}
    out = {}
    for key in raw.keySet():
        try:
            value = raw.get(key)
            text = str(value) if value is not None else None
            out[str(key)] = text if len(text or "") < 200 else (text[:200] + "...")
        except Exception as exc:
            out[str(key)] = f"<err {exc!r}>"
    return out


def _probe_feature_types(j: object) -> dict:
    """对 emw 试建候选边界特征，记录 6.3 对每个类型串的自校验结果。"""
    comp = j.component("comp1")
    phys = comp.physics(PHYSICS_TAG)
    candidates = [
        "ScatteringBoundaryCondition",
        "PerfectlyMatchedLayer",
        "PerfectElectricConductor",
        "PerfectMagneticConductor",
        "Port",
    ]
    result = {}
    for i, ftype in enumerate(candidates):
        try:
            phys.create(f"cand{i}", ftype, 2)
            result[ftype] = "OK"
            phys.remove(f"cand{i}")
        except Exception as exc:
            result[ftype] = f"FAIL: {str(exc)[:160]}"
    return result


if __name__ == "__main__":
    sys.exit(main())
