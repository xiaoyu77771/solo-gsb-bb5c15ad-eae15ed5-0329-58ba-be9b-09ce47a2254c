"""规则方案版本：创建版本、编辑草稿、发布、停用与版本差异。

判定口径：方案下存在已发布版本时，推演接口只读取该生效版本的规则快照；
停用生效版本后回退到实时规则图，已停用版本不再参与判定。
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, rule_versions, rules_store
from ..database import get_db
from ..schemas import RuleVersionCreate, RuleVersionRulePatch, RuleVersionUpdate

router = APIRouter(prefix="/api/rule-schemes", tags=["rule-schemes"])

DRAFT = models.RuleSchemeVersion.STATUS_DRAFT
PUBLISHED = models.RuleSchemeVersion.STATUS_PUBLISHED
DISABLED = models.RuleSchemeVersion.STATUS_DISABLED


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_scheme_or_404(db: Session, scheme_id: int) -> models.RuleScheme:
    scheme = db.get(models.RuleScheme, scheme_id)
    if scheme is None:
        raise HTTPException(404, f"规则方案 #{scheme_id} 不存在")
    return scheme


def _get_version_or_404(
    db: Session, scheme_id: int, version_id: int, role: str = "规则版本"
) -> models.RuleSchemeVersion:
    version = db.get(models.RuleSchemeVersion, version_id)
    if version is None or version.scheme_id != scheme_id:
        raise HTTPException(404, f"{role} #{version_id} 不存在于规则方案 #{scheme_id}")
    return version


# ---------- 方案 ----------

@router.get("")
def list_schemes(db: Session = Depends(get_db)):
    """规则方案列表（含当前生效版本信息）。"""
    schemes = db.query(models.RuleScheme).order_by(models.RuleScheme.id).all()
    return {
        "schemes": [rule_versions.scheme_summary(db, s) for s in schemes],
        "live_revision": rules_store.get_rule_revision(),
    }


@router.get("/{scheme_id}")
def get_scheme(scheme_id: int, db: Session = Depends(get_db)):
    """方案详情：全部版本、当前生效状态与每版严重级别统计/变更时间。"""
    scheme = _get_scheme_or_404(db, scheme_id)
    return rule_versions.scheme_detail(db, scheme)


# ---------- 版本生命周期 ----------

@router.post("/{scheme_id}/versions", status_code=201)
def create_version(
    scheme_id: int, body: RuleVersionCreate, db: Session = Depends(get_db)
):
    """创建版本：默认快照当前实时规则图；也可用 from_version_id 复制既有版本。"""
    scheme = _get_scheme_or_404(db, scheme_id)
    if body.from_version_id is not None:
        src = _get_version_or_404(db, scheme_id, body.from_version_id, "基准规则版本")
        rules = rule_versions.version_rules(src)
        source_revision = src.source_revision
    else:
        rules = rule_versions.snapshot_live_rules(db)
        source_revision = rules_store.get_rule_revision()
    if not rules:
        raise HTTPException(422, "规则图为空，无法创建版本")

    version = models.RuleSchemeVersion(
        scheme_id=scheme.id,
        version_no=rule_versions.next_version_no(db, scheme.id),
        status=DRAFT,
        note=body.note,
        rules=json.dumps(rules, ensure_ascii=False),
        source_revision=source_revision,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return rule_versions.version_detail(version)


@router.get("/{scheme_id}/versions/{version_id}")
def get_version(scheme_id: int, version_id: int, db: Session = Depends(get_db)):
    """版本详情：完整规则快照（含每条的严重级别与判定依据）。"""
    _get_scheme_or_404(db, scheme_id)
    version = _get_version_or_404(db, scheme_id, version_id)
    return rule_versions.version_detail(version)


@router.put("/{scheme_id}/versions/{version_id}")
def update_version(
    scheme_id: int,
    version_id: int,
    body: RuleVersionUpdate,
    db: Session = Depends(get_db),
):
    """编辑草稿：更新变更说明，或整体替换规则集。仅草稿可编辑。"""
    _get_scheme_or_404(db, scheme_id)
    version = _get_version_or_404(db, scheme_id, version_id)
    if version.status != DRAFT:
        raise HTTPException(409, "仅草稿版本可编辑；已发布/已停用版本为只读历史")

    data = body.model_dump(exclude_unset=True)
    if "note" in data:
        version.note = data["note"]
    if data.get("rules") is not None:
        rules = data["rules"]
        if not rules:
            raise HTTPException(422, "版本至少需要保留一条规则")
        ids = [r["id"] for r in rules]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, "版本内规则编号不能重复")
        for r in rules:
            if r["source"] == r["target"]:
                raise HTTPException(422, f"规则 {r['id']} 的两个类别不能相同")
        version.rules = json.dumps(rules, ensure_ascii=False)
    version.updated_at = _utcnow()
    db.commit()
    db.refresh(version)
    return rule_versions.version_detail(version)


@router.patch("/{scheme_id}/versions/{version_id}/rules/{rule_id}")
def patch_version_rule(
    scheme_id: int,
    version_id: int,
    rule_id: str,
    body: RuleVersionRulePatch,
    db: Session = Depends(get_db),
):
    """编辑草稿中的单条规则（严重级别、判定依据、启停等）。仅草稿可编辑。"""
    _get_scheme_or_404(db, scheme_id)
    version = _get_version_or_404(db, scheme_id, version_id)
    if version.status != DRAFT:
        raise HTTPException(409, "仅草稿版本可编辑；已发布/已停用版本为只读历史")

    rules = rule_versions.version_rules(version)
    target = next((r for r in rules if r["id"] == rule_id), None)
    if target is None:
        raise HTTPException(404, f"版本内不存在规则 {rule_id}")

    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        if value is not None:
            target[key] = value
    if target["source"] == target["target"]:
        raise HTTPException(422, "规则的两个类别不能相同")
    version.rules = json.dumps(rules, ensure_ascii=False)
    version.updated_at = _utcnow()
    db.commit()
    db.refresh(version)
    return rule_versions.version_detail(version)


@router.post("/{scheme_id}/versions/{version_id}/publish")
def publish_version(scheme_id: int, version_id: int, db: Session = Depends(get_db)):
    """发布版本：成为方案当前生效版本，原生效版本自动停用；判定即刻切换。"""
    _get_scheme_or_404(db, scheme_id)
    version = _get_version_or_404(db, scheme_id, version_id)
    if version.status == PUBLISHED:
        raise HTTPException(409, f"版本 v{version.version_no} 已处于发布状态")

    now = _utcnow()
    current = rule_versions.get_published_version(db, scheme_id)
    if current is not None and current.id != version.id:
        current.status = DISABLED
        current.disabled_at = now
    version.status = PUBLISHED
    version.published_at = now
    version.disabled_at = None
    version.updated_at = now
    db.commit()
    db.refresh(version)
    return rule_versions.version_detail(version)


@router.post("/{scheme_id}/versions/{version_id}/disable")
def disable_version(scheme_id: int, version_id: int, db: Session = Depends(get_db)):
    """停用版本：不再参与判定；无生效版本时推演回退到实时规则图。"""
    _get_scheme_or_404(db, scheme_id)
    version = _get_version_or_404(db, scheme_id, version_id)
    if version.status != PUBLISHED:
        raise HTTPException(409, "仅已发布的版本可以停用")

    version.status = DISABLED
    version.disabled_at = _utcnow()
    version.updated_at = version.disabled_at
    db.commit()
    db.refresh(version)
    return rule_versions.version_detail(version)


@router.delete("/{scheme_id}/versions/{version_id}", status_code=204)
def delete_version(scheme_id: int, version_id: int, db: Session = Depends(get_db)):
    """删除草稿版本；已发布/已停用版本保留为历史，不可删除。"""
    _get_scheme_or_404(db, scheme_id)
    version = _get_version_or_404(db, scheme_id, version_id)
    if version.status != DRAFT:
        raise HTTPException(409, "仅草稿版本可删除；已发布/已停用版本保留为历史")
    db.delete(version)
    db.commit()


# ---------- 版本差异 ----------

@router.get("/{scheme_id}/diff")
def diff_versions(
    scheme_id: int,
    base_id: int = Query(..., description="基准（较早）版本 ID"),
    target_id: int = Query(..., description="对照（较新）版本 ID"),
    db: Session = Depends(get_db),
):
    """比较同一方案的两个版本：新增/移除/严重级别/启停/判定依据变化。"""
    scheme = _get_scheme_or_404(db, scheme_id)
    if base_id == target_id:
        raise HTTPException(400, "请选择两个不同的规则版本进行比较")
    base = _get_version_or_404(db, scheme_id, base_id, "基准规则版本")
    target = _get_version_or_404(db, scheme_id, target_id, "对照规则版本")
    return rule_versions.build_version_diff(scheme, base, target)
