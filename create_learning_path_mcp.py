"""Create one Composio MCP session for both learning-path integrations."""

import json
import os
import webbrowser
from pathlib import Path

from composio import Composio
from dotenv import load_dotenv, set_key

load_dotenv()

api_key = os.getenv("COMPOSIO_API_KEY")
if not api_key:
    raise SystemExit("COMPOSIO_API_KEY is missing. Add it to .env before creating a session.")

user_id = os.getenv("COMPOSIO_USER_ID", "mcp-learning-path-user")
composio = Composio(api_key=api_key)
session = composio.sessions.create(
    user_id=user_id,
    toolkits=["youtube", "googledrive"],
    mcp=True,
)

for toolkit in ("youtube", "googledrive"):
    state = next(
        (
            item
            for item in session.toolkits(toolkits=[toolkit]).items
            if item.slug == toolkit
        ),
        None,
    )
    if state and state.connection and state.connection.is_active:
        continue

    request = session.authorize(toolkit)
    if not request.redirect_url or not webbrowser.open(request.redirect_url, new=2):
        raise SystemExit(
            f"Could not open the {toolkit} authorization page in your default browser."
        )
    print(f"Complete the {toolkit} sign-in in your browser; waiting for authorization...")
    request.wait_for_connection(timeout=300)

headers = json.dumps(session.mcp.headers or {})
env_path = Path(__file__).with_name(".env")
for key, value in (
    ("YOUTUBE_MCP_URL", session.mcp.url),
    ("GOOGLE_DRIVE_MCP_URL", session.mcp.url),
    ("YOUTUBE_MCP_HEADERS", headers),
    ("GOOGLE_DRIVE_MCP_HEADERS", headers),
):
    set_key(str(env_path), key, value)

print("Combined YouTube and Google Drive MCP session saved to .env.")
