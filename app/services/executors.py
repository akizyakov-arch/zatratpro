import asyncio
import os
from concurrent.futures import Executor, ThreadPoolExecutor
from functools import partial


_blocking_executor: ThreadPoolExecutor | None = None


def _default_max_workers() -> int:
    cpu_count = os.cpu_count() or 1
    return max(4, min(8, cpu_count))


def get_blocking_executor() -> ThreadPoolExecutor:
    global _blocking_executor
    if _blocking_executor is None:
        _blocking_executor = ThreadPoolExecutor(
            max_workers=_default_max_workers(),
            thread_name_prefix="zatratpro-blocking",
        )
    return _blocking_executor


async def run_blocking(func, /, *args, **kwargs):
    loop = asyncio.get_running_loop()
    call = partial(func, *args, **kwargs)
    return await loop.run_in_executor(get_blocking_executor(), call)


def _shutdown_executor(executor: Executor) -> None:
    executor.shutdown(wait=True, cancel_futures=False)


async def close_executors() -> None:
    global _blocking_executor
    if _blocking_executor is None:
        return
    executor = _blocking_executor
    _blocking_executor = None
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _shutdown_executor, executor)
