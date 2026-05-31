#!/usr/bin/env python3
"""Generate .cursor/mcp.json for the W&B MCP server from WANDB_API_KEY in .env."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
MCP_PATH = ROOT / ".cursor" / "mcp.json"

load_dotenv(ROOT / ".env")

api_key = os.getenv("WANDB_API_KEY")
if not api_key:
    raise SystemExit("WANDB_API_KEY not found in .env — add it from https://wandb.ai/authorize")

config = {
    "mcpServers": {
        "wandb": {
            "transport": "http",
            "url": "https://mcp.withwandb.com/mcp",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json, text/event-stream",
            },
        }
    }
}

MCP_PATH.parent.mkdir(parents=True, exist_ok=True)
MCP_PATH.write_text(json.dumps(config, indent=2) + "\n")
print(f"Wrote {MCP_PATH}")
print("Restart Cursor, then ask: 'List my W&B entities' to verify the connection.")
