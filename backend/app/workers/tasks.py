import asyncio
import functools

import redis as sync_redis
import structlog
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.modules.payments.worker_service import (
    run_deliver_notifications,
    run_pay_out_investments,
    run_process_pending_withdrawals,
    run_reconcile_payments,
    run_refresh_loan_statuses,
    run_send_loan_reminders,
)

logger = structlog.get_logger()

# Transient failures worth retrying (database/cache blips, rail timeouts).
TRANSIENT = (OperationalError, DBAPIError, ConnectionError, TimeoutError, sync_redis.exceptions.ConnectionError)
RETRY = {"autoretry_for": TRANSIENT, "retry_backoff": 30, "retry_backoff_max": 600, "retry_jitter": True, "max_retries": 3}


def single_flight(name: str, ttl_seconds: int):
    """Skip a scheduled run while a previous one is still going (Redis lock).

    Beat can fire again before a slow run finishes, and a re-queued task
    (acks_late) can overlap the original; money-moving jobs must never run twice
    concurrently. If Redis is unreachable the run is skipped, not risked.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"lock:task:{name}"
            try:
                client = sync_redis.Redis.from_url(get_settings().redis_url)
                acquired = client.set(key, "1", nx=True, ex=ttl_seconds)
            except sync_redis.exceptions.RedisError:
                logger.warning("task_skipped", task=name, reason="lock unavailable")
                return {"status": "skipped", "reason": "lock unavailable"}
            if not acquired:
                logger.info("task_skipped", task=name, reason="previous run still in progress")
                return {"status": "skipped", "reason": "already running"}
            try:
                result = fn(*args, **kwargs)
                client.incr("cache:generation")  # data changed: invalidate cached reads
                return result
            finally:
                try:
                    client.delete(key)
                except sync_redis.exceptions.RedisError:
                    pass  # the TTL releases it

        return wrapper

    return decorator


@celery_app.task(name="app.workers.tasks.accrue_savings_interest", bind=True)
def accrue_savings_interest(self):
    """Daily savings interest accrual (00:30 WAT).

    Not implemented: savings accounts cannot be opened yet (POST /savings/me/accounts
    returns 501), so there is nothing to accrue.
    """
    logger.info("task_skipped", task="accrue_savings_interest", reason="savings module not live")
    return {"status": "skipped", "accounts_processed": 0}


@celery_app.task(name="app.workers.tasks.send_loan_reminders", bind=True, **RETRY)
@single_flight("send_loan_reminders", ttl_seconds=600)
def send_loan_reminders(self):
    """Due-in-3-days, due-today and overdue repayment reminders (idempotent per loan per day)."""
    return asyncio.run(run_send_loan_reminders())


@celery_app.task(name="app.workers.tasks.deliver_notifications", bind=True, **RETRY)
@single_flight("deliver_notifications", ttl_seconds=120)
def deliver_notifications(self):
    """Push queued notifications (payments, decisions, sign-in requests, reminders)."""
    return asyncio.run(run_deliver_notifications())


@celery_app.task(name="app.workers.tasks.pay_out_investments", bind=True, **RETRY)
@single_flight("pay_out_investments", ttl_seconds=900)
def pay_out_investments(self):
    """Pay matured investments into wallets (idempotent per investment)."""
    return asyncio.run(run_pay_out_investments())


@celery_app.task(name="app.workers.tasks.refresh_loan_statuses", bind=True, **RETRY)
@single_flight("refresh_loan_statuses", ttl_seconds=600)
def refresh_loan_statuses(self):
    """Mark overdue installments and roll next_due_date forward for every open loan."""
    return asyncio.run(run_refresh_loan_statuses())


@celery_app.task(name="app.workers.tasks.process_pending_withdrawals", bind=True, **RETRY)
@single_flight("process_pending_withdrawals", ttl_seconds=600)
def process_pending_withdrawals(self):
    """Send held wallet withdrawals to the payment rail."""
    return asyncio.run(run_process_pending_withdrawals())


@celery_app.task(name="app.workers.tasks.reconcile_payments", bind=True, **RETRY)
@single_flight("reconcile_payments", ttl_seconds=600)
def reconcile_payments(self):
    """Resolve PENDING transfers/collections by querying the rail (missed webhooks, timeouts)."""
    return asyncio.run(run_reconcile_payments())


@celery_app.task(name="app.workers.tasks.food_basket_fulfillment_check", bind=True)
def food_basket_fulfillment_check(self):
    """Upcoming food basket deliveries. Not implemented: subscriptions return 501."""
    logger.info("task_skipped", task="food_basket_fulfillment_check", reason="module not live")
    return {"status": "skipped", "deliveries_checked": 0}
