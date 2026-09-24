"""Modern MCP 2026-07-28 and deliberate legacy stdio support via public SDK2 APIs."""

import base64
from contextlib import asynccontextmanager
from io import BytesIO
import json
import logging
import os
from typing import Annotated, Literal
from uuid import uuid4
from dotenv import load_dotenv
from mcp.server import MCPServer
import mcp.types as types
from pydantic import Field
from . import __version__
from .config import Config, SapError, jailed_path
from .worker import SapWorker

ScreenshotMode = Literal["none", "as_file", "as_base64", "as_imagecontent", "as_imageurl"]
Coordinate = Annotated[int, Field(strict=True, ge=0, le=100000)]
ShortText = Annotated[str, Field(max_length=10000)]
ElementId = Annotated[str, Field(min_length=6, max_length=1024)]


class SapGuiServer:
    def __init__(self, config: Config | None = None, *, worker=None):
        self.config = config or Config.from_env()
        self.worker = worker or SapWorker(self.config)
        self.last_screenshot = None

        @asynccontextmanager
        async def lifespan(_server):
            try:
                yield None
            finally:
                await self.worker.close()

        self.server = MCPServer(
            "mcp-sap-gui",
            version=__version__,
            lifespan=lifespan,
            instructions="Operate only the configured SAP session. SSO is the local Windows/SAP identity. Read current screen before changing it.",
        )
        self._setup_tools()

    def _save(self, filename, image):
        from PIL import Image

        target = jailed_path(self.config.output_root, filename)
        if target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
            raise SapError("Screenshot filename must use PNG, JPEG or BMP")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Re-resolve after parent creation; never overwrite an existing artifact.
        target = jailed_path(self.config.output_root, str(target))
        picture = Image.open(BytesIO(base64.b64decode(image, validate=True)))
        fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".bmp": "BMP"}[target.suffix.lower()]
        with target.open("xb") as output:
            picture.convert("RGB").save(output, format=fmt)
        return str(target)

    async def _call(self, method, arguments, screenshot="none", folder=None):
        try:
            if screenshot == "as_file" and not folder:
                raise SapError("as_file_target_folder is required for as_file")
            if screenshot == "as_file":
                # Check before any SAP side effect.
                jailed_path(self.config.output_root, os.path.join(folder, "check.png"))
            result = await self.worker.call(method, {**arguments, "capture": screenshot != "none"})
            image = result.pop("image", None)
            content = [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
            if image:
                self.last_screenshot = image
                if screenshot == "as_base64":
                    content.append(types.TextContent(type="text", text=image))
                elif screenshot == "as_imagecontent":
                    content.append(types.ImageContent(type="image", data=image, mime_type="image/png"))
                elif screenshot == "as_imageurl":
                    content.append(
                        types.EmbeddedResource(
                            type="resource",
                            resource=types.BlobResourceContents(
                                uri=f"sap-gui://screenshots/{uuid4().hex}.png",
                                mime_type="image/png",
                                blob=image,
                            ),
                        )
                    )
                elif screenshot == "as_file":
                    path = self._save(os.path.join(folder, f"sap-{uuid4().hex}.png"), image)
                    content.append(types.TextContent(type="text", text=f"Screenshot saved as {path}"))
            return types.CallToolResult(content=content)
        except TimeoutError:
            return self._error(
                "SAP operation exceeded its deadline; inspect SAP before restarting the MCP server"
            )
        except SapError as exc:
            return self._error(str(exc))
        except Exception:
            return self._error(
                "SAP operation or screenshot output failed; inspect configuration and the selected SAP session"
            )

    @staticmethod
    def _error(message):
        return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text=message)])

    def _setup_tools(self):
        tool = self.server.tool

        @tool(structured_output=False)
        async def launch_transaction(
            transaction: Annotated[str, Field(min_length=1, max_length=80)],
            return_screenshot: ScreenshotMode = "none",
            as_file_target_folder: str | None = None,
        ) -> types.CallToolResult:
            """Start a transaction in the configured session; preserves unrelated SAP sessions."""
            return await self._call(
                "launch_transaction", {"transaction": transaction}, return_screenshot, as_file_target_folder
            )

        @tool(structured_output=False)
        async def sap_click(
            x: Coordinate,
            y: Coordinate,
            return_screenshot: ScreenshotMode = "none",
            as_file_target_folder: str | None = None,
        ) -> types.CallToolResult:
            """Click physical screenshot pixels relative to the selected SAP window."""
            return await self._call(
                "pixel", {"action": "click", "x": x, "y": y}, return_screenshot, as_file_target_folder
            )

        @tool(structured_output=False)
        async def sap_move_mouse(
            x: Coordinate,
            y: Coordinate,
            return_screenshot: ScreenshotMode = "none",
            as_file_target_folder: str | None = None,
        ) -> types.CallToolResult:
            """Move within the selected SAP window using physical screenshot pixels."""
            return await self._call(
                "pixel", {"action": "move", "x": x, "y": y}, return_screenshot, as_file_target_folder
            )

        @tool(structured_output=False)
        async def sap_type(
            text: ShortText,
            return_screenshot: ScreenshotMode = "none",
            as_file_target_folder: str | None = None,
        ) -> types.CallToolResult:
            """Type WScript SendKeys text/special keys in the selected SAP window. Use sap_set_field for literal text."""
            return await self._call(
                "pixel", {"action": "type", "text": text}, return_screenshot, as_file_target_folder
            )

        @tool(structured_output=False)
        async def sap_scroll(
            direction: Literal["up", "down"],
            return_screenshot: ScreenshotMode = "none",
            as_file_target_folder: str | None = None,
        ) -> types.CallToolResult:
            """Scroll the selected SAP window."""
            return await self._call(
                "pixel",
                {"action": "scroll", "direction": direction},
                return_screenshot,
                as_file_target_folder,
            )

        @tool(structured_output=False)
        async def end_transaction() -> types.CallToolResult:
            """End only the configured session's current transaction. Unsaved work in that transaction can be lost."""
            return await self._call("end_transaction", {})

        @tool(structured_output=False)
        async def save_last_screenshot(
            filename: Annotated[str, Field(min_length=1, max_length=1024)],
        ) -> types.CallToolResult:
            """Save the last requested screenshot under SAP_OUTPUT_ROOT without overwriting a file."""
            try:
                if self.last_screenshot is None:
                    raise SapError(
                        "No screenshot available; request a screenshot with another SAP tool first"
                    )
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=self._save(filename, self.last_screenshot))]
                )
            except SapError as exc:
                return self._error(str(exc))
            except Exception:
                return self._error(
                    "Could not save screenshot; check output path and whether the file already exists"
                )

        @tool(structured_output=False, annotations=types.ToolAnnotations(read_only_hint=True))
        async def sap_get_screen(
            return_screenshot: ScreenshotMode = "none", as_file_target_folder: str | None = None
        ) -> types.CallToolResult:
            """Read up to 300 SAP COM controls and text (password fields redacted), optionally with screenshot."""
            return await self._call("sap_get_screen", {}, return_screenshot, as_file_target_folder)

        @tool(structured_output=False)
        async def sap_set_field(element_id: ElementId, text: ShortText) -> types.CallToolResult:
            """Set literal text through SAP GUI ActiveX/COM scripting, scoped to wnd[N] in this session."""
            return await self._call("sap_set_field", {"element_id": element_id, "text": text})

        @tool(structured_output=False)
        async def sap_press(element_id: ElementId) -> types.CallToolResult:
            """Press a SAP GUI button through its COM interface."""
            return await self._call("sap_press", {"element_id": element_id})

        @tool(structured_output=False)
        async def sap_send_vkey(
            key: Annotated[int, Field(strict=True, ge=0, le=134)],
        ) -> types.CallToolResult:
            """Send a documented SAP virtual key (0 is Enter) to the configured session."""
            return await self._call("sap_send_vkey", {"key": key})

        @tool(structured_output=False)
        async def sap_run_guixt_script(
            script: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+\.txt$")],
        ) -> types.CallToolResult:
            """Submit a preinstalled GuiXT InputScript to this exact SAP window; requires configured GuiXT opt-in. Completion is asynchronous."""
            return await self._call("sap_run_guixt_script", {"script": script})

    async def start(self):
        await self.server.run_stdio_async()


def main():
    load_dotenv(os.getenv("SAP_ENV_FILE", ".env"), override=False)
    logging.basicConfig(level=logging.WARNING)
    app = SapGuiServer()
    app.server.run()


if __name__ == "__main__":
    main()
