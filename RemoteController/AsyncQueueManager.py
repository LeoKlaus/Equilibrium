import asyncio

class AsyncQueueManager:

    def __init__(self):
        self.loop = asyncio.get_event_loop()

        self.sem = asyncio.Semaphore(n := 1)

    async def _task_wrapper(self, coro):
        await self.sem.acquire()
        await coro
        self.sem.release()

    def enqueue_task(self, coro):
        asyncio.run_coroutine_threadsafe(self._task_wrapper(coro), self.loop)

    async def _sync_task_wrapper(self, task):
        await self.sem.acquire()
        task()
        self.sem.release()

    def enqueue_sync_task(self, task):
        asyncio.run_coroutine_threadsafe(self._sync_task_wrapper(task), self.loop)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)