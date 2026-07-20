"""
MCP服务器配置模块 - 包含连接A股MCP服务器的配置信息
"""
from pathlib import Path

_MCP_SERVER_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "a-share-mcp-is-just-i-need"
)

SERVER_CONFIGS = {
    "a_share_mcp_v2": {
        "command": "uv",
        "args": [
            "run",
            "--directory",
            str(_MCP_SERVER_DIR),
            "python",
            "mcp_server.py",
        ],
        "transport": "stdio",
        "env": {
            "BAOSTOCK_SERVER_IP": "public-api.baostock.com",
        },
    }
}
