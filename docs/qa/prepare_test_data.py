#!/usr/bin/env python3
"""Prepare test data for lead collection manual testing."""
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.config import IndustryConfig
from server.workers import _set_job


TEST_INDUSTRIES = [
    {
        "slug": "qa-test-keywords-only",
        "name": "QA-仅关键词",
        "keywords": ["高考志愿"],
        "target_users": [],
        "platforms": ["douyin"],
        "reply_tone": "专业",
        "reply_style": "简洁",
        "categories": ["咨询"],
        "user_id": "qa-tester",
    },
    {
        "slug": "qa-test-target-only",
        "name": "QA-仅对标账号",
        "keywords": [],
        "target_users": ["https://www.douyin.com/user/MS4wLjABAAAAb3Xb3Xb3Xb3Xb3Xb3Xb3Xb3X"],
        "platforms": ["douyin"],
        "reply_tone": "专业",
        "reply_style": "简洁",
        "categories": ["咨询"],
        "user_id": "qa-tester",
    },
    {
        "slug": "qa-test-combined",
        "name": "QA-组合采集",
        "keywords": ["高考志愿"],
        "target_users": ["https://www.douyin.com/user/MS4wLjABAAAAb3Xb3Xb3Xb3Xb3Xb3Xb3Xb3X"],
        "platforms": ["douyin"],
        "reply_tone": "专业",
        "reply_style": "简洁",
        "categories": ["咨询"],
        "user_id": "qa-tester",
    },
    {
        "slug": "qa-test-empty",
        "name": "QA-空配置",
        "keywords": [],
        "target_users": [],
        "platforms": ["douyin"],
        "reply_tone": "专业",
        "reply_style": "简洁",
        "categories": ["咨询"],
        "user_id": "qa-tester",
    },
    {
        "slug": "qa-test-invalid-target",
        "name": "QA-含无效对标账号",
        "keywords": ["高考志愿"],
        "target_users": ["关注征兵的人", "https://www.douyin.com/user/MS4wLjABAAAAb3Xb3Xb3Xb3Xb3Xb3Xb3Xb3X"],
        "platforms": ["douyin"],
        "reply_tone": "专业",
        "reply_style": "简洁",
        "categories": ["咨询"],
        "user_id": "qa-tester",
    },
]


async def seed_test_industries():
    """Create or update test industry records in the database."""
    from server.models import SessionLocal
    from server.models.industry import Industry

    db = SessionLocal()
    try:
        for data in TEST_INDUSTRIES:
            industry = db.query(Industry).filter(Industry.slug == data["slug"]).first()
            if not industry:
                industry = Industry(
                    id=str(uuid.uuid4()),
                    slug=data["slug"],
                    name=data["name"],
                    user_id=data["user_id"],
                    keywords=data["keywords"],
                    target_users=data["target_users"],
                    platforms=data["platforms"],
                    reply_tone=data["reply_tone"],
                    reply_style=data["reply_style"],
                    categories=data["categories"],
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    hourly_send_limit=0,
                    daily_send_max=0,
                )
                db.add(industry)
                print(f"Created industry: {data['slug']}")
            else:
                industry.keywords = data["keywords"]
                industry.target_users = data["target_users"]
                industry.platforms = data["platforms"]
                industry.is_active = True
                industry.updated_at = datetime.now(timezone.utc)
                print(f"Updated industry: {data['slug']}")
        db.commit()
        print("Test industries seeded successfully.")
    finally:
        db.close()


async def seed_test_jobs():
    """Create a few historical jobs for the auto-replenishment check."""
    for i in range(3):
        job_id = f"qa-historical-empty-{i}"
        _set_job(
            job_id,
            user_id="qa-tester",
            type="collect",
            status="done",
            progress=100,
            industry_slug="qa-test-keywords-only",
            industry_name="QA-仅关键词",
            completed_at=datetime.now(timezone.utc),
            collect_summary={
                "candidate_comments": 0,
                "empty_reason": "no_source_comments",
                "warning": "MediaCrawler completed but produced no source comments.",
            },
        )
    print("Seeded historical empty jobs for qa-test-keywords-only.")


async def main():
    await seed_test_industries()
    await seed_test_jobs()


if __name__ == "__main__":
    asyncio.run(main())
