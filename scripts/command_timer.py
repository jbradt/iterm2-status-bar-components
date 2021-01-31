import asyncio
import time
from contextlib import contextmanager
from math import floor
from typing import Callable

from iterm2 import (
    StatusBarComponent,
    async_get_app,
    PromptMonitor,
    StatusBarRPC,
    run_forever,
    EachSessionOnceMonitor,
    Reference,
    Session,
    Connection,
)


class Timer:
    ICON_RUNNING = ""
    ICON_STOPPED = ""
    THRESHOLD = 2  # seconds

    def __init__(self):
        self._start_time = None
        self._stop_time = None

    def start(self):
        self._start_time = time.monotonic()
        self._stop_time = None

    def stop(self):
        if self._stop_time is None:
            self._stop_time = time.monotonic()

    @property
    def icon(self):
        if self._stop_time is None:
            return self.ICON_RUNNING
        else:
            return self.ICON_STOPPED

    @property
    def duration(self):
        if self._start_time is None:
            return 0

        stop_time = self._stop_time if self._stop_time is not None else time.monotonic()
        return int(floor(stop_time - self._start_time))

    @property
    def formatted_duration(self):
        duration = self.duration
        if duration < self.THRESHOLD:
            return ""

        if duration >= 3600:
            minutes, seconds = divmod(duration, 60)
            hours, minutes = divmod(minutes, 60)
            return f"{self.icon} {hours}:{minutes:02g}:{seconds:02g}"

        if duration >= 60:
            minutes, seconds = divmod(duration, 60)
            return f"{self.icon} {minutes}:{seconds:02g}"

        return f"{self.icon} {duration}s"


PromptMonitorFactoryType = Callable[[str], PromptMonitor]


class CommandMonitor:
    def __init__(self, session_id: str, pm_factory: PromptMonitorFactoryType):
        self.timer = Timer()
        self.session_id = session_id
        self._build_pm = pm_factory

    async def command_monitor(self):
        try:
            async with self._build_pm(self.session_id) as mon:
                print(f"Started monitoring session {self.session_id}")
                while True:
                    mode, info = await mon.async_get()
                    print(f"Session {self.session_id} received {mode}")
                    if mode == PromptMonitor.Mode.COMMAND_START and info:
                        self.timer.start()
                    elif mode in (PromptMonitor.Mode.COMMAND_END, PromptMonitor.Mode.PROMPT):
                        self.timer.stop()
        finally:
            print(f"Stopped monitoring session {self.session_id}")


class CommandMonitorManager:
    def __init__(self, pm_factory: PromptMonitorFactoryType):
        self._pm_factory = pm_factory
        self._instances = {}

    @contextmanager
    def instance_for_session_id(self, session_id):
        try:
            instance = CommandMonitor(session_id, self._pm_factory)
            self._instances[session_id] = instance
            yield instance
        finally:
            del self._instances[session_id]

    def get_timer_for_session_id_or_none(self, session_id):
        instance = self._instances.get(session_id)
        if instance is not None:
            return instance.timer


ALL_MODES = [
    PromptMonitor.Mode.COMMAND_START,
    PromptMonitor.Mode.COMMAND_END,
    PromptMonitor.Mode.PROMPT,
]


async def main(connection):
    app = await async_get_app(connection)

    component = StatusBarComponent(
        short_description="Running Command Timer",
        detailed_description="Shows the execution time of the current command",
        knobs=[],
        exemplar=f"{Timer.ICON_RUNNING} 45s",
        update_cadence=1,
        identifier="local.jbradt.command-timer",
    )

    monitor_manager = CommandMonitorManager(
        pm_factory=lambda sid: PromptMonitor(connection, sid, ALL_MODES)
    )

    @StatusBarRPC
    async def status_bar_update(knobs, session_id=Reference("id")):
        timer = monitor_manager.get_timer_for_session_id_or_none(session_id)
        if timer:
            return timer.formatted_duration

        return ""

    async def monitor_commands(session_id: str):
        with monitor_manager.instance_for_session_id(session_id) as monitor:
            await monitor.command_monitor()

    await component.async_register(connection, status_bar_update)
    await EachSessionOnceMonitor.async_foreach_session_create_task(
        app, monitor_commands
    )


if __name__ == "__main__":
    run_forever(main)
