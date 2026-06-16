# 雷霆捕获系统 v0.2 — 重构后项目结构

## 架构总览

```
shemeihuoke/
│
├── core/                         # ★ 业务核心引擎 (原 engine/)
│   ├── collectors/               #   平台采集器 (抖音/小红书爬虫)
│   ├── classify.py               #   LLM 意图分类 (待迁入 Dify)
│   ├── agent/                    #   PhoneAgent 执行/感知/记忆/规划
│   ├── device/                   #   ADB 设备连接/心跳/监督
│   ├── strategy/                 #   风控/防封/波次/节流策略
│   ├── task/                     #   任务图编排/调度/Worker
│   ├── vision/                   #   截图/OCR/UI 树解析
│   ├── proxy.py                  #   代理轮换 (线程安全)
│   ├── discover.py               #   评论发现编排 (→ 迁入 adapters)
│   ├── config.py                 #   系统配置 & 行业配置解析
│   └── session.py, browser_orchestrator.py, ...
│
├── adapters/                     # ★ 外部服务适配层 (NEW — 按优先级)
│   ├── dify/                     #   [P1] Dify AI 工作流客户端
│   │   ├── client.py             #     HTTP API 封装
│   │   └── __init__.py           #     配置说明
│   ├── postgres/                 #   [P2] PostgreSQL 迁移
│   │   ├── connection.py         #     连接工厂 (SQLite → PG)
│   │   ├── migrations/           #     Alembic 迁移脚本
│   │   └── __init__.py           #     迁移指南
│   ├── celery/                   #   [P3] Celery 任务队列
│   │   ├── app.py                #     Celery 应用 & Redis 配置
│   │   ├── collect.py            #     采集任务定义
│   │   ├── classify.py           #     分类任务定义 (含 Dify 回退)
│   │   └── send.py               #     私信发送任务定义
│   └── mediacrawler/             #   MediaCrawler 封装
│       ├── runner.py             #     子进程编排 & JSONL 解析
│       └── __init__.py
│
├── server/                       # FastAPI 服务端
│   ├── api/                      #   路由: auth/dashboard/agent/leads/
│   │   │                        #        industries/devices/jobs/stats
│   ├── models/                   #   SQLAlchemy 模型 (待 PG 方言增强)
│   ├── schemas/                  #   Pydantic 请求/响应模型
│   ├── services/                 #   LLM 客户端工厂/任务统计/迁移
│   ├── static/                   #   Web 控制台 (Vanilla JS SPA)
│   ├── middleware.py             #   安全头 + 速率限制
│   ├── auth.py                   #   JWT 认证
│   ├── config.py                 #   CORS 配置
│   ├── main.py                   #   FastAPI 入口
│   └── workers.py                #   后台自动恢复
│
├── deps/                         # ★ 外部依赖 (统一管理)
│   ├── MediaCrawler/             #   NanmiCoder/MediaCrawler
│   ├── Open-AutoGLM/             #   THU/Open-AutoGLM
│   └── crawl4ai/                 #   Crawl4AI 网页抓取引擎
│
├── config/                       # 系统 & 行业配置
│   ├── system.yaml               #   全局配置 (API Key/代理/设备)
│   ├── system.example.yaml
│   └── industries/               #   行业模板
│       ├── _template.yaml
│       ├── recruitment.yaml
│       ├── gaokao.yaml
│       └── renovation.yaml
│
├── requirements/                 # ★ 分层依赖文件 (NEW)
│   ├── base.txt                  #   核心依赖 (原 requirements.txt)
│   ├── server.txt                #   FastAPI + 认证 (原 requirements-server.txt)
│   └── adapters.txt              #   适配器依赖 (Dify/PG/Celery)
│
├── scripts/                      # 运维脚本
│   ├── db/                       #   数据库维护/迁移/检查
│   ├── device/                   #   ADB 设备辅助 + 手动登录
│   ├── diagnostics/              #   日志诊断 + 手动登录
│   └── smoke/                    #   API/LLM 快速验证
│
├── data/                         # 运行时数据 (gitignored)
│   ├── thunder.db                #   本地 SQLite
│   ├── ADBKeyboard.apk           #   ADB 输入法
│   ├── chrome_data/              #   浏览器持久化
│   └── checkpoints/              #   断点续传缓存
│
├── logs/                         # 运行日志 (gitignored)
│
├── cli.py                        # CLI 入口 (collect/send/stats/run)
├── pyproject.toml                # 项目元数据 & 依赖声明
├── start_system.bat              # Windows 启动脚本
├── stop_system.bat               # Windows 停止脚本
├── .env / .env.example           # 环境变量
├── README.md
└── PROJECT_STRUCTURE.md          # 本文件
```

## 模块边界

| 层 | 职责 | 依赖方向 |
|----|------|---------|
| `core/` | 纯业务逻辑，不依赖基础设施 | `core/` ← 无外部依赖 |
| `adapters/` | 外部服务抽象，隔离 I/O | `adapters/` → 外部 API/DB |
| `server/` | HTTP 层，编排 core + adapters | `server/` → `core/` + `adapters/` |
| `deps/` | 第三方源码，不修改 | `deps/` ← 独立版本 |

## 运行入口

| 入口 | 路径 | 端口 |
|------|------|------|
| FastAPI | `server/main.py` | `http://127.0.0.1:8000` |
| Web 控制台 | `server/static/index.html` | 同源访问 |
| CLI 采集 | `python cli.py collect -i <industry>` | — |
| CLI 发送 | `python cli.py send -i <industry>` | — |
| Celery Worker | `celery -A adapters.celery.app worker -l info` | — |
| Flower 监控 | `celery -A adapters.celery.app flower` | `http://:5555` |

## API 路由

| 路径 | 模块 | 说明 |
|------|------|------|
| `/api/auth/*` | `server/api/auth.py` | 注册/登录/JWT |
| `/api/dashboard/*` | `server/api/dashboard.py` | 控制中心聚合 |
| `/api/industries/*` | `server/api/industries.py` | 行业 CRUD |
| `/api/devices/*` | `server/api/devices.py` | 设备管理 |
| `/api/leads/*` | `server/api/leads.py` | 线索统计 |
| `/api/jobs/*` | `server/api/jobs.py` | 任务执行记录 |
| `/api/stats/*` | `server/api/stats.py` | 全局统计 |
| `/api/agent/*` | `server/api/agent.py` | Agent 调试 |
| `/api/system/health` | `server/main.py` | 系统健康检查 |

## 重构优先级路线图

### P1: Dify 集成 (解耦 Prompt 与代码) ✅ COMPLETE
- [x] `adapters/dify/client.py` — Dify HTTP 客户端 (生产级，含重试/批处理/结果归一化)
- [x] `adapters/dify/workflow-template.yml` — Dify 工作流导入模板
- [x] `core/classify.py` — 重构为 ClassificationRouter 架构:
       DifyBackend → DirectLLMBackend 自动回退
- [x] 提取 `ClassificationBackend` 抽象基类
- [x] 保留 `_BATCH_CLASSIFY_HEADER/_FOOTER` 在 DirectLLMBackend 内 (私有化)
- [x] `classify_batch()` 签名保持向后兼容
- [x] `.env.example` 新增 Dify 配置项
- [x] adapters/dify/__init__.py 已更新部署说明
- [ ] 部署 Dify 并导入 workflow-template.yml (需运维操作)

### P2: PostgreSQL 迁移 ✅ COMPLETE
- [x] `adapters/postgres/connection.py` — PG 连接工厂
- [x] `docker-compose.yml` — PostgreSQL 16 + Redis 7
- [x] `THUNDER_DATABASE_URL` → `.env` 指向 Docker PG
- [x] `server/models/` → 16 张表自动创建于 PostgreSQL
- [x] `skip_locked` 现在在 PG 上真正生效
- [x] Alembic 初始化完成，初始迁移脚本已生成并测试

### P3: Celery + Redis ✅ 基础设施就绪
- [x] Redis 7 运行中 (Docker, port 6379, healthcheck OK)
- [x] `adapters/celery/app.py` — Celery 配置 & 路由 & 任务队列
- [x] `adapters/celery/collect.py` — collect pipeline
- [x] `adapters/celery/classify.py` — classify pipeline (含 Dify 回返)
- [x] `adapters/celery/send.py` — send pipeline (rate_limit 15/h per device)
- [x] `send_dm_task` 已接入 `DeviceWorker.run()`
- [ ] 启动 Celery Worker: `celery -A adapters.celery.app worker -l info -Q collect,classify,send` (需 Docker 运行)

### P3: 定时发送 + 效果追踪 ✅ COMPLETE
- [x] 发送时段门控 (`core/strategy/policy.py`)
- [x] 周末暂停 / 单日最大发送量
- [x] Celery Beat 定时调度
- [x] TaskQueue 效果状态扩展
- [x] 手动标记已回复 / 已转化 API
- [x] 效果统计 API
- [x] 效果事件 Webhook
- [x] 前端发送时段、线索效果列、指标卡片

### P4: Web 控制台 (已完整，非紧急)
- [x] 6 页面 SPA (控制中心/项目/设备/线索/记录/设置)
- [ ] 可选项: 分离前后端 → 独立 Vue/React 前端 + Vite

### P4: 关键词报表 + A/B Test ✅ COMPLETE
- [x] `server/services/analytics.py` — 关键词/设备效果聚合
- [x] `server/services/abtest.py` — A/B 变体选择 + 结果统计
- [x] `Industry.reply_variants` + `TaskQueue.reply_variant_id`
- [x] `GET /api/stats/keywords` 关键词效果 API
- [x] `GET /api/stats/devices` 设备效果 API
- [x] A/B 变体 CRUD + 结果 API
- [x] `DeviceWorker` 发送时自动选择变体并记录
- [x] 前端"关键词效果"和"A/B 实验"页面

