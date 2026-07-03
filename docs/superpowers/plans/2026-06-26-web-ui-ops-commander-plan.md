# Web UI Ops Commander Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Rework the existing Web UI into the approved "执行指挥台" structure so the dashboard, navigation, and page responsibilities match the customer-manager workflow.

**Architecture:** Keep the existing FastAPI-served static app and current route ids (`overview`, `industries`, `devices`, `tasks`, `jobs`, `settings`) to avoid unnecessary router churn. Move dashboard-specific coordination out of the inline script into a new `dashboard.js` module, simplify the overview to a single primary action, retire the onboarding modal, and relabel the existing subviews to the new business-facing information architecture.

**Tech Stack:** FastAPI static frontend, vanilla JavaScript modules, Tailwind CSS, pytest contract tests, Playwright CLI smoke script.

---

## File Structure Map

**Existing files to modify**

- `server/static/index.html`
  - Owns the rendered shell, sidebar nav markup, subview templates, and the inline app bootstrap/router.
- `server/static/js/jobs.js`
  - Owns canonical job APIs and remains the task execution data source.
- `server/static/js/devices.js`
  - Owns canonical device APIs and remains the device execution data source.
- `tests/server/api/test_static_modules.py`
  - Owns static HTML/module wiring and UI contract assertions.
- `scripts/smoke/web_ui_acceptance.js`
  - Owns rendered UI smoke coverage across desktop/mobile.

**New files to create**

- `server/static/js/dashboard.js`
  - Owns overview CTA resolution, stage rendering, risk summaries, and onboarding replacement state helpers.
- `tests/server/api/test_ops_commander_contract.py`
  - Owns focused UI contract tests for the new navigation labels, overview structure, and onboarding retirement.

**Files intentionally left alone**

- `server/static/js/api.js`
  - Already owns fetch wrappers and auth error formatting.
- `tests/server/api/test_frontend_contract.py`
  - Route/API contracts remain valid; no scope change needed.
- Backend API files under `server/api/*`
  - This UI pass only reuses existing dashboard, device, jobs, and leads routes.

---

### Task 1: Lock The New UI Contracts In Tests First

**Files:**
- Create: `tests/server/api/test_ops_commander_contract.py`
- Modify: `tests/server/api/test_static_modules.py`
- Test: `tests/server/api/test_ops_commander_contract.py`

- [x] **Step 1: Write the failing contract test file for the approved navigation and overview structure**

```python
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[3] / "server" / "static"


def _html() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def test_primary_navigation_uses_business_labels():
    html = _html()
    assert "首页总览" in html
    assert "项目中心" in html
    assert "设备中心" in html
    assert "线索中心" in html
    assert "任务中心" in html
    assert "系统设置" in html


def test_overview_uses_single_primary_action():
    html = _html()
    assert 'id="overview-primary-action"' in html
    assert 'id="overview-btn-collect"' not in html
    assert 'id="overview-btn-send"' not in html


def test_onboarding_modal_is_removed_from_shell():
    html = _html()
    assert 'id="modal-onboarding"' not in html
    assert "startOnboarding()" not in html
```

- [x] **Step 2: Run the new contract test to prove current HTML fails it**

Run:

```bash
python -m pytest tests/server/api/test_ops_commander_contract.py -q
```

Expected:

```text
FAILED tests/server/api/test_ops_commander_contract.py::test_primary_navigation_uses_business_labels
FAILED tests/server/api/test_ops_commander_contract.py::test_overview_uses_single_primary_action
FAILED tests/server/api/test_ops_commander_contract.py::test_onboarding_modal_is_removed_from_shell
```

- [x] **Step 3: Extend the existing static module test to require the new dashboard module load order**

```python
def test_index_loads_api_job_device_and_dashboard_modules_before_inline_app():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    api_pos = html.index('src="/static/js/api.js"')
    jobs_pos = html.index('src="/static/js/jobs.js"')
    devices_pos = html.index('src="/static/js/devices.js"')
    dashboard_pos = html.index('src="/static/js/dashboard.js"')
    inline_app_pos = html.index("const API_BASE")
    assert api_pos < jobs_pos < devices_pos < dashboard_pos < inline_app_pos
```

- [x] **Step 4: Run the static module tests and capture the expected failure on missing dashboard.js**

Run:

```bash
python -m pytest tests/server/api/test_static_modules.py -q
```

Expected:

```text
FAILED tests/server/api/test_static_modules.py::test_index_loads_api_job_device_and_dashboard_modules_before_inline_app
```

- [x] **Step 5: Commit the red tests**

```bash
git add tests/server/api/test_ops_commander_contract.py tests/server/api/test_static_modules.py
git commit -m "test(ui): lock ops commander dashboard contracts"
```

---

### Task 2: Extract Dashboard Coordination Into A Dedicated Module

**Files:**
- Create: `server/static/js/dashboard.js`
- Modify: `server/static/index.html`
- Test: `tests/server/api/test_static_modules.py`

- [x] **Step 1: Create the dashboard module with the single-CTA decision helpers and public exports**

```javascript
(function (window) {
    'use strict';

    function resolveOverviewPrimaryAction(context) {
        if (!context.hasProject) {
            return { label: '创建项目', targetView: 'industries', mode: 'create-industry' };
        }
        if (!context.hasLLM) {
            return { label: '去系统设置', targetView: 'settings', mode: 'settings' };
        }
        if (!context.hasDevice) {
            return { label: '去设备接入', targetView: 'devices', mode: 'devices' };
        }
        if (!context.hasPending) {
            return { label: '开始采集', targetView: 'industries', mode: 'collect' };
        }
        if (context.isWorking) {
            return { label: '查看任务执行', targetView: 'jobs', mode: 'jobs' };
        }
        return { label: '开始发送', targetView: 'jobs', mode: 'send' };
    }

    function overviewStageItems(context) {
        return [
            { key: 'project', label: '项目配置', ready: context.hasProject, summary: context.projectSummary },
            { key: 'devices', label: '设备接入', ready: context.hasDevice, summary: context.deviceSummary },
            { key: 'collect', label: '采集线索', ready: context.hasPending, summary: context.collectSummary },
            { key: 'send', label: '发送任务', ready: context.canSend, summary: context.sendSummary },
        ];
    }

    window.DashboardUi = Object.freeze({
        resolveOverviewPrimaryAction,
        overviewStageItems,
    });
})(window);
```

- [x] **Step 2: Load the new module before the inline app bootstrap**

```html
<script src="/static/js/api.js"></script>
<script src="/static/js/jobs.js"></script>
<script src="/static/js/devices.js"></script>
<script src="/static/js/dashboard.js"></script>
<script>
const API_BASE = '';
```

- [x] **Step 3: Replace inline overview decision code with calls into `window.DashboardUi`**

```javascript
const primary = window.DashboardUi.resolveOverviewPrimaryAction({
    hasProject,
    hasLLM,
    hasDevice,
    hasPending,
    isWorking,
    canSend: hasProject && hasLLM && hasDevice && hasPending,
    projectSummary: `${overview.industry_count || 0} 个项目`,
    deviceSummary: `${devices.length} 台设备`,
    collectSummary: `${aggregate.totalPending} 条待发送`,
    sendSummary: isWorking ? '任务运行中' : '可开始发送',
});
```

- [x] **Step 4: Run the static module tests to verify the new module is wired correctly**

Run:

```bash
python -m pytest tests/server/api/test_static_modules.py -q
```

Expected:

```text
10 passed
```

- [x] **Step 5: Commit the module extraction**

```bash
git add server/static/index.html server/static/js/dashboard.js tests/server/api/test_static_modules.py
git commit -m "refactor(ui): extract dashboard coordination module"
```

---

### Task 3: Rebuild The Primary Navigation And Page Titles

**Files:**
- Modify: `server/static/index.html`
- Modify: `tests/server/api/test_ops_commander_contract.py`
- Test: `tests/server/api/test_ops_commander_contract.py`

- [x] **Step 1: Rewrite the primary sidebar labels without changing route ids**

```html
<button data-nav="overview" class="nav-btn ...">
    <span>首页总览</span>
</button>
<button data-nav="industries" class="nav-btn ...">
    <span>项目中心</span>
</button>
<button data-nav="devices" class="nav-btn ...">
    <span>设备中心</span>
</button>
<button data-nav="tasks" class="nav-btn ...">
    <span>线索中心</span>
</button>
<button data-nav="jobs" class="nav-btn ...">
    <span>任务中心</span>
</button>
<button data-nav="settings" class="nav-btn ...">
    <span>系统设置</span>
</button>
```

- [x] **Step 2: Remove `keywords` and `abtest` from the primary nav while keeping the routes untouched elsewhere**

```html
<!-- Remove these buttons from the primary nav only -->
<!-- <button data-nav="keywords">...</button> -->
<!-- <button data-nav="abtest">...</button> -->
```

- [x] **Step 3: Update the router title mapping to the new business-facing view titles**

```javascript
const VIEW_TITLES = {
    overview: '首页总览',
    industries: '项目中心',
    devices: '设备中心',
    tasks: '线索中心',
    jobs: '任务中心',
    settings: '系统设置',
    keywords: '关键词效果',
    abtest: 'A/B 实验',
};
```

- [x] **Step 4: Add assertions that the deprecated primary labels no longer appear in navigation**

```python
def test_legacy_primary_navigation_labels_are_removed():
    html = _html()
    assert "项目配置" not in html
    assert "设备准备" not in html
    assert "执行记录" not in html
```

- [x] **Step 5: Run the focused nav contract tests**

Run:

```bash
python -m pytest tests/server/api/test_ops_commander_contract.py -q
```

Expected:

```text
4 passed
```

- [x] **Step 6: Commit the navigation rewrite**

```bash
git add server/static/index.html tests/server/api/test_ops_commander_contract.py
git commit -m "feat(ui): rename primary navigation for ops commander flow"
```

---

### Task 4: Replace The Overview With A Single-Action Ops Commander Dashboard

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/static/js/dashboard.js`
- Modify: `tests/server/api/test_ops_commander_contract.py`
- Test: `tests/server/api/test_ops_commander_contract.py`

- [x] **Step 1: Replace the dual collect/send action area with a single primary action panel**

```html
<div class="p-6 rounded-2xl glass-panel flex flex-col justify-between gap-5">
    <div>
        <p class="text-xs font-semibold text-cyan-400 tracking-wide uppercase">当前卡点</p>
        <h3 id="overview-next-title" class="font-bold text-lg font-display text-slate-100 mt-2">等待状态加载</h3>
        <p id="overview-next-desc" class="text-xs text-slate-400 mt-2 leading-relaxed">系统会根据当前卡点给出唯一下一步。</p>
    </div>
    <button id="overview-primary-action" class="w-full py-3 bg-cyan-500 text-slate-950 font-bold rounded-lg transition-all">
        处理中
    </button>
</div>
```

- [x] **Step 2: Add the four-stage execution path container beneath the command card**

```html
<div id="overview-stage-list" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
    <div class="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-4 text-xs text-slate-400">
        正在加载执行路径...
    </div>
</div>
```

- [x] **Step 3: Render the primary action and stage cards from the dashboard module**

```javascript
function renderOverviewPrimaryAction(primary, primaryIndustry) {
    const button = document.getElementById('overview-primary-action');
    if (!button) return;
    button.innerText = primary.label;
    button.onclick = () => {
        if (primary.mode === 'create-industry') return window.showCreateIndustryModal();
        if (primary.mode === 'settings') return window.router.navigate('settings');
        if (primary.mode === 'devices') return window.router.navigate('devices');
        if (primary.mode === 'collect') return window.triggerCollect(primaryIndustry);
        if (primary.mode === 'send') return window.triggerSend(primaryIndustry);
        return window.router.navigate('jobs');
    };
}

function renderOverviewStages(items) {
    const list = document.getElementById('overview-stage-list');
    if (!list) return;
    list.innerHTML = items.map(item => `
        <div class="rounded-xl border ${item.ready ? 'border-emerald-500/30' : 'border-slate-800'} bg-slate-950/40 px-4 py-4">
            <p class="text-[11px] uppercase tracking-wide ${item.ready ? 'text-emerald-400' : 'text-slate-500'}">${item.label}</p>
            <p class="mt-2 text-sm text-slate-200">${item.summary}</p>
        </div>
    `).join('');
}
```

- [x] **Step 4: Assert that the new overview shell exposes the primary action and stage list**

```python
def test_overview_shell_exposes_ops_commander_regions():
    html = _html()
    assert 'id="overview-primary-action"' in html
    assert 'id="overview-stage-list"' in html
    assert "当前卡点" in html
```

- [x] **Step 5: Run the overview contract tests**

Run:

```bash
python -m pytest tests/server/api/test_ops_commander_contract.py -q
```

Expected:

```text
5 passed
```

- [x] **Step 6: Commit the overview redesign**

```bash
git add server/static/index.html server/static/js/dashboard.js tests/server/api/test_ops_commander_contract.py
git commit -m "feat(ui): redesign overview as ops commander dashboard"
```

---

### Task 5: Retire The Onboarding Modal And Fold First-Use Guidance Into Overview State

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/static/js/dashboard.js`
- Modify: `tests/server/api/test_ops_commander_contract.py`
- Test: `tests/server/api/test_ops_commander_contract.py`

- [x] **Step 1: Delete the onboarding modal markup from the static shell**

```html
<!-- Remove the entire modal block that begins here -->
<!-- <div id="modal-onboarding" role="dialog" ...> -->
<!-- and ends at the closing onboarding container -->
```

- [x] **Step 2: Delete the onboarding step data and functions from the inline bootstrap**

```javascript
// Remove these symbols entirely:
// const ONBOARDING_STEPS = [...]
// let onboardingCurrentStep = 0;
// function startOnboarding() {}
// function hideOnboarding() {}
// function completeOnboarding() {}
// function skipOnboarding() {}
// function renderOnboardingStep() {}
// function nextOnboardingStep() {}
// function prevOnboardingStep() {}
```

- [x] **Step 3: Replace the onboarding trigger with a first-use overview hint helper**

```javascript
function shouldShowFirstUseHint() {
    return localStorage.getItem('thunder_onboarding_seen') !== 'true';
}

function markFirstUseHintSeen() {
    localStorage.setItem('thunder_onboarding_seen', 'true');
}

function decorateOverviewForFirstUse(primary) {
    if (!shouldShowFirstUseHint()) return primary;
    return {
        ...primary,
        label: primary.label,
        hint: '首次使用建议按顺序完成：项目配置、设备接入、采集线索、发送任务。',
    };
}
```

- [x] **Step 4: Apply the first-use hint inside the overview title/description instead of opening a modal**

```javascript
const primary = decorateOverviewForFirstUse(
    window.DashboardUi.resolveOverviewPrimaryAction(context)
);
nextTitle.innerText = context.blockerTitle;
nextDesc.innerText = primary.hint || context.blockerDescription;
```

- [x] **Step 5: Run the focused tests to prove the modal is gone and the shell still passes**

Run:

```bash
python -m pytest tests/server/api/test_ops_commander_contract.py tests/server/api/test_static_modules.py -q
```

Expected:

```text
15 passed
```

- [x] **Step 6: Commit the onboarding retirement**

```bash
git add server/static/index.html server/static/js/dashboard.js tests/server/api/test_ops_commander_contract.py
git commit -m "feat(ui): fold first-use onboarding into overview guidance"
```

---

### Task 6: Align Subview Responsibilities, Copy, And Smoke Coverage

**Files:**
- Modify: `server/static/index.html`
- Modify: `scripts/smoke/web_ui_acceptance.js`
- Modify: `tests/server/api/test_ops_commander_contract.py`
- Test: `scripts/smoke/web_ui_acceptance.js`

- [x] **Step 1: Update the subview headings and descriptions to the approved page responsibilities**

```html
<!-- industries -->
<h3 class="font-bold text-lg font-display text-slate-100">项目中心</h3>
<p class="text-sm text-slate-400">创建和维护项目策略，包括平台、关键词、对标账号、采集与发送参数。</p>

<!-- devices -->
<h3 class="font-bold text-lg font-display text-slate-100">设备中心</h3>
<p class="text-sm text-slate-400">连接、检测并验收 Android 设备，处理在线状态和执行异常。</p>

<!-- tasks -->
<h3 class="font-bold text-lg font-display text-slate-100">线索中心</h3>
<p class="text-sm text-slate-400">查看线索库存、失败重发和导出结果，聚焦评论、状态和发送记录。</p>

<!-- jobs -->
<h3 class="font-bold text-lg font-display text-slate-100">任务中心</h3>
<p class="text-sm text-slate-400">查看采集与发送任务状态、取消请求、执行日志和复盘证据。</p>
```

- [x] **Step 2: Keep advanced/secondary routes out of the primary smoke nav loop**

```javascript
for (const nav of ['devices', 'tasks', 'jobs', 'settings', 'industries']) {
    await page.locator(`[data-nav="${nav}"]`).click();
    await page.waitForTimeout(300);
    const title = await page.locator('#current-view-title').innerText();
    views.push({ nav, title });
}
```

- [x] **Step 3: Add smoke assertions for the renamed titles and overview primary CTA**

```javascript
assert(await page.locator('#overview-primary-action').count() === 1, 'Overview primary CTA is missing');
await page.locator('[data-nav="overview"]').click();
await page.waitForTimeout(200);
assert((await page.locator('#current-view-title').innerText()) === '首页总览', 'Overview title did not update');
```

- [x] **Step 4: Add final contract assertions for the new subview headings**

```python
def test_subview_headings_match_ops_commander_information_architecture():
    html = _html()
    assert ">项目中心<" in html
    assert ">设备中心<" in html
    assert ">线索中心<" in html
    assert ">任务中心<" in html
```

- [x] **Step 5: Run the full frontend verification set**

Run:

```bash
python -m pytest tests/server/api/test_ops_commander_contract.py tests/server/api/test_static_modules.py tests/server/api/test_frontend_contract.py -q
node scripts/smoke/web_ui_acceptance.js
```

Expected:

```text
all pytest tests pass
web_ui_acceptance.js completes without throwing
```

- [x] **Step 6: Commit the responsibility alignment pass**

```bash
git add server/static/index.html scripts/smoke/web_ui_acceptance.js tests/server/api/test_ops_commander_contract.py
git commit -m "feat(ui): align subviews with ops commander responsibilities"
```

---

## Self-Review

### Spec Coverage

- Navigation rename and simplification: covered by Tasks 1, 3, and 6.
- Overview as single-action execution dashboard: covered by Tasks 2 and 4.
- Onboarding modal retirement and merge into homepage: covered by Task 5.
- Five-page responsibility boundaries: covered by Task 6.
- Keep existing backend/API surface and avoid unnecessary route churn: covered by Tasks 2 and 6.

No spec gaps remain for the approved UI scope.

### Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain.
- Every code-changing step includes concrete code snippets.
- Every verification step includes exact commands and expected outcomes.

### Type Consistency

- Primary route ids remain `overview`, `industries`, `devices`, `tasks`, `jobs`, `settings`.
- New overview CTA id is consistently `overview-primary-action`.
- New overview stage list id is consistently `overview-stage-list`.
- New module namespace is consistently `window.DashboardUi`.

---

**Completion note:** 已在本会话中以内联方式执行完毕。所有 6 个 Task 的代码变更、测试补充和验证命令均已完成，pytest 273 passed，ruff/mypy 通过。Smoke 脚本已按 ops commander 导航和 overview CTA 要求更新，可在具备 Node.js Playwright 的环境通过 `node scripts/smoke/web_ui_acceptance.js` 运行。
