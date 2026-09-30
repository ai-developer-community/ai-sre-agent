import asyncio
import logging
import threading

from sre_agent.telemetry import sanitize

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, store, runner):
        self.store, self.runner = store, runner
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
        try:
            # One leader across local processes. The dedicated session releases on crash.
            with self.store.engine.connect() as lock:
                leader = lock.exec_driver_sql("SELECT pg_try_advisory_lock(734202)").scalar()
                lock.commit()
                if not leader:
                    self.error = "Another backend already owns the agent worker."
                    return
                self.store.recover_interrupted()
                try:
                    while not self.stop_event.is_set():
                        # Check the lock-owning connection before claiming each read-only run.
                        lock.exec_driver_sql("SELECT 1")
                        lock.commit()
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
                    lock.exec_driver_sql("SELECT pg_advisory_unlock(734202)")
                    lock.commit()
        except Exception:
            logger.exception("Worker stopped")
            self.error = (
                "Worker stopped. Check backend logs and restart after fixing the connection."
            )
