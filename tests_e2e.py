"""端到端冒烟测试：通过 HTTP API 覆盖主要业务路径。"""
import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"
PASS, FAIL = 0, 0


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode()
            return resp.status, json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text)
        except json.JSONDecodeError:
            return e.code, text


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


# ---------- 1. 示例①：氰化钾→盐酸→乙醇 ----------
print("【场景1】氰化物酸化（应第 2 步严重中止）")
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("HTTP 200", s == 200, s)
check("status=danger", r["status"] == "danger", r["status"])
check("halted=True", r["halted"] is True)
fd = r["first_danger"]
check("首次危险在第 1 步(0基)", fd["step"] == 1, fd)
check("冲突对象为第 0 步氰化钾", fd["conflicts_with_step"] == 0 and fd["conflicts_with_reagent"] == "氰化钾")
check("命中 R001", fd["rule_id"] == "R001")
check("含反应方程式", "HCN" in fd["reaction"])
check("含机理依据", len(fd["rationale"]) > 20)
check("含参考文献", len(fd["references"]) >= 1)
check("受影响步骤=[1,2]", r["affected_steps"] == [1, 2], r["affected_steps"])
check("阻断步骤=[2]", r["blocked_steps"] == [2], r["blocked_steps"])
states = [t["state"] for t in r["timeline"]]
check("时间轴状态 ok/danger/blocked", states == ["ok", "danger", "blocked"], states)
f0 = r["findings"][0]
check("finding 可追溯双向类别", f0["incoming_category"] == "strong_acid"
      and f0["existing_category"] == "cyanide", f0)

# ---------- 2. 示例②：铵盐→碱→次氯酸钠 ----------
print("【场景2】铵盐中和后加 84（先警示后严重）")
s, r = call("POST", "/api/plans/2/simulate?persist=false")
check("status=danger", r["status"] == "danger")
check("第 1 步 medium 警示后继续", r["timeline"][1]["state"] == "warning")
med = [f for f in r["findings"] if f["severity"] == "medium"]
check("R015 氨气警示命中", any(f["rule_id"] == "R015" for f in med), med)
check("首次危险在第 2 步 R016 氯胺", r["first_danger"]["step"] == 2
      and r["first_danger"]["rule_id"] == "R016", r["first_danger"])

# ---------- 3. 安全方案（无类别临时试剂 + 普通盐）----------
print("【场景3】安全配液（应 safe）")
s, reagents = call("GET", "/api/reagents")
nacl = next(x for x in reagents if x["name"] == "氯化钠")
plan = {
    "name": "测试-安全盐水",
    "steps": [
        {"order_index": 0, "reagent_id": nacl["id"], "time_offset_min": 0, "amount_ml": 100},
        {"order_index": 1, "reagent_name": "纯水", "categories": [], "time_offset_min": 5, "amount_ml": 50},
    ],
}
s, r = call("POST", "/api/plans/simulate-dry", plan)
check("dry-run 200", s == 200, s)
check("status=safe", r["status"] == "safe", r)
check("无 finding", r["summary"]["findings"] == 0)

# ---------- 4. 自定义临时类别 + 规则全链路 ----------
print("【场景4】自定义规则与临时试剂")
s, r = call("POST", "/api/rules", {
    "id": "C001", "source": "azide", "target": "strong_acid",
    "directional": False, "severity": "high",
    "title": "叠氮化物遇酸生成易爆叠氮酸",
    "reaction": "N3- + H+ -> HN3",
    "rationale": "叠氮酸剧毒且对震动敏感易爆炸。",
    "references": ["测试文献 1"],
})
check("创建自定义规则", s == 201, (s, r))
plan = {
    "name": "测试-叠氮",
    "steps": [
        {"order_index": 0, "reagent_name": "叠氮化钠", "categories": ["azide"]},
        {"order_index": 1, "reagent_name": "稀盐酸", "categories": ["strong_acid"]},
    ],
}
s, r = call("POST", "/api/plans/simulate-dry", plan)
check("自定义规则即时生效", r["status"] == "danger" and r["first_danger"]["rule_id"] == "C001")

# 有向规则：source 类别"被加入"已含 target 的体系时才触发（与加液顺序相关）
s, _ = call("POST", "/api/rules", {
    "id": "C002", "source": "cat_x", "target": "cat_y",
    "directional": True, "severity": "high", "title": "有向测试",
})
s, r = call("POST", "/api/plans/simulate-dry", {
    "name": "测试-有向反向",
    "steps": [
        {"order_index": 0, "reagent_name": "X", "categories": ["cat_x"]},
        {"order_index": 1, "reagent_name": "Y", "categories": ["cat_y"]},
    ],
})
check("有向规则：target 后加入不命中", r["status"] == "safe", r["status"])
s, r = call("POST", "/api/plans/simulate-dry", {
    "name": "测试-有向正向",
    "steps": [
        {"order_index": 0, "reagent_name": "Y", "categories": ["cat_y"]},
        {"order_index": 1, "reagent_name": "X", "categories": ["cat_x"]},
    ],
})
check("有向规则：source 后加入命中", r["status"] == "danger", r["status"])

# ---------- 5. 方案 CRUD + 持久化推演 + 导出 + 记录 ----------
print("【场景5】方案保存 / 推演落盘 / JSON 导出 / 记录")
s, saved = call("POST", "/api/plans", {
    "name": "测试-持久化",
    "description": "e2e",
    "steps": [
        {"order_index": 0, "reagent_name": "硫化钠临时", "categories": ["sulfide"], "time_offset_min": 0, "amount_ml": 10},
        {"order_index": 1, "reagent_name": "盐酸临时", "categories": ["strong_acid"], "time_offset_min": 2, "amount_ml": 5},
        {"order_index": 2, "reagent_name": "水", "categories": [], "time_offset_min": 9, "amount_ml": 100},
    ],
})
check("创建方案", s == 201 and saved["id"] > 0, (s, saved))
pid = saved["id"]
check("步骤类别快照回显", saved["steps"][0]["categories"] == ["sulfide"], saved["steps"][0])

s, r = call("POST", f"/api/plans/{pid}/simulate?persist=true")
check("推演成功", s == 200)
check("返回 run_id", r.get("run_id") is not None)
run_id = r["run_id"]
check("R002 H2S 命中", r["first_danger"]["rule_id"] == "R002")
check("第 3 步被阻断", r["blocked_steps"] == [2])

s, exported = call("GET", f"/api/plans/{pid}/export")
check("导出 JSON 含完整结构", s == 200
      and {"engine", "rule_revision", "status", "first_danger", "timeline", "findings"} <= set(exported),
      s)

s, runs = call("GET", "/api/runs")
check("推演记录列表", s == 200 and any(x["id"] == run_id for x in runs))
s, one = call("GET", f"/api/runs/{run_id}")
check("记录详情可取回", s == 200 and one["first_danger"]["rule_id"] == "R002")
s, one_exp = call("GET", f"/api/runs/{run_id}/export")
check("记录可导出", s == 200 and one_exp["run_id"] == run_id)

s, _ = call("PUT", f"/api/plans/{pid}", {"name": "测试-持久化-改名"})
check("方案更新", s == 200, s)
s, _ = call("DELETE", f"/api/plans/{pid}")
check("方案删除", s == 204, s)

# ---------- 6. 试剂 CRUD 与引用保护 ----------
print("【场景6】试剂档案与引用保护")
s, rg = call("POST", "/api/reagents", {
    "name": "测试试剂A", "cas": "1-2-3", "state": "liquid",
    "categories": ["oxidizer", "custom_cat"],
})
check("创建试剂", s == 201, (s, rg))
rid = rg["id"]
s, _ = call("POST", "/api/plans", {
    "name": "测试-占用试剂",
    "steps": [{"order_index": 0, "reagent_id": rid}],
})
pid2 = _["id"]
s, err = call("DELETE", f"/api/reagents/{rid}")
check("被引用试剂拒绝删除", s == 409, s)
call("DELETE", f"/api/plans/{pid2}")
s, _ = call("DELETE", f"/api/reagents/{rid}")
check("解除引用后可删除", s == 204, s)
s, err = call("POST", "/api/plans/simulate-dry", {"name": "x", "steps": []})
check("空步骤被拒绝", s == 422, s)

# ---------- 7. 规则停用/启用、内置保护 ----------
print("【场景7】规则维护")
s, _ = call("PATCH", "/api/rules/R001", {"active": False})
check("内置规则可停用", s == 200)
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("停用后不再命中 R001", not any(f["rule_id"] == "R001" for f in r["findings"]))
s, _ = call("PATCH", "/api/rules/R001", {"active": True})
check("重新启用", s == 200)
s, _ = call("DELETE", "/api/rules/R001")
check("内置规则不可删除", s == 409)
s, _ = call("DELETE", "/api/rules/C001")
s2, _ = call("DELETE", "/api/rules/C002")
check("自定义规则可删除", s == 204 and s2 == 204, (s, s2))

# ---------- 8. 版本差异（同一方案两次记录对齐比较） ----------
print("【场景8】推演记录版本差异")
s, p3 = call("POST", "/api/plans", {
    "name": "测试-版本差异方案",
    "steps": [
        {"order_index": 0, "reagent_name": "叠氮化钠X", "categories": ["azide"]},
        {"order_index": 1, "reagent_name": "稀盐酸X", "categories": ["strong_acid"]},
        {"order_index": 2, "reagent_name": "水", "categories": []},
    ],
})
pid3 = p3["id"]

s, _ = call("POST", "/api/rules", {
    "id": "C010", "source": "azide", "target": "strong_acid",
    "directional": False, "severity": "high",
    "title": "叠氮化物遇酸生成易爆叠氮酸",
    "reaction": "N3- + H+ -> HN3",
    "rationale": "叠氮酸剧毒且对震动敏感易爆炸。",
    "references": ["差异测试文献"],
})
check("创建测试规则 C010", s == 201, s)

s, ra = call("POST", f"/api/plans/{pid3}/simulate?persist=true")
run_a = ra["run_id"]
check("第一次推演 danger", s == 200 and ra["status"] == "danger" and ra["blocked_steps"] == [2], (s, ra.get("status")))

call("PATCH", "/api/rules/C010", {"severity": "medium"})
s, rb = call("POST", f"/api/plans/{pid3}/simulate?persist=true")
run_b = rb["run_id"]
check("降级后第二次推演 warning", s == 200 and rb["status"] == "warning" and rb["blocked_steps"] == [], (s, rb.get("status")))

s, d = call("GET", f"/api/runs/diff?base_id={run_a}&target_id={run_b}")
check("差异接口 200", s == 200, s)
check("方案一致才返回", d.get("plan_id") == pid3, d.get("plan_id"))
check("两侧 run_id 正确", d["base"]["run_id"] == run_a and d["target"]["run_id"] == run_b)
check("状态 danger->warning", d["summary"]["status"] == {"base": "danger", "target": "warning", "changed": True})
check("首次危险消失", d["summary"]["first_danger"]["change"] == "removed")
check("阻断步骤 [2] 消失", d["summary"]["blocked_steps"]["removed"] == [2])
check("受影响步骤 [2] 消失", d["summary"]["affected_steps"]["removed"] == [2])
fc = d["summary"]["finding_changes"]
check("一条级别变化、无新增/消失", fc["severity"] == 1 and fc["added"] == 0 and fc["removed"] == 0, fc)
sev_entries = [f for f in d["findings"] if f["change"] == "severity"]
check("按步骤+规则对齐到 C010", len(sev_entries) == 1 and sev_entries[0]["rule_id"] == "C010"
      and sev_entries[0]["base_severity"] == "high" and sev_entries[0]["target_severity"] == "medium",
      sev_entries)
check("条目含两侧反应依据", sev_entries[0]["base"]["reaction"].startswith("N3-")
      and sev_entries[0]["target"]["rationale"].startswith("叠氮酸"), sev_entries)
check("命中计数 high 减少 1", any(x["key"] == "high" and x["delta"] == -1 for x in d["summary"]["counts"]),
      d["summary"]["counts"])

call("PATCH", "/api/rules/C010", {"active": False})
s, rc = call("POST", f"/api/plans/{pid3}/simulate?persist=true")
run_c = rc["run_id"]
check("停用后第三次推演 safe", s == 200 and rc["status"] == "safe", (s, rc.get("status")))

s, d2 = call("GET", f"/api/runs/diff?base_id={run_b}&target_id={run_c}")
check("停用规则：命中消失", s == 200 and d2["summary"]["finding_changes"]["removed"] == 1
      and d2["summary"]["first_danger"]["change"] == "none"
      and d2["summary"]["status"]["changed"] and d2["summary"]["status"]["target"] == "safe",
      d2["summary"])
rm = [f for f in d2["findings"] if f["change"] == "removed"]
check("消失条目带规则 ID 与步骤", rm and rm[0]["rule_id"] == "C010" and rm[0]["incoming_step"] == 1, rm)

# 重新启用（恢复 high）后改机理文案 → 与 run_a 相比级别一致、依据变化
call("PATCH", "/api/rules/C010", {"active": True, "severity": "high"})
call("PATCH", "/api/rules/C010", {"rationale": "叠氮酸剧毒且对震动敏感易爆炸；2026 修订：常压下沸点仅 37℃。"})
s, rd = call("POST", f"/api/plans/{pid3}/simulate?persist=true")
run_d = rd["run_id"]
s, d3 = call("GET", f"/api/runs/diff?base_id={run_a}&target_id={run_d}")
basis = [f for f in d3["findings"] if f["change"] == "basis"]
check("级别不变机理变化 → basis", s == 200 and len(basis) == 1 and basis[0]["changed_fields"] == ["rationale"]
      and basis[0]["base_severity"] == "high" and basis[0]["target_severity"] == "high", basis)
check("两侧机理都可追溯", basis[0]["base"]["rationale"].startswith("叠氮酸剧毒")
      and "2026 修订" in basis[0]["target"]["rationale"], basis)

s, dexp = call("GET", f"/api/runs/diff/export?base_id={run_a}&target_id={run_b}")
check("差异 JSON 可导出", s == 200 and dexp.get("kind") == "labmix-run-diff"
      and dexp["base"]["run_id"] == run_a and dexp["target"]["run_id"] == run_b
      and "findings" in dexp and "summary" in dexp, s)

# 错误路径：同记录比较 / 记录缺失 / 跨方案
s, e = call("GET", f"/api/runs/diff?base_id={run_a}&target_id={run_a}")
check("同一条记录 400", s == 400, s)
s, e = call("GET", f"/api/runs/diff?base_id={run_a}&target_id=999999")
check("对照记录缺失 404", s == 404, s)
s, e = call("GET", f"/api/runs/diff?base_id=999998&target_id={run_b}")
check("基准记录缺失 404", s == 404, s)
s, other = call("POST", "/api/plans/2/simulate?persist=true")
run_other = other["run_id"]
s, e = call("GET", f"/api/runs/diff?base_id={run_a}&target_id={run_other}")
check("方案不一致 409", s == 409, s)
s, e = call("GET", f"/api/runs/diff/export?base_id={run_a}&target_id={run_other}")
check("导出接口同样拒绝跨方案 409", s == 409, s)
s, e = call("GET", "/api/runs/diff")
check("缺少参数 422", s == 422, s)

call("DELETE", f"/api/plans/{pid3}")
call("DELETE", "/api/rules/C010")

# ---------- 9. 规则方案版本：创建/草稿编辑/发布/停用/差异 ----------
print("【场景9】规则方案版本模块")
s, schemes = call("GET", "/api/rule-schemes")
check("方案列表 200", s == 200 and len(schemes["schemes"]) >= 1, s)
scheme = schemes["schemes"][0]
sid = scheme["id"]
check("默认规则方案已内置", scheme["builtin"] is True and scheme["name"], scheme)
check("初始无生效版本", scheme["current_version"] is None, scheme.get("current_version"))

# 基线：无生效版本时判定使用实时规则图
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("基线 danger（实时规则图）", s == 200 and r["status"] == "danger", (s, r.get("status")))
check("基线 rule_version 为空", r.get("rule_version") is None, r.get("rule_version"))

# 创建版本（快照当前规则图）→ 草稿
s, v1 = call("POST", f"/api/rule-schemes/{sid}/versions", {"note": "初始快照"})
check("创建版本 201", s == 201, (s, v1))
check("新版本为草稿", v1["status"] == "draft", v1.get("status"))
check("版本号从 1 开始", v1["version_no"] == 1, v1.get("version_no"))
check("快照含全部规则", v1["rule_count"] >= 18, v1.get("rule_count"))
check("记录创建时间", bool(v1.get("created_at")), v1.get("created_at"))
v1_id = v1["id"]

s, vd = call("GET", f"/api/rule-schemes/{sid}/versions/{v1_id}")
r001 = next(x for x in vd["rules"] if x["id"] == "R001")
check("版本保留严重级别依据", r001["severity"] == "high" and len(r001["rationale"]) > 10
      and len(r001["references"]) >= 1, r001)

# 草稿不影响判定
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("草稿不参与判定", r["status"] == "danger" and r.get("rule_version") is None)

# 编辑草稿：R001 降级 + 修改依据；更新变更说明
s, _ = call("PATCH", f"/api/rule-schemes/{sid}/versions/{v1_id}/rules/R001",
            {"severity": "low", "rationale": "草稿修订：降级为提示"})
check("草稿内编辑规则", s == 200, s)
s, _ = call("PUT", f"/api/rule-schemes/{sid}/versions/{v1_id}", {"note": "初始快照（R001 降级）"})
check("草稿更新变更说明", s == 200 and _["note"] == "初始快照（R001 降级）", (s, _))
s, _ = call("PUT", f"/api/rule-schemes/{sid}/versions/{v1_id}",
            {"rules": [{"id": "X1", "source": "a", "target": "a"}]})
check("类别相同的规则被拒绝", s == 422, s)

# 发布 v1 → 判定只读取生效版本
s, v1p = call("POST", f"/api/rule-schemes/{sid}/versions/{v1_id}/publish")
check("发布成功", s == 200 and v1p["status"] == "published", (s, v1p.get("status")))
check("记录发布时间", bool(v1p.get("published_at")), v1p.get("published_at"))
s, rules_resp = call("GET", "/api/rules")
check("规则接口暴露生效版本", rules_resp.get("effective_version", {}).get("version_no") == 1,
      rules_resp.get("effective_version"))
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("发布后判定读快照（R001 low→不再中止）", r["status"] == "warning", r["status"])
check("报告标记版本来源", r["rule_version"]["version_no"] == 1
      and "v1" in r["rule_revision"], r.get("rule_revision"))
check("快照命中为 low", r["findings"][0]["severity"] == "low", r["findings"][:1])

# 实时规则图改动不影响生效版本
call("PATCH", "/api/rules/R001", {"severity": "high"})
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("实时改动被隔离（仍读快照）", r["status"] == "warning", r["status"])

# 基于 v1 创建 v2，恢复 R001 为严重并修订机理，发布 → v1 自动停用
s, v2 = call("POST", f"/api/rule-schemes/{sid}/versions",
             {"note": "恢复 R001 严重", "from_version_id": v1_id})
check("基于既有版本创建", s == 201 and v2["version_no"] == 2 and v2["status"] == "draft", (s, v2))
v2_id = v2["id"]
call("PATCH", f"/api/rule-schemes/{sid}/versions/{v2_id}/rules/R001",
     {"severity": "high", "rationale": "2026 修订：剧毒 HCN，恢复严重级别"})
s, _ = call("POST", f"/api/rule-schemes/{sid}/versions/{v2_id}/publish")
check("v2 发布", s == 200 and _["status"] == "published", (s, _.get("status")))
s, sch = call("GET", f"/api/rule-schemes/{sid}")
v1_state = next(x for x in sch["versions"] if x["id"] == v1_id)
check("v1 自动停用并记录时间", v1_state["status"] == "disabled" and v1_state["disabled_at"], v1_state)
check("当前生效为 v2", sch["current_version"]["version_no"] == 2, sch.get("current_version"))
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("v2 生效后恢复 danger", r["status"] == "danger" and "v2" in r["rule_revision"], r["status"])

# 版本差异：v1 → v2 应识别 R001 级别与依据变化
s, d = call("GET", f"/api/rule-schemes/{sid}/diff?base_id={v1_id}&target_id={v2_id}")
check("版本差异 200", s == 200 and d["kind"] == "labmix-rule-version-diff", (s, d.get("kind")))
check("差异属于本方案", d["scheme_id"] == sid, d.get("scheme_id"))
e = next((x for x in d["rules"] if x["rule_id"] == "R001"), None)
check("R001 级别变化 low→high", e and e["change"] == "severity"
      and e["base_severity"] == "low" and e["target_severity"] == "high", e)
check("变化字段含级别与机理", e and "severity" in e["changed_fields"]
      and "rationale" in e["changed_fields"], e and e["changed_fields"])
check("两侧依据都可追溯", e and e["base"]["rationale"].startswith("草稿修订")
      and "2026 修订" in e["target"]["rationale"], e)
check("差异汇总计数", d["summary"]["rule_changes"]["severity"] == 1
      and d["summary"]["rule_changes"]["unchanged"] >= 17, d["summary"]["rule_changes"])
check("差异含两侧版本时间", bool(d["base"]["created_at"]) and bool(d["target"]["published_at"]))

# 停用 v2 → 不再参与判定，回退实时规则图
s, _ = call("POST", f"/api/rule-schemes/{sid}/versions/{v2_id}/disable")
check("停用 v2", s == 200 and _["status"] == "disabled" and _["disabled_at"], (s, _))
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("停用后回退实时规则图", r["status"] == "danger" and r.get("rule_version") is None
      and r["rule_revision"] == schemes["live_revision"], (r["status"], r.get("rule_revision")))
s, sch = call("GET", f"/api/rule-schemes/{sid}")
check("停用后无生效版本", sch["current_version"] is None, sch.get("current_version"))

# 未发布的草稿不参与判定；草稿可删除
s, v3 = call("POST", f"/api/rule-schemes/{sid}/versions", {"note": "临时草稿"})
v3_id = v3["id"]
call("PATCH", f"/api/rule-schemes/{sid}/versions/{v3_id}/rules/R001", {"severity": "low"})
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("未发布草稿不影响判定", r["status"] == "danger", r["status"])
s, _ = call("DELETE", f"/api/rule-schemes/{sid}/versions/{v3_id}")
check("草稿可删除", s == 204, s)

# 重新发布 v1（回滚）→ 判定再次切换；随后清理
s, _ = call("POST", f"/api/rule-schemes/{sid}/versions/{v1_id}/publish")
check("已停用版本可重新发布", s == 200 and _["status"] == "published", (s, _))
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("回滚后判定读 v1", r["status"] == "warning" and "v1" in r["rule_revision"], r["status"])

# 错误路径
s, _ = call("POST", f"/api/rule-schemes/{sid}/versions/{v1_id}/publish")
check("重复发布 409", s == 409, s)
s, _ = call("PUT", f"/api/rule-schemes/{sid}/versions/{v1_id}", {"note": "x"})
check("已发布版本不可编辑 409", s == 409, s)
s, _ = call("PATCH", f"/api/rule-schemes/{sid}/versions/{v1_id}/rules/R001", {"severity": "low"})
check("已发布版本规则不可编辑 409", s == 409, s)
s, _ = call("DELETE", f"/api/rule-schemes/{sid}/versions/{v1_id}")
check("已发布版本不可删除 409", s == 409, s)
s, _ = call("POST", f"/api/rule-schemes/{sid}/versions/{v2_id}/disable")
check("非发布版本停用 409", s == 409, s)
s, _ = call("GET", f"/api/rule-schemes/{sid}/diff?base_id={v1_id}&target_id={v1_id}")
check("相同版本比较 400", s == 400, s)
s, _ = call("GET", f"/api/rule-schemes/{sid}/diff?base_id={v1_id}&target_id=999999")
check("对照版本缺失 404", s == 404, s)
s, _ = call("GET", f"/api/rule-schemes/{sid}/diff")
check("缺少参数 422", s == 422, s)
s, _ = call("GET", f"/api/rule-schemes/999999/versions/{v1_id}")
check("方案缺失 404", s == 404, s)

# 清理：停用生效版本，恢复实时规则图判定
call("POST", f"/api/rule-schemes/{sid}/versions/{v1_id}/disable")
s, r = call("POST", "/api/plans/1/simulate?persist=false")
check("清理后恢复实时判定", r["status"] == "danger" and r.get("rule_version") is None)

print(f"\n结果：{PASS} 通过，{FAIL} 失败")
sys.exit(1 if FAIL else 0)
