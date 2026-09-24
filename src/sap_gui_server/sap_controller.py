"""SAP's public COM scripting API, scoped to one exact SAP GUI session.

Imported safely on all platforms. Windows and desktop modules load only on use.
No process-wide SAP termination, process password arguments, or session auto-selection.
"""

import base64
from io import BytesIO
from pathlib import Path
import re
import subprocess
import sys
import time

from .config import Config, SapError, jailed_path


class SapController:
    def __init__(self, config: Config | None = None, *, application=None):
        self.config = config or Config.from_env()
        self.application = application
        self.session = None
        self.session_id = self.config.session_id

    def _application(self):
        if self.application is not None:
            return self.application
        if sys.platform != "win32":
            raise SapError(
                "SAP tools require SAP GUI for Windows in an interactive desktop; discovery works on other platforms"
            )
        import win32com.client

        try:
            self.application = win32com.client.GetObject("SAPGUI").GetScriptingEngine
        except Exception:
            if self.config.gui_path:
                executable = Path(self.config.gui_path).expanduser().resolve()
                if executable.is_dir():
                    executable /= "saplogon.exe"
                if executable.name.lower() != "saplogon.exe" or not executable.is_file():
                    raise SapError("SAP_GUI_PATH must name an installed saplogon.exe or its directory")
                subprocess.Popen(
                    [str(executable)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                deadline = time.monotonic() + min(10, self.config.timeout)
                while time.monotonic() < deadline:
                    try:
                        self.application = win32com.client.GetObject("SAPGUI").GetScriptingEngine
                        break
                    except Exception:
                        time.sleep(0.2)
            if self.application is None:
                raise SapError("Start SAP Logon, install/enable SAP GUI Scripting, or configure SAP_GUI_PATH")
        return self.application

    def _wait_ready(self):
        deadline = time.monotonic() + min(20, self.config.timeout)
        while self.session.Busy:
            if time.monotonic() >= deadline:
                raise SapError("SAP is still busy; inspect the configured session before retrying")
            time.sleep(0.05)

    def _session(self):
        if self.session is None:
            app = self._application()
            if self.session_id:
                self.session = app.FindById(self.session_id)
            elif self.config.connection:
                connection = app.OpenConnection(self.config.connection, True)
                self.session = connection.Children(0)
                self.session_id = self.session.Id
            else:
                raise SapError(
                    "Configure exact SAP_SESSION_ID for an existing/SSO session or SAP_CONNECTION for a new SAP Logon connection"
                )
            self._wait_ready()
            # Existing sessions must never receive login credentials or switch users.
            if (
                not self.config.session_id
                and self.config.user
                and self.config.password
                and not self.session.Info.User
            ):
                self.session.FindById("wnd[0]/usr/txtRSYST-MANDT").Text = self.config.client
                self.session.FindById("wnd[0]/usr/txtRSYST-BNAME").Text = self.config.user
                self.session.FindById("wnd[0]/usr/pwdRSYST-BCODE").Text = self.config.password
                self.session.FindById("wnd[0]/usr/txtRSYST-LANGU").Text = self.config.language
                self.session.FindById("wnd[0]").SendVKey(0)
                self._wait_ready()
        if self.session.Id != self.session_id:
            raise SapError("SAP session identity changed; restart with an explicit session identifier")
        self._wait_ready()
        actual_user = str(self.session.Info.User)
        if not actual_user:
            raise SapError(
                "Complete SSO/login in the configured SAP window; no password is required for an authenticated session"
            )
        if self.config.user and actual_user.casefold() != self.config.user.casefold():
            raise SapError(
                "The authenticated SAP user does not match SAP_USER; refusing to operate another identity"
            )
        return self.session

    def _element(self, element_id: str):
        if not re.fullmatch(r"wnd\[\d+\](?:/[^\x00-\x1f]+)?", element_id) or ".." in element_id:
            raise SapError("Element ID must be relative to the configured session, starting with wnd[N]")
        return self._session().FindById(element_id)

    def get_screen(self):
        session = self._session()
        elements = []
        stack = [(session, 0)]
        while stack and len(elements) < 300:
            item, depth = stack.pop()
            typ = str(item.Type)
            entry = {"id": str(item.Id), "type": typ, "name": str(item.Name)[:256]}
            if typ not in {"GuiPasswordField"}:
                try:
                    entry["text"] = str(item.Text)[:2048]
                except Exception:
                    pass
            else:
                entry["text"] = "[redacted]"
            elements.append(entry)
            if depth < 12:
                try:
                    children = item.Children
                    remaining = 300 - len(elements) - len(stack)
                    for n in reversed(range(min(children.Count, max(0, remaining)))):
                        stack.append((children(n), depth + 1))
                except Exception:
                    pass
        return {"session_id": self.session_id, "elements": elements, "truncated": bool(stack)}

    def launch_transaction(self, transaction: str):
        if not re.fullmatch(r"/?[A-Za-z0-9_/$-]{1,80}", transaction):
            raise SapError("Use a transaction code, not an SAP command string")
        self._session().StartTransaction(transaction)
        self._wait_ready()
        return self.get_screen()

    def end_session(self):
        # EndTransaction affects only the explicitly selected session. Never close SAP Logon.
        self._session().EndTransaction()
        return {"status": "transaction-ended", "session_id": self.session_id}

    def set_field(self, element_id: str, text: str):
        element = self._element(element_id)
        if str(element.Type) not in {"GuiTextField", "GuiCTextField", "GuiPasswordField"}:
            raise SapError("Element is not a writable SAP text field")
        element.Text = text
        return {"status": "field-updated", "session_id": self.session_id}

    def press(self, element_id: str):
        element = self._element(element_id)
        if str(element.Type) != "GuiButton":
            raise SapError("Element is not a SAP button")
        element.Press()
        self._wait_ready()
        return self.get_screen()

    def send_vkey(self, key: int):
        self._element("wnd[0]").SendVKey(key)
        self._wait_ready()
        return self.get_screen()

    def _window(self, *, main=False):
        import ctypes
        import win32gui

        # Match MSS physical pixels on each monitor; COM work stays on this STA thread.
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))

        session = self._session()
        window = session.FindById("wnd[0]") if main else session.ActiveWindow
        hwnd = int(window.Handle)
        if not win32gui.IsWindow(hwnd):
            raise SapError("The configured SAP session window no longer exists")
        return hwnd

    def _focus(self):
        import win32gui

        hwnd = self._window()
        win32gui.SetForegroundWindow(hwnd)
        if win32gui.GetForegroundWindow() != hwnd:
            raise SapError("Could not focus the configured SAP window; no keyboard or mouse input was sent")
        return hwnd

    def pixel_action(self, action: str, x: int = 0, y: int = 0, text: str = "", direction: str = "down"):
        import pyautogui
        import win32gui

        hwnd = self._focus()
        if action in {"click", "move"}:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if not 0 <= x < right - left or not 0 <= y < bottom - top:
                raise SapError("Coordinates are outside the configured SAP window")
            # Coordinates are physical pixels relative to the returned screenshot. No double DPI scaling.
            pyautogui.moveTo(left + x, top + y)
            if win32gui.GetForegroundWindow() != hwnd:
                raise SapError("SAP focus changed before input")
            if action == "click":
                pyautogui.click()
        elif action == "type":
            import win32com.client

            win32com.client.Dispatch("WScript.Shell").SendKeys(text)
        elif action == "scroll":
            pyautogui.scroll(5 if direction == "up" else -5)
        else:
            raise SapError("Unsupported pixel action")
        return {"status": "input-sent", "session_id": self.session_id}

    def screenshot(self):
        import win32gui
        from mss import mss
        from PIL import Image

        left, top, right, bottom = win32gui.GetWindowRect(self._window())
        if right <= left or bottom <= top or (right - left) * (bottom - top) > 30_000_000:
            raise SapError("SAP window has unsupported screenshot dimensions")
        with mss() as capture:
            raw = capture.grab({"left": left, "top": top, "width": right - left, "height": bottom - top})
            picture = Image.frombytes("RGB", raw.size, raw.rgb)
        buffer = BytesIO()
        picture.save(buffer, format="PNG")
        if buffer.tell() > 7_000_000:
            raise SapError("Screenshot exceeds the 7 MB limit")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def run_guixt(self, script: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.txt", script):
            raise SapError("Use a preinstalled simple .txt script name from GUIXT_SCRIPT_ROOT")
        path = jailed_path(self.config.guixt_root, script, existing=True)
        if not path.is_file():
            raise SapError("GuiXT script must be a preinstalled file")
        if any(c in str(path) for c in ';,"\r\n'):
            raise SapError("GuiXT script path contains a reserved separator")
        executable = Path(self.config.guixt_path)
        if not executable.is_absolute() or executable.name.lower() != "guixt.exe" or not executable.is_file():
            raise SapError("Configure GUIXT_PATH as the absolute installed guixt.exe path")
        hwnd = self._window(main=True)
        subprocess.run(
            [str(executable), f"findsession=hwnd:'{hwnd}'", f"input=OK:process={path}"],
            timeout=min(10, self.config.timeout),
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {
            "status": "submitted",
            "session_id": self.session_id,
            "message": "GuiXT accepted the external call; script completion is asynchronous. Inspect the same session before further input.",
        }

    def execute(self, method: str, arguments: dict):
        screenshot = arguments.pop("capture", False)
        actions = {
            "launch_transaction": self.launch_transaction,
            "end_transaction": self.end_session,
            "sap_get_screen": self.get_screen,
            "sap_set_field": self.set_field,
            "sap_press": self.press,
            "sap_send_vkey": self.send_vkey,
            "pixel": self.pixel_action,
            "sap_run_guixt_script": self.run_guixt,
        }
        if method not in actions:
            raise SapError("Unsupported SAP operation")
        result = actions[method](**arguments)
        if screenshot:
            result["image"] = self.screenshot()
        return result

    def close(self):
        # Release references only: EOF/cancellation never closes or ends a user's SAP session.
        self.session = None
        self.application = None
