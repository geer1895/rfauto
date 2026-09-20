"""HFSS -> ADS 联动编排（二阶段, ADR-0003）。

Phase 1: HFSS 求解 -> 导出 .sNp (adapter.export_touchstone, 已含契约校验)
Phase 2: ADS 网表 -> hpeesofsim -> .ds -> 系统指标 (B 档)
         若 ADS 全线受阻 -> C 档保底（s3p + port_map.json + ads_import_guide.md）

P3 实现。run_two_phase 的 ads_sim_fn 可注入, 便于单测(不耗 ADS license)
用 FakeAdapter 驱动; 真机走默认实现 _default_ads_sim。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.core.contracts import AdsExchangeContract
from rfauto.core.errors import ContractViolationError

logger = logging.getLogger(__name__)


class HfssAdsLink:
    """二阶段 HFSS-ADS 验证链路编排。

    rounds=N 固定往返（ADR-0003, 默认 N=2）; 每轮都走 phase1(导出 sNp)
    + phase2(ADS 仿真/系统指标), 结果写入 output_dir。
    """

    def __init__(
        self,
        output_dir: Path | None = None,
        ads_dir: Path | None = None,
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path(".")
        self.ads_dir = ads_dir

    # ----------------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------------
    def run_two_phase(
        self,
        hfss_adapter: Any,
        ads_recipe: Any,
        contract: AdsExchangeContract,
        rounds: int = 2,
        ads_sim_fn: Callable | None = None,
    ) -> dict[str, Any]:
        """运行二阶段链路。

        hfss_adapter: 实现 export_touchstone(path, contract) 的适配器
            (SimulatorAdapter: FakeAdapter / HfssAdapter);
        ads_recipe: AdsCircuitRecipe（含系统指标清单）;
        contract: AdsExchangeContract（端口顺序/阻抗/单位）;
        ads_sim_fn(snp_path, out_dir, contract) -> dict: 可注入的 ADS 仿真实现;
            默认 _default_ads_sim（真机 B 档 + C 档保底）。
        """
        if ads_sim_fn is None:
            ads_sim_fn = self._default_ads_sim
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []

        for round_idx in range(rounds):
            logger.info("Starting verification round %d/%d", round_idx + 1, rounds)
            round_dir = self.output_dir / f"round{round_idx + 1}"
            round_dir.mkdir(parents=True, exist_ok=True)

            t0 = time.time()
            snp_path = self._phase1_export(hfss_adapter, contract, round_dir, round_idx + 1)
            solve_s = time.time() - t0

            t1 = time.time()
            phase2 = ads_sim_fn(snp_path, round_dir, contract)
            sim_s = time.time() - t1

            phase2["solve_time_s"] = solve_s
            phase2["sim_time_s"] = sim_s
            results.append({
                "round": round_idx + 1,
                "snp_path": str(snp_path),
                "phase2": phase2,
            })

        summary = {
            "rounds_completed": rounds,
            "results": results,
            "status": "ok",
        }
        self.write_report(summary)
        return summary

    # ----------------------------------------------------------------
    # Phase 1
    # ----------------------------------------------------------------
    def _phase1_export(
        self, hfss_adapter: Any, contract: AdsExchangeContract,
        round_dir: Path, round_idx: int,
    ) -> Path:
        """Phase 1: 通过 adapter 导出 Touchstone（含契约校验）。

        请求一个占位扩展名, 实际扩展名由 adapter 按端口数修正并返回。
        """
        req = round_dir / f"round{round_idx}.sNp"
        snp = hfss_adapter.export_touchstone(req, contract.touchstone)
        snp = Path(snp)
        logger.info("Phase 1: 导出 sNp = %s", snp)
        return snp

    # ----------------------------------------------------------------
    # Phase 2 (默认 B 档 + C 档保底)
    # ----------------------------------------------------------------
    def _default_ads_sim(
        self, snp_path: Path, out_dir: Path, contract: AdsExchangeContract,
    ) -> dict[str, Any]:
        """默认 ADS 仿真: B 档(网表+hpeesofsim+系统指标); 受阻则 C 档保底。
        """
        from rfauto.linkage import ads_circuit
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        recipe = ads_circuit.AdsCircuitRecipe(
            topology="wilkinson_snp", contract=contract,
        )
        try:
            netlist = out_dir / "netlist.txt"
            ads_circuit.render_netlist(recipe, snp_path, netlist, contract)
            from rfauto.adapters import ads_netlist
            ads_netlist.run_hpeesofsim(netlist, ads_dir=self.ads_dir)
            ds = out_dir / "netlist.txt.ds"
            payload = ads_circuit.parse_results(ds, ads_dir=self.ads_dir, contract=contract)
            logger.info("Phase 2 (B 档) 完成: metrics=%s", payload["metrics"])
            return {"status": "b_ok", "metrics": payload["metrics"],
                    "n_ports": payload["n_ports"]}
        except ContractViolationError:
            raise  # 契约违规必须显式报错（验收项 2），不降级到 C 档保底
        except Exception as exc:
            logger.warning("Phase 2 (B 档) 受阻, 落 C 档保底: %s", exc)
            self._write_c_fallback(snp_path, out_dir, contract, exc)
            return {"status": "c_fallback", "metrics": {},
                    "reason": str(exc), "n_ports": None}

    def _write_c_fallback(
        self, snp_path: Path, out_dir: Path, contract: AdsExchangeContract, exc: Exception,
    ) -> None:
        """C 档保底: 自动产 s3p + port_map.json + ads_import_guide.md。
        """
        out_dir = Path(out_dir)
        port_map = {
            "snp_path": str(snp_path),
            "port_order": contract.touchstone.port_order,
            "renormalization_ohm": contract.touchstone.renormalization_ohm,
            "frequency_unit": contract.touchstone.frequency_unit,
            "b_fallback_reason": str(exc),
        }
        (out_dir / "port_map.json").write_text(
            json.dumps(port_map, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        (out_dir / "ads_import_guide.md").write_text(
            self._ads_import_guide(snp_path, contract, exc), encoding="utf-8",
        )
        logger.info("C 档保底已写: %s (port_map.json + ads_import_guide.md)", out_dir)

    @staticmethod
    def _ads_import_guide(snp_path: Path, contract: AdsExchangeContract, exc: Exception) -> str:
        """生成 ADS 手动导入指引（C 档产物, 无 markdown 代码围栏）。"""
        n = len(contract.touchstone.port_order)
        nodes = " ".join(f"P{i}" for i in range(1, n + 1))
        g = [
            "# ADS 手动导入指引（C 档保底）",
            "",
            "自动 B 档(hpeesofsim)受阻, 请按以下步骤在 ADS 中手动导入并验证。",
            "",
            "## 1. 数据文件",
            f"- Touchstone: {snp_path}",
            f"- 端口顺序: {contract.touchstone.port_order}",
            f"- 参考阻抗: {contract.touchstone.renormalization_ohm} Ohm",
            f"- 频率单位: {contract.touchstone.frequency_unit}",
            "",
            "## 2. 建议网表片段（SnP 组件, ADR-0009）",
            "SnP 组件行（每条语句独占一行）:",
            f"SnP:SNP1  {nodes} NumPorts={n} File=\"{snp_path}\" Type=\"touchstone\" InterpMode=\"linear\" InterpDom=\"\" ExtrapMode=\"constant\" Temp=27.0 CheckPassivity=0",
            "",
            "## 3. 受阻原因",
            str(exc),
        ]
        return "\n".join(g)

    # ----------------------------------------------------------------
    # 从已有 sNp 直接跑 ADS 链路（link 命令用, 不重跑 HFSS）
    # ----------------------------------------------------------------
    def run_from_snp(
        self,
        snp_path: str | Path,
        contract: AdsExchangeContract,
        rounds: int = 2,
        ads_sim_fn: Callable | None = None,
    ) -> dict[str, Any]:
        """基于一份现成 Touchstone 跑 N 轮 ADS 验证（ADR-0003 链路后端）。

        供 rfauto link 使用: 直接消费 runs/<run_id>/results 的 sNp,
        不重新调用 HFSS。每轮拷贝 sNp 到 roundN 目录 -> ADS 仿真。
        """
        if ads_sim_fn is None:
            ads_sim_fn = self._default_ads_sim
        snp_path = Path(snp_path)
        if not snp_path.exists():
            raise FileNotFoundError(f"Touchstone 不存在: {snp_path}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []

        for round_idx in range(rounds):
            round_dir = self.output_dir / f"round{round_idx + 1}"
            round_dir.mkdir(parents=True, exist_ok=True)
            copy = round_dir / snp_path.name
            if copy.resolve() != snp_path.resolve():
                import shutil
                shutil.copy2(snp_path, copy)
            t1 = time.time()
            phase2 = ads_sim_fn(copy, round_dir, contract)
            sim_s = time.time() - t1
            phase2["sim_time_s"] = sim_s
            results.append({
                "round": round_idx + 1,
                "snp_path": str(copy),
                "phase2": phase2,
            })

        summary = {
            "rounds_completed": rounds,
            "results": results,
            "status": "ok",
        }
        self.write_report(summary)
        return summary

    # ----------------------------------------------------------------
    # 报告
    # ----------------------------------------------------------------
    def write_report(self, summary: dict[str, Any]) -> Path:
        """写 Markdown 报告（P3 报告生成器 v1）。"""
        path = self.output_dir / "ads_link_report.md"
        lines: list[str] = ["# HFSS -> ADS 联动报告", ""]
        lines.append(f"- 往返次数: {summary['rounds_completed']}")
        lines.append("")
        lines.append("| 轮次 | 状态 | system_gain_db | input_vswr | amplitude_balance_db |")
        lines.append("|------|------|----------------|------------|----------------------|")
        for r in summary["results"]:
            p2 = r["phase2"]
            m = p2.get("metrics") or {}
            g = "-"
            if "system_gain_db" in m:
                g = f"{m['system_gain_db']:.4f}"
            v = "-"
            if "input_vswr" in m:
                v = f"{m['input_vswr']:.4f}"
            a = "-"
            if "amplitude_balance_db" in m:
                a = f"{m['amplitude_balance_db']:.4f}"
            lines.append(f"| {r['round']} | {p2['status']} | {g} | {v} | {a} |")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("报告已生成: %s", path)
        return path

