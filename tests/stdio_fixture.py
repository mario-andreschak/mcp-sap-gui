"""Controlled backend fixture; never included in the wheel."""

from sap_gui_server.server import SapGuiServer
from tests.test_server import Fake

if __name__ == "__main__":
    app = SapGuiServer(worker=Fake(result={"session_id": "controlled-fixture", "elements": []}))
    app.server.run()
