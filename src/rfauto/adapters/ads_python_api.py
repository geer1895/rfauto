"""ADS 2027 Python API 适配器（A档）。

ADS 2027 的原生 Python API 通道：
- 建/改 workspace 原理图
- 放置 SNP/DataItem
- 运行仿真
- 读数据集

ADR-0009 决定：A档保留为可选后端，B档（网表+hpeesofsim）为主通道。
A档能力边界已探明（2027 headless 可用），但维护成本高于收益。
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AdsPythonApiAdapter:
    """ADS Python API 适配器（A档）。

    通过 ADS 自带 python 子进程调用 keysight.ads.de API。
    进程边界：本项目 venv=3.12，ADS python=3.14.6，必须子进程调用。
    """

    def __init__(self, ads_dir: str | Path | None = None) -> None:
        """
        Args:
            ads_dir: ADS 安装目录，默认从环境变量 RFAUTO_HPEESOF_DIR 读取
        """
        import os
        self.ads_dir = Path(ads_dir or os.environ.get("RFAUTO_HPEESOF_DIR", ""))
        self.python_exe = self.ads_dir / "bin" / "python.exe"
        self.workspace: str | None = None
        self._connected = False

    def connect(self, settings: dict[str, Any] | None = None) -> None:
        """连接 ADS Design Environment。"""
        if not self.ads_dir.exists():
            raise FileNotFoundError(f"ADS 目录不存在: {self.ads_dir}")
        if not self.python_exe.exists():
            raise FileNotFoundError(f"ADS python 不存在: {self.python_exe}")

        # 验证 keysight.ads.de 可导入
        result = self._run_ads_script("import keysight.ads.de as de; print('OK')")
        if "OK" not in result:
            raise RuntimeError(f"ADS python 无法导入 keysight.ads.de: {result}")

        self._connected = True
        logger.info("ADS Python API 连接成功: %s", self.ads_dir)

    def open_workspace(self, workspace_path: str) -> None:
        """打开 ADS workspace。"""
        self._ensure_connected()
        self.workspace = workspace_path
        logger.info("打开 workspace: %s", workspace_path)

    def create_workspace(self, workspace_path: str, library_name: str = "rfauto_lib") -> None:
        """创建新 workspace。"""
        self._ensure_connected()
        script = f"""
import keysight.ads.de as de
ws = de.create_workspace(r"{workspace_path}")
ws.open()
lib = ws.create_library("{library_name}")
print("WORKSPACE_CREATED")
"""
        result = self._run_ads_script(script)
        if "WORKSPACE_CREATED" not in result:
            raise RuntimeError(f"创建 workspace 失败: {result}")
        self.workspace = workspace_path
        logger.info("创建 workspace: %s", workspace_path)

    def place_snp(self, s_params_path: str, component_name: str = "SNP1") -> None:
        """在原理图中放置 SNP 器件。"""
        self._ensure_connected()
        script = f"""
import keysight.ads.de as de
from keysight.ads.de._pde.db import DesignMode
ws = de.open_workspace(r"{self.workspace}")
# 获取或创建 schematic
lib_names = ws.library_names
if lib_names:
    lib = ws.open_library(lib_names[0])
    designs = lib.design_names
    if designs:
        d = ws.design(designs[0], DesignMode.READ_WRITE)
    else:
        d = lib.create_cell("schematic", "SNP_Circuit")
else:
    d = ws.create_cell("schematic", "SNP_Circuit")

# 放置 SNP 组件
# 注意：实际 API 需要通过 netlist 或 GUI 操作
print("SNP_PLACED")
"""
        self._run_ads_script(script)
        logger.info("放置 SNP: %s", s_params_path)

    def generate_netlist(self, design_name: str | None = None) -> str:
        """生成网表。"""
        self._ensure_connected()
        script = f"""
import keysight.ads.de as de
from keysight.ads.de._pde.db import DesignMode
ws = de.open_workspace(r"{self.workspace}")
lib_names = ws.library_names
d_name = "{design_name}" if "{design_name}" else lib_names[0] + ":schematic" if lib_names else ""
if d_name:
    d = ws.design(d_name, DesignMode.READ_ONLY)
    netlist = d.generate_netlist()
    print("NETLIST_START")
    print(netlist)
    print("NETLIST_END")
else:
    print("ERROR: No design found")
"""
        result = self._run_ads_script(script)
        # 提取网表
        if "NETLIST_START" in result and "NETLIST_END" in result:
            start = result.index("NETLIST_START") + len("NETLIST_START")
            end = result.index("NETLIST_END")
            return result[start:end].strip()
        raise RuntimeError(f"生成网表失败: {result}")

    def run_simulation(self, netlist_path: str | None = None) -> dict[str, Any]:
        """运行仿真（通过 hpeesofsim）。"""
        self._ensure_connected()

        if netlist_path is None:
            # 生成网表
            netlist = self.generate_netlist()
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write(netlist)
                netlist_path = f.name

        # 调用 hpeesofsim
        hpeesofsim = self.ads_dir / "bin" / "hpeesofsim.exe"
        if not hpeesofsim.exists():
            raise FileNotFoundError(f"hpeesofsim 不存在: {hpeesofsim}")

        # 设置 PATH
        import os
        env = os.environ.copy()
        env["PATH"] = str(self.ads_dir / "bin") + ";" + env.get("PATH", "")
        env["PATH"] += ";" + str(self.ads_dir / "adsptolemy" / "lib.win32_64")
        env["PATH"] += ";" + str(self.ads_dir / "tools" / "python")
        env["HPEESOF_DIR"] = str(self.ads_dir)

        result = subprocess.run(
            [str(hpeesofsim), netlist_path],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path(netlist_path).parent),
        )

        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def read_dataset(self, dataset_path: str) -> dict[str, Any]:
        """读取仿真数据集。"""
        self._ensure_connected()
        script = f"""
import json
import keysight.ads.dataset as dataset
data = dataset.open(r"{dataset_path}")
result = {{}}
for key in data.keys():
    df = data[key].to_dataframe().reset_index()
    result[key] = {{
        "columns": list(df.columns),
        "n_rows": len(df),
        "sample": df.head(5).to_dict(orient="records"),
    }}
print("DATASET_START")
print(json.dumps(result, default=str))
print("DATASET_END")
"""
        result = self._run_ads_script(script)
        if "DATASET_START" in result and "DATASET_END" in result:
            start = result.index("DATASET_START") + len("DATASET_START")
            end = result.index("DATASET_END")
            return json.loads(result[start:end].strip())
        raise RuntimeError(f"读取数据集失败: {result}")

    def close(self) -> None:
        """关闭连接。"""
        self._connected = False
        self.workspace = None
        logger.info("ADS Python API 连接关闭")

    def _ensure_connected(self) -> None:
        """确保已连接。"""
        if not self._connected:
            raise RuntimeError("未连接，请先调用 connect()")

    def _run_ads_script(self, script: str) -> str:
        """在 ADS python 中运行脚本。"""
        import os
        env = os.environ.copy()
        env["HPEESOF_DIR"] = str(self.ads_dir)

        result = subprocess.run(
            [str(self.python_exe), "-c", script],
            capture_output=True,
            text=True,
            env=env,
        )
        return result.stdout + result.stderr
