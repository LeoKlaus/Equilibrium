import asyncio
import logging
import threading

from api.log_broadcaster import LogBroadcaster


def _make_record(message: str, logger_name: str = "some.module", level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name=logger_name, level=level, pathname=__file__, lineno=1,
        msg=message, args=(), exc_info=None,
    )


async def test_emit_appends_a_formatted_line_to_the_backlog():
    broadcaster = LogBroadcaster(asyncio.get_running_loop())

    broadcaster.emit(_make_record("hello", level=logging.WARNING))
    await asyncio.sleep(0)  # wait for call_soon_threadsafe callback

    assert len(broadcaster.backlog) == 1
    line = broadcaster.backlog[0]
    assert line.message == "hello"
    assert line.level == "WARNING"
    assert line.logger == "some.module"
    assert "hello" in line.formatted
    assert line.timestamp


async def test_backlog_is_bounded():
    broadcaster = LogBroadcaster(asyncio.get_running_loop(), backlog_size=3)

    for i in range(5):
        broadcaster.emit(_make_record(f"line {i}"))
    await asyncio.sleep(0)

    assert len(broadcaster.backlog) == 3
    assert [line.message for line in broadcaster.backlog] == ["line 2", "line 3", "line 4"]


async def test_emit_broadcasts_to_connected_clients():
    broadcaster = LogBroadcaster(asyncio.get_running_loop())
    received = []

    class FakeConnection:
        async def send_json(self, message):
            received.append(message)

    broadcaster.manager.active_connections.append(FakeConnection())

    broadcaster.emit(_make_record("pushed live"))
    # Two hops needed: one for the call_soon_threadsafe callback to run
    # (schedules the broadcast Task), one more for that Task itself to run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0]["message"] == "pushed live"


async def test_emit_is_safe_to_call_from_another_thread():
    # ir_manager/rf_manager/ha_manager log from inside loop.run_in_executor
    # worker threads, not the event loop's own thread - emit() must not
    # assume it's already running on the loop.
    loop = asyncio.get_running_loop()
    broadcaster = LogBroadcaster(loop)

    thread = threading.Thread(target=broadcaster.emit, args=(_make_record("from a worker thread"),))
    thread.start()
    thread.join()
    await asyncio.sleep(0)

    assert any(line.message == "from a worker thread" for line in broadcaster.backlog)


async def test_emit_does_not_raise_when_the_loop_is_already_closed():
    # A closed-loop RuntimeError from call_soon_threadsafe must not
    # propagate - logging.Handler.emit() is contractually not allowed
    # to raise, and the backlog write should still succeed either way.
    other_loop = asyncio.new_event_loop()
    other_loop.close()
    broadcaster = LogBroadcaster(other_loop)

    broadcaster.emit(_make_record("after loop closed"))  # must not raise

    assert broadcaster.backlog[-1].message == "after loop closed"
