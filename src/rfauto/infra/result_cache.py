"""rfauto result cache — fine-grained SHA-256 keys (§8.4)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

# ── 内容寻址键成分（#106 / #158）─────────────────────────────────────────
#
# 键成分**分列**存放，便于定位"为什么失效"（why_miss）。
# #106：recipe_version（配方文档 schema 版本）与 schema_version（插件参数
# schema 版本）语义不同，必须分列——任一变化都不得复用旧数值结果。
CONTENT_KEY_FIELDS: tuple[str, ...] = (
    "model_name",
    "rendered_script_hash",   # 渲染脚本内容哈希（建模脚本变更）
    "geometry_spec_hash",
    "material_config_hash",
    "mesh_params",            # 网格参数（网格是数值实验的一部分）
    "params_canonical_json",
    "setup_hash",
    "export_contract_hash",
    "adapter_version",        # 适配器/求解器通道版本
    "aedt_version",
    "plugin_version",
    "recipe_version",         # #106：配方 schema 版本
    "schema_version",         # #106：插件参数 schema 版本
)

# 哪些成分变化**必须 miss**，值为 why_miss 的人类可读解释。
INVALIDATION_REASONS: dict[str, str] = {
    "model_name": "模型不同（不同物理器件不可复用）",
    "rendered_script_hash": "渲染脚本内容变化（建模脚本已改，旧几何结果作废）",
    "geometry_spec_hash": "几何规格变化",
    "material_config_hash": "材料配置变化",
    "mesh_params": "网格参数变化（网格是数值实验的一部分，不同网格=不同结果）",
    "params_canonical_json": "设计参数变化",
    "setup_hash": "求解 setup/目标变化",
    "export_contract_hash": "交换契约变化（端口/归一化约定可能不同）",
    "adapter_version": "适配器/求解器版本变化（数值内核可能不同）",
    "aedt_version": "AEDT 版本变化",
    "plugin_version": "插件版本变化",
    "recipe_version": "recipe schema 版本变化（#106：配方语义可能不兼容）",
    "schema_version": "插件参数 schema 版本变化（#106：参数→几何映射可能已变）",
}

# #158：study/seed **明确不进键**——同几何不同 study 合法复用同一数值结果
# （配对实验）；新轨迹（新物理模型/新网格）须换 study/seed 并升
# recipe_version/schema_version，否则会误命中旧数值。
KEY_EXCLUDED_SCOPES: tuple[str, ...] = ("study", "seed")

# provenance 取值：命中=复用缓存产物；miss=需真跑。
PROVENANCE_CACHE = "cache"
PROVENANCE_MISS = "miss"

# #158 语义说明（写进 lookup 结果，便于调用方与审计理解跨 study 复用）。
CROSS_STUDY_NOTE = (
    "同几何跨 study 复用合法（配对实验，key 与 study/seed 解耦）；"
    "新轨迹（新物理模型/新网格）须换 study/seed 并升 "
    "recipe_version/schema_version/mesh_params，否则误命中旧数值"
)

# 生产接线（P2①）：manifest 里真跑产物的 provenance 取值。
PROVENANCE_COMPUTED = "computed"

# #106：配方文档缺 recipe_version 时的口径——与 service.recipe_migrate 一致
# （version 0 = 未版本化的历史配方，migrate 后升为 1）。
UNVERSIONED_RECIPE_VERSION = "0"


def sha256_text(text: str) -> str:
    """UTF-8 文本的 SHA-256 十六进制摘要（键成分哈希统一入口）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ResultCache:
    """Content-addressable cache keyed by a SHA-256 of simulation parameters.

    模式（环境变量 ``RFAUTO_CACHE``）：
    - ``readwrite``（默认）：读写均开
    - ``readonly``：命中可查，不写新条目（C5 修复：原先该档等同 readwrite）
    - ``off``：完全旁路（check 恒 miss、store 空操作）

    每个条目在 store 时写入 ``_manifest.json``（含 model 名与时间戳），
    ``clear(model_name=...)`` 据此选择性清理（C5 修复：原先找 meta.json 的
    ``model_name`` 字段，而 store 从不写该文件——选择性清理永久 no-op）。
    """

    _CACHE_DIR = Path(".rfauto_cache")
    _MANIFEST = "_manifest.json"

    def __init__(self, cache_dir: str | Path = _CACHE_DIR) -> None:
        self.cache_dir = Path(cache_dir)
        mode = os.environ.get("RFAUTO_CACHE", "readwrite").lower()
        if mode not in ("off", "readonly", "readwrite"):
            mode = "readwrite"
        self._mode = mode
        self.enabled = mode != "off"
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- Key computation ----------------------------------------------------

    @staticmethod
    def compute_key(
        *,
        model_name: str = "",
        plugin_version: str = "",
        geometry_spec_hash: str = "",
        material_config_hash: str = "",
        params_canonical_json: str = "",
        setup_hash: str = "",
        export_contract_hash: str = "",
        adapter_version: str = "",
        aedt_version: str = "",
    ) -> str:
        """Return a hex SHA-256 digest of the canonical key components."""
        payload = json.dumps(
            {
                "model_name": model_name,
                "plugin_version": plugin_version,
                "geometry_spec_hash": geometry_spec_hash,
                "material_config_hash": material_config_hash,
                "params_canonical_json": params_canonical_json,
                "setup_hash": setup_hash,
                "export_contract_hash": export_contract_hash,
                "adapter_version": adapter_version,
                "aedt_version": aedt_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ---- Content-addressed key (#106 / #158) ---------------------

    @staticmethod
    def canonical_json(obj: object) -> str:
        """把任意 JSON 可序列化对象收敛成稳定字符串（键排序、无空格）。"""
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def content_components(cls, **fields: object) -> dict[str, str]:
        """校验并归一化内容寻址键成分（分列，便于 why_miss 定位）。

        - 未知成分名 → TypeError（防止 study/seed 等被误当键成分：#158）；
        - None 归一为空串；dict 走 canonical_json；
        - 其余非字符串（int/float/list/bool）→ TypeError（键必须可复现）。
        """
        unknown = sorted(set(fields) - set(CONTENT_KEY_FIELDS))
        if unknown:
            raise TypeError(
                f"未知缓存键成分: {unknown}；可选成分={list(CONTENT_KEY_FIELDS)}。"
                "注意 study/seed 不进键（#158，见 KEY_EXCLUDED_SCOPES）"
            )
        components: dict[str, str] = {}
        for name in CONTENT_KEY_FIELDS:
            value = fields.get(name, "")
            if value is None:
                value = ""
            if isinstance(value, dict):
                value = cls.canonical_json(value)
            if not isinstance(value, str):
                raise TypeError(
                    f"缓存键成分 {name!r} 必须是字符串（或 dict），"
                    f"收到 {type(value).__name__}"
                )
            components[name] = value
        return components

    @classmethod
    def compute_content_key(cls, **fields: object) -> str:
        """返回内容寻址键（SHA-256），成分分列存入 payload。

        覆盖：渲染脚本内容（rendered_script_hash）+ 网格参数（mesh_params）+
        适配器版本（adapter_version）+ recipe_version + schema_version（#106），
        另含几何/材料/参数/setup/契约/AEDT 版本。

        study/seed 不在键中（#158）：同几何不同 study 命中同一缓存条目，
        由 lookup 以 provenance="cache" 标记复用来源。
        """
        components = cls.content_components(**fields)
        payload = json.dumps(
            {
                "kind": "rfauto.result_cache.content",
                "version": 1,
                "excluded_scopes": list(KEY_EXCLUDED_SCOPES),
                "components": components,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def components_for_run(
        cls,
        *,
        model_name: str,
        recipe_data: dict | None,
        params_canonical_json: str,
        plugin_version: str = "",
        plugin_schema_version: object = "",
        adapter_version: str = "",
        aedt_version: str = "",
        export_contract: object = None,
        rendered_script: str | None = None,
        geometry_spec: object = None,
        material_config: object = None,
        mesh_params: object = None,
    ) -> dict[str, str]:
        """从生产路径现成输入派生 13 成分（P2① 生产接线，api.run_once /
        optimizer 共用**一处**派生，防两处各自为政漂移——原 compute_key 时代
        api.py 用裸 setup JSON、optimizer 用 setup+objectives 截断哈希各行其是）。

        #106 语义分列（不得互相顶替）：
        - ``recipe_version`` ← 配方文档 ``recipe_version`` 字段（配方 schema 版本；
          缺省 ``UNVERSIONED_RECIPE_VERSION``="0"，与 recipe_migrate 口径一致）；
        - ``schema_version`` ← 插件类 ``schema_version``（插件参数 schema 版本，
          参数→几何映射的版本）；
        - ``plugin_version`` 保留历史 ``schema{N}`` 字串（粗粒度插件身份）。

        study/seed 不在此派生（#158，见 KEY_EXCLUDED_SCOPES）：由 lookup/store
        以 provenance 记入 manifest。objectives 不进键——Touchstone 与目标无关，
        同几何异目标合法复用同一数值结果。

        可选成分（rendered_script / geometry_spec / material_config / mesh_params）
        调用点没有就留空串（"" = 该入口未提供），dict 走 canonical_json，
        pydantic 模型走 model_dump()。setup / 契约一律 canonical_json → SHA-256。
        """
        recipe = recipe_data or {}

        def _hash_obj(obj: object) -> str:
            if obj is None:
                return ""
            if hasattr(obj, "model_dump"):
                obj = obj.model_dump()
            if isinstance(obj, str):
                return sha256_text(obj)
            return sha256_text(cls.canonical_json(obj))

        if mesh_params is None:
            mesh_str = ""
        elif isinstance(mesh_params, str):
            mesh_str = mesh_params
        else:
            mesh_str = cls.canonical_json(mesh_params)

        recipe_version_raw = recipe.get("recipe_version")
        recipe_version = (
            UNVERSIONED_RECIPE_VERSION
            if recipe_version_raw is None
            else str(recipe_version_raw)
        )

        return cls.content_components(
            model_name=str(model_name or ""),
            rendered_script_hash=sha256_text(rendered_script) if rendered_script else "",
            geometry_spec_hash=_hash_obj(geometry_spec),
            material_config_hash=_hash_obj(material_config),
            mesh_params=mesh_str,
            params_canonical_json=str(params_canonical_json or ""),
            setup_hash=sha256_text(cls.canonical_json(recipe.get("setup") or {})),
            export_contract_hash=_hash_obj(export_contract),
            adapter_version=str(adapter_version or ""),
            aedt_version=str(aedt_version or ""),
            plugin_version=str(plugin_version or ""),
            recipe_version=recipe_version,
            schema_version="" if plugin_schema_version is None else str(plugin_schema_version),
        )

    # ---- Check / Store / Clear ----------------------------------------------

    def check(self, key: str) -> Path | None:
        """Return cached result directory path, or ``None`` if miss.

        完整性校验（C5）：条目必须含 manifest 且至少一个 Touchstone 文件，
        半成品/损坏条目按 miss 处理（原先只判 is_dir 就判命中）。
        """
        if not self.enabled:
            return None
        entry = self.cache_dir / key
        if not entry.is_dir():
            return None
        if not (entry / self._MANIFEST).is_file():
            return None
        if not list(entry.glob("params.s*p")):
            return None
        return entry

    def store(
        self,
        key: str,
        source_dir: str | Path,
        sparams_path: str | Path | None = None,
        metrics_path: str | Path | None = None,
        model_name: str = "",
        study: str = "",
        seed: str = "",
        components: dict[str, str] | None = None,
    ) -> Path:
        """Copy *source_dir* contents into the cache under *key*.

        原子性（C5）：先写临时目录再改名，中途崩溃不会留下被 check 判为
        命中的半成品。model_name 写入条目 manifest 供选择性清理。

        （#158）：study/seed **不参与 key**，只作为 provenance 记入
        manifest——同几何不同 study 复用同一条目，lookup 据此标 cross_study。
        components 为内容寻址键的**分列成分**（compute_content_key 的输入，
        content_components 归一化后），供 diagnose_miss 给出 why_miss。
        """
        if self._mode != "readwrite":
            return Path(source_dir)

        dest = self.cache_dir / key
        tmp = self.cache_dir / f"{key}.tmp-{os.getpid()}"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(str(source_dir), str(tmp))

        for extra in (sparams_path, metrics_path):
            if extra is not None:
                extra_p = Path(extra)
                if extra_p.is_file():
                    shutil.copy2(str(extra_p), str(tmp / extra_p.name))

        manifest = {
            "key": key,
            "model": model_name,
            "stored_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            # 产物来源=真跑（provenance="computed"）；命中侧改写为
            # "cache"（lookup 返回值），manifest 保留原始求解 provenance。
            "provenance": PROVENANCE_COMPUTED,
            "study": study,
            "seed": seed,
        }
        if components is not None:
            try:
                manifest["components"] = self.content_components(**components)
            except Exception:  # 非本模块产出的成分：退化为字符串快照
                manifest["components"] = {k: str(v) for k, v in components.items()}
        (tmp / self._MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8",
        )

        if dest.exists():
            shutil.rmtree(dest)
        os.replace(tmp, dest)
        return dest

    def clear(self, model_name: str | None = None) -> int:
        """Clear cache entries.

        If *model_name* is given, only entries whose manifest ``model`` matches
        are removed（兼容旧条目的 meta.json ``model``/``model_name`` 键）.
        Otherwise the entire cache is purged.

        Returns the number of entries removed.
        """
        if not self.cache_dir.exists():
            return 0

        removed = 0
        if model_name is None:
            # Purge everything（含历史遗留的半成品/无 manifest 条目）
            for child in self.cache_dir.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                    removed += 1
            return removed

        # Selective clear
        for child in self.cache_dir.iterdir():
            if not child.is_dir():
                continue
            entry_model = self._entry_model(child)
            if entry_model == model_name:
                shutil.rmtree(child)
                removed += 1
        return removed

    @classmethod
    def _entry_model(cls, entry: Path) -> str | None:
        """读取条目声明的 model 名（manifest 优先，兼容旧 meta.json）。"""
        manifest = entry / cls._MANIFEST
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                return data.get("model")
            except Exception:
                return None
        # 旧格式条目：结果目录里可能带 meta.json（历史行为）
        legacy = entry / "meta.json"
        if legacy.is_file():
            try:
                data = json.loads(legacy.read_text(encoding="utf-8"))
                return data.get("model_name") or data.get("model")
            except Exception:
                return None
        return None

    # ---- Provenance / why_miss (#106 / #158) ----------------------------

    @classmethod
    def _load_manifest(cls, entry: str | Path) -> dict | None:
        """读条目 manifest；不存在或损坏返回 None（best-effort）。"""
        manifest = Path(entry) / cls._MANIFEST
        if not manifest.is_file():
            return None
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def read_manifest(self, key: str) -> dict | None:
        """按 key 读条目 manifest（往返校验/审计用）。"""
        return self._load_manifest(self.cache_dir / key)

    def lookup(
        self,
        key: str,
        *,
        study: str = "",
        seed: str = "",
        components: dict[str, str] | None = None,
    ) -> dict:
        """查询缓存并返回带 provenance 的结果（#158）。

        key 由 compute_content_key 产出（**不含 study/seed**）。返回 dict：

        - hit / path / provenance（"cache" | "miss"）；
        - origin_study / origin_seed：条目原始 study/seed（manifest）；
        - requester_study / requester_seed：本次请求作用域；
        - cross_study：同几何跨 study 复用（origin_study 非空且 != study）；
        - why_miss：miss 时的失效原因（diagnose_miss，best-effort）；
        - note：#158 语义说明（配对合法 / 新轨迹须换 study/seed）。
        """
        result: dict = {
            "hit": False,
            "path": None,
            "key": key,
            "provenance": PROVENANCE_MISS,
            "origin_study": "",
            "origin_seed": "",
            "requester_study": study,
            "requester_seed": seed,
            "cross_study": False,
            "why_miss": [],
            "note": CROSS_STUDY_NOTE,
        }
        if not self.enabled:
            result["why_miss"] = ["缓存已旁路（RFAUTO_CACHE=off）"]
            return result
        entry = self.check(key)
        if entry is None:
            if components:
                # why_miss 是观测性（#105）：扫描 manifest 失败不得阻塞真跑主路径
                try:
                    result["why_miss"] = self.diagnose_miss(components)
                except Exception as exc:  # pragma: no cover - 防御性
                    result["why_miss"] = [f"why_miss 诊断失败（best-effort）: {exc}"]
            return result
        manifest = self._load_manifest(entry) or {}
        origin_study = str(manifest.get("study", ""))
        result.update({
            "hit": True,
            "path": entry,
            "provenance": PROVENANCE_CACHE,
            "origin_study": origin_study,
            "origin_seed": str(manifest.get("seed", "")),
            "cross_study": bool(origin_study) and origin_study != study,
        })
        return result

    def diagnose_miss(self, components: dict[str, str] | None = None) -> list[str]:
        """给出 miss 的 why_miss 解释（best-effort，#105 不阻塞主路径）。

        扫描已缓存条目 manifest 的 components，取与请求成分差异最少的条目，
        按 INVALIDATION_REASONS 逐字段列出 旧值 → 新值（原因）。无历史条目
        可比对时返回单条说明，便于日志定位"为什么没命中"。
        """
        if not components:
            return ["未提供键成分，无法比对（why_miss 需 content_components）"]
        try:
            request = self.content_components(**components)
        except Exception:
            request = {name: str(components.get(name, "")) for name in CONTENT_KEY_FIELDS}
        best: tuple[list[str], dict] | None = None
        if self.cache_dir.exists():
            for child in sorted(self.cache_dir.iterdir()):
                if not child.is_dir():
                    continue
                manifest = self._load_manifest(child)
                if not manifest:
                    continue
                stored = manifest.get("components")
                if not isinstance(stored, dict):
                    continue
                diffs = [
                    name for name in CONTENT_KEY_FIELDS
                    if str(stored.get(name, "")) != request[name]
                ]
                if not diffs:
                    continue
                if best is None or len(diffs) < len(best[0]):
                    best = (diffs, stored)
        if best is None:
            return ["无历史条目可比对（首次写入或缓存已清空）"]
        diffs, stored = best
        out: list[str] = []
        for name in diffs:
            old_value = stored.get(name, "")
            new_value = request[name]
            reason = INVALIDATION_REASONS.get(name, "成分变化")
            out.append(f"{name}: {old_value!r} -> {new_value!r} ({reason})")
        return out
