"""Run a deterministic multi-device claim/commit load test."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.task.scheduler as scheduler_module
from core.task.scheduler import MatrixTaskScheduler
from server.models import Base
from server.models.task import TaskQueue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--devices", type=int, default=30)
    parser.add_argument("--tasks", type=int, default=3000)
    parser.add_argument("--db-path", default="tmp/matrix_load.db")
    parser.add_argument("--keep-db", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 60},
    )
    Base.metadata.create_all(bind=engine)
    local_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    scheduler_module.SessionLocal = local_session

    db = local_session()
    db.add_all(
        TaskQueue(
            industry_slug="matrix-load",
            owner_user_id="load-user",
            video_id=f"video-{index}",
            comment_id=f"comment-{index}",
            text=f"lead {index}",
            user_id=f"user-{index}",
            status="pending",
        )
        for index in range(args.tasks)
    )
    db.commit()
    db.close()

    claimed_ids: list[int] = []
    claims_by_device: Counter[str] = Counter()
    failures: list[str] = []

    def claim_and_commit(device_no: int):
        device_id = f"device-{device_no}"
        scheduler = MatrixTaskScheduler(
            industry_slug="matrix-load",
            owner_user_id="load-user",
            job_id="matrix-load-job",
        )
        try:
            claim = scheduler.claim_for_device(device_id)
            if not claim.ok:
                return device_id, 0, claim.reason
            token = claim.task.get("claim_token", "") if claim.task else ""
            committed = scheduler.mark_task_done(
                claim.task_id,
                device_id,
                claim_token=token,
            )
            return device_id, claim.task_id, "" if committed else "commit_failed"
        finally:
            scheduler.close()

    rounds = (args.tasks + args.devices - 1) // args.devices
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.devices) as pool:
        for _round in range(rounds):
            results = list(pool.map(claim_and_commit, range(args.devices)))
            for device_id, task_id, error in results:
                if task_id:
                    claimed_ids.append(task_id)
                    claims_by_device[device_id] += 1
                elif error != "no_task":
                    failures.append(error)

    duplicate_claims = len(claimed_ids) - len(set(claimed_ids))
    counts = list(claims_by_device.values()) or [0]
    report = {
        "devices": args.devices,
        "tasks": args.tasks,
        "claimed": len(claimed_ids),
        "duplicate_claims": duplicate_claims,
        "failures": len(failures),
        "failure_reasons": dict(Counter(failures)),
        "fairness_spread": max(counts) - min(counts),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    engine.dispose()
    if not args.keep_db and db_path.exists():
        db_path.unlink()
    return 0 if duplicate_claims == 0 and not failures and len(claimed_ids) == args.tasks else 1


if __name__ == "__main__":
    raise SystemExit(main())
