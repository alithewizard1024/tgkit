"""One asyncio loop in a background thread. Telethon runs only on this loop.

Why this design: user code is plain, synchronous Python. Any thread may call the bot
(including hooks), and the call is handed to the loop, which waits for the result.
The loop itself never runs user code, because hooks run in worker threads."""
import asyncio
import threading


async def _as_coroutine(awaitable):
    return await awaitable


def _discard(awaitable):
    if asyncio.iscoroutine(awaitable):
        awaitable.close()


class Runtime:
    def __init__(self):
        self._loop = None
        self._thread = None
        self._lock = threading.Lock()

    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lock:
            if self.running():
                return
            ready = threading.Event()

            def target():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                ready.set()
                self._loop.run_forever()

            self._thread = threading.Thread(target=target, name="tgkit-loop", daemon=True)
            self._thread.start()
            ready.wait()

    def call(self, awaitable, timeout=None):
        """Runs an awaitable on the loop and returns its result. Blocks the calling thread.

        Telethon sometimes returns Futures or Tasks instead of coroutines (disconnect does),
        so anything awaitable is accepted and wrapped in a coroutine first."""
        if not self.running():
            _discard(awaitable)
            raise RuntimeError("the runtime is not started")
        if threading.current_thread() is self._thread:
            _discard(awaitable)
            raise RuntimeError("call() from inside the loop would deadlock; use 'await' there")
        return asyncio.run_coroutine_threadsafe(_as_coroutine(awaitable), self._loop).result(timeout)

    def stop(self):
        with self._lock:
            if not self.running():
                return
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=10)
            self._loop.close()
            self._thread = None
            self._loop = None
