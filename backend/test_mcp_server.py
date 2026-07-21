"""
Test MCP Server for MCP Tour De Control.

A simple FastMCP server with 4 tools for testing the full pipeline.
Run with: python test_mcp_server.py
Or use via stdio in the app config: command=python, args=test_mcp_server.py
"""

import os
import platform
from datetime import datetime, timezone

from fastmcp import FastMCP

mcp = FastMCP("Test Server")


@mcp.tool()
def get_server_time() -> dict:
    """Get the current server date and time with timezone info."""
    now = datetime.now(timezone.utc)
    return {
        "utc": now.isoformat(),
        "timestamp": int(now.timestamp()),
        "day_of_week": now.strftime("%A"),
        "formatted": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


@mcp.tool()
def system_info() -> dict:
    """Get system information: OS, platform, Python version, hostname."""
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
        "architecture": platform.machine(),
    }


@mcp.tool()
def list_files(path: str = ".") -> dict:
    """List files and directories at the given path. Returns names, sizes, and types."""
    try:
        entries = []
        for entry in sorted(os.listdir(path)):
            full_path = os.path.join(path, entry)
            is_dir = os.path.isdir(full_path)
            size = os.path.getsize(full_path) if not is_dir else None
            entries.append({
                "name": entry,
                "type": "directory" if is_dir else "file",
                "size_bytes": size,
            })
        return {"path": os.path.abspath(path), "count": len(entries), "entries": entries}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def echo(message: str) -> dict:
    """Echo back a message with metadata. Useful for testing script generation."""
    return {
        "original_message": message,
        "length": len(message),
        "uppercase": message.upper(),
        "word_count": len(message.split()),
        "echoed_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    mcp.run()
