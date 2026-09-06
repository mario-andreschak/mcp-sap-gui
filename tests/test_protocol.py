import subprocess
import sys


def test_actual_child_stdio_both_protocol_eras():
    result = subprocess.run(
        [sys.executable, "scripts/smoke_protocol.py"], capture_output=True, text=True, timeout=45
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "modern:" in result.stdout and "legacy:" in result.stdout


def test_actual_wire_success_with_controlled_backend():
    result = subprocess.run(
        [sys.executable, "scripts/smoke_protocol.py", "--fixture"], capture_output=True, text=True, timeout=45
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "modern:" in result.stdout and "legacy:" in result.stdout
