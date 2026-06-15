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
├── server/                 # FastAPI 后台服务端 (设备管理、状态监控、安全过滤)
│   ├── api/                # 路由接口 (设备心跳监控、行业管理、统计面板)
│   ├── models/             # SQLAlchemy 数据模型
│   ├── schemas/            # Pydantic 请求/响应模型
│   ├── services/           # 服务层组件 (LLM 客户端创建与缓存)
│   ├── static/             # 后台单页控制台
│   ├── middleware.py       # 安全控制中间件 (速率限制、安全头防护)
│   └── main.py             # 后端应用主启动入口
├── engine/                 # 核心获客与发送控制引擎
│   ├── collectors/         # 数据采集模块 (Playwright & Crawl4AI 采集器)
│   │   ├── base.py         # 采集器基类与 Playwright 上下文初始化
│   │   ├── douyin.py       # 抖音视频及评论并行安全抓取
│   │   └── xiaohongshu.py  # 小红书博主增量与评论数据提取
│   ├── queue.py            # 任务队列模块 (WAL 机制、指数退避冷却过滤)
│   ├── sender.py           # 私信发送模块 (AutoGLM 手机模拟、智能话术生成)
│   ├── checkpoint.py       # 断点续传管理器 (Windows 平台安全文件替换)
│   ├── proxy.py            # 代理轮换模块 (线程安全代理切换)
│   └── config.py           # 行业配置安全解析 (路径防穿越限制)
├── scripts/                # 系统运维辅助脚本
│   ├── db/                 # 数据库维护、检查、迁移脚本
│   ├── device/             # ADB/设备辅助脚本
│   ├── diagnostics/        # 日志和运行状态诊断脚本
│   └── smoke/              # API/LLM 快速验证脚本
├── data/                   # 本地持久化数据与浏览器环境
│   ├── thunder.db          # 本地 SQLite WAL 数据库
│   ├── checkpoints/        # 任务断点缓存
│   └── ADBKeyboard.apk     # 自动化控制专用的 ADB 键盘服务
├── Open-AutoGLM/           # UI 自动化组件 (提供 Android/iOS 设备连接支持)
└── crawl4ai/               # 高效率 AI 网页抓取引擎 (本地扩展依赖)
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

您可以运行以下测试脚本以验证异步心跳、冷却机制、代理池轮换及智能 Prompt 功能的正常工作：
```bash
python "C:/Users/Administrator/.gemini/antigravity/brain/1e844de7-6a73-467e-a9c2-c0a31c9ae1e4/scratch/verify_optimizations.py"
```
