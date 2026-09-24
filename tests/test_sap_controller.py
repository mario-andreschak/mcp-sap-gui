from types import SimpleNamespace
from unittest.mock import Mock
import sys
import pytest
from sap_gui_server.config import Config, SapError, jailed_path
from sap_gui_server.sap_controller import SapController


class Children:
    def __init__(self, items):
        self.items = items
        self.Count = len(items)

    def __call__(self, n):
        return self.items[n]


def fixture(user="ALICE"):
    password = SimpleNamespace(
        Id="/app/con[3]/ses[2]/wnd[0]/pwd",
        Type="GuiPasswordField",
        Name="password",
        Text="secret-canary",
        Children=Children([]),
    )
    field = SimpleNamespace(
        Id="/app/con[3]/ses[2]/wnd[0]/usr/txt",
        Type="GuiTextField",
        Name="field",
        Text="Hello",
        Children=Children([]),
    )
    session = SimpleNamespace(
        Id="/app/con[3]/ses[2]",
        Type="GuiSession",
        Name="ses[2]",
        Busy=False,
        Info=SimpleNamespace(User=user),
        Children=Children([password, field]),
        StartTransaction=Mock(),
        EndTransaction=Mock(),
        FindById=Mock(return_value=field),
        ActiveWindow=SimpleNamespace(Handle=900),
    )
    app = SimpleNamespace(
        FindById=Mock(return_value=session),
        OpenConnection=Mock(return_value=SimpleNamespace(Children=Children([session]))),
    )
    return app, session, field


def test_exact_sso_session_preserves_other_sessions_and_has_no_password():
    app, session, _ = fixture()
    c = SapController(Config(session_id=session.Id), application=app)
    c.launch_transaction("SE16")
    c.end_session()
    app.FindById.assert_called_once_with(session.Id)
    app.OpenConnection.assert_not_called()
    session.StartTransaction.assert_called_once_with("SE16")
    session.EndTransaction.assert_called_once()
    c.close()
    session.EndTransaction.assert_called_once()


def test_no_arbitrary_existing_session_and_identity_assertion():
    app, session, _ = fixture()
    with pytest.raises(SapError, match="Configure exact"):
        SapController(Config(), application=app).get_screen()
    with pytest.raises(SapError, match="does not match"):
        SapController(Config(session_id=session.Id, user="BOB"), application=app).launch_transaction("SE16")
    session.StartTransaction.assert_not_called()


def test_new_connection_sso_and_control_text_reads():
    app, session, field = fixture()
    c = SapController(Config(connection="Development SSO"), application=app)
    screen = c.get_screen()
    app.OpenConnection.assert_called_once_with("Development SSO", True)
    assert "secret-canary" not in str(screen)
    assert "Hello" in str(screen)
    c.set_field("wnd[0]/usr/txt", "literal{ENTER}")
    assert field.Text == "literal{ENTER}"


def test_existing_session_never_receives_login_credentials():
    app, session, _ = fixture(user="")
    c = SapController(Config(session_id=session.Id, user="ALICE", password="do-not-send"), application=app)
    with pytest.raises(SapError, match="Complete SSO"):
        c.get_screen()
    session.FindById.assert_not_called()


@pytest.mark.parametrize("element", ["/app/con[0]/ses[0]/wnd[0]", "wnd[0]/../wnd[1]", "wnd[0]\n"])
def test_cross_session_control_ids_rejected(element):
    app, session, _ = fixture()
    c = SapController(Config(session_id=session.Id), application=app)
    with pytest.raises(SapError):
        c.set_field(element, "text")
    app.FindById.assert_not_called()


def test_root_boundary_and_symlink(tmp_path):
    base = tmp_path / "safe"
    base.mkdir()
    outside = tmp_path / "safe-evil"
    outside.mkdir()
    assert jailed_path(str(base), "new.png") == base / "new.png"
    with pytest.raises(SapError):
        jailed_path(str(base), str(outside / "x.png"))
    try:
        (base / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit test symlinks")
    with pytest.raises(SapError):
        jailed_path(str(base), "link/x.png")


def test_guixt_targets_exact_hwnd_and_rejects_command_injection(tmp_path, monkeypatch):
    app, session, _ = fixture()
    executable = tmp_path / "guixt.exe"
    executable.write_bytes(b"")
    script = tmp_path / "reviewed.txt"
    script.write_text("Return")
    c = SapController(
        Config(session_id=session.Id, guixt_root=str(tmp_path), guixt_path=str(executable)), application=app
    )
    window = Mock(return_value=900)
    monkeypatch.setattr(c, "_window", window)
    run = Mock()
    monkeypatch.setattr("sap_gui_server.sap_controller.subprocess.run", run)
    assert c.run_guixt("reviewed.txt")["status"] == "submitted"
    window.assert_called_once_with(main=True)
    args = run.call_args.args[0]
    assert args == [str(executable), "findsession=hwnd:'900'", f"input=OK:process={script}"]
    with pytest.raises(SapError):
        c.run_guixt("reviewed.txt;OK:/nSE16")
    assert run.call_count == 1


def test_config_hides_password_and_rejects_invalid_timeout(monkeypatch):
    assert "canary" not in repr(Config(password="canary"))
    monkeypatch.setenv("SAP_OPERATION_TIMEOUT", "nan")
    with pytest.raises(SapError):
        Config.from_env()


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows binding/window check")
def test_native_windows_screenshot_of_disposable_window():
    import base64
    from io import BytesIO
    from PIL import Image
    import win32gui
    import win32con
    import pythoncom
    import pyautogui

    assert pyautogui is not None and pythoncom is not None
    app, session, _ = fixture()
    hwnd = win32gui.CreateWindowEx(
        0,
        "STATIC",
        "MCP SAP disposable test window",
        win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
        100,
        100,
        400,
        220,
        0,
        0,
        0,
        None,
    )
    try:
        session.ActiveWindow.Handle = hwnd
        c = SapController(Config(session_id=session.Id), application=app)
        picture = Image.open(BytesIO(base64.b64decode(c.screenshot())))
        assert picture.size == (400, 220)
        assert picture.format == "PNG"
    finally:
        win32gui.DestroyWindow(hwnd)
