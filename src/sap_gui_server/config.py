"""Configuration contains no chat identity delegation or credential transport."""

from dataclasses import dataclass, field
from pathlib import Path
import os
import re


class SapError(Exception):
    """A deliberately safe, actionable message suitable for an MCP tool error."""


@dataclass(frozen=True)
class Config:
    session_id: str = ""
    connection: str = ""
    user: str = ""
    password: str = field(default="", repr=False)
    client: str = ""
    language: str = "EN"
    gui_path: str = ""
    output_root: str = ""
    guixt_root: str = ""
    guixt_path: str = ""
    timeout: float = 30.0

    @classmethod
    def from_env(cls):
        try:
            timeout = float(os.getenv("SAP_OPERATION_TIMEOUT", "30"))
        except ValueError as exc:
            raise SapError("SAP_OPERATION_TIMEOUT must be between 1 and 120 seconds") from exc
        if not 1 <= timeout <= 120:
            raise SapError("SAP_OPERATION_TIMEOUT must be between 1 and 120 seconds")
        session_id = os.getenv("SAP_SESSION_ID", "")
        if session_id and not re.fullmatch(r"/app/con\[\d+\]/ses\[\d+\]", session_id):
            raise SapError("SAP_SESSION_ID must be an exact /app/con[N]/ses[N] identifier")
        return cls(
            session_id=session_id,
            connection=os.getenv("SAP_CONNECTION", ""),
            user=os.getenv("SAP_USER", ""),
            password=os.getenv("SAP_PASSWORD", ""),
            client=os.getenv("SAP_CLIENT", ""),
            language=os.getenv("SAP_LANGUAGE", "EN"),
            gui_path=os.getenv("SAP_GUI_PATH", ""),
            output_root=os.getenv("SAP_OUTPUT_ROOT", ""),
            guixt_root=os.getenv("GUIXT_SCRIPT_ROOT", ""),
            guixt_path=os.getenv("GUIXT_PATH", ""),
            timeout=timeout,
        )


def jailed_path(root: str, candidate: str, *, existing: bool = False) -> Path:
    if not root:
        raise SapError("Configure the corresponding output/script root before using file operations")
    base = Path(root).expanduser().resolve(strict=True)
    if not base.is_dir():
        raise SapError("Configured root must be an existing directory")
    target = Path(candidate).expanduser()
    target = (target if target.is_absolute() else base / target).resolve(strict=existing)
    if not target.is_relative_to(base) or target == base:
        raise SapError("Path must remain inside the configured root")
    return target
