"""Industry management routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from server.auth import get_current_user
from server.models import get_db
from server.models.industry import Industry
from server.models.user import User
from server.schemas.industry import (
    IndustryCreate, IndustryOut, IndustryStats, IndustryUpdate,
)
from server.secret_store import decrypt_secret, has_secret
from server.workers import run_collect_job, run_send_job

router = APIRouter(prefix="/api/industries", tags=["industries"])


def _single_platform(platforms: list[str] | None) -> list[str]:
    cleaned = [str(p).strip() for p in (platforms or []) if str(p).strip()]
    return [cleaned[0] if cleaned else "douyin"]


def _to_industry_config(industry: Industry):
    """Convert DB model to engine-compatible IndustryConfig."""
    from core.config import IndustryConfig
    user = industry.user
    return IndustryConfig(
        name=industry.name,
        slug=industry.slug,
        keywords=industry.keywords or [],
        reply_tone=industry.reply_tone,
        reply_style=industry.reply_style,
        reply_hook=getattr(industry, "reply_hook", ""),
        categories=industry.categories or [],
        daily_limit=industry.daily_limit,
        video_max_age_days=industry.video_max_age_days,
        comment_max_age_hours=industry.comment_max_age_hours,
        platforms=_single_platform(industry.platforms),
        llm_provider=industry.llm_provider or "deepseek",
        llm_model=industry.llm_model or "deepseek-chat",
        deepseek_key=decrypt_secret(user.deepseek_key) if user else "",
        zhipu_key=decrypt_secret(user.zhipu_key) if user else "",
        openai_key=decrypt_secret(user.openai_key) if user else "",
        intent_keywords=industry.intent_keywords or [],
        noise_keywords=industry.noise_keywords or [],
        target_users=industry.target_users or [],
        user_id=industry.user_id,
        matrix_target_devices=industry.matrix_target_devices or 30,
        lead_inventory_days=industry.lead_inventory_days or 3,
        global_daily_limit=industry.global_daily_limit or 0,
        auto_replenish_enabled=bool(industry.auto_replenish_enabled),
        replenish_threshold_days=industry.replenish_threshold_days or 1,
        keyword_batch_size=industry.keyword_batch_size or 12,
        collect_authors_per_run=industry.collect_authors_per_run or 60,
        collect_video_limit=industry.collect_video_limit or 120,
        compliance_mode=bool(getattr(industry, "compliance_mode", False)),
        webhook_url=getattr(industry, "webhook_url", "") or "",
        auto_export_enabled=bool(getattr(industry, "auto_export_enabled", False)),
    )


def _matrix_capacity(ind: Industry, db: Session, user_id: str) -> dict:
    from server.models.device import Device

    active_devices = db.query(Device).filter(
        Device.user_id == user_id,
        Device.is_active == True,
    ).count()
    target_devices = max(active_devices, ind.matrix_target_devices or 30)
    return {
        "active_devices": active_devices,
        "target_devices": target_devices,
        "per_device_daily_limit": ind.daily_limit or 15,
        "inventory_days": ind.lead_inventory_days or 3,
        "global_daily_limit": ind.global_daily_limit or 0,
        "threshold_days": ind.replenish_threshold_days or 1,
    }


import os
import re
import json_repair

SYSTEM_PROMPT = """你是一个专业的互联网精准营销专家和获客配置专家。请根据用户输入的“业务描述”（比如他是做什么的、目标客户群是谁），自动分析并生成一套行业匹配的配置。

输出的配置必须是 JSON 格式，且必须包含以下字段：
1. "name": 简短的行业项目名称（不超过10个字，例如："成人英语口语"）。
2. "slug": 行业的英文标识符（由英文字母、数字和减号组成，不超过32个字符，首字符为字母，必须唯一，例如："adult-english"）。
3. "keywords": 目标用户的搜索关键词/评论区高频词列表（数组，包含 20 到 30 个词，尽量覆盖用户可能表达需求的词汇，如"怎么学"、"费用"、"推荐"等）。
4. "reply_tone": 意图回复语气人设（例如："英语口语教练"、"资深留学规划师"）。
5. "reply_style": 回复风格设计建议（例如："以口语化、亲切和专业解答为主，穿插短句"）。
6. "categories": 潜在客户咨询分类列表（数组，包含 4 到 6 个分类，例如：["英语口语咨询", "成人培训咨询", "课程费用咨询", "上课时间咨询", "其他"]）。

请直接返回合法的 JSON，不要使用 markdown 格式包裹，也不要包含任何额外的文字说明。"""


class IndustryGenerateConfigReq(BaseModel):
    description: str


def select_available_llm(user: User | None = None):
    """Detect available LLM provider and model by checking env variables or system.yaml."""
    if os.getenv("THUNDER_DEEPSEEK_KEY"):
        return "deepseek", "deepseek-chat"
    if os.getenv("THUNDER_ZHIPU_KEY"):
        return "zhipu", "glm-4-flash"
    if os.getenv("THUNDER_OPENAI_KEY"):
        return "openai", "gpt-4o-mini"

    if user:
        if has_secret(user.deepseek_key):
            return "deepseek", "deepseek-chat"
        if has_secret(user.zhipu_key):
            return "zhipu", "glm-4-flash"
        if has_secret(user.openai_key):
            return "openai", "gpt-4o-mini"

    # Fallback to loading system.yaml config
    try:
        from core.config import load_system
        cfg = load_system()
        api_keys = cfg.get("api_keys", {})
        if api_keys.get("deepseek"):
            return "deepseek", "deepseek-chat"
        if api_keys.get("zhipu"):
            return "zhipu", "glm-4-flash"
        if api_keys.get("openai"):
            return "openai", "gpt-4o-mini"
    except Exception:
        pass

    # Default fallback
    return "deepseek", "deepseek-chat"


@router.post("/generate-config")
def generate_industry_config(
    req: IndustryGenerateConfigReq,
    current_user: User = Depends(get_current_user),
):
    provider, model = select_available_llm(current_user)
    
    # Check if current user has overriding API keys
    user_key = None
    if provider == "deepseek" and current_user.deepseek_key:
        user_key = decrypt_secret(current_user.deepseek_key)
    elif provider == "zhipu" and current_user.zhipu_key:
        user_key = decrypt_secret(current_user.zhipu_key)
    elif provider == "openai" and current_user.openai_key:
        user_key = decrypt_secret(current_user.openai_key)

    from server.services.llm import get_llm_client
    try:
        client = get_llm_client(provider=provider, model=model, api_key=user_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法初始化 LLM 客户端: {str(e)}")

    prompt = f"业务描述：{req.description}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        result = resp.choices[0].message.content.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 接口调用异常: {str(e)}")

    try:
        config_data = json_repair.loads(result)
        if not config_data or not isinstance(config_data, dict):
            raise ValueError("Parsed result is not a dictionary")
    except Exception as e:
        raise HTTPException(
            status_code=520,
            detail=f"解析 LLM 返回的 JSON 失败，原始输出: {result[:200]}... 错误: {str(e)}"
        )

    name = config_data.get("name", "未命名项目")
    slug = config_data.get("slug", "industry-project")
    keywords = config_data.get("keywords", [])
    reply_tone = config_data.get("reply_tone", "业内人士")
    reply_style = config_data.get("reply_style", "亲切专业")
    categories = config_data.get("categories", [])

    # Validate and normalize slug format
    slug = re.sub(r'[^a-z0-9_-]', '', slug.lower())
    if not slug or not slug[0].isalpha():
        slug = "ind-" + slug if slug else "industry"
    slug = slug[:32]

    # Normalize keywords to list of strings
    if not isinstance(keywords, list):
        keywords = [str(keywords)] if keywords else []
    else:
        keywords = [str(k).strip() for k in keywords if k]

    # Normalize categories to list of strings
    if not isinstance(categories, list):
        categories = [str(categories)] if categories else []
    else:
        categories = [str(c).strip() for c in categories if c]

    return {
        "name": name,
        "slug": slug,
        "keywords": keywords,
        "reply_tone": reply_tone,
        "reply_style": reply_style,
        "categories": categories,
        "llm_provider": provider,
        "llm_model": model,
    }


class IndustryGenerateBigDataConfigReq(BaseModel):
    description: str
    seed_keyword: str


BIGDATA_SYSTEM_PROMPT = """你是一个专业的互联网数据分析师和获客配置专家。请根据用户提供的“业务描述”以及从抖音平台采集到的“热门视频描述与用户评论数据”（大数据文本池），分析用户的真实关注点、痛点以及搜索意图，并生成一套精准的行业匹配配置。

输出的配置必须是 JSON 格式，且必须包含以下字段：
1. "name": 简短的行业项目名称（不超过10个字，例如："成人英语口语"）。
2. "slug": 行业的英文标识符（由英文字母、数字和减号组成，不超过32个字符，首字符为字母，必须唯一，例如："adult-english"）。
3. "keywords": 目标用户的精准搜索关键词/痛点意图词列表（数组，包含 20 到 30 个词，必须是真实网民在大数据评论中表达需求的词汇，如具体的身体状况、政审问题、专业报考等，不要使用包含完全相同前缀词的硬拼接死板词）。
4. "reply_tone": 意图回复语气人设（例如："英语口语教练"、"资深留学规划师"）。
5. "reply_style": 回复风格设计建议（例如："以口语化、亲切和专业解答为主，穿插短句"）。
6. "categories": 潜在客户咨询分类列表（数组，包含 4 到 6 个分类，例如：["英语口语咨询", "成人培训咨询", "课程费用咨询", "上课时间咨询", "其他"]）。

请直接返回合法的 JSON，不要使用 markdown 格式包裹，也不要包含任何额外的文字说明。"""


@router.post("/generate-config-bigdata")
async def generate_industry_config_bigdata(
    req: IndustryGenerateBigDataConfigReq,
    current_user: User = Depends(get_current_user),
):
    provider, model = select_available_llm(current_user)
    
    user_key = None
    if provider == "deepseek" and current_user.deepseek_key:
        user_key = decrypt_secret(current_user.deepseek_key)
    elif provider == "zhipu" and current_user.zhipu_key:
        user_key = decrypt_secret(current_user.zhipu_key)
    elif provider == "openai" and current_user.openai_key:
        user_key = decrypt_secret(current_user.openai_key)

    from server.services.llm import get_llm_client
    try:
        client = get_llm_client(provider=provider, model=model, api_key=user_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法初始化 LLM 客户端: {str(e)}")

    comments_pool = []
    collector = None
    try:
        from core.collectors.douyin import DouyinCollector
        collector = DouyinCollector()
        session_ok = await collector._ensure_session()
        if session_ok:
            comments_pool = await collector.collect_hot_comments(req.seed_keyword, max_videos=5)
    except Exception as e:
        # Fallback to standard generation if crawler fails, but with warning logged
        pass
    finally:
        if collector:
            try:
                await collector._cleanup()
            except Exception:
                pass

    prompt = f"业务描述：{req.description}\n\n"
    if comments_pool:
        prompt += "【抓取到的社媒热门大数据（视频描述与用户评论）】:\n"
        prompt += "\n".join(comments_pool[:120])
    else:
        prompt += "【说明】未成功抓取到社媒大数据评论，请直接根据业务描述进行推理生成行业匹配词库。"

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": BIGDATA_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        result = resp.choices[0].message.content.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 接口调用异常: {str(e)}")

    try:
        config_data = json_repair.loads(result)
        if not config_data or not isinstance(config_data, dict):
            raise ValueError("Parsed result is not a dictionary")
    except Exception as e:
        raise HTTPException(
            status_code=520,
            detail=f"解析 LLM 返回的 JSON 失败，原始输出: {result[:200]}... 错误: {str(e)}"
        )

    name = config_data.get("name", "未命名项目")
    slug = config_data.get("slug", "industry-project")
    keywords = config_data.get("keywords", [])
    reply_tone = config_data.get("reply_tone", "业内人士")
    reply_style = config_data.get("reply_style", "亲切专业")
    categories = config_data.get("categories", [])

    slug = re.sub(r'[^a-z0-9_-]', '', slug.lower())
    if not slug or not slug[0].isalpha():
        slug = "ind-" + slug if slug else "industry"
    slug = slug[:32]

    if not isinstance(keywords, list):
        keywords = [str(keywords)] if keywords else []
    else:
        keywords = [str(k).strip() for k in keywords if k]

    if not isinstance(categories, list):
        categories = [str(categories)] if categories else []
    else:
        categories = [str(c).strip() for c in categories if c]

    return {
        "name": name,
        "slug": slug,
        "keywords": keywords,
        "reply_tone": reply_tone,
        "reply_style": reply_style,
        "categories": categories,
        "llm_provider": provider,
        "llm_model": model,
        "bigdata_used": len(comments_pool) > 0
    }




@router.get("", response_model=list[IndustryOut])
def list_industries(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Industry)
        .filter(Industry.user_id == current_user.id, Industry.is_active == True)
        .order_by(Industry.created_at.desc())
        .all()
    )


@router.post("", response_model=IndustryOut, status_code=201)
def create_industry(
    data: IndustryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if db.query(Industry).filter(
        Industry.user_id == current_user.id, Industry.slug == data.slug
    ).first():
        raise HTTPException(status_code=400, detail="Slug already exists")
    industry = Industry(user_id=current_user.id, **data.model_dump())
    db.add(industry)
    db.commit()
    db.refresh(industry)
    return industry


@router.get("/{industry_id}", response_model=IndustryOut)
def get_industry(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    return ind


@router.put("/{industry_id}", response_model=IndustryOut)
def update_industry(
    industry_id: str,
    data: IndustryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(ind, key, val)
    db.commit()
    db.refresh(ind)
    return ind


@router.delete("/{industry_id}")
def delete_industry(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    slug = ind.slug

    # Clean engine-side data
    try:
        from server.models.task import TaskQueue, TargetBlogger
        db.query(TaskQueue).filter(TaskQueue.industry_slug == slug).delete()
        db.query(TargetBlogger).filter(TargetBlogger.industry_slug == slug).delete()
        # Note: collected_videos logic might need joining or simpler to ignore for now since it's just dedup memory.
        db.commit()
    except Exception as e:
        db.rollback()

    ind.is_active = False
    db.commit()
    return {"ok": True, "cleaned_slug": slug}


@router.post("/{industry_id}/collect")
def trigger_collect(
    industry_id: str,
    skip_discover: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    cfg = _to_industry_config(ind)
    job_id = run_collect_job(cfg, skip_discover=skip_discover)
    return {"job_id": job_id}


@router.get("/{industry_id}/replenishment-plan")
def get_replenishment_plan(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from server.services.task_stats import replenishment_plan
    cap = _matrix_capacity(ind, db, current_user.id)
    return {
        **replenishment_plan(
            ind.slug,
            target_devices=cap["target_devices"],
            per_device_daily_limit=cap["per_device_daily_limit"],
            inventory_days=cap["inventory_days"],
            global_daily_limit=cap["global_daily_limit"],
            threshold_days=cap["threshold_days"],
        ),
        "auto_enabled": bool(ind.auto_replenish_enabled),
    }


class ReplenishRequest(BaseModel):
    force: bool = False


@router.post("/{industry_id}/replenish")
def trigger_replenishment(
    industry_id: str,
    body: ReplenishRequest = ReplenishRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from server.services.task_stats import replenishment_plan
    cap = _matrix_capacity(ind, db, current_user.id)
    plan = replenishment_plan(
        ind.slug,
        target_devices=cap["target_devices"],
        per_device_daily_limit=cap["per_device_daily_limit"],
        inventory_days=cap["inventory_days"],
        global_daily_limit=cap["global_daily_limit"],
        threshold_days=cap["threshold_days"],
    )
    if not body.force and not plan.get("should_replenish"):
        return {"ok": True, "started": False, "reason": "库存充足，无需补采", "plan": plan}

    cfg = _to_industry_config(ind)
    job_id = run_collect_job(cfg, skip_discover=bool(plan.get("skip_discover")))
    return {
        "ok": True,
        "started": True,
        "job_id": job_id,
        "skip_discover": bool(plan.get("skip_discover")),
        "mode": plan.get("mode"),
        "plan": plan,
    }


class SendRequest(BaseModel):
    devices: list[str] | None = None


@router.post("/{industry_id}/send")
def trigger_send(
    industry_id: str,
    body: SendRequest = SendRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    device_ids = [str(d).strip() for d in (body.devices or []) if str(d).strip()]
    if device_ids:
        from server.models.device import Device

        devices = (
            db.query(Device)
            .filter(
                Device.user_id == current_user.id,
                Device.is_active == True,
                Device.id.in_(device_ids),
            )
            .all()
        )
        allowed_ids = {device.id for device in devices}
        rejected = [device_id for device_id in device_ids if device_id not in allowed_ids]
        if rejected:
            raise HTTPException(
                status_code=400,
                detail=f"Device not found or not owned by current user: {', '.join(rejected)}",
            )
        unavailable = []
        now = datetime.now(timezone.utc)
        for device in devices:
            status = device.runtime_status or "idle"
            reason = ""
            if status in {"offline", "keyboard_error", "cooldown", "isolated"}:
                reason = status
            elif int(device.consecutive_failures or 0) >= 5:
                reason = "too_many_failures"
            elif device.cooldown_until:
                cooldown_until = device.cooldown_until
                if cooldown_until.tzinfo is None:
                    cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
                if cooldown_until > now:
                    reason = f"cooldown_until:{cooldown_until.isoformat()}"
            if reason:
                unavailable.append(f"{device.name or device.id}({reason})")
        if unavailable:
            raise HTTPException(
                status_code=400,
                detail=f"Selected device unavailable: {', '.join(unavailable)}",
            )
    cfg = _to_industry_config(ind)
    job_id = run_send_job(cfg, device_ids=device_ids or None)
    return {"job_id": job_id}


@router.get("/{industry_id}/stats", response_model=IndustryStats)
def get_industry_stats(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from server.services.task_stats import (
        queue_stats, blogger_source_stats, inventory_stats,
        industry_daily_quota_state,
    )
    qs = queue_stats(ind.slug)
    bs = blogger_source_stats(ind.slug)
    cap = _matrix_capacity(ind, db, current_user.id)
    inv = inventory_stats(
        ind.slug,
        target_devices=cap["target_devices"],
        per_device_daily_limit=cap["per_device_daily_limit"],
        inventory_days=cap["inventory_days"],
        global_daily_limit=cap["global_daily_limit"],
    )
    quota = industry_daily_quota_state(ind.slug)
    total = qs.get("total", 0)
    done = qs.get("done", 0)
    failed = qs.get("failed", 0)
    return IndustryStats(
        total_tasks=total,
        pending=qs.get("pending", 0),
        done=done,
        failed=failed,
        active_bloggers=bs.get("active", 0),
        success_rate=round(done / max(done + failed, 1) * 100, 1),
        active_devices=cap["active_devices"],
        matrix_target_devices=cap["target_devices"],
        daily_send_capacity=inv["daily_send_capacity"],
        global_daily_limit=ind.global_daily_limit or 0,
        global_sent_today=quota["sent"],
        global_reserved=quota["reserved"],
        target_pending=inv["target_pending"],
        pending_deficit=inv["pending_deficit"],
        stock_days=inv["stock_days"],
    )


@router.get("/{industry_id}/tasks")
def get_industry_tasks(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = Query(default=None, pattern="^(pending|claimed|retry|done|failed)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from server.models.task import TaskQueue
    from sqlalchemy import or_
    
    query = db.query(TaskQueue).filter(
        TaskQueue.industry_slug == ind.slug,
        or_(TaskQueue.owner_user_id == current_user.id, TaskQueue.owner_user_id == "", TaskQueue.owner_user_id == None)
    )
    
    now = datetime.now().isoformat()
    if status == "retry":
        query = query.filter(TaskQueue.status == "pending", TaskQueue.retry_after != None, TaskQueue.retry_after != "", TaskQueue.retry_after > now)
    elif status == "pending":
        query = query.filter(TaskQueue.status == "pending", or_(TaskQueue.retry_after == None, TaskQueue.retry_after == "", TaskQueue.retry_after <= now))
    elif status:
        query = query.filter(TaskQueue.status == status)
        
    tasks = query.order_by(TaskQueue.id.desc()).limit(limit).offset(offset).all()
    return [
        {
            c.name: getattr(t, c.name)
            for c in TaskQueue.__table__.columns
        }
        for t in tasks
    ]


@router.post("/{industry_id}/tasks/{task_id}/retry")
def retry_failed_task(
    industry_id: str,
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from server.models.task import TaskQueue
    try:
        task = db.query(TaskQueue).filter(
            TaskQueue.id == task_id,
            TaskQueue.industry_slug == ind.slug,
            or_(TaskQueue.owner_user_id == current_user.id, TaskQueue.owner_user_id == "", TaskQueue.owner_user_id == None)
        ).first()
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status != "failed":
            raise HTTPException(status_code=400, detail="Only failed tasks can be retried")
            
        task.status = "pending"
        task.consumer_id = None
        task.claim_token = None
        task.claimed_at = None
        task.processed_at = None
        task.retry_after = None
        task.error = None
        db.commit()
        return {"ok": True, "task_id": task_id, "status": "pending"}
    except Exception as e:
        db.rollback()
        raise


@router.post("/{industry_id}/tasks/retry-failed")
def retry_all_failed_tasks(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from server.models.task import TaskQueue
    try:
        tasks = db.query(TaskQueue).filter(
            TaskQueue.industry_slug == ind.slug,
            TaskQueue.status == "failed",
            or_(TaskQueue.owner_user_id == current_user.id, TaskQueue.owner_user_id == "", TaskQueue.owner_user_id == None)
        ).all()
        count = len(tasks)
        for task in tasks:
            task.status = "pending"
            task.consumer_id = None
            task.claim_token = None
            task.claimed_at = None
            task.processed_at = None
            task.retry_after = None
            task.error = None
        db.commit()
        return {"ok": True, "count": count, "status": "pending"}
    except Exception as e:
        db.rollback()
        raise


@router.get("/{industry_id}/funnel")
def get_industry_funnel(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from server.services.task_stats import (
        inventory_stats,
        keyword_funnel_stats,
        source_type_funnel_stats,
        blogger_source_stats,
        source_performance_stats,
        industry_daily_quota_state,
        replenishment_plan,
    )
    from server.models.job import Job
    cap = _matrix_capacity(ind, db, current_user.id)
    inventory = inventory_stats(
        ind.slug,
        target_devices=cap["target_devices"],
        per_device_daily_limit=cap["per_device_daily_limit"],
        inventory_days=cap["inventory_days"],
        global_daily_limit=cap["global_daily_limit"],
    )
    replenish = replenishment_plan(
        ind.slug,
        target_devices=cap["target_devices"],
        per_device_daily_limit=cap["per_device_daily_limit"],
        inventory_days=cap["inventory_days"],
        global_daily_limit=cap["global_daily_limit"],
        threshold_days=cap["threshold_days"],
        source_limit=limit,
    )
    quota = industry_daily_quota_state(ind.slug)
    recent_collect = (
        db.query(Job)
        .filter(
            Job.user_id == current_user.id,
            Job.industry_slug == ind.slug,
            Job.type == "collect",
        )
        .order_by(Job.created_at.desc())
        .first()
    )
    recent_send = (
        db.query(Job)
        .filter(
            Job.user_id == current_user.id,
            Job.industry_slug == ind.slug,
            Job.type == "send",
        )
        .order_by(Job.created_at.desc())
        .first()
    )
    recent_payload = recent_collect.payload if recent_collect else {}
    if isinstance(recent_payload, str):
        try:
            import json
            recent_payload = json.loads(recent_payload)
        except Exception:
            recent_payload = {}
    recent_send_payload = recent_send.payload if recent_send else {}
    if isinstance(recent_send_payload, str):
        try:
            import json
            recent_send_payload = json.loads(recent_send_payload)
        except Exception:
            recent_send_payload = {}
    return {
        "industry_slug": ind.slug,
        "inventory": inventory,
        "quota": {
            **quota,
            "global_daily_limit": ind.global_daily_limit or 0,
        },
        "replenishment": {
            **replenish,
            "auto_enabled": bool(ind.auto_replenish_enabled),
        },
        "latest_collect": {
            "job_id": recent_collect.id if recent_collect else "",
            "status": recent_collect.status if recent_collect else "",
            "created_at": recent_collect.created_at.isoformat() if recent_collect and recent_collect.created_at else None,
            "completed_at": recent_collect.completed_at.isoformat() if recent_collect and recent_collect.completed_at else None,
            "summary": (recent_payload or {}).get("collect_summary", {}),
        },
        "latest_send": {
            "job_id": recent_send.id if recent_send else "",
            "status": recent_send.status if recent_send else "",
            "created_at": recent_send.created_at.isoformat() if recent_send and recent_send.created_at else None,
            "completed_at": recent_send.completed_at.isoformat() if recent_send and recent_send.completed_at else None,
            "summary": (recent_send_payload or {}).get("send_summary", {}),
        },
        "source_types": source_type_funnel_stats(ind.slug),
        "bloggers": blogger_source_stats(ind.slug),
        "keywords": keyword_funnel_stats(ind.slug, limit=limit),
        "source_performance": source_performance_stats(ind.slug, limit=limit),
    }


@router.get("/{industry_id}/bloggers")
def get_industry_bloggers(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from server.services.task_stats import get_bloggers
    bloggers = get_bloggers("all", ind.slug)
    return bloggers


def _get_owned_industry(industry_id: str, user: User, db: Session) -> Industry:
    ind = db.query(Industry).filter(Industry.id == industry_id).first()
    if not ind or ind.user_id != user.id:
        raise HTTPException(status_code=404, detail="Industry not found")
    return ind
