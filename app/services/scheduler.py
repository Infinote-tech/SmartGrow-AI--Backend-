"""
Optional background scheduler for the Adaptive Irrigation Policy.

When POLICY_SCHEDULER_ENABLED=true, every POLICY_SCHEDULER_INTERVAL_MINUTES the policy runs `decide()` for each tray
in POLICY_SCHEDULER_TRAY_IDS and records the recommendation. It is off by default and never started in tests.
A failure for one tray is logged and does not stop the others.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.database import mongo
from app.services.irrigation_policy_service import IrrigationPolicyService

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def run_policy_cycle(tray_ids: list[str] | None = None, db=None) -> dict[str, str]:
    """Run the policy once for every tray. Returns {tray_id: "ok" | error message}."""
    service = IrrigationPolicyService.from_db(db if db is not None else mongo.get_db())
    outcome: dict[str, str] = {}
    for tray_id in tray_ids if tray_ids is not None else settings.policy_scheduler_tray_list:
        try:
            await service.decide(tray_id)
            outcome[tray_id] = "ok"
        except Exception as exc:  # noqa: BLE001 - one bad tray must not stop the cycle
            logger.exception("Policy decision failed for tray %s", tray_id)
            outcome[tray_id] = str(exc)
    return outcome


def start_scheduler() -> AsyncIOScheduler | None:
    """Start the scheduler if enabled. Must be called from inside the running event loop (app lifespan)."""
    global _scheduler
    if not settings.policy_scheduler_enabled:
        return None
    if not settings.policy_scheduler_tray_list:
        logger.warning("POLICY_SCHEDULER_ENABLED is true but POLICY_SCHEDULER_TRAY_IDS is empty; not starting")
        return None
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_policy_cycle,
        "interval",
        minutes=settings.policy_scheduler_interval_minutes,
        id="adaptive_irrigation_policy",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Policy scheduler started for trays %s", settings.policy_scheduler_tray_list)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
