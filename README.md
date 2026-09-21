# 实验室配液相容性推演台（LabMix Compatibility Console）

录入**试剂属性**与**按时间排列的加液步骤**，系统依据一张**可维护的相容性规则图**逐步推演：
每加入一种试剂，就与当前体系中已有的全部试剂按"类别对"匹配禁忌规则；
首次出现**严重危险反应（起火 / 爆炸 / 剧毒气体）即中止推演**，并标出：

- 🛑 **首次危险反应**发生在第几步、与哪一步加入的哪种试剂冲突；
- ⛔ **受影响步骤**（发生反应的步骤）与**被阻断步骤**（中止后未执行的步骤）；
- 🔎 每条命中都附**可追溯判定依据**：规则编号、反应方程式、机理解释、匹配类别对、
  参与的加液步骤编号、参考文献、规则图版本号。

支持方案保存、历史推演记录、规则图升级后的**版本差异比对**，一键**导出 JSON 结果**，
规则图以 YAML 声明式维护并提供网页可视化。

内置**规则方案版本模块**：把当前规则图快照为版本，支持**创建版本 → 编辑草稿 → 发布 → 停用**
的完整生命周期；每版冻结严重级别与判定依据（机理 / 方程式 / 参考文献）并记录创建、发布、
停用时间；方案详情可按版本查看差异与当前生效状态。**发布版本后，判定接口只读取当前生效
版本的快照；停用后该版本不再参与判定**（无生效版本时回退到实时规则图）。

> ⚠️ 本工具用于教学、方案预检与安全评审辅助，**不能替代**实验室 SOP、MSDS 与专业安全评估。

---

## 一、单条命令启动

需要 Docker 20.10+（带 Compose 插件）。在项目根目录执行：

```bash
docker compose up -d --build
```

启动后访问：

| 入口 | 地址 |
| --- | --- |
| **网页界面** | <http://localhost:8000/> |
| API 文档（Swagger） | <http://localhost:8000/docs> |
| 健康检查 | <http://localhost:8000/api/health> |

端口为 **8000**（宿主机）。如被占用，修改 `docker-compose.yml` 中 `"8000:8000"` 左侧端口即可。

常用命令：

```bash
docker compose logs -f      # 查看日志
docker compose down         # 停止
docker compose down -v      # 停止并删除数据卷（清空所有方案/试剂/记录）
```

数据（SQLite 数据库 `labmix.db`、可现场编辑的 `rules.yaml`）持久化在命名卷 `labmix-data`（容器内 `/data`）。

### 不用 Docker 的本地启动

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# 打开 http://localhost:8000
```

---

## 二、快速上手（3 分钟）

系统首次启动已内置 **24 种常见试剂**、**18 条相容性规则**和 **2 个示例方案**：

1. 打开 **📋 配液方案** 页，左侧是方案编辑器，点击「＋ 添加步骤」按时间排列加液步骤；
   每步可从档案库选择试剂，或直接填写"临时试剂 + 类别"。
2. 点击 **▶ 预检（不保存）** 立即推演；或 **💾 保存方案** 后在方案卡片上点 **⚡ 推演**。
3. 查看报告：
   - 顶部横幅给出**首次危险**与受影响/阻断步骤汇总；
   - 左侧**逐步时间轴**展示每一步是"相容 / 警示 / 严重 / 已阻断"；
   - 右侧列出全部**命中规则**，点击任意一条查看反应方程式、机理、参考文献与参与步骤。
4. 点击 **导出 JSON** 下载完整推演报告；所有推演自动保存在 **🗂️ 推演记录** 中，可回溯、可再导出。
5. 在 **🗂️ 推演记录** 页顶部选择**同一方案**的两条记录（或先点记录上的「差异」按钮选入），
   点 **🔍 比较版本差异**：系统按步骤编号 + 规则 ID 对齐两次命中，列出新增 / 消失 / 严重级别变化，
   并汇总总体状态、首次危险、受影响 / 阻断步骤的变化；可用顶部筛选按变化类型或关键字过滤，并
   **⬇ 导出差异 JSON**。仅允许比较同一方案，记录缺失或方案不一致会返回明确的 4xx 错误。
6. 打开 **示例①「氰化物废液酸化处理（错误做法）」** 点「推演」，可看到第 2 步
   盐酸 + 氰化钾命中规则 `R001`（生成剧毒 HCN），推演立即中止，第 3 步被阻断。
7. 在 **🕸️ 规则图** 页的 **📦 规则方案版本** 卡片点「＋ 创建版本」把当前规则图快照为草稿；
   「编辑草稿」调整严重级别与判定依据后「发布」，推演立即只读取该生效版本；
   用「🔀 版本差异比较」任选两版查看规则与级别变化；「停用」后判定回退实时规则图。

---

## 三、规则图如何维护

规则图 = **类别节点** + **相容性禁忌边**，数据模型刻意保持简单透明：

```
试剂(Reagent) --携带 1..n 个类别标签--> [类别节点] --规则边(severity)--> [类别节点]
```

### 方式 A：改 YAML（推荐用于随版本管理的正式规则）

规则图源文件：[`data/rules.yaml`](data/rules.yaml)

```yaml
- id: R001
  source: cyanide
  target: strong_acid
  directional: false        # 无向边：两个类别谁先加入都会命中
  severity: high            # high=严重(中止) / medium=警示(继续) / low=提示
  title: 酸与氰化物接触生成剧毒氰化氢
  reaction: CN⁻ + H⁺ → HCN↑
  rationale: 酸性条件下氰离子立即质子化……
  references:
    - GB 17914-2013……
```

- 容器环境：编辑命名卷内的 `/data/rules.yaml`（首次启动时从仓库模板自动复制），
  然后 `docker compose restart` 即可生效；
- 本地开发：直接编辑 `data/rules.yaml` 后重启服务。
- 类别中文名在文件顶部 `categories:` 段维护。内置规则只能在网页上**停用 / 调整级别**，
  文案以 YAML 为唯一来源（避免网页改动与版本库漂移）。

### 方式 B：网页追加（适合现场临时规则）

**🕸️ 规则图** 页右侧「追加自定义规则」：填编号（建议 `C` 开头）、类别 A/B、
严重级别、方程式、机理与文献，提交后立即参与推演，可随时删除。

规则图页同时提供**力导向可视化**：节点颜色对应该类别关联规则的最高级别，
边颜色表示严重级别、虚线表示有向规则；点击边查看判定依据，悬停节点高亮其全部关联边。

### 推演规则

- 每个步骤只加入一种试剂，加入前与**体系内已存在**的所有试剂按类别两两匹配；
- `high` 级首次命中 → 该试剂视为未安全加入，记录**首次危险**，后续步骤全部标记为阻断；
- `medium` / `low` 级命中 → 记录 finding，推演继续；
- 无向边双向等价匹配；有向边只按 `source → target` 触发。

### 判定读取哪套规则？

判定接口（`POST /api/plans/{id}/simulate`、`POST /api/plans/simulate-dry`、`GET /api/plans/{id}/export`）
的规则来源按以下优先级确定：

1. **默认规则方案存在已发布版本** → 只读取该生效版本的规则快照（实时规则图的后续改动不影响判定）；
2. **无生效版本**（从未发布，或生效版本已停用）→ 回退读取实时规则图中 `active=true` 的规则（旧行为）。

已停用（disabled）的版本不参与判定；草稿（draft）版本在发布前同样不参与判定。
推演报告与历史记录中的 `rule_revision` 会标明来源：实时规则图为 YAML 版本号（如 `2026.09`），
生效版本为 `YAML版本·vN`（如 `2026.09·v2`），报告另附 `rule_version` 对象便于追溯。

---

## 三·补、规则方案版本模块

「🕸️ 规则图」页中部的 **📦 规则方案版本** 卡片管理规则方案的版本生命周期。
系统启动时自动创建内置「默认规则方案」，它对应实时规则图（YAML 内置规则 + 网页自定义规则）。

### 生命周期

```
创建版本（快照当前规则图 / 复制既有版本）
        │
        ▼
     草稿 draft ──发布──▶ 生效中 published ──停用──▶ 已停用 disabled
        │  可编辑/可删除        │  判定唯一来源            │  不再参与判定
        │                     │  发布新版本时自动停用旧版本  │  可重新发布（回滚）
        └──────── 仅草稿可编辑、可删除；已发布/已停用版本为只读历史 ◀┘
```

- **创建版本**：对当前实时规则图做完整快照（含每条的严重级别、机理、方程式、参考文献、启停状态），
  或基于既有版本复制（用于回滚/派生）；可填写变更说明；
- **编辑草稿**：仅草稿可编辑——修改变更说明、单条规则的严重级别 / 判定依据 / 启停，或整体替换规则集；
- **发布**：成为方案**当前生效版本**，判定接口即刻切换为只读该快照；原生效版本自动停用；
- **停用**：生效版本停用后不再参与判定，判定回退到实时规则图；
- **保留历史**：每版记录创建 / 发布 / 停用时间与严重级别依据，已发布与已停用版本不可删除。

### 方案详情：版本列表与版本差异

版本卡片中每个版本显示状态（草稿 / 生效中 / 已停用）、规则数、严重级别分布与各项变更时间；
「查看」可浏览该版冻结的全部规则及判定依据。下方的 **🔀 版本差异比较** 选择同一方案的
两个版本后按规则编号对齐，识别：

- `added` 新增规则 / `removed` 移除规则；
- `severity` 严重级别变化（含两侧级别与全部变化字段）；
- `active` 启停状态变化；
- `basis` 判定依据变化（标题、方程式、机理、参考文献、类别对、方向）；
- `unchanged` 一致；

并汇总两侧严重级别分布与启用规则数的增减。点击任意差异条目可对照查看两侧的完整判定依据。

`GET /api/rule-schemes/{sid}/diff?base_id=&target_id=` 返回结构（摘要）：

```json
{
  "kind": "labmix-rule-version-diff",
  "scheme_id": 1, "scheme_name": "默认规则方案",
  "base":   { "version_id": 1, "version_no": 1, "status": "disabled",
              "created_at": "…", "published_at": "…", "disabled_at": "…",
              "rule_count": 18, "severity_counts": {"high": 14, "medium": 4, "low": 0} },
  "target": { "version_id": 2, "version_no": 2, "status": "published", "…": "…" },
  "summary": {
    "rule_changes": { "added": 0, "removed": 0, "severity": 1, "active": 0, "basis": 0, "unchanged": 17 },
    "severity_counts": [ { "key": "high", "label": "严重", "base": 14, "target": 15, "delta": 1 } ],
    "active_count": { "base": 18, "target": 18 }
  },
  "rules": [
    { "change": "severity", "rule_id": "R001",
      "base_severity": "low", "target_severity": "high",
      "changed_fields": ["severity", "rationale"],
      "base":   { "id": "R001", "severity": "low",  "title": "…", "rationale": "…", "references": ["…"] },
      "target": { "id": "R001", "severity": "high", "title": "…", "rationale": "…", "references": ["…"] } }
  ]
}
```

---

## 四、导出的 JSON 结果结构

`GET /api/plans/{id}/export`（实时推演）或 `GET /api/runs/{id}/export`（历史记录）：

```json
{
  "engine": "labmix-compat-engine",
  "engine_version": "1.0",
  "rule_revision": "2026.09·v2",
  "rule_version": { "scheme_id": 1, "scheme_name": "默认规则方案",
                    "version_id": 2, "version_no": 2, "status": "published",
                    "published_at": "2026-09-21T08:00:00" },
  "status": "danger",                    // safe | warning | danger
  "halted": true,
  "first_danger": {
    "finding_id": "F001",
    "step": 1,                          // 首次危险发生在第 1 步（0 基）
    "reagent_name": "盐酸",
    "conflicts_with_step": 0,
    "conflicts_with_reagent": "氰化钾",
    "rule_id": "R001",
    "title": "酸与氰化物接触生成剧毒氰化氢",
    "reaction": "CN⁻ + H⁺ → HCN↑（剧毒气体）",
    "rationale": "……",
    "references": ["GB 17914-2013……"]
  },
  "affected_steps": [1],                // 发生反应的步骤
  "blocked_steps": [2],                 // 中止后未执行的步骤
  "summary": { "total_steps": 3, "executed_steps": 2, "findings": 1,
               "high": 1, "medium": 0, "low": 0 },
  "timeline": [
    { "order_index": 1, "reagent_name": "盐酸", "state": "danger",
      "state_label": "发生严重反应", "finding_ids": ["F001"],
      "interactions": [ { "rule_id": "R001", "with_reagent": "氰化钾" } ] }
  ],
  "findings": [
    { "id": "F001", "rule_id": "R001", "severity": "high",
      "incoming_step": 1, "incoming_reagent": "盐酸", "incoming_category": "strong_acid",
      "existing_step": 0, "existing_reagent": "氰化钾", "existing_category": "cyanide",
      "match_direction": "existing->incoming", "rule_directional": false,
      "title": "……", "reaction": "……", "rationale": "……", "references": ["……"] }
  ]
}
```

> `rule_version` 在判定读取已发布版本时给出方案 / 版本号 / 发布时间等溯源信息；
> 未发布版本（判定使用实时规则图）时为 `null`，`rule_revision` 相应为 YAML 版本号。

---

## 五、版本差异视图（规则升级影响评估）

当规则图升级（修改 `rules.yaml` 重启、网页停用/改级、追加自定义规则）后，对**同一方案**重新推演，
即可在「🗂️ 推演记录」中比较新旧两条记录。对齐口径为

```
对齐键 = 加入步骤编号 incoming_step + 规则 ID rule_id
         （同一步多条命中再按冲突步骤 existing_step 与类别对区分）
```

每个对齐位置归类为 `added`（新增命中）/ `removed`（消失命中）/ `severity`（严重级别变化）/
`basis`（级别未变但标题、方程式、机理、文献、类别对、匹配方向等反应依据变化）/ `unchanged`（一致）；
同时汇总：

- **总体状态**：`safe / warning / danger` 及其是否变化；
- **两次规则图版本号**；
- **首次危险**：无 / 新增 / 消除 / 位置或规则变化（含两侧步骤、试剂、规则与方程式摘要）；
- **受影响步骤 / 阻断步骤 / 警示步骤**：编号集合的新增与消失；
- **逐步状态对齐表**与命中计数（总数及 high/medium/low）的增减。

`GET /api/runs/diff?base_id={旧记录}&target_id={新记录}` 返回结构（摘要）：

```json
{
  "kind": "labmix-run-diff",
  "plan_id": 3, "plan_name": "……",
  "base":   { "run_id": 7, "rule_revision": "2026.09", "status": "danger",  "created_at": "……" },
  "target": { "run_id": 9, "rule_revision": "2026.10", "status": "warning", "created_at": "……" },
  "summary": {
    "status":         { "base": "danger", "target": "warning", "changed": true },
    "rule_revision":  { "base": "2026.09", "target": "2026.10", "changed": true },
    "first_danger":   { "change": "removed", "base": { "step": 1, "rule_id": "R001", "…": "…" }, "target": null },
    "affected_steps": { "base": [1,2], "target": [1], "added": [], "removed": [2] },
    "blocked_steps":  { "base": [2], "target": [], "added": [], "removed": [2] },
    "steps":          { "items": [ { "step": 1, "base_state": "danger", "target_state": "warning", "change": "changed" } ] },
    "counts":         [ { "key": "high", "label": "严重命中", "base": 1, "target": 0, "delta": -1 } ],
    "finding_changes": { "added": 0, "removed": 0, "severity": 1, "basis": 0, "unchanged": 0 }
  },
  "findings": [
    { "change": "severity", "rule_id": "R001", "incoming_step": 1, "existing_step": 0,
      "base_severity": "high", "target_severity": "medium",
      "basis_changed": false, "changed_fields": [],
      "base":   { "rule_id": "R001", "severity": "high", "title": "…", "reaction": "…",
                  "rationale": "…", "references": ["…"], "incoming_reagent": "盐酸", "…": "…" },
      "target": { "rule_id": "R001", "severity": "medium", "…": "…" } }
  ]
}
```

`GET /api/runs/diff/export` 以相同结构返回，并附带
`Content-Disposition: attachment; filename="runs-{base}-vs-{target}-diff.json"` 下载头。

> 注意：差异比较只对**同一方案**有意义——方案步骤本身被修改会体现在"逐步状态对齐"表中，
> 但 finding 的对齐仍以步骤编号与规则 ID 为准。记录所属方案被删除（`plan_id` 为空）时拒绝比较。

---

## 六、HTTP API 速览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/reagents?q=` | 试剂列表（可按名称/CAS/分子式搜索） |
| POST/PUT/DELETE | `/api/reagents[/{id}]` | 试剂增改删（被步骤引用时拒绝删除） |
| GET/POST | `/api/plans` | 方案列表 / 新建（含步骤） |
| GET/PUT/DELETE | `/api/plans/{id}` | 方案详情 / 修改 / 删除 |
| POST | `/api/plans/{id}/simulate?persist=true` | 按当前规则图推演并（可选）保存记录 |
| POST | `/api/plans/simulate-dry` | 不保存方案，直接预检 |
| GET | `/api/plans/{id}/export` | 实时推演并下载 JSON |
| GET | `/api/rules[?active_only=true]` | 规则边 + 类别元信息 + 版本号 + 当前生效版本 |
| POST | `/api/rules` | 追加自定义规则 |
| PATCH/DELETE | `/api/rules/{id}` | 启停 / 改级别（自定义规则可删） |
| GET | `/api/rule-schemes` | 规则方案列表（含当前生效版本） |
| GET | `/api/rule-schemes/{sid}` | 方案详情：全部版本、生效状态、每版级别统计与变更时间 |
| POST | `/api/rule-schemes/{sid}/versions` | 创建版本（快照实时规则图或 `from_version_id` 复制） |
| GET/PUT/DELETE | `/api/rule-schemes/{sid}/versions/{vid}` | 版本详情 / 编辑草稿 / 删除草稿 |
| PATCH | `/api/rule-schemes/{sid}/versions/{vid}/rules/{rid}` | 编辑草稿内单条规则（级别、依据、启停） |
| POST | `/api/rule-schemes/{sid}/versions/{vid}/publish` | 发布版本（成为当前生效版本，旧版自动停用） |
| POST | `/api/rule-schemes/{sid}/versions/{vid}/disable` | 停用版本（不再参与判定，回退实时规则图） |
| GET | `/api/rule-schemes/{sid}/diff?base_id=&target_id=` | 同一方案两个版本的规则差异 |
| GET | `/api/runs[/{id}[/export]]` | 历史推演记录、详情、导出 |
| GET | `/api/runs/diff?base_id=&target_id=` | 同一方案两条记录的**版本差异** |
| GET | `/api/runs/diff/export?base_id=&target_id=` | 下载版本差异 JSON |

**版本差异接口的 4xx 约定**：缺少参数 → `422`；两条记录 ID 相同 → `400`；
任一记录不存在 → `404`（错误信息标明是基准还是对照记录）；
两条记录不属于同一方案（含方案已删除、记录未关联方案）→ `409`。

**规则版本接口的 4xx 约定**：方案 / 版本不存在 → `404`；同一版本比较 → `400`；
重复发布、停用非发布版本、编辑或删除非草稿版本 → `409`；草稿校验失败（空规则集、
编号重复、类别对相同）→ `422`。

完整交互模型见 <http://localhost:8000/docs>。

---

## 七、目录结构

```
.
├── app/
│   ├── main.py            # FastAPI 入口：建库、同步规则图、挂载网页
│   ├── config.py           # 路径 / DB 配置（环境变量可覆盖）
│   ├── database.py         # SQLite 引擎与会话
│   ├── models.py           # ORM：试剂 / 方案 / 步骤 / 规则 / 推演记录 / 规则方案版本
│   ├── schemas.py          # Pydantic 请求响应模型
│   ├── rules_store.py      # 读取并同步 YAML 规则图
│   ├── rule_versions.py    # 规则方案版本：快照、生命周期、判定来源、版本差异
│   ├── engine.py           # 相容性逐步推演引擎（核心算法）
│   ├── deduce.py           # 方案 → 引擎输入 → 报告 → 落盘
│   ├── diffing.py          # 两条历史记录的版本差异对齐与汇总
│   ├── seed.py             # 内置试剂与示例方案
│   └── routers/            # reagents / plans / rules / rule_versions / runs 路由
├── data/
│   └── rules.yaml          # 声明式规则图（类别 + 规则边）
├── web/                    # 原生 HTML/CSS/JS 界面（无构建步骤）
│   ├── index.html
│   ├── style.css
│   └── app.js              # 含力导向规则图可视化与规则版本管理
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 八、配置项

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_DATA_DIR` | `./data`（本地）/ `/data`（容器） | SQLite 与现场 `rules.yaml` 所在目录 |
| `DATABASE_URL` | `sqlite:///<APP_DATA_DIR>/labmix.db` | 数据库连接串 |

---

### 安全与合规说明

内置规则参考了 GB 15603《危险化学品仓库储存通则》、GB 30000《化学品分类和标签规范》系列、
《Prudent Practices in the Laboratory》(NRC) 及无机化学通用结论，仅覆盖教学实验中最常见的
配伍禁忌，**不保证完备**；新增试剂或特殊工艺请结合 MSDS、院校/单位安全规程并咨询安全管理员。
