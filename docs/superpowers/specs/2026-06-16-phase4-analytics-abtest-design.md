# Phase 4 设计：关键词报表 + A/B Test

> **阶段**: 4 / 6  
> **主题**: 关键词报表 + 文案 A/B Test  
> **依据**: `C:/Users/Administrator/Desktop/雷霆捕获系统_客户使用习惯审计报告.md`  
> **前置依赖**: Phase 3（定时发送 + 效果追踪）已完成  
> **状态**: 已批准，待实施

---

## 1. 目标

基于 Phase 3 积累的效果数据，帮助客户优化关键词和私信文案，提升 ROI。

具体目标：
1. 提供按 `source_keyword` 统计的**关键词效果报表**（曝光/采集/发送/回复/转化）。
2. 支持项目级**文案 A/B Test**：配置多个回复变体，随机分组发送，自动对比回复率/转化率。
3. 在前端增加"关键词效果"页面和"A/B 实验"管理界面。

---

## 2. 范围

### 2.1 包含

- 新增 `server/services/analytics.py`：关键词/文案/设备聚合查询。
- 新增 `server/services/abtest.py`：A/B 分组算法、变体选择、结果统计。
- 扩展 `Industry` 模型：支持 `reply_variants` 字段。
- 扩展 `TaskQueue`：记录 `reply_variant_id`。
- 新增 API：
  - `GET /api/stats/keywords?industry_slug=...&days=...`
  - `GET /api/stats/devices?industry_slug=...&days=...`
  - `POST /api/industries/{id}/abtest/variants`
  - `DELETE /api/industries/{id}/abtest/variants/{variant_id}`
  - `GET /api/industries/{id}/abtest/results`
- 修改 `DeviceWorker._generate_reply()`：根据 A/B 分组选择变体文案。
- 前端新增"关键词效果"和"A/B 实验"页面。
- 相关测试。

### 2.2 不包含

- 设备效能对比（本次只做 API，UI 放到后续）。
- 行业趋势分析 / 竞品监控（超出 Phase 4 范围）。
- 自动推荐胜出文案后的自动切换（本阶段只展示结果）。

---

## 3. 数据模型变更

### 3.1 `sa_industries` 扩展

```python
reply_variants = Column(JSON, default=list)  # [{id, name, tone, style, hook, weight, enabled}]
```

### 3.2 `sa_task_queue` 扩展

```python
source_keyword = Column(String(128), default="", index=True)  # 已存在，本次强化索引
reply_variant_id = Column(String(64), default="", index=True)
```

### 3.3 `IndustryConfig` 扩展

```python
reply_variants: list[dict] = field(default_factory=list)
```

---

## 4. API 设计

### 4.1 关键词效果报表

```http
GET /api/stats/keywords?industry_slug=recruitment&days=7
```

响应：

```json
{
  "industry_slug": "recruitment",
  "days": 7,
  "keywords": [
    {
      "keyword": "当兵",
      "collected": 120,
      "sent": 45,
      "replied": 8,
      "converted": 2,
      "reply_rate": 0.178,
      "conversion_rate": 0.044
    }
  ]
}
```

### 4.2 A/B 变体管理

```http
POST /api/industries/{industry_id}/abtest/variants
Content-Type: application/json

{
  "name": "正式版",
  "reply_tone": "退伍老兵",
  "reply_style": "稳重可靠",
  "reply_hook": "需要的话我可以帮你分析入伍条件",
  "weight": 50
}
```

```http
DELETE /api/industries/{industry_id}/abtest/variants/{variant_id}
```

### 4.3 A/B 实验结果

```http
GET /api/industries/{industry_id}/abtest/results?days=7
```

响应：

```json
{
  "industry_id": "i1",
  "variants": [
    {
      "id": "v1",
      "name": "默认版",
      "sent": 60,
      "replied": 6,
      "converted": 1,
      "reply_rate": 0.10,
      "conversion_rate": 0.017
    },
    {
      "id": "v2",
      "name": "热情版",
      "sent": 60,
      "replied": 12,
      "converted": 3,
      "reply_rate": 0.20,
      "conversion_rate": 0.05
    }
  ],
  "winner": "v2"
}
```

---

## 5. 核心逻辑

### 5.1 关键词聚合

```python
def aggregate_by_keyword(industry_slug: str, days: int = 7) -> list[dict]:
    base = db.query(TaskQueue).filter(
        TaskQueue.industry_slug == industry_slug,
        TaskQueue.fetched_at >= since,
    )
    rows = base.with_entities(
        TaskQueue.source_keyword,
        func.count().label("collected"),
        func.sum(case((TaskQueue.status.in_(["sent", "replied", "converted"]), 1), else_=0)).label("sent"),
        func.sum(case((TaskQueue.status.in_(["replied", "converted"]), 1), else_=0)).label("replied"),
        func.sum(case((TaskQueue.status == "converted", 1), else_=0)).label("converted"),
    ).group_by(TaskQueue.source_keyword).all()
    return [normalize(row) for row in rows]
```

### 5.2 A/B 变体选择

```python
def select_reply_variant(industry: IndustryConfig) -> dict | None:
    variants = [v for v in (industry.reply_variants or []) if v.get("enabled", True)]
    if not variants:
        return None
    total_weight = sum(v.get("weight", 1) for v in variants)
    r = random.uniform(0, total_weight)
    cumulative = 0
    for v in variants:
        cumulative += v.get("weight", 1)
        if r <= cumulative:
            return v
    return variants[-1]
```

### 5.3 回复生成适配

在 `DeviceWorker._generate_reply()` 中：

```python
variant = select_reply_variant(self.industry)
if variant:
    tone = variant.get("reply_tone", self.industry.reply_tone)
    style = variant.get("reply_style", self.industry.reply_style)
    hook = variant.get("reply_hook", self.industry.reply_hook)
    # 记录变体到 task
    self._scheduler.mark_reply_variant(claim.task_id, variant.get("id"))
else:
    tone = self.industry.reply_tone
    style = self.industry.reply_style
    hook = self.industry.reply_hook
```

---

## 6. 前端改动

### 6.1 关键词效果页面

- 在主导航新增"关键词效果"
- 表格展示：关键词、采集量、发送量、回复量、转化量、回复率、转化率
- 按回复率/转化率排序

### 6.2 A/B 实验页面

- 在项目详情内新增"A/B 实验"标签
- 变体列表：名称、人设、风格、钩子、权重、操作
- "新增变体"弹窗
- 实验结果卡片：各变体指标对比 + 胜出标记

---

## 7. 测试计划

- `tests/server/services/test_analytics.py`：关键词聚合逻辑
- `tests/server/services/test_abtest.py`：变体选择、权重、结果统计
- `tests/server/api/test_abtest.py`：变体 CRUD API
- `tests/core/task/test_worker_abtest.py`：发送时变体选择
- 全量回归：`python -m pytest tests/ -q`

---

## 8. 验收标准

- [ ] 可按关键词查看转化率排名
- [ ] 可创建文案 A/B 实验并查看结果
- [ ] 报表数据与 TaskQueue 状态一致
- [ ] `python -m pytest tests/` 通过

---

## 9. 风险与回滚

| 风险 | 缓解措施 |
|---|---|
| source_keyword 为空导致报表缺失 | 在采集时强制记录来源关键词 |
| A/B 变体权重为 0 导致死循环 | 选择时过滤 weight <= 0 的变体 |
| 旧数据缺少 reply_variant_id | 统计时归入"默认版" |

---

*设计文档版本：v1.0*  
*创建日期：2026-06-16*
