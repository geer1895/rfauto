"""RunArtifact 数据契约。

RunArtifact：每次仿真运行的标准化数据契约。
设计决策：
- schema: run_id/recipe_hash/mapping_hash/fidelity/seed/measurement_metadata
- 入 runs 数据湖，供代理与 Agent 消费
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RunArtifact:
    """仿真运行数据契约。"""
    run_id: str
    recipe_hash: str
    mapping_hash: str
    fidelity: str  # "fake" | "hfss" | "ads"
    seed: int | None = None
    measurement_metadata: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    cost: float | None = None
    status: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "recipe_hash": self.recipe_hash,
            "mapping_hash": self.mapping_hash,
            "fidelity": self.fidelity,
            "seed": self.seed,
            "measurement_metadata": self.measurement_metadata,
            "metrics": self.metrics,
            "params": self.params,
            "timestamp": self.timestamp,
            "cost": self.cost,
            "status": self.status,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunArtifact:
        return cls(**data)

    @classmethod
    def compute_recipe_hash(cls, recipe_data: dict[str, Any]) -> str:
        """计算配方哈希。"""
        content = json.dumps(recipe_data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @classmethod
    def compute_mapping_hash(cls, mapping: dict[str, str]) -> str:
        """计算映射哈希。"""
        content = json.dumps(mapping, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class RunArtifactStore:
    """RunArtifact 存储（JSON 文件）。"""

    def __init__(self, base_dir: str):
        from pathlib import Path
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, artifact: RunArtifact) -> str:
        """保存 RunArtifact。"""
        path = self._base_dir / f"{artifact.run_id}.json"
        path.write_text(artifact.to_json(), encoding="utf-8")
        return str(path)

    def load(self, run_id: str) -> RunArtifact:
        """加载 RunArtifact。"""
        path = self._base_dir / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"RunArtifact 不存在: {run_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return RunArtifact.from_dict(data)

    def list_runs(self, fidelity: str | None = None) -> list[str]:
        """列出所有 run_id。"""
        runs = []
        for path in self._base_dir.glob("*.json"):
            run_id = path.stem
            if fidelity:
                try:
                    artifact = self.load(run_id)
                    if artifact.fidelity == fidelity:
                        runs.append(run_id)
                except Exception:
                    continue
            else:
                runs.append(run_id)
        return sorted(runs)
