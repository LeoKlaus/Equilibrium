import asyncio
import logging


class AsyncQueueManager:

    def __init__(self):
        self.logger = logging.getLogger(__package__)
        self.loop = asyncio.get_event_loop()

        self.sem = asyncio.Semaphore(n := 1)

    async def _task_wrapper(self, coro):
        await self.sem.acquire()
        try:
            await coro
        except Exception as e:
            self.logger.exception(e)
        self.sem.release()

    def enqueue_task(self, coro):
        asyncio.run_coroutine_threadsafe(self._task_wrapper(coro), self.loop)

    async def _sync_task_wrapper(self, task, *args):
        await self.sem.acquire()
        try:
            task(args)
        except Exception as e:
            self.logger.exception("message")
        self.sem.release()

    def enqueue_sync_task(self, task, *args):
        asyncio.run_coroutine_threadsafe(self._sync_task_wrapper(task, args), self.loop)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)