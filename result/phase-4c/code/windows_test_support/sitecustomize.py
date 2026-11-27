"""Use named-pipe wakeups in in-process ASGI tests and their restart subprocesses."""

import asyncio
from asyncio import windows_utils
import _winapi


class PipeLoop(asyncio.ProactorEventLoop):
    def _make_self_pipe(self):
        read, write = windows_utils.pipe(overlapped=(True, False))
        self._ssock = windows_utils.PipeHandle(read)
        self._csock = windows_utils.PipeHandle(write)
        self._internal_fds += 1

    def _write_to_self(self):
        if self._csock is not None:
            try:
                _winapi.WriteFile(self._csock.fileno(), b"\0", overlapped=False)
            except (OSError, ValueError):
                pass


class PipeLoopPolicy(asyncio.WindowsProactorEventLoopPolicy):
    _loop_factory = PipeLoop


def install():
    asyncio.set_event_loop_policy(PipeLoopPolicy())


install()
