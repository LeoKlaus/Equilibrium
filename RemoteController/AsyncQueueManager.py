import asyncio

class AsyncQueueManager:

    def __init__(self):
        self.loop = asyncio.get_event_loop()

        self.sem = asyncio.Semaphore(n := 1)
        #threading.Thread(target=self.loop.run_forever).start()

    async def _task_wrapper(self, coro):
        await self.sem.acquire()
        await coro
        self.sem.release()

    def enqueue_task(self, coro):
        asyncio.run_coroutine_threadsafe(self._task_wrapper(coro), self.loop)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)