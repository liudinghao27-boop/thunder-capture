# Web UI 前后端同步自动化测试 SOP

## 目标

用自动化 E2E 测试替代人工反复点击采集/发送页面的验收方式，重点发现四类问题：

- 后端接口返回成功，但前端没有刷新或渲染错误。
- 前端展示的数量、状态、列表行数与 API 返回值不一致。
- 未登录、已登录、异常请求等权限/错误场景的 UI 表现与后端状态码不一致。
- 页面运行时 JavaScript 错误、接口 4xx/5xx 未被识别，导致人工测试卡住。

## 技术方案

入口脚本：`scripts/smoke/ui_sync_e2e.py`

执行方式：

```powershell
.\scripts\smoke\run_ui_sync_e2e.bat
```

或：

```powershell
.\.venv\Scripts\python.exe scripts\smoke\ui_sync_e2e.py --base-url http://127.0.0.1:8000
```

脚本能力：

- 如果本地 `127.0.0.1:8000` 未启动，会自动用 SQLite 模式启动临时 FastAPI 服务。
- 使用 Playwright 打开真实浏览器，走注册、登录、导航、接口请求和 DOM 读取。
- 自动创建灰度项目并在结束前删除，避免污染业务数据。
- 通过 `SyncMapping` 显式维护 UI 选择器和 API 字段路径的映射。
- 失败时输出 `report.json`、`api-responses.json`、`final-state.png`。

报告目录：

```text
output/ui-sync/YYYYMMDD-HHMMSS/
```

## 当前覆盖场景

| 场景 | 校验内容 |
| --- | --- |
| 权限变更 | 未登录看到登录表单；登录后设置页可见且 `/api/auth/settings` 返回 200 |
| 数据提交后 UI 更新 | 创建项目 API 返回 201 后，项目卡片展示项目名称和 slug |
| Dashboard 同步 | `#stat-industries` 对齐 `/api/dashboard/state.project.industry_count`；`#stat-devices` 对齐设备总数 |
| 列表渲染/分页 | 线索表格行数对齐 `/api/leads?limit=50` 的返回数量或空状态 |
| 任务视图 | 任务表格行数对齐 `/api/jobs?limit=100` 的返回数量或空状态 |
| 异常场景 | 无效发送任务返回 404 且包含 `detail`，用于验证前后端错误契约 |

## 自动触发

GitHub Actions workflow：`.github/workflows/ui-sync-e2e.yml`

触发方式：

- `push` 到 `main/master/feat/**/fix/**` 且影响 `server/**`、`core/**` 或 E2E 脚本。
- PR 变更影响核心后端、前端静态页面或 E2E 脚本。
- 每日定时巡检。
- 手动 `workflow_dispatch`。

## 灰度验证结果

本地灰度验证命令：

```powershell
.\.venv\Scripts\python.exe scripts\smoke\ui_sync_e2e.py --base-url http://127.0.0.1:8000
```

最近一次结果：

- 成功率：8/8。
- 执行耗时：约 15 秒。
- 问题发现率：首轮发现 1 个测试框架误判点，即预期 404 请求污染浏览器 console；已改为 Playwright API request 验证。
- 相比人工测试：不再需要手动注册、点页面、查看日志、截图留证；失败会直接给出字段、预期值、实际值和截图。

## 失败排查

1. 打开最新 `output/ui-sync/*/report.json`，先看 `failed` 和 `mismatches`。
2. 查看 `final-state.png` 判断 UI 是否停在错误页面。
3. 查看 `api-responses.json` 判断后端返回是否符合预期。
4. 如果服务未启动，查看 `tmp/ui-sync-server.err.log`。
5. 如果浏览器不可用，执行：

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 扩展新页面

新增同步校验时，优先复用以下纯函数：

- `get_payload_path(payload, "a.b.length")`
- `SyncMapping(name, selector, api_path, kind)`
- `compare_ui_snapshot(api_payload, ui_snapshot, mappings)`

新增页面的推荐步骤：

1. 先写 `tests/scripts/test_ui_sync_e2e_helpers.py` 中的字段映射单元测试。
2. 在 `scripts/smoke/ui_sync_e2e.py` 中新增一个浏览器步骤。
3. 每个步骤都返回 `{name, ok, mismatches}`，避免失败信息只存在日志里。
