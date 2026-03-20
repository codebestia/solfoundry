"""Celery application configuration.

Uses Redis as broker and result backend.
Configure via CELERY_BROKER_URL and CELERY_RESULT_BACKEND env vars.
"""

import os

from celery import Celery

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery_app = Celery(
    "solfoundry",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["app.tasks.deadline_watcher"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "release-expired-claims": {
            "task": "app.tasks.deadline_watcher.release_expired_claims_task",
            "schedule": 3600.0,  # Every hour
        },
    },
)
