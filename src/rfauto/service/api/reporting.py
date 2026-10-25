"""api.reporting —— 报告与运维面（replay_run/get_metrics/generate_report_for_run/run_tolerance/list_models/doctor/run_link）与配方迁移·可复现导出（recipe_migrate/repro_export）。

自 api.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体逐字节搬迁。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.core.contracts import AdsExchangeContract
from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

from .run_core import run_once


def replay_run(run_id: str) -> dict[str, Any]:
    """复现任一次 run：用其 recipe 快照重跑，并核对 plugin/schema 版本。

    P1 实现（验收项："rfauto replay 可复现任一次（含 plugin/schema 版本核对）"）。

    K20 审查④ freshness gate（aurora_l Wave-B B2）：replay 的语义是"复现
    **源 run** 的配方"，源 run 产物/快照被顶替时不设门就会拿被顶替后的
    快照重跑却仍冠源 run 之名（错配归因，与 report 面同族病灶；replay 是
    verify_run 消费口里最后一个未接线的 CLI 面）。与
    ``generate_report_for_run`` 同款语义：stale（含 ``snapshot_replaced``/
    ``snapshot_missing``）→ 拒重跑（stage="freshness_gate"）；legacy（老
    run 无 manifest）→ 放行带 note（增量兼容红线：老 run 行为不变）；
    fresh → 放行。校验面自身故障不阻断重跑主路径（#105 best-effort，
    note 记账不伪装成门）。
    """
    run_dir = Path("runs") / run_id
    meta_path = run_dir / "meta.json"
    snapshot = run_dir / "recipe.snapshot.yaml"
    errors: list[str] = []
    if not meta_path.exists():
        errors.append(f"未找到 run: {run_id}（缺少 {meta_path}）")
    if not snapshot.exists():
        errors.append(f"缺少配方快照: {snapshot}")
    if errors:
        return error_envelope(errors)

    # freshness gate：读快照重跑前先校验（generate_report_for_run 同款；
    # stale→拒重跑，legacy→放行带 note，verify 面故障→note 记账不阻断）
    freshness_status = "unknown"
    freshness_note = ""
    try:
        from rfauto.service.runs_verify_service import verify_run  # 同层 service 直引

        freshness = verify_run(run_dir)
        freshness_status = str(freshness.get("status", "unknown"))
        if freshness_status == "stale":
            return error_envelope(
                list(freshness.get("errors") or ["run 产物新鲜度校验未通过"]),
                stage="freshness_gate",
                run_id=str(freshness.get("run_id") or run_id), status="stale",
                issues=freshness.get("issues") or [])
        freshness_note = str(freshness.get("note") or "")
    except Exception as exc:  # pragma: no cover - 观测面兜底（#105）
        freshness_note = f"新鲜度校验不可用（非阻断）: {exc}"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # 版本核对：plugin/schema 与当前注册的模型不一致时显式报错
    import yaml
    with open(snapshot, encoding="utf-8") as f:
        snap_data = yaml.safe_load(f)
    model_name = snap_data.get("model", "")
    try:
        from rfauto.models.registry import get as get_plugin_cls
        get_plugin_cls(model_name)  # 存在性核对
    except KeyError:
        return error_envelope([f"快照中的模型 '{model_name}' 当前未注册"])

    warnings: list[str] = []
    # schema 版本核对：meta 与快照不一致时降级为 warning（快照重跑仍忠实于源 run 配方）
    if "schema_version" in snap_data and str(meta.get("schema_version")) != str(snap_data["schema_version"]):
        warnings.append(
            f"schema 版本不一致: meta={meta.get('schema_version')}, 快照={snap_data['schema_version']}"
        )
    # git SHA 核对：不一致只提示（完整环境复现留给 P2 golden 回归）
    current_sha = ""
    try:
        import subprocess
        current_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        pass
    recorded_sha = meta.get("git_sha", "")
    if recorded_sha and current_sha and recorded_sha != current_sha:
        warnings.append(
            f"git 版本不一致: run 记录于 {recorded_sha}, 当前 HEAD 为 {current_sha}（复现结果可能有差异）"
        )

    # 用快照重跑（run_once 内部会创建新的 run 目录并再次快照）
    adapter_name = meta.get("adapter", "fake")
    result = run_once(snapshot, adapter_name=adapter_name)

    envelope = ok_envelope(
        source_run_id=run_id,
        replay_run_id=result.get("run_id"),
        version_warnings=warnings,
        result=result,
        freshness={"status": freshness_status, "note": freshness_note},
    )
    # ok 透传内层 run_once 结果（复现失败≠本调用崩，历史形状无顶层 errors）
    envelope["ok"] = bool(result.get("ok", False))
    return envelope


def get_metrics(run_id: str) -> dict[str, Any]:
    """读取某次 run 的指标。"""
    metrics_path = Path("runs") / run_id / "results" / "metrics.json"
    if not metrics_path.exists():
        return error_envelope([f"未找到 run: {run_id}"])
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    return ok_envelope(data=data)


def generate_report_for_run(
    run_id: str,
    *,
    fmt: str = "markdown",
    output: str | Path | None = None,
) -> dict[str, Any]:
    """按已完成的 run 重建报告（缺口 8：CLI report 命令此前是 stub）。

    读取 runs/<run_id>/results/metrics.json 重新生成 report.md / report.html；
    output 指定输出文件时写入该路径。S 参数曲线图不重绘（结果文件已在）。

    K4 freshness gate（aurora_l A3，R2 侦察 Top1：老 ``rfauto report``
    命令是用户病灶第二入口）：读 Touchstone 重建曲线前先
    ``runs_verify_service.verify_run`` 校验 run 收官指纹（与
    report_render.render_run_report 同款语义）。stale=旧 sNp 顶替/漏拷/
    sidecar 错配 → 错误信封拒绝出图（stage="freshness_gate" 标记报告面）；
    legacy=老 run 无 manifest → 放行带 note（增量兼容红线：老 run 行为
    不变）；校验面自身故障不阻塞报告主路径（#105 best-effort）。
    """
    run_dir = Path("runs") / run_id
    metrics_path = run_dir / "results" / "metrics.json"
    if not metrics_path.exists():
        return error_envelope([f"未找到 run 指标: {metrics_path}"])

    data = json.loads(metrics_path.read_text(encoding="utf-8"))

    # freshness gate：读 s_files 前先校验（照 report_render.py 同款；
    # stale→拒出图，legacy→放行带 note，verify 面故障→note 记账不阻断）
    freshness_status = "unknown"
    freshness_note = ""
    try:
        from rfauto.service.runs_verify_service import verify_run  # 同层 service 直引

        freshness = verify_run(run_dir)
        freshness_status = str(freshness.get("status", "unknown"))
        if freshness_status == "stale":
            return error_envelope(
                list(freshness.get("errors") or ["run 产物新鲜度校验未通过"]),
                stage="freshness_gate",
                run_id=freshness.get("run_id"), status="stale",
                issues=freshness.get("issues") or [])
        freshness_note = str(freshness.get("note") or "")
    except Exception as exc:  # pragma: no cover - 观测面兜底（#105）
        freshness_note = f"新鲜度校验不可用（非阻断）: {exc}"

    # 尽量从结果目录的 Touchstone 重建 S 参数曲线（报告含图，不丢历史信息）
    freq_data = None
    try:
        import numpy as np
        import skrf

        s_files = sorted((run_dir / "results").glob("params.s*p"))
        if s_files:
            network = skrf.Network(str(s_files[0]))
            freqs_ghz = np.asarray(network.f, dtype=float) / 1e9
            freq_data = {"freqs": freqs_ghz.tolist()}
            freq_data["s11_db"] = (20.0 * np.log10(np.abs(network.s[:, 0, 0]) + 1e-15)).tolist()
            if network.s.shape[1] >= 2:
                freq_data["s21_db"] = (
                    20.0 * np.log10(np.abs(network.s[:, 1, 0]) + 1e-15)
                ).tolist()
    except Exception:
        freq_data = None

    from rfauto.infra.report import generate_report

    dest_dir = Path(output).parent if output else run_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    # generate_report 以 run_dir 为根放置 report.md/html；指定 output 时
    # 用临时改写目标的方式最简：生成后移动
    report_path = generate_report(
        run_dir, data.get("metrics", {}), format=fmt, freq_data=freq_data,
    )
    if output and Path(report_path) != Path(output):
        Path(report_path).replace(output)
        report_path = Path(output)
    return ok_envelope(
        run_id=run_id,
        format=fmt,
        report=str(report_path),
        metrics=data.get("metrics", {}),
        freshness={"status": freshness_status, "note": freshness_note},
    )


def run_tolerance(
    recipe_path: str | Path,
    *,
    adapter_name: str = "fake",
    n_samples: int = 200,
) -> dict[str, Any]:
    """公差分析（孤岛接线）——`rfauto tolerance <recipe>` 服务入口。

    以 objectives 为规格、tolerance.tolerances 为公差，Monte Carlo 出良率。
    """
    from rfauto.optimization.optimizer import run_tolerance_analysis
    return run_tolerance_analysis(
        recipe_path, adapter_name=adapter_name, n_samples=n_samples,
    )


def list_models() -> dict[str, Any]:
    """列出已注册的模型插件（AU-7：附带插件加载失败账本 load_errors）。

    load_errors 为 models.registry 的结构化失败记录（内置插件 ImportError /
    entry-point 加载失败），缺省空列表——注册失败不再静默不可见，
    ok 恒 True（列模型是只读操作，加载失败不改列行为）。
    """
    from rfauto.models import registry as _registry
    from rfauto.models.registry import list_models as _list_models
    return ok_envelope(
        models=_list_models(),
        load_errors=list(_registry.load_errors),
    )


def doctor() -> dict[str, Any]:
    """环境探测：AEDT/ADS 版本、license、路径、已测试版本组合核对。"""
    from rfauto.infra.config import doctor_check, load_settings
    settings = load_settings()
    raw = doctor_check(settings)

    checks = []
    # Python 版本
    import sys
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append({"name": "Python", "status": "ok", "detail": py_ver})

    # AEDT
    aedt = raw.get("aedt", {})
    if aedt.get("exists"):
        from rfauto.infra.version_probe import compat_level
        level = compat_level("aedt", aedt.get("version", ""))
        checks.append({
            "name": "AEDT",
            "status": "ok",
            "detail": f"{aedt.get('path', '')}（版本 {aedt.get('version', '?')}，{level}）",
        })
    elif aedt.get("note") == "not configured":
        # 项目 B：未显式配置时自动探测本机安装
        from rfauto.infra.version_probe import compat_level, detect_aedt_versions
        detected = detect_aedt_versions()
        if detected:
            for inst in detected[:3]:
                level = compat_level("aedt", inst["aedt_version"])
                checks.append({
                    "name": "AEDT（自动发现）",
                    "status": "ok",
                    "detail": f"{inst['path']}（版本 {inst['aedt_version']}，{level}，来源 {inst['source']}）",
                })
        else:
            checks.append({"name": "AEDT", "status": "未配置",
                           "detail": "设置 RFAUTO_AEDT_PATH 或编辑 configs/settings.yaml；自动探测未发现安装"})
    else:
        checks.append({"name": "AEDT", "status": "缺失", "detail": f"路径不存在: {aedt.get('path', '')}"})

    # ADS
    ads = raw.get("ads", {})
    if ads.get("exists"):
        from rfauto.infra.version_probe import compat_level, detect_ads_version
        ads_version = detect_ads_version(ads.get("path", "")) or "?"
        level = compat_level("ads", ads_version)
        checks.append({
            "name": "ADS",
            "status": "ok",
            "detail": f"{ads.get('path', '')}（版本 {ads_version}，{level}）",
        })
    elif ads.get("note") == "not configured":
        checks.append({"name": "ADS", "status": "未配置", "detail": "设置 RFAUTO_HPEESOF_DIR 或编辑 configs/settings.yaml"})
    else:
        checks.append({"name": "ADS", "status": "缺失", "detail": f"路径不存在: {ads.get('path', '')}"})

    # 缓存模式
    checks.append({"name": "缓存模式", "status": "ok", "detail": settings.cache_mode})

    envelope = ok_envelope(checks=checks)
    # ok 透传探测汇总位（历史形状；全绿才 True）
    envelope["ok"] = raw.get("ok", True)
    return envelope


def run_link(
    run_id: str,
    *,
    rounds: int = 2,
    ads_dir: str | Path | None = None,
    to_ads: bool = True,
) -> dict[str, Any]:
    """把某次 HFSS 运行送入 ADS 联动链路（P3, ADR-0003, N=2 往返）。

    定位 runs/<run_id>/results 下的 Touchstone -> AdsExchangeContract ->
    HfssAdsLink.run_from_snp(二阶段 N 轮)。B 档受阻自动落 C 档保底。

    ``to_ads=False``（E2-2 门语义接线）：只定位 run/结果不执行 ADS 联动，
    返回 skipped 信封（ok=True + skipped + reason）——CLI ``link`` 缺省
    不联动，``--to-ads`` 才执行（旗标语义与行为一致）。服务层缺省 True，
    直接调用方（既有消费面）行为不变。
    """
    run_dir = Path("runs") / run_id
    if not run_dir.exists():
        return error_envelope([f"run 不存在: {run_id}"])
    if not to_ads:
        return skipped_envelope(
            "--to-ads 未指定：已定位 run，未执行 ADS 联动（缺省不联动）",
            run_id=run_id)

    results_dir = run_dir / "results"
    snp_candidates = sorted(results_dir.glob("params.s*")) if results_dir.exists() else []
    if not snp_candidates:
        return error_envelope([f"run 未找到 Touchstone 结果: {run_id}"])
    snp_path = snp_candidates[0]

    contract = AdsExchangeContract()

    # 项目 A：通道选择（审计信息；实际仿真仍由 HfssAdsLink 默认 B 档执行，
    # B 档受阻时其内建 C 档保底。M/A 档按 prefer 显式启用）
    from rfauto.linkage.ads_channel import select_ads_channel

    channel_selection = select_ads_channel(ads_dir)
    if channel_selection.get("ok") and channel_selection.get("channel") == "c":
        channel_selection["note"] = "仅 C 档可用：B 档 hpeesofsim 缺失，联运将以人工保底结束"

    from rfauto.linkage.hfss_ads_link import HfssAdsLink
    ads_out = run_dir / "ads"
    link = HfssAdsLink(output_dir=ads_out, ads_dir=ads_dir)
    summary = link.run_from_snp(snp_path, contract, rounds=rounds)
    return ok_envelope(
        run_id=run_id,
        snp_path=str(snp_path),
        ads_channel=channel_selection,
        rounds_completed=summary["rounds_completed"],
        summary=summary,
    )



# ─── recipe migrate（方向 7：配方版本化）────────────────────────────────────────

_CURRENT_RECIPE_VERSION = 1


def recipe_migrate(recipe_path: str | Path) -> dict[str, Any]:
    """Migrate a recipe to the current recipe_version.

    方向 7 验收口径：recipe migrate 有新旧 schema 双向测试。
    - version 0 (missing recipe_version) → adds recipe_version: 1
    - version 1 → no-op (already current)
    - unknown version → error

    Returns: {ok, recipe_path, from_version, to_version, changed}
    """
    import yaml

    path = Path(recipe_path)
    if not path.exists():
        return error_envelope([f"配方文件不存在: {path}"])

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return error_envelope(["配方顶层必须是映射"])

    current_ver = data.get("recipe_version", 0)

    if current_ver == _CURRENT_RECIPE_VERSION:
        return ok_envelope(
            recipe_path=str(path),
            from_version=current_ver,
            to_version=current_ver,
            changed=False,
            message=f"配方已是最新版本 (v{current_ver})",
        )

    if current_ver > _CURRENT_RECIPE_VERSION:
        return error_envelope(
            [f"配方版本 {current_ver} 高于当前支持的版本 {_CURRENT_RECIPE_VERSION}"])

    # version 0 → 1: add recipe_version field
    # 写面守卫：`rfauto recipe migrate <path>` 是用户把目标路径作为命令本意的
    # 显式入口（explicit），允许原地升级 recipes/ 下的配方；其余库代码路径
    # 一律不得改写 recipes/ 原件（infra.recipe_guard，处置账见 待办清单
    # 「fix-recipe-pollution」条）。
    from rfauto.infra.recipe_guard import write_recipe_text

    data["recipe_version"] = _CURRENT_RECIPE_VERSION
    write_recipe_text(
        path,
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        explicit=True,
    )
    return ok_envelope(
        recipe_path=str(path),
        from_version=current_ver,
        to_version=_CURRENT_RECIPE_VERSION,
        changed=True,
        message=f"配方已从 v{current_ver} 升级到 v{_CURRENT_RECIPE_VERSION}",
    )


# ─── repro export（方向 7：可复现性）────────────────────────────────────────────

def repro_export(run_id: str, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Export a reproducibility package for a completed run.

    方向 7 验收口径：任一历史 run 的 repro 包在干净 venv 中重建并跑通
    fake 档重放。

    Exports to <output_dir>/<run_id>_repro/:
      - recipe.snapshot.yaml  (final recipe)
      - meta.json             (full provenance)
      - sparams/              (Touchstone files)
      - reproduce.py          (one-click replay script)
      - provenance.json       (environment fingerprint)

    Returns: {ok, output_dir, files, message}
    """
    run_dir = Path("runs") / run_id
    if not run_dir.is_dir():
        return error_envelope([f"run 不存在: {run_id}"])

    meta_path = run_dir / "meta.json"
    snapshot_path = run_dir / "recipe.snapshot.yaml"
    if not meta_path.exists():
        return error_envelope([f"run 缺少 meta.json: {run_id}"])

    # Output directory
    out_base = Path(output_dir) if output_dir else Path("runs") / "repro"
    out_dir = out_base / f"{run_id}_repro"
    out_dir.mkdir(parents=True, exist_ok=True)

    files: list[str] = []

    # 1. Copy recipe snapshot
    if snapshot_path.exists():
        import shutil
        dest = out_dir / "recipe.snapshot.yaml"
        shutil.copy2(snapshot_path, dest)
        files.append("recipe.snapshot.yaml")
    else:
        return error_envelope([f"run 缺少配方快照: {run_id}"])

    # 2. Copy meta.json
    import shutil
    meta_dest = out_dir / "meta.json"
    shutil.copy2(meta_path, meta_dest)
    files.append("meta.json")

    # 3. Extract provenance
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    provenance = {
        "run_id": run_id,
        "git_sha": meta.get("git_sha", "unknown"),
        "package_version": meta.get("package_version", "unknown"),
        "python_version": meta.get("python_version", "unknown"),
        "os": meta.get("os", "unknown"),
        "pip_freeze_sha": meta.get("pip_freeze_sha", "unknown"),
        "solver_versions": meta.get("solver_versions", {}),
        "optuna_seed": meta.get("optuna_seed") or meta.get("seed"),
        "aedt_version": meta.get("aedt_version", ""),
        "ads_version": meta.get("ads_version", ""),
        "timestamp": meta.get("timestamp", ""),
    }
    prov_path = out_dir / "provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2, default=str), encoding="utf-8")
    files.append("provenance.json")

    # 4. Copy S-parameter files
    sparams_dir = run_dir / "results"
    if sparams_dir.exists():
        snp_files = sorted(sparams_dir.glob("*.s*p"))
        if snp_files:
            sparams_out = out_dir / "sparams"
            sparams_out.mkdir(exist_ok=True)
            for f in snp_files:
                shutil.copy2(f, sparams_out / f.name)
                files.append(f"sparams/{f.name}")

    # 5. Copy trials data (Optuna trajectory)
    trials_dir = run_dir / "trials"
    if trials_dir.exists():
        trials_out = out_dir / "trials"
        trials_out.mkdir(exist_ok=True)
        for f in sorted(trials_dir.glob("*")):
            if f.is_file():
                shutil.copy2(f, trials_out / f.name)
                files.append(f"trials/{f.name}")

    # 6. Generate reproduce.py
    adapter = meta.get("adapter", "fake")
    recipe_name = "recipe.snapshot.yaml"
    repro_script = _generate_reproduce_py(run_id, recipe_name, adapter)
    script_path = out_dir / "reproduce.py"
    script_path.write_text(repro_script, encoding="utf-8")
    files.append("reproduce.py")

    return ok_envelope(
        run_id=run_id,
        output_dir=str(out_dir),
        files=files,
        message=f"复现包已导出到 {out_dir}",
    )


def _generate_reproduce_py(run_id: str, recipe_name: str, adapter: str) -> str:
    """Generate a standalone reproduce.py script."""
    lines = [
        "#!/usr/bin/env python3",
        f'"""Reproduce run {run_id}."""',
        "import json, sys",
        "from pathlib import Path",
        "",
        "def main():",
        f"    recipe = Path(__file__).parent / \"{recipe_name}\"",
        "    if not recipe.exists():",
        "        print(f\"ERROR: {recipe}\"); sys.exit(1)",
        "    from rfauto.service.api import run_once",
        f"    result = run_once(recipe, adapter_name=\"{adapter}\")",
        "    if not result.get(\"ok\"):",
        "        print(f\"ERROR: {result.get('errors')}\"); sys.exit(1)",
        "    meta_path = Path(__file__).parent / \"meta.json\"",
        "    if meta_path.exists():",
        "        orig = json.loads(meta_path.read_text(encoding=\"utf-8\")).get(\"metrics\", {})",
        "        new = result.get(\"metrics\", {})",
        "        for k in sorted(set(orig) | set(new)):",
        "            ov, nv = orig.get(k), new.get(k)",
        "            if isinstance(ov, (int, float)) and isinstance(nv, (int, float)):",
        "                print(f\"  {k}: {ov:.4f} -> {nv:.4f}\")",
        "    print(json.dumps(result.get(\"metrics\", {}), indent=2))",
        "",
        "if __name__ == \"__main__\":",
        "    main()",
    ]
    return "\n".join(lines)
