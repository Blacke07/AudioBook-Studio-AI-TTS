"""API gate concurrency and cancellation, without services or inference."""
import asyncio
import unittest
from project_access import ProjectAccess


class ProjectAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_readers_share_access_and_writer_waits_for_all_readers(self):
        gate=ProjectAccess()
        entered=asyncio.Event()
        async def writer():
            async with gate.hold(write=True):
                entered.set()
        async with gate.hold():
            async with gate.hold():
                task=asyncio.create_task(writer())
                await asyncio.sleep(0)
                self.assertFalse(entered.is_set())
            self.assertFalse(entered.is_set())
        await asyncio.wait_for(task,1)
        self.assertTrue(entered.is_set())

    async def test_cancelled_waiting_writer_does_not_strand_readers(self):
        gate=ProjectAccess()
        async def writer():
            async with gate.hold(write=True):
                self.fail('Writer entered while a reader was active')
        async with gate.hold():
            task=asyncio.create_task(writer())
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            async with asyncio.timeout(1):
                async with gate.hold():
                    pass

    async def test_waiting_writer_precedes_new_readers(self):
        gate=ProjectAccess()
        order=[]
        async def enter(write):
            async with gate.hold(write=write):
                order.append('writer' if write else 'reader')
        async with gate.hold():
            writer=asyncio.create_task(enter(True))
            await asyncio.sleep(0)
            reader=asyncio.create_task(enter(False))
            await asyncio.sleep(0)
        await asyncio.wait_for(asyncio.gather(writer,reader),1)
        self.assertEqual(order,['writer','reader'])
