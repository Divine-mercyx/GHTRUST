from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "ghtrust_mfb",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Africa/Lagos",
    enable_utc=True,
    task_track_started=True,
    # Reliability: acknowledge only after the task finishes, and re-queue it if the
    # worker process dies mid-run — a crash must never silently drop a job.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=270,  # raises inside the task first, so it can log/clean up
    task_time_limit=300,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=500,  # recycle processes to cap memory growth
    broker_connection_retry_on_startup=True,
    result_expires=24 * 3600,
    task_always_eager=settings.celery_task_always_eager,
    task_routes={
        "app.workers.tasks.accrue_savings_interest": {"queue": "scheduled"},
        "app.workers.tasks.send_loan_reminders": {"queue": "notifications"},
        "app.workers.tasks.refresh_loan_statuses": {"queue": "scheduled"},
        "app.workers.tasks.process_pending_withdrawals": {"queue": "transactions"},
        "app.workers.tasks.reconcile_payments": {"queue": "reconciliation"},
        "app.workers.tasks.food_basket_fulfillment_check": {"queue": "scheduled"},
    },
    beat_schedule={
        "accrue-savings-interest-daily": {
            "task": "app.workers.tasks.accrue_savings_interest",
            "schedule": crontab(hour=0, minute=30),
        },
        "refresh-loan-statuses-daily": {
            "task": "app.workers.tasks.refresh_loan_statuses",
            "schedule": crontab(hour=0, minute=15),
        },
        "loan-payment-reminders": {
            "task": "app.workers.tasks.send_loan_reminders",
            "schedule": crontab(hour=8, minute=0),
        },
        # Hourly, so an investment maturing today is paid early that day (idempotent).
        "pay-out-investments": {
            "task": "app.workers.tasks.pay_out_investments",
            "schedule": crontab(minute=5),
        },
        "deliver-notifications": {
            "task": "app.workers.tasks.deliver_notifications",
            "schedule": crontab(minute="*"),
        },
        "process-pending-withdrawals": {
            "task": "app.workers.tasks.process_pending_withdrawals",
            "schedule": crontab(minute="*/15"),
        },
        "payment-reconciliation": {
            "task": "app.workers.tasks.reconcile_payments",
            "schedule": crontab(minute="*/20"),
        },
        "food-basket-fulfillment-check": {
            "task": "app.workers.tasks.food_basket_fulfillment_check",
            "schedule": crontab(hour=9, minute=0),
        },
    },
)


# ── Worker observability ───────────────────────────────────────────────────────
from celery.signals import task_failure, task_retry, worker_process_init  # noqa: E402


@worker_process_init.connect
def _init_worker_process(**_):
    """Structured JSON logs and error tracking in every worker process."""
    from app.core.observability import init_error_tracking
    from app.core.logging import configure_logging

    configure_logging(json_logs=settings.app_env != "development", debug=settings.debug)
    init_error_tracking(settings, component="worker")


@task_failure.connect
def _log_task_failure(sender=None, task_id=None, exception=None, **_):
    import structlog

    from app.core.observability import capture_exception

    structlog.get_logger().error(
        "task_failed", task=getattr(sender, "name", None), task_id=task_id, error=repr(exception)
    )
    if exception is not None:
        capture_exception(exception)


@task_retry.connect
def _log_task_retry(request=None, reason=None, **_):
    import structlog

    structlog.get_logger().warning(
        "task_retrying", task=getattr(request, "task", None), task_id=getattr(request, "id", None), reason=repr(reason)
    )
