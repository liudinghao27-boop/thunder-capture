## 人工测试环境搭建与数据准备记录

### 测试环境配置

- **操作系统**: Windows 11
- **Python**: 3.12.10
- **数据库**: PostgreSQL 14+ (通过 `THUNDER_DATABASE_URL` 配置)
- **缓存/任务队列**: Redis 6+ (通过 `REDIS_URL` 配置)
- **浏览器**: Chrome / Edge (自动检测)
- **Cookie 文件**: `data/douyin_cookies.json`

### 检查脚本

环境就绪检查脚本：`docs/qa/check_test_env.py`

```bash
python docs/qa/check_test_env.py
```

检查项：
1. 数据库连接及核心表（jobs, task_queue, industry_daily_quota）存在
2. Redis 连接
3. Cookie 文件有效性
4. 行业配置文件存在
5. Chrome/Edge 浏览器路径

### 测试数据准备脚本

测试数据准备脚本：`docs/qa/prepare_test_data.py`

```bash
python docs/qa/prepare_test_data.py
```

创建的测试行业：

| 行业 slug | 类型 | 关键词 | 对标账号 | 用途 |
|-----------|------|--------|----------|------|
| qa-test-keywords-only | 仅关键词 | 高考志愿 | 无 | TC-CS-01, TC-BD-02 |
| qa-test-target-only | 仅对标账号 | 无 | 占位 URL | TC-CS-02 |
| qa-test-combined | 组合 | 高考志愿 | 占位 URL | TC-CS-03, TC-BD-04 |
| qa-test-empty | 空配置 | 无 | 无 | TC-BD-01 |
| qa-test-invalid-target | 含无效账号 | 高考志愿 | 中文描述+URL | TC-BD-03 |

同时会创建 3 条历史空采集 Job，用于验证 `_recent_collect_failures` 的自动补充暂停逻辑。

### 环境搭建步骤

1. 确认 `.env` 中数据库和 Redis 配置正确
2. 启动 PostgreSQL 和 Redis 服务
3. 运行数据库迁移（如需要）：
   ```bash
   alembic upgrade head
   ```
4. 运行环境检查脚本：
   ```bash
   python docs/qa/check_test_env.py
   ```
5. 运行测试数据准备脚本：
   ```bash
   python docs/qa/prepare_test_data.py
   ```
6. 启动后端服务：
   ```bash
   uvicorn server.main:app --host 0.0.0.0 --port 8000
   ```
7. 启动 Celery Worker：
   ```bash
   celery -A adapters.celery.app worker --loglevel=info
   ```
8. 访问前端页面：`http://localhost:8000/`

### 环境与生产一致性说明

- 数据库 schema 与生产一致（通过 alembic 迁移）
- Cookie 使用真实抖音登录态（注意：测试环境需确保 Cookie 不过期）
- 行业配置与生产使用相同 YAML 结构
- 爬虫子进程使用与生产相同的 MediaCrawler 代码
- 日志保留路径 `data/mc_failures/` 与生产一致

### 注意事项

- 测试 Cookie 应与生产环境隔离，避免影响生产账号
- 测试期间频繁采集可能触发平台风控，建议每轮测试后间隔 10 分钟以上
- 沙箱环境无法通过抖音风控，部分 P0 用例需在真实网络/浏览器环境中执行
- 所有测试数据建议标记为 `qa-` 前缀，便于测试后清理
