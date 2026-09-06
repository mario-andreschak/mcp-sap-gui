# MCP SAP GUI

MCP tools for one configured **SAP GUI for Windows** session. This repair uses Python MCP SDK 2.1.1 and serves both the published 2026-07-28 protocol (`server/discover`) and legacy initialization over stdio. The original seven tool names remain available; COM control tools and optional GuiXT InputScripts add alternatives to image recognition.

## Install and select a session

Use Python 3.11–3.13 on an interactive Windows desktop with your licensed SAP GUI, a configured SAP Logon connection, and SAP GUI Scripting installed and enabled by your administrator. The implementation targets the public SAP GUI 8.00/8.10 scripting interface. CI checks Python and Windows bindings; **actual SAP 8.00/8.10 systems have not been exercised in CI**. Consult SAP's current platform/patch matrix for your installation. This does not support SAP GUI for Java or a headless SAP desktop.

```powershell
python -m pip install .
Copy-Item .env.example .env
# Edit .env to select the intended session.
python -m sap_gui_server.server
```

For repeatable development use `uv sync --frozen --python 3.13`, `uv run pytest`, and `uv build`. `build.bat` builds from local source; `setup.bat` creates a template without prompting for or echoing a password. Node is optional and only needed for `run.bat debug` (MCP Inspector).

An existing authenticated session, including SSO, needs no password:

```dotenv
SAP_SESSION_ID=/app/con[0]/ses[0]
# Optional assertion, checked against the authenticated SAP user:
SAP_USER=YOUR_SAP_USER
```

Use the exact ID of a session reserved for automation. SAP GUI's scripting recorder displays the connection/session indexes. The server never chooses an arbitrary active window or the first existing session. To open a new connection instead, omit `SAP_SESSION_ID` and set `SAP_CONNECTION` to its exact SAP Logon description. New connections may use existing Windows/SAP SSO; optional `SAP_CLIENT`, `SAP_USER`, `SAP_PASSWORD` and `SAP_LANGUAGE` fill the login controls through COM. Passwords are never process arguments or log entries.

SSO uses the identity of the local Windows/SAP session. It does **not** infer the identity of a chat user, exchange a ChatGPT token, or implement remote Microsoft on-behalf-of authentication. Run a separate local server under each intended Windows user; no shared remote authentication endpoint exists here. This distinction is part of issue #8's remaining integration requirement.

For a custom installation set `SAP_GUI_PATH` to the installed `saplogon.exe` or its directory, for example `C:\Program Files\SAP\FrontEnd\SAPGUI`. This is used to start SAP Logon when its running COM object is absent. The default expects SAP Logon already running, avoiding a guessed 32-bit registry path (#3).

Scripting text reads use SAP control properties, not Win32 window captions, addressing the 64-bit text-reading report (#6). Password controls are redacted. Read-only scripting policies may permit reads but reject writes; the server reports that failure and never changes SAP security settings. SAP's [scripting requirements](https://help.sap.com/docs/sap_gui_for_windows/b47d018c3b9b45e897faf66a6c0885a8/45a62269a13d4522997bedf3e6ff56f8.html) and [GUI documentation](https://help.sap.com/docs/sap_gui_for_windows) describe installation and administrator prerequisites.

## Tools

| Tool | Operation |
|---|---|
| `launch_transaction` | Start a transaction code in the selected session |
| `end_transaction` | End that session's transaction, preserving other sessions and SAP Logon |
| `sap_click`, `sap_move_mouse` | Physical screenshot pixels relative to that SAP window |
| `sap_type` | Existing WScript SendKeys semantics, including explicit special keys |
| `sap_scroll` | Scroll up/down within that window |
| `save_last_screenshot` | Save the last requested screenshot inside the configured output root |
| `sap_get_screen` | Read up to 300 COM control IDs/types/text; password fields redacted |
| `sap_set_field` | Set literal text in a session-relative SAP text field |
| `sap_press` | Press a SAP COM button |
| `sap_send_vkey` | Send a documented SAP virtual key (0 is Enter) |
| `sap_run_guixt_script` | Submit a preinstalled InputScript to the exact session window |

Control IDs must start with `wnd[N]`, such as `wnd[0]/usr/ctxtFIELD`; cross-session absolute IDs are rejected. These are public SAP ActiveX/COM scripting operations (#2), with typed methods rather than arbitrary COM method evaluation. See SAP's [application API](https://help.sap.com/docs/sap_gui_for_windows/b47d018c3b9b45e897faf66a6c0885a8/a020c8f8cfaf48ec9b579d5961889639.html) and [session API](https://help.sap.com/docs/PRODUCT_ID/b47d018c3b9b45e897faf66a6c0885a8/a4e022f6c155414d9c8ae8eba422cac5.html).

Screenshot-capable tools accept `return_screenshot`: `none` (default), `as_file`, `as_base64`, `as_imagecontent`, or `as_imageurl`. The last spelling remains compatible but now returns a valid embedded PNG blob resource, not a fake remotely retrievable URL. Screenshots are physical pixels without double DPI scaling and are bounded to 30 million pixels / 7 MB. `SAP_OUTPUT_ROOT` must be an existing directory before file writes; `as_file_target_folder` must resolve inside it. Saving never overwrites an existing file. No screenshot is captured by default, so `save_last_screenshot` requires a preceding explicit screenshot request.

## GuiXT (#1)

Install GuiXT/InputAssistant as appropriate for your licensed setup. Set `GUIXT_PATH` to the absolute `guixt.exe` and `GUIXT_SCRIPT_ROOT` to an existing directory containing reviewed InputScripts with simple names such as `read_order.txt`. Explicitly enable `AllowExternalInput Yes` in GuiXT's profile; the server does not alter it. The tool accepts a script name, verifies the root boundary, and invokes GuiXT with `findsession=hwnd:'…'` for the selected SAP window. No shell or caller-supplied command fragments are used.

GuiXT submissions are asynchronous. A successful result means the external invocation was accepted; it does not prove business-process completion. Inspect that same session and any script-specific output before issuing more input. There is no automatic retry or generic cancellation of a script already accepted by GuiXT. See the [vendor's external InputScript contract](https://www.synactive.com/docu_e/externalscriptcall.html?treepath=InputAssistant%3B), including the opt-in introduced in 2026 Q1 1.

## Lifecycle and migration

All COM work runs in one serialized STA worker process. `SAP_OPERATION_TIMEOUT` defaults to 30 seconds (1–120). Cancellation or a deadline terminates only this server's worker process and refuses further work until the MCP server is restarted. An already-issued SAP action cannot be rolled back; inspect the session before resuming. No `taskkill`, process-name matching, global SAP termination, or automatic multiple-logon popup action remains. Closing MCP releases handles and leaves SAP sessions open. Explicit `end_transaction` may discard unsaved work **in the chosen transaction**.

Execution failures have `isError=true`, invalid inputs/unknown tools follow SDK error semantics, and stdout contains only MCP JSON-RPC. Tool arguments, form text, credentials and COM exception details are not logged. The local stdio process has the desktop privileges of its Windows user. Use a dedicated automation session and keep output/script directories under that user's control.

Version 0.2 replaces the broken SDK1 constructor/decorators and process-wide control behavior. `SAP_SYSTEM` is replaced by `SAP_CONNECTION` (a Logon description) or `SAP_SESSION_ID`; passwords are optional. File outputs now require a root. Old code importing internal controller methods should migrate to the named MCP tools. The integration helper uses the Python interpreter that invokes it; run it from the environment containing the package.

## Validation and Docker

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `uv build` validate source, controlled COM mocks, timeout/cancellation, real child-process modern/legacy protocol sessions, installed package discovery, and error behavior. Windows CI imports native bindings and captures a disposable test window. It does not log in to SAP, run a transaction on a real system, or prove SSO/GuiXT in your landscape.

The Dockerfile now builds from this checkout and runs a non-root protocol/discovery image. A Linux container cannot access an interactive licensed Windows SAP GUI. SAP tool calls in that image return an explicit platform error; use the native Windows package for automation. This corrects the invalid Dockerfile in #4 without claiming containerized SAP or a verified Glama deployment. Updating/claiming a third-party directory listing remains separate external work.

Before production use, on a disposable SAP client: verify the selected SSO identity and optional mismatch assertion; read text on your GUI patch; start a harmless transaction and verify another open session is untouched; exercise a control, screenshot and GuiXT script; cancel a long request and confirm no unrelated process closes. Record GUI version, patch, Windows build, scripting policies and outcomes. These native SAP acceptance gates remain explicit until tested.
