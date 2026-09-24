import json
import sys
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Literal


def get_settings_path(mode: Literal["cline", "roo"]) -> Path:
    """Get the path to the settings file based on mode."""
    base_path = Path(os.path.expanduser("~")) / "AppData" / "Roaming" / "Code" / "User" / "globalStorage"

    if mode == "cline":
        return base_path / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
    else:  # roo
        return base_path / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json"


def create_backup(file_path: Path) -> Path:
    """Create a backup of the file with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = file_path.parent / f"{file_path.stem}_backup_{timestamp}{file_path.suffix}"
    shutil.copy2(file_path, backup_path)
    return backup_path


def validate_json_structure(data: Dict[str, Any]) -> bool:
    """Validate the basic structure of the settings JSON."""
    if not isinstance(data, dict):
        return False
    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        return False
    return True


def get_mcp_config() -> Dict[str, Any]:
    """Get the MCP SAP GUI configuration with the current path."""
    current_path = os.path.abspath(os.path.dirname(__file__))
    return {
        "command": sys.executable,
        "args": ["-m", "sap_gui_server.server"],
        "cwd": current_path,
        "disabled": False,
    }


def update_settings(mode: Literal["cline", "roo"]) -> None:
    """Update the settings file safely."""
    settings_path = get_settings_path(mode)

    # Check if file exists
    if not settings_path.exists():
        print(f"Error: Settings file not found at {settings_path}")
        sys.exit(1)

    try:
        # Read existing settings
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)

        # Validate structure
        if not validate_json_structure(settings):
            print("Error: Invalid settings file structure")
            sys.exit(1)

        # Create backup
        backup_path = create_backup(settings_path)
        print(f"Backup created at: {backup_path}")

        # Update configuration
        mcp_config = get_mcp_config()
        settings["mcpServers"]["mcp-sap-gui"] = mcp_config

        # Write updated settings atomically
        temp_path = settings_path.parent / f"{settings_path.stem}_temp{settings_path.suffix}"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

        # Validate the written JSON
        with open(temp_path, "r", encoding="utf-8") as f:
            test_load = json.load(f)
            if not validate_json_structure(test_load):
                print("Error: Failed to validate written JSON")
                os.unlink(temp_path)
                sys.exit(1)

        # Atomic rename
        os.replace(temp_path, settings_path)
        print(f"Successfully updated {mode} settings")

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in settings file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to update settings: {e}")
        sys.exit(1)


def main():
    if len(sys.argv) != 2 or sys.argv[1].lower() not in ["cline", "roo"]:
        print("Usage: python integrate.py [cline|roo]")
        sys.exit(1)

    mode = sys.argv[1].lower()
    update_settings(mode)


if __name__ == "__main__":
    main()
