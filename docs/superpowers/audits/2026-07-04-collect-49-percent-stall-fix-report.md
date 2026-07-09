# 采集任务 49% 卡死修复报告

## 问题结论

本次故障的核心根因是采集任务进入 `discover` 阶段后，后台会等待 MediaCrawler 子进程返回采集结果。旧实现直接 `await process.communicate()`，没有超时和强制退出机制；当抖音页面跳转、登录态异常、网络/代理异常、Playwright 页面长时间不返回时，worker 会一直卡在 discovery，前端只能看到进度心跳推进到上限 49%，且不会进入分类、去重、入队阶段，因此最终表现为“49% 卡死、0 条有效线索”。

## 执行链路

1. Web UI 发起采集任务。
2. API 创建 collect job。
3. `server.workers.run_collect_job()` 进入 `_collect()`。
4. 进度从 0% 到 12%，进入 `discover` 阶段。
5. `_discovery_heartbeat()` 每 20 秒推进 2%，最高只到 49%。
6. `core.discover.run_discovery()` 调用 MediaCrawler：
   - 关键词采集：`adapters.mediacrawler.runner.run_platform()`
   - 对标账号采集：`adapters.mediacrawler.runner.run_target_accounts()`
7. MediaCrawler 返回后才会进入 50% 以后的分类、队列入库、完成阶段。

因此，49% 不是分类或入库阶段，而是“正在等待外部采集子进程结束”的标志。

## 已确认问题

| 优先级 | 问题 | 判定依据 | 修复状态 |
| --- | --- | --- | --- |
| 高 | MediaCrawler 子进程无超时，可能无限等待 | 会阻断采集任务完成，导致前端长期停在 49% | 已修复 |
| 高 | 采集异常时 job 缺少结构化失败摘要 | 前端/日志无法区分空结果、超时、普通失败 | 已修复 |
| 中 | discovery 单测未 mock 对标账号采集分支 | 单测会误触发真实 MediaCrawler，增加误判 | 已修复 |
| 中 | 超时场景缺少自动化回归测试 | 后续容易再次引入 49% 卡死问题 | 已补测试 |

## 修复内容

### 1. MediaCrawler 子进程超时与强制退出

文件：`adapters/mediacrawler/runner.py`

- 新增默认超时时间：180 秒。
- 支持通过环境变量 `THUNDER_MEDIACRAWLER_TIMEOUT_SECONDS` 调整。
- 使用 `asyncio.wait_for(process.communicate(), timeout=...)` 包裹子进程等待。
- 超时后执行 `process.kill()` 并等待退出。
- 日志保留 workspace、cmd、耗时、stdout/stderr tail，便于定位页面、登录、网络、代理问题。

### 2. 采集 job 失败状态结构化

文件：`server/workers.py`

- 新增 `_collect_failure_summary()`。
- discovery 超时时设置：
  - `status=failed`
  - `progress=100`
  - `phase=discover_timeout`
  - `collect_summary.empty_reason=discovery_timeout`
- 普通采集失败设置：
  - `phase=collect_failed`
  - `collect_summary.empty_reason=collect_failed`
- 前端和接口可以直接显示失败原因，不再停留在运行中状态。

### 3. 自动化测试补充

文件：

- `tests/adapters/test_mediacrawler.py`
- `tests/server/test_workers.py`
- `tests/core/test_discover.py`

覆盖内容：

- MediaCrawler 子进程卡住时会被 timeout kill。
- collect job 遇到 discovery timeout 后会失败收口，不会继续卡 49%。
- discovery 单测不再误触发真实 MediaCrawler。
- 原有关键词/对标账号采集、空结果、有效线索入队路径保持可用。

## 二次验证结果

已执行验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\adapters\test_mediacrawler.py tests\server\test_workers.py tests\core\test_discover.py tests\core\test_classify.py tests\server\api\test_execution_views.py -q
```

结果：

```text
38 passed, 1 warning
```

已执行静态检查：

```powershell
.\.venv\Scripts\python.exe -m ruff check adapters\mediacrawler\runner.py server\workers.py tests\adapters\test_mediacrawler.py tests\server\test_workers.py tests\core\test_discover.py
```

结果：

```text
All checks passed!
```

已执行编译检查：

```powershell
.\.venv\Scripts\python.exe -m compileall adapters\mediacrawler\runner.py server\workers.py tests\adapters\test_mediacrawler.py tests\server\test_workers.py tests\core\test_discover.py
```

结果：通过。

## 仍需真实环境观察的点

本次修复保证任务不会再无限卡在 49%，并且能把失败原因结构化返回。但如果真实抖音采集仍然返回 0 条，需要继续根据新的失败摘要和 MediaCrawler 日志排查：

1. 抖音登录态是否有效。
2. 浏览器 CDP 是否连接成功。
3. 搜索关键词是否触发平台风控或空结果。
4. 对标账号 ID 是否为 MediaCrawler 支持的 sec_uid/creator_id 格式。
5. 页面结构变化是否导致 MediaCrawler JSONL 输出为空。

## 建议运行参数

真实测试时可先使用较短超时，便于快速发现异常：

```powershell
$env:THUNDER_MEDIACRAWLER_TIMEOUT_SECONDS="120"
```

稳定后可恢复默认 180 秒，或根据矩阵设备规模单独配置。
