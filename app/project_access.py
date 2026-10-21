"""Concurrent API readers; exclusive project changes. Dialogs do not acquire this gate."""
import asyncio
from contextlib import asynccontextmanager


class ProjectAccess:
    def __init__(self):
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @asynccontextmanager
    async def hold(self, write=False):
        async with self._condition:
            if write:
                self._waiting_writers += 1
                try:
                    await self._condition.wait_for(lambda:not self._writer and not self._readers)
                    self._writer = True
                finally:
                    self._waiting_writers -= 1
                    self._condition.notify_all()
            else:
                await self._condition.wait_for(lambda:not self._writer and not self._waiting_writers)
                self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                if write:
                    self._writer = False
                else:
                    self._readers -= 1
                self._condition.notify_all()
