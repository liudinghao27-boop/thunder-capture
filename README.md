# 雷霆捕获系统 (Thunder Capture SaaS)

雷霆捕获系统是一款针对主流社交平台（抖音、小红书等）的社媒私域流量获客与自动化营销矩阵系统。系统能够精准采集目标行业视频下的评论线索，通过大模型（LLM）进行智能意图分类，并利用智谱 AutoGLM 等手机端自动化工具进行上下文感知的精准私信引流。

---

## 📂 项目结构目录

整理后的项目结构清晰、模块分明：

```
shemeihuoke/
├── cli.py                  # 命令行控制台入口 (采集、发送、状态统计)
├── config/                 # 系统与行业配置文件
│   ├── system.yaml         # 全局系统配置 (API 密钥、注册设备、限流阀值)
│   └── industries/         # 行业策略配置 (征兵咨询、高考志愿、装修获客等)
├── docs/                   # 项目文档中心
│   ├── README.md           #   文档索引与使用指南
│   └── superpowers/        #   研发管理文档 (设计/计划/SOP/审计/归档)
├── server/                 # FastAPI 后台服务端 (设备管理、状态监控、安全过滤)
│   ├── api/                # 路由接口 (auth/dashboard/agent/leads/industries/devices/jobs/stats)
│   ├── models/             # SQLAlchemy 数据模型
│   ├── schemas/            # Pydantic 请求/响应模型
│   ├── services/           # 服务层组件 (LLM 客户端/任务统计/迁移/导出)
│   ├── static/             # 后台单页控制台 (Vanilla JS + Tailwind)
│   ├── middleware.py       # 安全控制中间件 (速率限制、安全头防护)
│   ├── auth.py             # JWT 认证
│   └── main.py             # 后端应用主启动入口
├── core/                   # 核心获客与发送控制引擎
│   ├── agent/              #   PhoneAgent 执行/感知/记忆/规划
│   ├── classify.py         #   LLM 意图分类
│   ├── collectors/         #   数据采集模块 (抖音/小红书)
│   ├── device/             #   ADB 设备连接/心跳/监督
│   ├── strategy/           #   风控/防封/波次/节流策略
│   ├── task/               #   任务图编排/调度/Worker
│   ├── vision/             #   截图/OCR/UI 树解析
│   ├── proxy.py            #   代理轮换模块
│   ├── discover.py         #   评论发现编排
│   └── config.py           #   系统配置 & 行业配置解析
├── adapters/               # 外部服务适配层
│   ├── dify/               #   Dify AI 工作流客户端
│   ├── postgres/           #   PostgreSQL 连接与 Alembic 迁移
│   ├── celery/             #   Celery 任务队列 (采集/分类/发送)
│   └── mediacrawler/       #   MediaCrawler 子进程封装
├── deps/                   # 外部依赖源码 (统一管理)
│   ├── MediaCrawler/       #   NanmiCoder/MediaCrawler
│   ├── Open-AutoGLM/       #   THU/Open-AutoGLM
│   └── crawl4ai/           #   Crawl4AI 网页抓取引擎
├── scripts/                # 系统运维辅助脚本
│   ├── db/                 # 数据库维护、检查、迁移脚本
│   ├── device/             # ADB/设备辅助脚本
│   ├── diagnostics/        # 日志和运行状态诊断脚本
│   └── smoke/              # API/LLM 快速验证脚本
├── data/                   # 本地持久化数据与浏览器环境 (gitignored)
│   ├── thunder.db          # 本地 SQLite WAL 数据库
│   ├── checkpoints/        # 任务断点缓存
│   └── ADBKeyboard.apk     # 自动化控制专用的 ADB 键盘服务
├── logs/                   # 运行日志 (gitignored)
├── pyproject.toml          # 项目元数据 & 依赖声明
├── start_system.bat        # Windows 启动脚本
├── stop_system.bat         # Windows 停止脚本
├── .env / .env.example     # 环境变量
├── README.md
└── PROJECT_STRUCTURE.md    # 详细项目结构说明
```

---

## ⚡ 核心功能特性

1. **多端并行与错误隔离**：抖音评论抓取采用 `Promise.all` 并行处理，且单条抓取失败自动降级隔离，确保任务不因单点网络限流而中断。
2. **防封号指数退避冷却**：在任务重试时，根据已失败次数自动计算冷却时长（如第 1 次冷却 5 分钟，第 2 次冷却 15 分钟），系统仅会申领已经度过冷却期的任务，保护营销账号安全。
3. **网络请求隐蔽与代理池轮换**：无缝对接 `system.yaml` 中的 `proxies` 属性，利用 `ProxyRotator` 对 Playwright 和 Crawl4AI 进行全局代理 IP 轮换，支持用户名密码认证。
4. **异步非阻塞设备心跳**：后台对移动设备的 ADB 心跳监测全面更改为 `asyncio` 子进程模型，避免传统阻塞式 IO 造成的高并发 FastAPI 事件循环死锁。
5. **上下文感知的高级 AI 智能回复**：利用 LLM 意图分类数据，针对每条线索注入细分领域（Category）、提问重点（Question）、推荐主题（Reply Topic），生成的私信文案更具亲和力与针对性。

---

## 🔧 快速开始

### 1. 环境依赖安装
在项目根目录，安装核心与后台依赖：
```bash
pip install -r requirements.txt
pip install -r requirements-server.txt

# 安装 AutoGLM 手机控制模块 (以可编辑模式安装)
cd Open-AutoGLM
pip install -e .
cd ..
```

### 2. 系统配置
1. 复制 `.env.example` 为 `.env` 并填写您的 DeepSeek 或智谱大模型 API Key：
   ```env
   THUNDER_DEEPSEEK_KEY=your_key_here
   THUNDER_ZHIPU_KEY=your_key_here
   ```
2. 复制 `config/system.example.yaml` 为 `config/system.yaml`，配置您的连接设备 ADB 序列号、轮换代理池：
   ```yaml
   api_keys:
     deepseek: "${THUNDER_DEEPSEEK_KEY}"
     zhipu: "${THUNDER_ZHIPU_KEY}"

   proxies:
     - http://user:pass@proxy1:port
     - http://user:pass@proxy2:port
   ```

---

## 🚀 运行使用

### 启动 FastAPI 服务端
启动用于管理设备及查看数据的后台 API 服务：
```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

### 控制台 CLI 常用命令

* **查看系统运行状态与设备队列统计**：
  ```bash
  python cli.py stats
  ```
* **执行一次完整的 采集 + AI分类 + 自动回复 流程**：
  ```bash
  # 对 "recruitment" (征兵行业) 执行全套流程
  python cli.py run -i recruitment
  ```
* **定时自动循环采集**：
  ```bash
  # 每 60 分钟自动增量采集一次数据
  python cli.py collect -i recruitment --loop 60
  ```
* **手动重置/清空本地数据库**：
  ```bash
  python scripts/db/reset_db.py
  ```

---

## 🧪 自动化测试验证

运行 pytest 验证核心业务逻辑、API 路由与适配器：

```bash
python -m pytest tests/ -q
```

其他常用检查：

```bash
# 代码风格检查
python -m ruff check server/ core/ tests/ adapters/ cli.py

# 类型检查
python -m mypy server/ core/ adapters/ cli.py --ignore-missing-imports

# 数据库迁移验证
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic upgrade head
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic check
```
