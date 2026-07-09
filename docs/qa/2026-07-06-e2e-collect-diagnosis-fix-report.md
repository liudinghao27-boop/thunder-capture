# 2026-07-06 端到端采集故障排查与修复报告

## 一、全链路节点

当前采集链路为：

1. Web/API 创建行业项目与采集任务。
2. `server.workers.run_collect_job` 创建后台任务，进度进入 `discover`。
3. `core.discover.run_discovery` 启动 ShadowBrowser，并准备独立 MediaCrawler 工作区。
4. `adapters.mediacrawler.runner.run_platform` 调用 MediaCrawler 子进程执行抖音搜索采集。
5. MediaCrawler 写出 `data/douyin/jsonl/*_comments_*.jsonl`。
6. 适配器解析 JSONL 为候选评论。
7. `classify_batch` 对候选评论做意向分类。
8. `enqueue_classified_result` 将通过分类的线索写入队列。
9. Job 摘要回写 `collect_summary`，前端通过任务状态接口展示。

## 二、确认根因

本轮排查确认，采集持续失败不是单一“完全没有数据”，而是两个问题叠加：

1. MediaCrawler 已经采到 JSONL，但后续子进程超时或登录入口异常导致退出码非 0，外层适配器直接抛错，未解析已生成的 JSONL。
2. 抖音登录入口点击逻辑依赖 `//p[text()='登录']` 精确匹配，页面结构变化或按钮文本变成“登录 / 注册”等形式时会失败。

历史失败工作区验证：

- `data/mc_failures/thunder_mc_6deby2jy_1783325261_error_attempt1` 中存在 `search_comments_2026-07-06.jsonl`。
- 使用修复后的解析逻辑可从该失败现场解析出 284 条评论。

## 三、修复内容

### 1. 失败后回收已生成 JSONL

文件：`adapters/mediacrawler/runner.py`

- 新增 `MediaCrawlerProcessError` 和 `MediaCrawlerTimeoutError`，在子进程失败/超时时保留 stdout、stderr、工作区路径。
- 子进程失败工作区移动到 `data/mc_failures/` 后，将异常对象的 `workspace` 指向保留目录。
- `run_platform` 与 `run_target_accounts` 在失败/超时后尝试解析保留工作区中的 JSONL。
- 如果解析到评论，则记录 warning 并返回候选评论，不再让整个采集任务直接失败。
- 失败工作区中的 JSONL 不删除，保留作证据。

### 2. Windows 输出编码兼容

文件：`adapters/mediacrawler/runner.py`

- 新增 `_decode_process_output`，优先 UTF-8，失败后回退 GB18030。
- 避免日志中“登录按钮未找到”等中文变成乱码，便于定位真实失败原因。

### 3. 抖音登录入口识别增强

文件：`deps/MediaCrawler/media_platform/douyin/login.py`

- 新增 `_click_login_entry`：
  - 先尝试多个 Playwright selector。
  - 再用 DOM fallback 扫描 `button/a/p/span/div/[role=button]`。
  - 支持“登录”“登录 / 注册”“立即登录”“扫码登录”“验证码登录”“手机号登录”等文本变体。
- 新增 `_login_page_snapshot`：
  - 登录入口仍找不到时，在异常中带上页面文本快照，方便下次定位。

### 4. 采集失败语义化摘要

文件：`server/workers.py`

- `_collect_failure_summary` 增加 `crawler_login_required` 分类。
- 登录/Cookie/二维码相关失败会提示刷新 `data/douyin_cookies.json` 或重新完成会话登录。

### 5. 顺手修复发送任务缩进错误

文件：`server/workers.py`

- 修复 `run_send_job` 中 `_maybe_auto_replenish` / `_send` 作用域错位问题。
- 该问题会导致静态检查报 `industry_cfg/job_id/device_ids` 未定义，影响发送任务稳定性。

## 四、验证结果

### 自动化测试

执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\adapters\test_douyin_login.py tests\adapters\test_mediacrawler.py tests\core\test_discover.py tests\server\test_workers.py tests\server\api\test_jobs_status.py -q
```

结果：

```text
44 passed
```

执行：

```powershell
.\.venv\Scripts\python.exe -m ruff check adapters\mediacrawler\runner.py server\workers.py tests\adapters\test_mediacrawler.py tests\adapters\test_douyin_login.py tests\server\test_workers.py deps\MediaCrawler\media_platform\douyin\login.py
```

结果：

```text
All checks passed
```

执行：

```powershell
.\.venv\Scripts\python.exe -m compileall adapters\mediacrawler server\workers.py core\discover.py deps\MediaCrawler\media_platform\douyin\login.py tests\adapters\test_mediacrawler.py tests\adapters\test_douyin_login.py tests\server\test_workers.py
```

结果：编译通过。

### 真实采集验证

验证 1：历史失败现场回收。

- 输入：`data/mc_failures/thunder_mc_6deby2jy_1783325261_error_attempt1`
- 结果：解析出 284 条评论。

验证 2：真实 discovery 链路，设置 `THUNDER_MEDIACRAWLER_TIMEOUT_SECONDS=75`。

- MediaCrawler 两次 75 秒超时。
- 第二次失败工作区保留到 `data/mc_failures/thunder_mc_z2bdh3m0_1783326734_timeout_attempt1`。
- 修复后的外层逻辑从失败工作区回收 70 条评论，并返回给 discovery。

验证 3：真实后台 collect job，设置 `THUNDER_MEDIACRAWLER_TIMEOUT_SECONDS=75`。

- Job 进度从 `discover` 推进到 `classify`，最终内存状态 `done`。
- `collect_summary.candidate_comments = 69`。
- 本次 smoke 使用临时用户 `codex-smoke`，数据库中不存在该用户，因此 Job 持久化出现外键报错；正式 Web UI 登录用户不会触发该测试用户问题。
- 本次 smoke 禁用了 LLM，分类通过数为 0，因此未入队。采集候选评论链路已验证恢复。

## 五、结论

本轮已修复导致“已采集但没有进线索池前置阶段”的核心问题：MediaCrawler 失败/超时后不再直接丢弃已生成 JSONL。

当前可确认：

- 后端采集可以从真实抖音搜索结果中拿到评论数据。
- 子进程超时/异常时可以回收已生成评论。
- 进度不会长期卡在 49%，会继续进入分类阶段。
- 如果完全卡在登录，会给出 `crawler_login_required`，而不是泛化失败。

仍需注意：

- 外部平台采集无法承诺永久 100% 成功，抖音登录态、风控、页面结构、IP 环境都会变化。
- 当前真实 smoke 禁用 LLM 后分类通过数为 0；要验证最终入队，需要使用正式登录用户、有效行业配置和可用 LLM/关键词漏斗。
