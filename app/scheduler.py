import asyncio
import logging
import os
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.services.re_engagement import run_reengagement_job

log = logging.getLogger("scheduler")

REENGAGEMENT_ENABLED = os.getenv("REENGAGEMENT_ENABLED", "true").lower() == "true"
REENGAGEMENT_INTERVAL_HOURS = int(os.getenv("REENGAGEMENT_INTERVAL_HOURS", "24"))
REENGAGEMENT_INACTIVE_DAYS = int(os.getenv("REENGAGEMENT_INACTIVE_DAYS", "3"))
REENGAGEMENT_MIN_BALANCE_CENTS = int(os.getenv("REENGAGEMENT_MIN_BALANCE_CENTS", "500"))

_scheduler_task: asyncio.Task | None = None


async def _run_reengagement_once():
    async with SessionLocal() as db:
        try:
            result = await run_reengagement_job(
                db=db,
                inactive_days=REENGAGEMENT_INACTIVE_DAYS,
                min_balance_cents=REENGAGEMENT_MIN_BALANCE_CENTS,
                dry_run=False,
            )
            log.info(
                f"[SCHEDULER] Re-engagement job complete: "
                f"eligible={result.get('eligible_count', 0)}, "
                f"sent={result.get('sent_count', 0)}, "
                f"failed={result.get('failed_count', 0)}"
            )
            return result
        except Exception as e:
            log.exception(f"[SCHEDULER] Re-engagement job failed: {e}")
            return {"error": str(e)}


async def _scheduler_loop():
    interval_seconds = REENGAGEMENT_INTERVAL_HOURS * 3600
    
    log.info(
        f"[SCHEDULER] Starting re-engagement scheduler: "
        f"interval={REENGAGEMENT_INTERVAL_HOURS}h, "
        f"inactive_days={REENGAGEMENT_INACTIVE_DAYS}, "
        f"min_balance=${REENGAGEMENT_MIN_BALANCE_CENTS/100:.0f}"
    )
    
    await asyncio.sleep(60)
    
    while True:
        try:
            log.info(f"[SCHEDULER] Running re-engagement job at {datetime.now(timezone.utc).isoformat()}")
            await _run_reengagement_once()
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Scheduler cancelled, shutting down")
            break
        except Exception as e:
            log.exception(f"[SCHEDULER] Unexpected error: {e}")
        
        log.info(f"[SCHEDULER] Next run in {REENGAGEMENT_INTERVAL_HOURS} hours")
        await asyncio.sleep(interval_seconds)


def start_scheduler():
    global _scheduler_task
    
    if not REENGAGEMENT_ENABLED:
        log.info("[SCHEDULER] Re-engagement scheduler is disabled (REENGAGEMENT_ENABLED=false)")
        return
    
    if _scheduler_task is not None:
        log.warning("[SCHEDULER] Scheduler already running")
        return
    
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    log.info("[SCHEDULER] Re-engagement scheduler started")


def stop_scheduler():
    global _scheduler_task
    
    if _scheduler_task is not None:
        _scheduler_task.cancel()
        _scheduler_task = None
        log.info("[SCHEDULER] Re-engagement scheduler stopped")
