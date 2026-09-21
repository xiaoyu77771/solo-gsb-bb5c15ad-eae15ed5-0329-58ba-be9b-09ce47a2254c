"""规则方案版本：快照、生命周期（草稿/发布/停用）与版本差异。

设计要点：
- 规则方案（RuleScheme）是实时规则图（YAML 内置规则 + 网页自定义规则）的命名集合，
  系统启动时自动创建一个内置的「默认规则方案」；
- 版本（RuleSchemeVersion）在创建时对当前规则图做**完整快照**，每版保留严重级别、
  判定依据（机理/方程式/参考文献）与创建/发布/停用时间；
- 生命周期：draft → published → disabled。同一方案至多一个 published 版本，
  发布新版本会自动停用旧版本；仅草稿可编辑、可删除；
- 判定口径：方案存在已发布版本时，推演**只读取该生效版本的快照**；
  没有生效版本时回退到实时规则图（保持旧行为）；已停用版本不参与判定。
"""
import json
from types import SimpleNamespace

from sqlalchemy.orm import Session

from . import models, rules_store

DEFAULT_SCHEME_NAME = "默认规则方案"

STATUS_LABELS = {
    models.RuleSchemeVersion.STATUS_DRAFT: "草稿",
    models.RuleSchemeVersion.STATUS_PUBLISHED: "生效中",
    models.RuleSchemeVersion.STATUS_DISABLED: "已停用",
}

# 版本差异中参与"判定依据"比较的字段（严重级别、启用状态单独归类）
BASIS_FIELDS = (
    "source",
    "target",
    "directional",
    "title",
    "reaction",
    "rationale",
    "references",
)

CHANGE_LABELS = {
    "added": "新增规则",
    "removed": "移除规则",
    "severity": "严重级别变化",
    "active": "启停状态变化",
    "basis": "判定依据变化",
    "unchanged": "一致",
}


# ---------- 方案与快照 ----------

def ensure_default_scheme(db: Session) -> models.RuleScheme:
    """确保内置默认规则方案存在（启动时调用）。"""
    scheme = (
        db.query(models.RuleScheme)
        .filter(models.RuleScheme.builtin.is_(True))
        .first()
    )
    if scheme is None:
        scheme = models.RuleScheme(
            name=DEFAULT_SCHEME_NAME,
            description="内置规则图（data/rules.yaml）与网页自定义规则的集合；"
            "创建版本即对当前规则图做快照，发布后推演只读取生效版本。",
            builtin=True,
        )
        db.add(scheme)
        db.commit()
        db.refresh(scheme)
    return scheme


def snapshot_live_rules(db: Session) -> list[dict]:
    """对当前实时规则图（内置 + 自定义，含停用标记）做完整快照。"""
    rules = db.query(models.Rule).order_by(models.Rule.id).all()
    return [
        {
            "id": r.id,
            "source": r.source,
            "target": r.target,
            "directional": bool(r.directional),
            "severity": r.severity,
            "title": r.title,
            "reaction": r.reaction,
            "rationale": r.rationale,
            "references": json.loads(r.references or "[]"),
            "active": bool(r.active),
            "builtin": bool(r.builtin),
        }
        for r in rules
    ]


def version_rules(version: models.RuleSchemeVersion) -> list[dict]:
    return json.loads(version.rules or "[]")


def next_version_no(db: Session, scheme_id: int) -> int:
    current_max = (
        db.query(models.RuleSchemeVersion)
        .filter(models.RuleSchemeVersion.scheme_id == scheme_id)
        .order_by(models.RuleSchemeVersion.version_no.desc())
        .first()
    )
    return (current_max.version_no + 1) if current_max else 1


def get_published_version(
    db: Session, scheme_id: int
) -> models.RuleSchemeVersion | None:
    return (
        db.query(models.RuleSchemeVersion)
        .filter(
            models.RuleSchemeVersion.scheme_id == scheme_id,
            models.RuleSchemeVersion.status == models.RuleSchemeVersion.STATUS_PUBLISHED,
        )
        .first()
    )


# ---------- 判定入口 ----------

def _snapshot_to_engine_rules(rules: list[dict]):
    """快照 dict → 引擎可用的轻量规则对象（仅启用中的规则参与判定）。"""
    return [
        SimpleNamespace(
            id=r["id"],
            source=r["source"],
            target=r["target"],
            directional=bool(r.get("directional", False)),
            severity=r.get("severity", "medium"),
            title=r.get("title", ""),
            reaction=r.get("reaction", ""),
            rationale=r.get("rationale", ""),
            references=r.get("references", []),
        )
        for r in rules
        if r.get("active", True)
    ]


def version_info_dict(
    scheme: models.RuleScheme, version: models.RuleSchemeVersion
) -> dict:
    return {
        "scheme_id": scheme.id,
        "scheme_name": scheme.name,
        "version_id": version.id,
        "version_no": version.version_no,
        "status": version.status,
        "status_label": STATUS_LABELS.get(version.status, version.status),
        "published_at": version.published_at.isoformat() if version.published_at else None,
    }


def revision_label(version: models.RuleSchemeVersion) -> str:
    """推演报告中的规则版本标识：YAML 版本号 + 方案版本号，便于追溯。"""
    base = version.source_revision or "rules"
    return f"{base}·v{version.version_no}"


def get_effective_source(db: Session):
    """判定用规则来源。

    返回 (rules_for_engine, revision_label, version_info|None)：
    - 默认方案存在已发布版本 → 只读取该版本快照中的启用规则；
    - 否则 → 实时规则图中 active=True 的规则（旧行为，保持兼容）。
    """
    scheme = (
        db.query(models.RuleScheme)
        .filter(models.RuleScheme.builtin.is_(True))
        .first()
    )
    if scheme is not None:
        version = get_published_version(db, scheme.id)
        if version is not None:
            rules = _snapshot_to_engine_rules(version_rules(version))
            return rules, revision_label(version), version_info_dict(scheme, version)

    rules = db.query(models.Rule).filter(models.Rule.active.is_(True)).all()
    return rules, rules_store.get_rule_revision(), None


# ---------- 序列化 ----------

def _severity_counts(rules: list[dict]) -> dict:
    counts = {"high": 0, "medium": 0, "low": 0}
    for r in rules:
        counts[r.get("severity", "medium")] = counts.get(r.get("severity", "medium"), 0) + 1
    return counts


def version_summary(version: models.RuleSchemeVersion) -> dict:
    rules = version_rules(version)
    return {
        "id": version.id,
        "scheme_id": version.scheme_id,
        "version_no": version.version_no,
        "status": version.status,
        "status_label": STATUS_LABELS.get(version.status, version.status),
        "note": version.note,
        "source_revision": version.source_revision,
        "revision_label": revision_label(version),
        "rule_count": len(rules),
        "active_count": sum(1 for r in rules if r.get("active", True)),
        "severity_counts": _severity_counts(rules),
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "updated_at": version.updated_at.isoformat() if version.updated_at else None,
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "disabled_at": version.disabled_at.isoformat() if version.disabled_at else None,
    }


def version_detail(version: models.RuleSchemeVersion) -> dict:
    return version_summary(version) | {"rules": version_rules(version)}


def scheme_summary(db: Session, scheme: models.RuleScheme) -> dict:
    published = get_published_version(db, scheme.id)
    versions = (
        db.query(models.RuleSchemeVersion)
        .filter(models.RuleSchemeVersion.scheme_id == scheme.id)
        .order_by(models.RuleSchemeVersion.version_no.desc())
        .all()
    )
    return {
        "id": scheme.id,
        "name": scheme.name,
        "description": scheme.description,
        "builtin": bool(scheme.builtin),
        "created_at": scheme.created_at.isoformat() if scheme.created_at else None,
        "version_count": len(versions),
        "draft_count": sum(
            1 for v in versions if v.status == models.RuleSchemeVersion.STATUS_DRAFT
        ),
        "current_version": version_summary(published) if published else None,
    }


def scheme_detail(db: Session, scheme: models.RuleScheme) -> dict:
    versions = (
        db.query(models.RuleSchemeVersion)
        .filter(models.RuleSchemeVersion.scheme_id == scheme.id)
        .order_by(models.RuleSchemeVersion.version_no.desc())
        .all()
    )
    return scheme_summary(db, scheme) | {
        "versions": [version_summary(v) for v in versions]
    }


# ---------- 版本差异 ----------

def _rule_snapshot_for_diff(r: dict | None) -> dict | None:
    if r is None:
        return None
    return {
        "id": r.get("id"),
        "source": r.get("source"),
        "target": r.get("target"),
        "directional": bool(r.get("directional", False)),
        "severity": r.get("severity"),
        "title": r.get("title", ""),
        "reaction": r.get("reaction", ""),
        "rationale": r.get("rationale", ""),
        "references": r.get("references", []),
        "active": bool(r.get("active", True)),
        "builtin": bool(r.get("builtin", False)),
    }


def build_version_diff(
    scheme: models.RuleScheme,
    base: models.RuleSchemeVersion,
    target: models.RuleSchemeVersion,
) -> dict:
    """同一方案两个版本的规则差异：按规则 ID 对齐，识别新增/移除/级别/启停/依据变化。"""
    base_rules = {r["id"]: r for r in version_rules(base)}
    target_rules = {r["id"]: r for r in version_rules(target)}

    entries: list[dict] = []
    change_rank = {"added": 0, "severity": 1, "active": 2, "basis": 3, "removed": 4, "unchanged": 5}
    for rid in sorted(set(base_rules) | set(target_rules)):
        a, b = base_rules.get(rid), target_rules.get(rid)
        if a is None:
            change, changed_fields = "added", []
        elif b is None:
            change, changed_fields = "removed", []
        else:
            changed_fields = [f for f in BASIS_FIELDS if a.get(f) != b.get(f)]
            if a.get("severity") != b.get("severity"):
                change = "severity"
                changed_fields = ["severity"] + changed_fields
            elif a.get("active", True) != b.get("active", True):
                change = "active"
                changed_fields = ["active"] + changed_fields
            elif changed_fields:
                change = "basis"
            else:
                change = "unchanged"
        entries.append(
            {
                "change": change,
                "change_label": CHANGE_LABELS[change],
                "rule_id": rid,
                "base_severity": a.get("severity") if a else None,
                "target_severity": b.get("severity") if b else None,
                "changed_fields": changed_fields,
                "base": _rule_snapshot_for_diff(a),
                "target": _rule_snapshot_for_diff(b),
            }
        )

    entries.sort(
        key=lambda e: (change_rank[e["change"]], e["rule_id"])
    )
    counts = {c: sum(1 for e in entries if e["change"] == c) for c in CHANGE_LABELS}

    sev_counts = []
    base_sev = _severity_counts(list(base_rules.values()))
    target_sev = _severity_counts(list(target_rules.values()))
    for key, label in (("high", "严重"), ("medium", "警示"), ("low", "提示")):
        sev_counts.append(
            {
                "key": key,
                "label": label,
                "base": base_sev.get(key, 0),
                "target": target_sev.get(key, 0),
                "delta": target_sev.get(key, 0) - base_sev.get(key, 0),
            }
        )

    return {
        "kind": "labmix-rule-version-diff",
        "scheme_id": scheme.id,
        "scheme_name": scheme.name,
        "base": version_summary(base),
        "target": version_summary(target),
        "summary": {
            "rule_changes": counts,
            "severity_counts": sev_counts,
            "active_count": {
                "base": sum(1 for r in base_rules.values() if r.get("active", True)),
                "target": sum(1 for r in target_rules.values() if r.get("active", True)),
            },
        },
        "rules": entries,
    }
