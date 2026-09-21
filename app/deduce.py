"""从已保存方案构建引擎输入并执行推演、落盘推演记录。"""
import json

from sqlalchemy.orm import Session

from . import engine, models, rule_versions


def _step_categories(db: Session, step: models.Step) -> list[str]:
    """步骤关联试剂的类别：优先试剂档案，兜底步骤创建时的快照。"""
    if step.reagent_id is not None:
        reagent = db.get(models.Reagent, step.reagent_id)
        if reagent is not None:
            return json.loads(reagent.categories or "[]")
    return json.loads(step.categories or "[]")


def plan_to_input(db: Session, plan: models.Plan) -> list[engine.InputStep]:
    ordered = sorted(plan.steps, key=lambda s: (s.order_index, s.id))
    inputs = []
    for s in ordered:
        inputs.append(
            engine.InputStep(
                order_index=s.order_index,
                time_offset_min=s.time_offset_min,
                amount_ml=s.amount_ml,
                note=s.note,
                reagent=engine.InputReagent(
                    name=s.reagent_name,
                    categories=_step_categories(db, s),
                ),
            )
        )
    return inputs


def build_report(db: Session, plan: models.Plan) -> dict:
    """推演判定：只读取当前生效的规则版本；无生效版本时回退到实时规则图。"""
    rules, revision, version_info = rule_versions.get_effective_source(db)
    steps = plan_to_input(db, plan)
    report = engine.simulate(steps, rules, revision)
    report["plan_name"] = plan.name
    report["rule_version"] = version_info  # None 表示使用实时规则图
    return report


def persist_run(db: Session, plan: models.Plan, report: dict, persist: bool = True):
    if not persist:
        return None
    run = models.Run(
        plan_id=plan.id,
        plan_name=plan.name,
        rule_revision=report.get("rule_revision", ""),
        status=report["status"],
        report=json.dumps(report, ensure_ascii=False),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run.id
