"""Celery task queue adapter.

Replaces native threading (core/task/worker.py) with Celery workers.
Benefits over threading:
- Horizontal scaling: run workers on multiple machines
- Auto-retry with exponential backoff (built-in)
- Rate limiting (built-in)
- Task monitoring via Flower dashboard
- Graceful shutdown with task revocation

Requires: Redis as message broker (or RabbitMQ)

Setup:
1. Install: pip install -r requirements/adapters.txt
2. Start Redis: redis-server
3. Start worker: celery -A adapters.celery.app worker -l info -Q collect,classify,send
4. Monitor: celery -A adapters.celery.app flower
"""
