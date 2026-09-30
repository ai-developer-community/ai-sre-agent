import asyncio
import logging
import threading

from sre_agent.telemetry import sanitize

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, store, runner, rollbacks=None):
        self.store, self.runner = store, runner
        self.rollbacks = rollbacks
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True, name="investigator")
        self.busy = False
        self.error = None

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.lead()
            except Exception:
                logger.exception("Worker connection failed; retrying")
                self.error = "Worker connection unavailable. Retrying; check backend logs."
            self.stop_event.wait(1)

    def lead(self):
        # Standby instances retry until the previous revision finishes its active run.
        # Keep this dedicated session until that run exits, including during shutdown.
        with self.store.engine.connect() as lock:
            leader = False
            try:
                leader = lock.exec_driver_sql("SELECT pg_try_advisory_lock(734202)").scalar()
                lock.commit()
                if not leader:
                    self.error = "Another backend owns the agent worker. Waiting for leadership."
                    return
                self.error = None
                self.store.recover_interrupted()
                if self.rollbacks:
                    self.rollbacks.recover_interrupted()
                while not self.stop_event.is_set():
                    lock.exec_driver_sql("SELECT 1")
                    lock.commit()
                    action = self.rollbacks.claim() if self.rollbacks else None
                    if action:
                        self.busy = True
                        try:
                            self.rollbacks.execute(action)
                        finally:
                            self.busy = False
                        continue
                    run = self.store.claim()
                    if not run:
                        self.stop_event.wait(0.5)
                        continue
                    self.busy = True
                    try:
                        result = asyncio.run(self.runner.run(run))
                        self.store.finish(run, result)
                    except Exception as exc:
                        logger.exception("Investigation failed")
                        message = sanitize(str(exc))[:500]
                        self.store.finish(
                            run,
                            f"Investigation failed: {message}\nNo diagnosis was established. "
                            "Check credentials/model configuration, "
                            "then send a message to retry.",
                            failed=True,
                        )
                    finally:
                        self.busy = False
            finally:
                if leader:
                    try:
                        lock.exec_driver_sql("SELECT pg_advisory_unlock(734202)")
                        lock.commit()
                    except Exception:
                        # Never return a potentially locked session to the pool.
                        lock.invalidate()
                        raise
