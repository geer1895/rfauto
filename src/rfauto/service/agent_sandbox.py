"""配方沙箱：agent 自主修改配方的隔离区（借鉴 Pi 的"写面隔离"思路）。

agent 对配方的一切自主修改只能落在 runs/recipe_sandbox/ 下的草稿副本；
真实 recipes/ 目录永不被 agent 直接写。草稿生效的唯一通道是
promote → 既有三层 Gate（propose→收件箱批准→apply），与人工提案同链同权。
守卫：路径解析后必须位于沙箱根内（防 ../ 与符号链接逃逸），后缀白名单
.yaml/.yml（防借沙箱写可执行脚本）。
"""

from __future__ import annotations

import difflib
import hashlib
import shutil
from pathlib import Path
from typing import Any

SANDBOX_ROOT = Path("runs") / "recipe_sandbox"
ALLOWED_SUFFIXES = {".yaml", ".yml"}


class SandboxViolation(PermissionError):
    """试图越出沙箱（路径逃逸/非法后缀）时抛出。"""


class RecipeSandbox:
    """每个真实配方对应一份确定性命名的草稿（stem+源路径哈希）。"""

    def __init__(self, root: Path | None = None):
        self.root = (root or SANDBOX_ROOT).resolve()

    # ── 守卫 ──────────────────────────────────────────────────────────────
    def _guard(self, path: str | Path) -> Path:
        p = Path(path)
        p = p if p.is_absolute() else self.root / p
        p = p.resolve()
        if self.root != p and self.root not in p.parents:
            raise SandboxViolation(f"路径越出沙箱: {p}")
        if p.suffix.lower() not in ALLOWED_SUFFIXES:
            raise SandboxViolation(f"沙箱只允许 {sorted(ALLOWED_SUFFIXES)}: {p.name}")
        return p

    def draft_path(self, recipe_path: str | Path) -> Path:
        src = Path(recipe_path).resolve()
        tag = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:8]
        return self._guard(f"{src.stem}_{tag}.yaml")

    # ── 草稿生命周期 ──────────────────────────────────────────────────────
    def stage(self, recipe_path: str | Path) -> dict[str, Any]:
        """复制真实配方为草稿；已存在则不覆盖（保留未 promote 的编辑）。"""
        draft = self.draft_path(recipe_path)
        if draft.exists():
            return {"ok": True, "draft": str(draft), "already_staged": True}
        # copyfile 绕不过 yaml 出口，先行校验草稿目标（沙箱根禁指向 recipes/）
        from rfauto.infra.recipe_guard import check_recipe_write_target

        check_recipe_write_target(draft)
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(recipe_path), draft)
        return {"ok": True, "draft": str(draft), "already_staged": False}

    def discard(self, recipe_path: str | Path) -> dict[str, Any]:
        draft = self.draft_path(recipe_path)
        draft.unlink(missing_ok=True)
        return {"ok": True, "discarded": str(draft)}

    def list_drafts(self) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        return {"ok": True,
                "drafts": [str(p) for p in sorted(self.root.glob("*.yaml"))]}

    # ── 编辑（写面只在沙箱内）────────────────────────────────────────────
    def _load_yaml(self, path: Path) -> dict[str, Any]:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _save_yaml(self, path: Path, data: dict[str, Any]) -> None:
        # 统一出口守卫：草稿写面不得越到受保护 recipes/ 下
        from rfauto.infra.recipe_guard import write_recipe_yaml

        write_recipe_yaml(path, data)

    def _effective(self, entry: Any) -> Any:
        return entry.get("value") if isinstance(entry, dict) else entry

    def apply_param_edits(self, recipe_path: str | Path,
                          params: dict[str, Any]) -> dict[str, Any]:
        """参数合并进草稿（标量自动落到既有 {"value":...} 结构内）。"""
        if not isinstance(params, dict) or not params:
            return {"ok": False, "error": "params 必须是非空 dict"}
        staged = self.stage(recipe_path)
        draft = Path(staged["draft"])
        data = self._load_yaml(draft)
        params_sec = data.setdefault("params", {})
        for key, value in params.items():
            if key in params_sec and isinstance(params_sec[key], dict):
                params_sec[key]["value"] = value
            else:
                params_sec[key] = value
        self._save_yaml(draft, data)
        return {**staged, "applied": params}

    def write_yaml(self, recipe_path: str | Path, content: str) -> dict[str, Any]:
        """整文件覆写草稿（给将来的原文编辑模式；守卫同 apply）。"""
        draft = self.draft_path(recipe_path)
        # 统一出口守卫：沙箱根不可被指到受保护 recipes/ 下
        from rfauto.infra.recipe_guard import write_recipe_text

        write_recipe_text(draft, content)
        return {"ok": True, "draft": str(draft)}

    # ── 对比与生效 ────────────────────────────────────────────────────────
    def diff(self, recipe_path: str | Path) -> dict[str, Any]:
        draft = self.draft_path(recipe_path)
        if not draft.exists():
            return {"ok": False, "error": "尚无草稿（先 edit_recipe_draft）"}
        src = Path(recipe_path)
        orig_text = src.read_text(encoding="utf-8").splitlines()
        draft_text = draft.read_text(encoding="utf-8").splitlines()
        text_diff = "\n".join(difflib.unified_diff(
            orig_text, draft_text, fromfile=str(src), tofile=str(draft), lineterm=""))
        orig_p = self._load_yaml(src).get("params", {})
        draft_p = self._load_yaml(draft).get("params", {})
        params_changed = {k: {"old": self._effective(orig_p.get(k)),
                              "new": self._effective(draft_p.get(k))}
                          for k in set(orig_p) | set(draft_p)
                          if self._effective(orig_p.get(k)) != self._effective(draft_p.get(k))}
        return {"ok": True, "draft": str(draft), "unified_diff": text_diff,
                "params_changed": params_changed}

    def promote(self, recipe_path: str | Path,
                adapter_name: str = "fake") -> dict[str, Any]:
        """草稿差异走三层 Gate：目前仅支持 params 差异（其余节返回原因）。

        propagate 的是标量值 dict（agent_propose 的 L1/L2 以此校验白名单与范围），
        批准链 apply 时用的仍是真实配方——草稿只是差异的载体。
        params 之外的节按解析后的结构对比，有任何差异都整体拒绝。
        """
        d = self.diff(recipe_path)
        if not d.get("ok"):
            return d
        src, draft = Path(recipe_path), Path(d["draft"])
        orig_wo = {k: v for k, v in self._load_yaml(src).items() if k != "params"}
        draft_wo = {k: v for k, v in self._load_yaml(draft).items() if k != "params"}
        if orig_wo != draft_wo:
            return {"ok": False, "stage": "promote",
                    "error": "草稿含 params 之外的改动，Gate 提案目前只支持 params；"
                             "请把其他改动整理成文字建议转告用户",
                    "diff": d}
        params = {k: v["new"] for k, v in d["params_changed"].items()}
        if not params:
            return {"ok": False, "stage": "promote", "error": "草稿与真实配方无差异"}
        from rfauto.service.api import agent_propose
        proposed = agent_propose(recipe_path, params, adapter_name=adapter_name)
        return {**proposed, "sandbox_promote": True, "params_proposed": params}


# ─── F8 模板草案沙箱（RecipeSandbox 的兄弟类：写面隔离同构，后缀白名单 .py）────
#
# LLM 模板草案生成器（service/proposal_chain_service.py）产出的渲染脚本草案
# 只能落在 runs/template_sandbox/ 下；src/rfauto/adapters/openems_templates.py
# 与 docs/templates/** 永不被 agent 写。草稿"生效"= promote：验证器（compile
# 门 + CSXCAD 离线几何实测 + 闭式锚裁判）→ AgentGate 三层 → 迁入本沙箱的
# promoted/ 准入区（仍在 runs/ 内；正式入厂注册四件套留人工 commit）。
# 守卫与 RecipeSandbox 同模式：路径解析后必须位于沙箱根内、后缀白名单。

TEMPLATE_SANDBOX_ROOT = Path("runs") / "template_sandbox"
TEMPLATE_ALLOWED_SUFFIXES = {".py"}
PROMOTED_DIRNAME = "promoted"


class TemplateDraftSandbox:
    """模板渲染脚本草案沙箱（.py 白名单；根 runs/template_sandbox）。"""

    def __init__(self, root: Path | None = None):
        self.root = (root or TEMPLATE_SANDBOX_ROOT).resolve()

    # ── 守卫 ──────────────────────────────────────────────────────────────
    def _guard(self, path: str | Path) -> Path:
        p = Path(path)
        p = p if p.is_absolute() else self.root / p
        p = p.resolve()
        if self.root != p and self.root not in p.parents:
            raise SandboxViolation(f"路径越出模板沙箱: {p}")
        if p.suffix.lower() not in TEMPLATE_ALLOWED_SUFFIXES:
            raise SandboxViolation(
                f"模板沙箱只允许 {sorted(TEMPLATE_ALLOWED_SUFFIXES)}: {p.name}")
        return p

    def draft_path(self, name: str) -> Path:
        """草稿名 → 沙箱内路径（无后缀自动补 .py；越界/非法后缀抛 SandboxViolation）。"""
        stem = str(name)
        if not stem.lower().endswith(".py") and "." not in Path(stem).name:
            stem = f"{stem}.py"
        return self._guard(stem)

    @property
    def promoted_dir(self) -> Path:
        return self.root / PROMOTED_DIRNAME

    # ── 草稿生命周期 ──────────────────────────────────────────────────────
    def write_draft(self, name: str, content: str) -> dict[str, Any]:
        """写草稿（唯一写入口；先过守卫再落盘，覆盖同名草稿）。"""
        draft = self.draft_path(name)
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(content, encoding="utf-8")
        return {"ok": True, "draft": str(draft)}

    def read_draft(self, name: str) -> str:
        return self.draft_path(name).read_text(encoding="utf-8")

    def discard(self, name: str) -> dict[str, Any]:
        draft = self.draft_path(name)
        draft.unlink(missing_ok=True)
        return {"ok": True, "discarded": str(draft)}

    def list_drafts(self) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        return {"ok": True,
                "drafts": [str(p) for p in sorted(self.root.glob("*.py"))],
                "promoted": [str(p) for p in sorted(self.promoted_dir.glob("*.py"))]
                if self.promoted_dir.exists() else []}

    def promote_path(self, name: str) -> Path:
        """promoted/ 准入区目标路径（守卫同草稿：仍在沙箱根内、.py 后缀）。"""
        draft = self.draft_path(name)
        return self._guard(self.promoted_dir / draft.name)

    def move_to_promoted(self, name: str) -> Path:
        """草稿迁入 promoted/（写面只在沙箱内；调用方须先过验证器与三层 Gate）。"""
        draft = self.draft_path(name)
        if not draft.exists():
            raise FileNotFoundError(f"草稿不存在: {draft}")
        target = self.promote_path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(draft, target)
        return target
