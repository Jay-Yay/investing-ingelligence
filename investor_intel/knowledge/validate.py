from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import yaml

_FM = re.compile(r"^---\n(.*?)\n---\n", re.S)
_LINK = re.compile(r"\[[^\]]*\]\(([^)]+\.md)\)")

# OKF v0.1이 요구하는 유일한 필수 필드는 type이다. 나머지는 이 번들이 스스로에게 건 계약.
_REQUIRED = ("type",)
_BUNDLE_CONTRACT = ("title", "description", "timestamp", "status")


def validate_bundle(root: Path) -> dict:
    files = sorted(root.rglob("*.md"))
    issues: list[str] = []
    types = Counter()
    missing = Counter()
    broken_links = 0
    total_links = 0
    orphan_dirs = []

    existing = {p.resolve() for p in files}
    for p in files:
        raw = p.read_text(encoding="utf-8")
        m = _FM.match(raw)
        if not m:
            issues.append(f"frontmatter 없음: {p.relative_to(root)}")
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            issues.append(f"YAML 파싱 실패: {p.relative_to(root)} ({e})")
            continue
        for f in _REQUIRED:
            if not fm.get(f):
                issues.append(f"필수 필드 `{f}` 누락: {p.relative_to(root)}")
        types[fm.get("type", "?")] += 1
        if fm.get("type") not in ("Index", "Bundle", "Log"):
            for f in _BUNDLE_CONTRACT:
                if not fm.get(f):
                    missing[f] += 1
        for target in _LINK.findall(raw):
            if target.startswith(("http", "#")):
                continue
            total_links += 1
            if (p.parent / target).resolve() not in existing:
                broken_links += 1
                if broken_links <= 5:
                    issues.append(f"깨진 링크: {p.relative_to(root)} -> {target}")

    for d in sorted({p.parent for p in files}):
        if not (d / "index.md").exists():
            orphan_dirs.append(str(d.relative_to(root)))

    return {
        "files": len(files),
        "types": dict(types.most_common()),
        "required_field_violations": sum(1 for i in issues if "필수 필드" in i),
        "bundle_contract_missing": dict(missing),
        "links_total": total_links,
        "links_broken": broken_links,
        "dirs_without_index": orphan_dirs,
        "issues_sample": issues[:12],
        "ok": broken_links == 0 and not any("필수 필드" in i or "YAML" in i for i in issues),
    }
