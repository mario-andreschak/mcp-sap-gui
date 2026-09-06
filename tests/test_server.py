import asyncio
import base64
from io import BytesIO
from PIL import Image
import pytest
from sap_gui_server.config import Config, SapError
from sap_gui_server.server import SapGuiServer
from sap_gui_server.worker import SapWorker
from tests.fake_worker import hang, echo


class Fake:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result or {"status": "ok"}
        self.error = error

    async def call(self, method, args):
        self.calls.append((method, args))
        if self.error:
            raise self.error
        return dict(self.result)

    async def close(self):
        pass


async def test_catalog_preserves_original_tools_and_adds_control_paths():
    s = SapGuiServer(worker=Fake())
    tools = await s.server.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "launch_transaction",
        "sap_click",
        "sap_move_mouse",
        "sap_type",
        "sap_scroll",
        "end_transaction",
        "save_last_screenshot",
        "sap_get_screen",
        "sap_set_field",
        "sap_press",
        "sap_send_vkey",
        "sap_run_guixt_script",
    }
    with pytest.raises(Exception):
        await s.server.call_tool("sap_click", {"x": -1, "y": 0})
    assert not s.worker.calls


async def test_execution_errors_are_marked_and_raw_exception_is_scrubbed():
    s = SapGuiServer(worker=Fake(error=RuntimeError("secret-canary")))
    result = await s.server.call_tool("end_transaction", {})
    assert result.is_error
    assert "secret-canary" not in str(result)
    s.worker.error = SapError("Complete SSO login")
    result = await s.server.call_tool("end_transaction", {})
    assert result.is_error and "Complete SSO" in result.content[0].text


async def test_screenshot_blob_and_output_jailed_before_side_effect(tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    worker = Fake(result={"status": "ok", "image": encoded})
    s = SapGuiServer(Config(output_root=str(tmp_path)), worker=worker)
    r = await s.server.call_tool("sap_get_screen", {"return_screenshot": "as_imageurl"})
    assert r.content[1].resource.blob == encoded
    assert r.content[1].resource.mime_type == "image/png"
    r = await s.server.call_tool("save_last_screenshot", {"filename": "capture.png"})
    assert not r.is_error and (tmp_path / "capture.png").is_file()
    r = await s.server.call_tool("save_last_screenshot", {"filename": "capture.png"})
    assert r.is_error
    count = len(worker.calls)
    r = await s.server.call_tool(
        "sap_click", {"x": 0, "y": 0, "return_screenshot": "as_file", "as_file_target_folder": "../escape"}
    )
    assert r.is_error and len(worker.calls) == count


async def test_worker_actual_spawn_and_orderly_release():
    worker = SapWorker(Config(timeout=4), target=echo)
    assert await worker.call("one", {}) == {"method": "one"}
    assert await worker.call("two", {}) == {"method": "two"}
    await worker.close()
    assert worker.process is None


async def test_worker_timeout_terminates_only_owned_worker_and_refuses_retry():
    worker = SapWorker(Config(timeout=0.4), target=hang)
    with pytest.raises(TimeoutError):
        await worker.call("hang", {})
    assert worker.process is None and worker.tainted
    with pytest.raises(SapError, match="previous operation"):
        await worker.call("again", {})


async def test_worker_cancellation_cannot_leave_queued_input_running():
    worker = SapWorker(Config(timeout=5), target=hang)
    task = asyncio.create_task(worker.call("hang", {}))
    await asyncio.sleep(0.25)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.tainted and worker.process is None
