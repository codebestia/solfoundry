"""Deadline watcher — Celery periodic task (Issue #16).

Runs every hour via Celery Beat. Scans active claims and releases
those that have passed their deadline.
"""

import logging

from app.celery_app import celery_app
from app.services import claim_service

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.deadline_watcher.release_expired_claims_task")
def release_expired_claims_task() -> dict:
    """
    Periodic task: release all expired claims.

    Returns a summary dict with the count of released claims.
    """
    released = claim_service.release_expired_claims()
    if released > 0:
        logger.info("Deadline watcher released %d expired claim(s)", released)
    else:
        logger.debug("Deadline watcher: no expired claims found")
    return {"released": released}
