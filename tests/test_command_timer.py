import asyncio
from datetime import timedelta
from typing import Tuple
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time
from iterm2 import PromptMonitor

from scripts.command_timer import Timer, CommandMonitorManager


class TestTimerOutput:
    def test_never_started(self):
        timer = Timer()
        assert timer.formatted_duration == ""

    @pytest.mark.parametrize(
        ("duration_seconds", "expected_duration_string"),
        [
            (0, ""),
            (1, ""),
            (2, "2s"),
            (20, "20s"),
            (60, "1:00"),
            (65, "1:05"),
            (60 * 60, "1:00:00"),
            (60 * 60 + 65, "1:01:05"),
            (60 * 60 * 15 + 60 * 45 + 23, "15:45:23"),
        ],
    )
    def test_running_and_stopped(self, duration_seconds, expected_duration_string):
        def _parse_result(result_string: str) -> Tuple[str, str]:
            if result_string == "":
                return "", ""

            i, d = result_string.split(" ")
            return i, d

        with freeze_time("2021-03-14T01:55:00") as frozen_time:
            timer = Timer()
            timer.start()

            frozen_time.tick(delta=timedelta(seconds=duration_seconds))

            icon, duration_string = _parse_result(timer.formatted_duration)
            if expected_duration_string != "":
                assert icon == Timer.ICON_RUNNING, "Icon was not the running icon"
            assert duration_string == expected_duration_string

            timer.stop()

            icon, duration_string = _parse_result(timer.formatted_duration)
            if expected_duration_string != "":
                assert icon == Timer.ICON_STOPPED, "Icon was not the stopped icon"
            assert duration_string == expected_duration_string

            frozen_time.tick(delta=timedelta(minutes=15))

            icon, duration_string = _parse_result(timer.formatted_duration)
            if expected_duration_string != "":
                assert icon == Timer.ICON_STOPPED, "Icon was not the stopped icon"
            assert (
                duration_string == expected_duration_string
            ), "Time should not have advanced after stopping"


class FakePM:
    def __init__(self, queue):
        self.__queue = queue

    async def async_get(self):
        item = await self.__queue.get()
        self.__queue.task_done()
        return item

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_command_monitor(event_loop: asyncio.AbstractEventLoop):
    queue = asyncio.Queue()
    manager = CommandMonitorManager(lambda sid: FakePM(queue))

    session_id = "abc"

    with manager.instance_for_session_id(session_id) as monitor:
        monitor.timer = MagicMock(spec=Timer)
        assert manager.get_timer_for_session_id_or_none(session_id) is monitor.timer

        monitor_task = event_loop.create_task(monitor.command_monitor())

        await queue.put((PromptMonitor.Mode.COMMAND_START, "ls"))
        await queue.join()
        monitor.timer.start.assert_called_once()
        monitor.timer.stop.assert_not_called()

        monitor.timer.reset_mock()

        await queue.put((PromptMonitor.Mode.PROMPT, None))
        await queue.join()
        monitor.timer.start.assert_not_called()
        monitor.timer.stop.assert_called_once()

        monitor_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await monitor_task

    assert manager.get_timer_for_session_id_or_none(session_id) is None
