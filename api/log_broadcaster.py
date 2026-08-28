import asyncio
import contextlib
import logging
from collections import deque

from api import LOG_FORMAT
from api.models.log_line import LogLine
from api.websocket_connection_manager.websocket_connection_manager import WebsocketConnectionManager

DEFAULT_BACKLOG_SIZE = 200


class LogBroadcaster(logging.Handler):
    """Attached to the root logger for the app's lifetime (see
    api.lifespan) to back both GET /system/logs and the /ws/logs
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, backlog_size: int = DEFAULT_BACKLOG_SIZE):
        super().__init__()
        self.setFormatter(logging.Formatter(LOG_FORMAT))
        self._loop = loop
        self.manager = WebsocketConnectionManager()
        self.backlog: deque[LogLine] = deque(maxlen=backlog_size)
        # Keeps broadcast tasks alive until they finish - asyncio only
        # holds a weak reference to a task once nothing else does, so an
        # unreferenced fire-and-forget task can be garbage-collected
        # mid-flight.
        self._pending_broadcasts: set[asyncio.Task] = set()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # self.format() populates record.asctime (it's referenced
            # in LOG_FORMAT) before returning the fully formatted line.
            formatted = self.format(record)
            line = LogLine(
                timestamp=record.asctime,
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
                formatted=formatted,
            )
        except Exception:
            self.handleError(record)
            return

        self.backlog.append(line)
        with contextlib.suppress(RuntimeError):  # loop already closed (e.g. shutting down)
            self._loop.call_soon_threadsafe(self._schedule_broadcast, line)

    def _schedule_broadcast(self, line: LogLine) -> None:
        # Reached via call_soon_threadsafe, so this itself always runs
        # on the captured loop's own thread - safe to create the task
        # here no matter which thread emit() ran on.
        task = asyncio.ensure_future(self.manager.broadcast_json(line), loop=self._loop)
        self._pending_broadcasts.add(task)
        task.add_done_callback(self._pending_broadcasts.discard)
