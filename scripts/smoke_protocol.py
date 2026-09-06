"""Raw stdio acceptance runs installed production code; no SAP calls on Windows."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

MODERN = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


def run(era, command=None, *, fixture=False):
    messages = []
    if era == "modern":
        messages.append({"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": MODERN}})
    else:
        messages.append(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "clientInfo": {"name": "sap-smoke", "version": "1"},
                    "capabilities": {},
                },
            }
        )
        messages.append({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def params(data):
        return {**data, **({"_meta": MODERN} if era == "modern" else {})}

    messages.extend(
        [
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": params({})},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": params({"name": "save_last_screenshot", "arguments": {"filename": "none.png"}}),
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": params({"name": "missing_tool", "arguments": {}}),
            },
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": params({"name": "sap_click", "arguments": {"x": -1, "y": 0}}),
            },
        ]
    )
    if fixture:
        messages.append(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": params({"name": "sap_get_screen", "arguments": {}}),
            }
        )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SAP_", "GUIXT_"))}
    env["SAP_ENV_FILE"] = str(Path(tempfile.gettempdir()) / "nonexistent-mcp-sap.env")
    # Exchanges are sequential so EOF does not cancel still-running request handlers.
    process = subprocess.Popen(
        command or [sys.executable, "-m", "sap_gui_server.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        replies = {}
        for message in messages:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            if "id" in message:
                line = process.stdout.readline()
                assert line, "Missing protocol response"
                response = json.loads(line)
                assert response["id"] == message["id"], response
                replies[response["id"]] = response
        process.stdin.close()
        process.wait(timeout=8)
        assert process.returncode == 0
        assert not process.stdout.read().strip()
        stderr = process.stderr.read()
        assert "Traceback" not in stderr, stderr
        if fixture:
            assert not replies[6]["result"].get("isError")
            assert "controlled-fixture" in replies[6]["result"]["content"][0]["text"]
        tools = replies[2]["result"]["tools"]
        assert len(tools) == 12
        assert replies[3]["result"]["isError"] is True
        assert "error" in replies[4] or replies[4].get("result", {}).get("isError")
        assert "error" in replies[5] or replies[5].get("result", {}).get("isError")
        if era == "modern":
            assert replies[1]["result"]["resultType"] == "complete"
            assert replies[2]["result"]["resultType"] == "complete"
            assert "ttlMs" in replies[2]["result"] and "cacheScope" in replies[2]["result"]
        else:
            assert replies[1]["result"]["protocolVersion"] == "2025-11-25"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    print(f"{era}: discovery/list/error/invalid-input/EOF passed")


if __name__ == "__main__":
    for era in ["modern", "legacy"]:
        fixture = sys.argv[1:] == ["--fixture"]
        command = [sys.executable, "-m", "tests.stdio_fixture"] if fixture else sys.argv[1:] or None
        run(era, command, fixture=fixture)
