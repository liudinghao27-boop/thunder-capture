"""Concurrency and quota invariants for a 30-device matrix."""

import concurrent.futures

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.task.scheduler import MatrixTaskScheduler
from server.models import Base
from server.models.task import IndustryDailyQuota, TaskQueue


@pytest.fixture
def matrix_db(tmp_path, monkeypatch):
    db_path = tmp_path / "matrix.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=engine)
    local_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("core.task.scheduler.SessionLocal", local_session)

    db = local_session()
    db.add_all(
        TaskQueue(
            industry_slug="matrix-test",
            owner_user_id="user-1",
            video_id=f"video-{index}",
            comment_id=f"comment-{index}",
            text=f"lead {index}",
            user_name=f"user {index}",
            user_id=f"uid-{index}",
            status="pending",
        )
        for index in range(300)
    )
    db.commit()
    db.close()
    yield local_session
    engine.dispose()


@pytest.mark.matrix
def test_30_devices_never_claim_the_same_task(matrix_db):
    def claim(device_no):
        scheduler = MatrixTaskScheduler(
            industry_slug="matrix-test",
            owner_user_id="user-1",
            job_id="job-30",
        )
        try:
            return scheduler.claim_for_device(f"device-{device_no}")
        finally:
            scheduler.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
        claims = list(pool.map(claim, range(30)))

    assert [claim.reason for claim in claims if not claim.ok] == []
    task_ids = [claim.task_id for claim in claims]
    assert len(task_ids) == 30
    assert len(set(task_ids)) == 30


@pytest.mark.matrix
def test_combined_limits_reserve_one_slot_per_claim(matrix_db):
    scheduler = MatrixTaskScheduler(
        industry_slug="matrix-test",
        owner_user_id="user-1",
        global_daily_limit=100,
        daily_send_max=80,
        job_id="job-quota",
    )
    try:
        claim = scheduler.claim_for_device("device-quota")
        assert claim.ok is True
    finally:
        scheduler.close()

    db = matrix_db()
    try:
        quota = (
            db.query(IndustryDailyQuota)
            .filter(IndustryDailyQuota.industry_slug == "matrix-test")
            .one()
        )
        assert quota.reserved == 1
    finally:
        db.close()
