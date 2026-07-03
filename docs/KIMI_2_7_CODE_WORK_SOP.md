# Kimi 2.7 Code 执行工作 SOP

## 项目目标

将当前项目继续升级为 **AI Agent 驱动的多设备智能执行矩阵系统**。

当前重点不是做新功能堆叠，而是先把已经开始的 Web UI 重构和后端状态链路收口，保证：

- 前后端接口一致
- Web UI 操作路径清晰
- 首页总览能给出唯一下一步动作
- 任务状态、设备状态、线索状态可追踪
- 后续可以稳定扩展到 30 台设备矩阵执行

---

## 当前代码状态

当前已有部分改动尚未最终完成，重点文件包括：

- `server/api/dashboard.py`
- `server/static/index.html`
- `server/static/js/dashboard.js`
- `tests/server/api/test_dashboard.py`
- `tests/server/api/test_static_modules.py`
- `tests/server/api/test_ops_commander_contract.py`

当前已知测试状态：

```bash
python -m pytest tests/server/api/test_dashboard.py tests/server/api/test_static_modules.py tests/server/api/test_ops_commander_contract.py -q
```

当前应重点修复的失败项：

- 导航命名未完全符合契约
- 首页总览单一主按钮 `overview-primary-action` 未完全落地
- 旧双按钮 `overview-btn-collect` / `overview-btn-send` 需要彻底移除
- onboarding 弹窗逻辑需要彻底删除或折叠为首页状态引导

---

## 总体执行原则

1. 不要重写整个项目。
2. 不要大规模改目录结构。
3. 不要破坏已有 API 路由。
4. 优先让现有测试通过。
5. 每完成一个阶段都必须运行对应测试。
6. 修复 UI 时要以客户经理使用视角为准：用户进入首页后必须知道下一步做什么。
7. 矩阵设备能力先打基础，不要一次性写完复杂调度系统。

---

## 阶段 1：Web UI 重构收口

### 目标

让当前 Web UI 的「首页总览 / 执行指挥台」完成契约测试。

### 需要完成

#### 1. 修复左侧主导航命名

保留现有 route id，不要改路由 key，只改显示名称。

必须匹配：

| route id | 显示名称 |
|---|---|
| `overview` | `首页总览` |
| `industries` | `项目中心` |
| `devices` | `设备中心` |
| `tasks` | `线索中心` |
| `jobs` | `任务中心` |
| `settings` | `系统设置` |

验收点：

```bash
python -m pytest tests/server/api/test_ops_commander_contract.py -q
```

其中 `test_primary_navigation_uses_business_labels` 必须通过。

#### 2. 首页总览改成单一主按钮

必须新增：

```html
id="overview-primary-action"
```

必须移除：

```html
id="overview-btn-collect"
id="overview-btn-send"
```

单一主按钮根据当前状态自动切换：

- 未创建项目：创建项目
- 未配置 LLM：去系统设置
- 未接入设备：去设备中心
- 无待发送线索：开始采集
- 有任务执行中：查看任务中心
- 已具备条件：开始发送

相关逻辑应集中在：

```text
server/static/js/dashboard.js
```

页面内 `index.html` 只负责调用 `window.DashboardUi` 返回的结果并渲染。

#### 3. 增加执行阶段列表

首页总览需要有：

```html
id="overview-stage-list"
```

用于展示：

- 项目配置
- 设备接入
- 采集线索
- 发送任务

#### 4. 删除 onboarding 弹窗

必须移除：

```html
id="modal-onboarding"
```

必须移除相关 JS：

```javascript
startOnboarding()
ONBOARDING_STEPS
nextOnboardingStep()
prevOnboardingStep()
skipOnboarding()
```

首次使用提示应放在首页总览状态说明中，不要再用弹窗遮挡操作。

### 阶段 1 验收命令

```bash
python -m pytest tests/server/api/test_dashboard.py tests/server/api/test_static_modules.py tests/server/api/test_ops_commander_contract.py -q
```

目标：

```text
全部通过
```

---

## 阶段 2：后端 Dashboard 状态链路收口

### 目标

`/api/dashboard/state` 成为首页总览的结构化状态来源。

### 已有方向

后端需要返回结构化字段：

```json
{
  "has_llm": true,
  "can_collect": true,
  "can_send": false,
  "next_action": "...",
  "lead_inventory": {},
  "device_matrix": {},
  "active_jobs": [],
  "has_active_job": false,
  "warnings": []
}
```

### 需要确认

1. `has_llm` 不能从 `warnings` 文案推导。
2. 前端不能再出现：

```javascript
warnings.every(...)
```

3. LLM 可用性应从结构化来源判断：

- 环境变量
- 用户密钥
- system.yaml 配置

### 阶段 2 验收命令

```bash
python -m pytest tests/server/api/test_dashboard.py -q
```

目标：

```text
全部通过
```

---

## 阶段 3：任务执行链路稳定性

### 目标

解决 Web UI 显示任务完成，但真实手机端没有动作的问题。

### 核查路径

#### 1. 任务创建

检查：

- Web 是否真的调用发送任务 API
- 后端是否创建 job
- job payload 是否包含 industry、devices、limit、mode 等必要参数

#### 2. worker 是否启动

检查：

- job 状态是否从 `pending` 进入 `running`
- worker 日志是否出现该 job_id
- 是否进入设备锁定逻辑

#### 3. 设备识别

检查：

- ADB 是否能识别真实设备
- 设备是否进入 `idle`
- `keyboard_ready` 是否为 true
- ADB keyboard 是否自动安装和启用

#### 4. 手机动作

检查：

- 是否打开目标 App
- 是否进入私信页面
- 是否输入文本
- 是否点击发送
- 是否保存截图证据

#### 5. 任务结束

检查：

- 成功时 lead 状态是否变为 done
- 失败时 lead 状态是否变为 failed
- 已发送时间是否记录为发送成功时间，而不是采集时间

---

## 阶段 4：取消 / 暂停任务能力

### 目标

点击取消后，任务必须真正停止，不只是 UI 变状态。

### 必须实现

1. Web 点击取消
2. 后端写入 `cancel_requested`
3. worker 循环检测取消标记
4. 当前设备停止继续发送
5. job 状态变为 `cancelled`
6. 设备释放为 `idle` 或异常隔离
7. 日志记录取消来源

### 验收方式

人工测试：

1. 创建发送任务
2. 手机开始执行
3. 点击取消
4. 观察手机是否停止后续动作
5. 查看 job 状态是否为 cancelled
6. 查看日志是否有 cancel_requested

---

## 阶段 5：线索池功能补齐

### 目标

让线索池状态分类准确，失败线索可重新发送。

### 必须检查

1. 未发送列表只显示 pending
2. 已发送列表只显示 done
3. 失败列表只显示 failed
4. 已发送时间显示发送成功时间
5. 失败列表支持单条重发
6. 失败列表支持一键重发
7. 一键重发不能重复发送已成功线索

### 验收方式

人工测试：

1. 制造一条 failed 线索
2. 在失败栏看到该线索
3. 点击单条重发
4. 点击一键重发
5. 确认状态从 failed 重新回到 pending 或直接创建新发送任务

---

## 阶段 6：采集系统升级

### 目标

提高采集结果准确度，并为多平台独立采集器做准备。

### 必须实现

1. 对标账号持久化
2. 重启后仍能读取对标账号
3. 每次采集读取当前项目的对标账号
4. 每次采集同时支持关键词搜索新目标线索
5. 采集结果进入线索池
6. 采集结果去重
7. 关键词漏斗可解释

### 平台策略

平台采集器应独立：

- 抖音采集器
- 快手采集器
- 视频号采集器
- 小红书采集器

同一时间只允许选择一个平台采集，不做跨平台并发采集。

---

## 阶段 7：30台设备矩阵执行基础

### 目标

从单设备执行升级为多设备调度。

### 设备状态

设备池至少支持：

- `idle`
- `running`
- `cooldown`
- `offline`
- `isolated`

### 调度规则

1. 自动选择 idle 设备
2. 每台设备独立领取线索
3. 每台设备独立记录进度
4. 单设备失败不影响全局任务
5. 设备异常自动隔离
6. 支持全局每日上限
7. 支持单设备每日上限
8. 支持发送间隔和随机延迟

### 风控策略

必须支持：

- 单设备每日上限
- 全局每日上限
- 每小时上限
- 发送间隔
- 失败熔断
- 设备冷却
- 账号隔离

---

## 阶段 8：截图 / OCR / UI解析驱动决策

### 目标

形成真正的 AI Agent 设备执行闭环。

### 必须能力

1. 每个关键步骤截图
2. OCR 识别当前页面文字
3. 判断当前页面状态
4. 判断是否出现风控弹窗
5. 判断是否登录失效
6. 判断是否发送成功
7. 根据状态决定下一步动作
8. 失败时保存证据

### Agent 决策输出

每一步至少输出：

```json
{
  "page_state": "chat_input_ready",
  "confidence": 0.92,
  "next_action": "input_message",
  "reason": "识别到输入框和发送按钮",
  "screenshot": "..."
}
```

---

## 阶段 9：完整测试 SOP

### 自动测试

```bash
python -m pytest tests/server/api -q
```

### UI 契约测试

```bash
python -m pytest tests/server/api/test_static_modules.py tests/server/api/test_ops_commander_contract.py -q
```

### Dashboard 测试

```bash
python -m pytest tests/server/api/test_dashboard.py -q
```

### 人工测试清单

1. 启动程序
2. 打开 Web UI
3. 注册新账号
4. 登录
5. 创建项目
6. 输入关键词
7. 输入对标账号
8. 保存项目
9. 重启程序确认项目仍存在
10. 启动采集
11. 查看采集日志
12. 查看线索池是否入库
13. 检查去重
14. 连接真实手机
15. 检查设备识别
16. 检查 ADB keyboard
17. 启动发送任务
18. 观察手机是否真实动作
19. 点击取消
20. 确认任务停止
21. 查看失败线索
22. 执行一键重发
23. 查看任务日志
24. 查看截图证据

---

## 当前最高优先级

### P0

1. 修复 UI 契约测试剩余失败项
2. 首页总览改为单一主按钮
3. 删除旧 onboarding 弹窗
4. 保证 dashboard/static/ops commander 测试通过

### P1

1. 真实设备发送链路
2. 取消任务真实停止
3. 失败重发
4. 已发送时间修正

### P2

1. 采集精准度和去重
2. 多平台独立采集器
3. 对标账号资料库

### P3

1. 30台设备矩阵调度
2. OCR/UI解析
3. AI Agent 决策闭环

---

## 给 Kimi 2.7 Code 的执行要求

1. 先跑测试，不要直接改。
2. 先修 P0，确保 UI 契约测试全绿。
3. 每次只改相关文件，不要重构无关模块。
4. 修一个问题跑一次对应测试。
5. 不要删除用户已有配置和数据文件。
6. 不要使用 `git reset --hard`。
7. 所有改动完成后给出：
   - 修改文件列表
   - 测试命令
   - 测试结果
   - 仍未完成项
   - 下一步建议

