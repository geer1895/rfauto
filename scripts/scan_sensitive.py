#!/usr/bin/env python3
"""ADS desensitization scanner: regex blacklist for proprietary content."""
import re
import sys
from pathlib import Path

BLACKLIST = [r"keysight.*internal", r"encrypted.*model", r"\.encrypted$"]
EXCLUDE = {".git", ".venv", "venv", "__pycache__", "node_modules", ".ruff_cache", "pyaedt-main", "pyaedt_reference", "scripts", ".cache", ".hypothesis", ".pytest_cache"}

def main():
    pats = [re.compile(p, re.IGNORECASE) for p in BLACKLIST]
    violations = []
    for f in Path(".").rglob("*"):
        if f.is_file() and f.suffix in (".py", ".yaml", ".yml", ".json", ".md"):
            if any(d in f.parts for d in EXCLUDE):
                continue
            try:
                c = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for p in pats:
                for m in p.finditer(c):
                    violations.append(f"{f}:{m.start()}: {m.group()}")
    if violations:
        print(f"SENSITIVE CONTENT: {len(violations)} violations")
        for v in violations[:20]:
            print(f"  {v}")
        sys.exit(1)
    print("Desensitization scan: clean.")

if __name__ == "__main__":
    main()
