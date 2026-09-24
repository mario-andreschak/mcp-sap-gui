"""One serialized STA worker process. Only our worker is terminated on timeout."""

import asyncio
import multiprocessing
import sys
import time
from .config import Config, SapError


def _work(pipe, config):
    sys.stdout = sys.stderr
    initialized = False
    controller = None
    try:
        if sys.platform == "win32":
            import pythoncom

            pythoncom.CoInitialize()
            initialized = True
        from .sap_controller import SapController

        controller = SapController(config)
        while True:
            request = pipe.recv()
            if request is None:
                break
            try:
                result = controller.execute(request["method"], request["arguments"])
                pipe.send({"result": result})
            except SapError as exc:
                pipe.send({"error": str(exc)})
            except Exception:
                # COM exceptions can contain form data, login or command details.
                pipe.send(
                    {
                        "error": "SAP operation failed. Inspect the selected SAP window, scripting permissions and configured element ID."
                    }
                )
    except (EOFError, BrokenPipeError):
        pass
    finally:
        if controller is not None:
            controller.close()
        if initialized:
            import pythoncom

            pythoncom.CoUninitialize()
        pipe.close()


class SapWorker:
    def __init__(self, config: Config, *, target=_work):
        self.config = config
        self.target = target
        self.lock = asyncio.Lock()
        self.process = None
        self.pipe = None
        self.tainted = False

    def _start(self):
        ctx = multiprocessing.get_context("spawn")
        self.pipe, child = ctx.Pipe()
        self.process = ctx.Process(target=self.target, args=(child, self.config), daemon=True)
        self.process.start()
        child.close()

    def _terminate(self):
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=2)
            self.process.close()
            self.process = None
        if self.pipe is not None:
            self.pipe.close()
            self.pipe = None

    async def call(self, method: str, arguments: dict):
        deadline = time.monotonic() + self.config.timeout
        async with asyncio.timeout(self.config.timeout):
            async with self.lock:
                if self.tainted:
                    raise SapError(
                        "A previous operation timed out or was cancelled. Inspect SAP and restart this MCP server before more input."
                    )
                if self.process is None:
                    self._start()
                try:
                    self.pipe.send({"method": method, "arguments": arguments})
                    while not self.pipe.poll():
                        if not self.process.is_alive():
                            raise SapError("SAP worker exited; inspect SAP and restart this MCP server")
                        if time.monotonic() >= deadline:
                            raise TimeoutError()
                        await asyncio.sleep(0.02)
                    response = self.pipe.recv()
                    if "error" in response:
                        raise SapError(response["error"])
                    return response["result"]
                except (asyncio.CancelledError, TimeoutError, EOFError, BrokenPipeError):
                    self.tainted = True
                    self._terminate()
                    raise

    async def close(self):
        self.tainted = True
        if self.pipe is not None:
            try:
                self.pipe.send(None)
            except (EOFError, BrokenPipeError, OSError):
                pass
            deadline = time.monotonic() + 1
            while self.process.is_alive() and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
        self._terminate()
