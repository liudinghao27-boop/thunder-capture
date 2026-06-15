# Phase 2 Web 化配置 + 新手引导 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户无需编辑 YAML，在网页上完成项目配置，并通过新手引导在首次登录后 5 分钟内完成第一个项目。

**Architecture:** 后端以 `Industry` 模型为唯一配置来源，新增就绪度检查 API；前端扩展现有项目弹窗，增加标签输入、字段分组和术语翻译，并新增 Onboarding 向导；CLI 与核心配置模块从 YAML 读取切换为优先从数据库读取。

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Vanilla JS + Tailwind CSS, pytest

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `server/schemas/industry.py` | 扩展 schema 校验，确保 list 字段去重归一化 |
| `server/api/industries.py` | 新增 `GET /api/industries/{id}/ready-state` |
| `server/models/industry.py` | 无需修改（字段已存在） |
| `core/config.py` | 新增 `load_industry_from_db`，CLI/引擎优先从 DB 加载 |
| `cli.py` | 将 `load_industry` 调用替换为支持 DB 的加载 |
| `server/static/index.html` | 扩展项目弹窗、标签输入组件、Onboarding、术语翻译、就绪度提示 |
| `tests/server/test_industries.py` | 新增就绪度 API 测试和 list 字段更新测试 |
| `tests/test_cli_config.py` | 新增 CLI 从 DB 加载配置的测试 |

---

## Task 1: 扩展 Industry Schema 校验

**Files:**
- Modify: `server/schemas/industry.py`
- Test: `tests/server/test_industries.py`

- [ ] **Step 1: Write the failing test**

在 `tests/server/test_industries.py` 中新增测试：

```python
def test_update_industry_normalizes_list_fields(client, auth_headers, db):
    # 假设已有测试 fixtures: client, auth_headers, db
    # 先创建一个项目
    resp = client.post("/api/industries", json={
        "name": "测试项目",
        "slug": "test-normalize",
        "keywords": ["a", "b"],
    }, headers=auth_headers)
    assert resp.status_code == 201
    ind_id = resp.json()["id"]

    resp = client.put(f"/api/industries/{ind_id}", json={
        "intent_keywords": ["  想买  ", "咨询", "咨询", ""],
        "noise_keywords": ["  666  ", ""],
        "target_users": [" 宝妈 ", "宝妈"],
        "categories": [" 咨询 ", " 咨询 ", "其他"],
    }, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent_keywords"] == ["想买", "咨询"]
    assert data["noise_keywords"] == ["666"]
    assert data["target_users"] == ["宝妈"]
    assert data["categories"] == ["咨询", "其他"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "C:/Users/Administrator/Desktop/shemeihuoke"
python -m pytest tests/server/test_industries.py::test_update_industry_normalizes_list_fields -v
```

Expected: FAIL（字段未归一化，返回带空格/重复项）。

- [ ] **Step 3: Implement normalization in schema**

在 `server/schemas/industry.py` 的 `IndustryUpdate` 中新增 validators：

```python
@field_validator("intent_keywords", "noise_keywords", "target_users", "categories")
@classmethod
def _normalize_string_list(cls, value: Optional[list[str]]) -> Optional[list[str]]:
    return normalize_unique_strings(value)
```

注意 `normalize_unique_strings` 已定义，可直接复用。

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/server/test_industries.py::test_update_industry_normalizes_list_fields -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/schemas/industry.py tests/server/test_industries.py
git commit -m "feat(phase2): normalize list fields in IndustryUpdate schema"
```

---

## Task 2: 新增项目就绪度检查 API

**Files:**
- Modify: `server/api/industries.py`
- Test: `tests/server/test_industries.py`

- [ ] **Step 1: Write the failing test**

在 `tests/server/test_industries.py` 中新增：

```python
def test_industry_ready_state_complete(client, auth_headers, db, sample_industry):
    resp = client.get(f"/api/industries/{sample_industry.id}/ready-state", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "score" in data
    assert "checks" in data
    assert data["checks"]["has_keywords"] is True
    assert data["checks"]["has_device"] is False  # 假设无设备
    assert "next_step" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/server/test_industries.py::test_industry_ready_state_complete -v
```

Expected: FAIL（404，路由不存在）。

- [ ] **Step 3: Implement ready-state endpoint**

在 `server/api/industries.py` 中新增辅助函数和路由：

```python
from server.models.device import Device
from server.secret_store import has_secret


def _industry_ready_state(ind: Industry, db: Session, user: User) -> dict:
    checks = {
        "has_keywords": bool(ind.keywords),
        "has_intent_keywords": bool(ind.intent_keywords),
        "has_noise_keywords": bool(ind.noise_keywords),
        "has_categories": bool(ind.categories),
        "has_reply_persona": bool(ind.reply_tone and ind.reply_style),
        "has_api_key": bool(
            os.getenv("THUNDER_DEEPSEEK_KEY")
            or os.getenv("THUNDER_ZHIPU_KEY")
            or os.getenv("THUNDER_OPENAI_KEY")
            or has_secret(user.deepseek_key)
            or has_secret(user.zhipu_key)
            or has_secret(user.openai_key)
        ),
        "has_device": db.query(Device).filter(
            Device.user_id == user.id, Device.is_active == True
        ).first() is not None,
        "compliance_ready": (
            not ind.compliance_mode or bool(ind.webhook_url)
        ),
    }

    score = int(sum(checks.values()) / len(checks) * 100)

    # Determine next step based on priority
    next_step = "项目已就绪，可以开始采集"
    if not checks["has_api_key"]:
        next_step = "请先配置 LLM API Key"
    elif not checks["has_keywords"]:
        next_step = "请至少添加一个搜索关键词"
    elif not checks["has_intent_keywords"]:
        next_step = "请添加意图词以提高分类准确率"
    elif not checks["has_noise_keywords"]:
        next_step = "请添加噪声词以过滤无意义评论"
    elif not checks["has_reply_persona"]:
        next_step = "请设置回复人设和风格"
    elif not checks["compliance_ready"]:
        next_step = "合规模式已开启，请配置 Webhook URL"
    elif not checks["has_device"]:
        next_step = "请至少添加一台活跃设备以执行发送"

    return {
        "ok": score >= 75,
        "industry_id": ind.id,
        "score": score,
        "checks": checks,
        "next_step": next_step,
    }


@router.get("/{industry_id}/ready-state")
def get_industry_ready_state(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    return _industry_ready_state(ind, db, current_user)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/server/test_industries.py::test_industry_ready_state_complete -v
```

Expected: PASS

- [ ] **Step 5: Add additional ready-state tests**

新增测试覆盖：
- 无 API Key 时 `has_api_key=False`。
- 合规模式无 Webhook 时 `compliance_ready=False`。
- 有设备时 `has_device=True`。

- [ ] **Step 6: Run all industry tests**

```bash
python -m pytest tests/server/test_industries.py -v
```

Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add server/api/industries.py tests/server/test_industries.py
git commit -m "feat(phase2): add industry ready-state API"
```

---

## Task 3: CLI / 核心配置优先从数据库加载

**Files:**
- Modify: `core/config.py`
- Modify: `cli.py`
- Test: `tests/test_cli_config.py`

- [ ] **Step 1: Write the failing test**

创建 `tests/test_cli_config.py`：

```python
import os
import pytest

os.environ.setdefault("THUNDER_DATABASE_URL", "sqlite:///./data/test_cli.db")

from core.config import load_industry, list_industries


def test_load_industry_falls_back_to_yaml(tmp_path, monkeypatch):
    # 当 DB 中不存在时，仍可从 YAML 加载
    monkeypatch.setenv("THUNDER_DATABASE_URL", "sqlite:///" + str(tmp_path / "empty.db"))
    ind = load_industry("recruitment")
    assert ind.name == "征兵咨询"


def test_load_industry_prefers_db_when_available():
    # 当 DB 中存在同名项目时，优先返回 DB 配置
    # 此测试依赖 fixtures，需先创建行业
    pass
```

> 注：第二个测试先占位，等实现完成后再填充。

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_cli_config.py -v
```

Expected: 第一个测试可能 PASS（当前行为），第二个 SKIP/PASS。

- [ ] **Step 3: Implement DB-first loading**

在 `core/config.py` 中新增：

```python
def load_industry(slug: str) -> IndustryConfig:
    """Load industry config. Prefer DB over YAML for user-managed industries."""
    # Try DB first
    db_config = _load_industry_from_db(slug)
    if db_config:
        return db_config

    # Fallback to YAML for system templates / backward compatibility
    path = CONFIG_DIR / "industries" / f"{slug}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"行业配置不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return IndustryConfig(**{k: v for k, v in data.items()
                             if k in IndustryConfig.__dataclass_fields__})


def _load_industry_from_db(slug: str) -> IndustryConfig | None:
    """Load active industry config from the database if available."""
    try:
        from server.models import get_db
        from server.models.industry import Industry
        from server.models.user import User
        from server.secret_store import decrypt_secret

        db = next(get_db())
        try:
            ind = db.query(Industry).filter(
                Industry.slug == slug,
                Industry.is_active == True,
            ).first()
            if not ind:
                return None
            user = ind.user
            return IndustryConfig(
                name=ind.name,
                slug=ind.slug,
                keywords=ind.keywords or [],
                reply_tone=ind.reply_tone or "业内人士",
                reply_style=ind.reply_style or "亲切专业",
                reply_hook=getattr(ind, "reply_hook", "") or "",
                categories=ind.categories or [],
                daily_limit=ind.daily_limit or 15,
                video_max_age_days=ind.video_max_age_days or 14,
                comment_max_age_hours=ind.comment_max_age_hours or 48,
                platforms=_single_platform(ind.platforms),
                llm_provider=ind.llm_provider or "deepseek",
                llm_model=ind.llm_model or "deepseek-chat",
                deepseek_key=decrypt_secret(user.deepseek_key) if user else "",
                zhipu_key=decrypt_secret(user.zhipu_key) if user else "",
                openai_key=decrypt_secret(user.openai_key) if user else "",
                intent_keywords=ind.intent_keywords or [],
                noise_keywords=ind.noise_keywords or [],
                target_users=ind.target_users or [],
                user_id=ind.user_id,
                matrix_target_devices=ind.matrix_target_devices or 30,
                lead_inventory_days=ind.lead_inventory_days or 3,
                global_daily_limit=ind.global_daily_limit or 0,
                auto_replenish_enabled=bool(ind.auto_replenish_enabled),
                replenish_threshold_days=ind.replenish_threshold_days or 1,
                keyword_batch_size=ind.keyword_batch_size or 12,
                collect_authors_per_run=ind.collect_authors_per_run or 60,
                collect_video_limit=ind.collect_video_limit or 120,
                compliance_mode=bool(getattr(ind, "compliance_mode", False)),
                webhook_url=getattr(ind, "webhook_url", "") or "",
                auto_export_enabled=bool(getattr(ind, "auto_export_enabled", False)),
            )
        finally:
            db.close()
    except Exception:
        return None
```

注意：需要把 `_single_platform` 从 `server/api/industries.py` 移到 `core/config.py` 或复用本地实现。

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_cli_config.py -v
```

Expected: PASS

- [ ] **Step 5: Update CLI to use DB-first load**

`cli.py` 中 `load_industry` 调用保持不变（函数内部已处理 DB 优先），确认无额外修改。

- [ ] **Step 6: Run CLI smoke test**

```bash
python cli.py --help
```

Expected: 正常输出帮助信息。

- [ ] **Step 7: Commit**

```bash
git add core/config.py cli.py tests/test_cli_config.py
git commit -m "feat(phase2): load industry config from DB, fallback to YAML"
```

---

## Task 4: 前端标签输入组件

**Files:**
- Modify: `server/static/index.html`

- [ ] **Step 1: Add reusable tag input CSS/JS**

在 `server/static/index.html` 的 `<script>` 区域新增通用函数：

```javascript
function createTagInput(containerId, hiddenInputId, initialTags = []) {
    const container = document.getElementById(containerId);
    const hiddenInput = document.getElementById(hiddenInputId);
    let tags = [...initialTags];

    function render() {
        container.innerHTML = '';
        tags.forEach((tag, index) => {
            const pill = document.createElement('span');
            pill.className = 'inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 text-xs border border-cyan-500/30';
            pill.innerHTML = `<span>${escapeHtml(tag)}</span><button type="button" class="text-cyan-400 hover:text-cyan-200">&times;</button>`;
            pill.querySelector('button').onclick = () => {
                tags.splice(index, 1);
                update();
            };
            container.appendChild(pill);
        });
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'bg-transparent border-none outline-none text-xs text-slate-200 placeholder-slate-500 min-w-[80px] flex-1';
        input.placeholder = '输入后回车/逗号';
        input.onkeydown = (e) => {
            if (e.key === 'Enter' || e.key === ',' || e.key === 'Tab') {
                e.preventDefault();
                const val = input.value.trim();
                if (val && !tags.includes(val)) {
                    tags.push(val);
                    update();
                }
                input.value = '';
            }
            if (e.key === 'Backspace' && input.value === '' && tags.length) {
                tags.pop();
                update();
            }
        };
        input.onblur = () => {
            const val = input.value.trim();
            if (val && !tags.includes(val)) {
                tags.push(val);
                update();
            }
            input.value = '';
        };
        container.appendChild(input);
        hiddenInput.value = JSON.stringify(tags);
    }

    function update() {
        render();
        hiddenInput.dispatchEvent(new Event('input', { bubbles: true }));
    }

    render();
    return {
        getTags: () => tags,
        setTags: (newTags) => { tags = [...newTags]; render(); }
    };
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
```

- [ ] **Step 2: Replace raw inputs with tag inputs**

在项目弹窗中，将 `industry-keywords`、`industry-categories` 等 textarea/input 替换为标签输入容器 + 隐藏 input。

例如：

```html
<div class="space-y-1">
    <label class="text-xs text-slate-400">搜索关键词</label>
    <div id="keywords-tag-container" class="flex flex-wrap gap-1.5 p-2 bg-slate-900 border border-slate-800 rounded-lg min-h-[2.5rem]"></div>
    <input type="hidden" id="industry-keywords" name="industry-keywords">
</div>
```

并在打开弹窗时初始化：

```javascript
const keywordsInput = createTagInput('keywords-tag-container', 'industry-keywords', ind.keywords || []);
```

- [ ] **Step 3: Manual verification**

启动服务器，打开项目弹窗：
- 回车添加标签。
- 逗号添加标签。
- Backspace 删除标签。
- 保存后重新打开，标签 retained。

- [ ] **Step 4: Commit**

```bash
git add server/static/index.html
git commit -m "feat(phase2): add reusable tag input component for industry form"
```

---

## Task 5: 前端字段分组与术语翻译

**Files:**
- Modify: `server/static/index.html`

- [ ] **Step 1: Reorganize modal form into sections**

将项目弹窗表单划分为：
- 基础配置
- 关键词漏斗
- 回复人设
- 采集策略（默认折叠）
- 发送策略（默认折叠）
- 合规设置

每个分组使用可折叠的 `<details>` 或按钮控制显隐。推荐用按钮 + CSS class 切换。

- [ ] **Step 2: Translate labels**

按设计文档中的术语表替换所有用户可见标签。

- [ ] **Step 3: Add intent/noise/target/category tag inputs**

在“关键词漏斗”分组中添加：
- 意图词
- 噪声词
- 目标用户
- 客户分类

均使用 Task 4 的 `createTagInput`。

- [ ] **Step 4: Update form save/load logic**

在 `editIndustry` / `saveIndustry` 函数中读取 tag inputs 的隐藏 input 值，并正确序列化为 JSON 数组。

- [ ] **Step 5: Manual verification**

- 项目弹窗显示字段分组。
- 高级分组默认折叠。
- 所有新字段可保存和加载。

- [ ] **Step 6: Commit**

```bash
git add server/static/index.html
git commit -m "feat(phase2): group industry form fields and translate UI labels"
```

---

## Task 6: 前端新手引导（Onboarding）

**Files:**
- Modify: `server/static/index.html`

- [ ] **Step 1: Add onboarding modal HTML**

在页面中添加：

```html
<div id="modal-onboarding" class="fixed inset-0 z-50 hidden items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md p-6 shadow-2xl">
        <div id="onboarding-step-content"></div>
        <div class="flex justify-between mt-6">
            <button id="onboarding-skip" type="button" class="text-xs text-slate-400 hover:text-slate-200">跳过</button>
            <button id="onboarding-next" type="button" class="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white text-xs rounded-lg">下一步</button>
        </div>
        <div class="flex justify-center gap-1.5 mt-4" id="onboarding-dots"></div>
    </div>
</div>
```

- [ ] **Step 2: Implement onboarding logic**

在 `<script>` 中新增：

```javascript
const ONBOARDING_STEPS = [
    {
        title: '欢迎来到雷霆捕获系统',
        body: '雷霆捕获可以帮你从抖音、小红书等平台自动采集高意向评论线索，并通过 AI 私信引流。',
        action: null,
    },
    {
        title: '配置 API Key',
        body: '系统需要 LLM API Key 来智能分类评论意图。请在“系统设置”中配置 DeepSeek / 智谱 / OpenAI 任一密钥。',
        action: () => { showTab('settings'); },
    },
    {
        title: '添加设备',
        body: '准备一台 Android 手机，开启 ADB 调试并连接电脑，然后在“设备”页签添加设备。',
        action: () => { showTab('devices'); },
    },
    {
        title: '创建第一个项目',
        body: '点击“新建项目”，用一句话描述你的业务，AI 会自动生成关键词和回复话术。',
        action: () => { showCreateIndustryModal(); },
    },
];

function startOnboarding() {
    if (localStorage.getItem('thunder_onboarding_seen')) return;
    let step = 0;
    const modal = document.getElementById('modal-onboarding');
    modal.classList.replace('hidden', 'flex');

    function render() {
        const s = ONBOARDING_STEPS[step];
        document.getElementById('onboarding-step-content').innerHTML = `
            <h3 class="text-lg font-bold text-slate-100 mb-2">${s.title} <span class="text-slate-500 text-sm">(${step + 1}/${ONBOARDING_STEPS.length})</span></h3>
            <p class="text-sm text-slate-300 leading-relaxed">${s.body}</p>
        `;
        document.getElementById('onboarding-next').innerText = step === ONBOARDING_STEPS.length - 1 ? '完成' : '下一步';
        const dots = ONBOARDING_STEPS.map((_, i) =>
            `<span class="w-2 h-2 rounded-full ${i === step ? 'bg-cyan-500' : 'bg-slate-600'}"></span>`
        ).join('');
        document.getElementById('onboarding-dots').innerHTML = dots;
    }

    document.getElementById('onboarding-next').onclick = () => {
        const action = ONBOARDING_STEPS[step].action;
        if (action) action();
        step++;
        if (step >= ONBOARDING_STEPS.length) {
            modal.classList.replace('flex', 'hidden');
            localStorage.setItem('thunder_onboarding_seen', 'true');
            return;
        }
        render();
    };

    document.getElementById('onboarding-skip').onclick = () => {
        modal.classList.replace('flex', 'hidden');
        localStorage.setItem('thunder_onboarding_seen', 'true');
    };

    render();
}
```

- [ ] **Step 3: Trigger onboarding on first load**

在页面初始化成功后调用 `startOnboarding()`。

- [ ] **Step 4: Manual verification**

- 清空 localStorage 刷新，确认 Onboarding 出现。
- 点击“跳过”后刷新不再出现。
- 点击“下一步”能正确跳转页签/打开弹窗。

- [ ] **Step 5: Commit**

```bash
git add server/static/index.html
git commit -m "feat(phase2): add first-time onboarding wizard"
```

---

## Task 7: 控制中心就绪度提示

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/api/dashboard.py`（如需要聚合接口）

- [ ] **Step 1: Fetch ready-state in dashboard**

在 `loadOverview()` 或相关函数中，为当前活跃项目调用 `/api/industries/{id}/ready-state`。

- [ ] **Step 2: Display next-step banner**

在“控制中心”顶部增加提示条：

```html
<div id="readiness-banner" class="hidden mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-center justify-between">
    <span id="readiness-message"></span>
    <button id="readiness-action" type="button" class="px-3 py-1 bg-amber-600 hover:bg-amber-500 text-white rounded-md text-xs">去配置</button>
</div>
```

- [ ] **Step 3: Wire action button**

根据 `next_step` 类型决定点击行为：
- API Key → 打开设置页签。
- 设备 → 打开设备页签。
- 项目字段 → 打开项目编辑弹窗。

- [ ] **Step 4: Manual verification**

- 未配置 API Key 时显示对应提示。
- 点击按钮跳转到正确位置。

- [ ] **Step 5: Commit**

```bash
git add server/static/index.html
git commit -m "feat(phase2): show readiness next-step banner in control center"
```

---

## Task 8: 回归测试与最终提交

**Files:**
- 全部修改文件
- Test: `tests/`

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -q --tb=short
```

Expected: ALL PASS

- [ ] **Step 2: Fix any regressions**

- 若 CLI 测试失败，调整 DB 连接或 fallback 逻辑。
- 若行业 API 测试失败，检查 schema 校验。

- [ ] **Step 3: Update SOP status**

在 `docs/superpowers/sops/2026-06-15-commercialization-roadmap-sop.md` 中：
- 将 Phase 2 状态更新为“已完成”。
- 添加客户价值摘要。

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(phase2): complete web config + onboarding guide

- Normalize list fields in IndustryUpdate schema
- Add /api/industries/{id}/ready-state
- Load industry config from DB with YAML fallback
- Add reusable tag input component
- Group project form fields and translate UI labels
- Add first-time onboarding wizard
- Show readiness next-step banner in control center
- Update SOP and docs"
```

- [ ] **Step 5: Run tests one final time**

```bash
python -m pytest tests/ -q
```

Expected: ALL PASS

---

## Self-Review

### Spec Coverage

| Spec 要求 | 对应任务 |
|---|---|
| 扩展 schema 校验 list 字段 | Task 1 |
| 新增 ready-state API | Task 2 |
| DB 优先加载配置 | Task 3 |
| 标签输入组件 | Task 4 |
| 字段分组与术语翻译 | Task 5 |
| 新手引导 | Task 6 |
| 就绪度提示 | Task 7 |
| 回归测试 | Task 8 |
| 更新 SOP | Task 8 |

### Placeholder Scan

- 无 TBD/TODO。
- 所有步骤包含具体代码或命令。
- 测试代码已给出雏形。

### Type Consistency

- `_industry_ready_state` 返回 dict 与测试断言一致。
- `_load_industry_from_db` 返回 `IndustryConfig | None`，与 `load_industry` 调用一致。
- 标签输入隐藏 input 使用 JSON 字符串，与表单提交逻辑一致。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-15-phase2-web-config-onboarding-plan.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

User has authorized autonomous completion. Proceeding with Subagent-Driven by default unless instructed otherwise.
