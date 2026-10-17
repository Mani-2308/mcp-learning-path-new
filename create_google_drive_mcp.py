import json
import os
from pathlib import Path
import webbrowser

from composio import Composio
from dotenv import load_dotenv, set_key

load_dotenv()

api_key = os.getenv("COMPOSIO_API_KEY")
if not api_key:
    raise SystemExit("COMPOSIO_API_KEY is missing. Add it to .env before creating a session.")

composio = Composio(api_key=api_key)

session = composio.sessions.create(
    user_id=os.getenv("COMPOSIO_USER_ID", "mcp-learning-path-user"),
    toolkits=["googledrive"],
    mcp=True,
)

connection = next(
    (
        item.connection
        for item in session.toolkits(toolkits=["googledrive"]).items
        if item.slug == "googledrive"
    ),
    None,
)
if not connection or not connection.is_active:
    request = session.authorize("googledrive")
    if not request.redirect_url or not webbrowser.open(request.redirect_url, new=2):
        raise SystemExit(
            "Could not open the Google Drive authorization page in your default browser."
        )
    print("Complete the Google Drive sign-in in your browser; waiting for authorization...")
    request.wait_for_connection(timeout=300)

env_path = Path(__file__).with_name(".env")
set_key(str(env_path), "GOOGLE_DRIVE_MCP_URL", session.mcp.url)
set_key(
    str(env_path),
    "GOOGLE_DRIVE_MCP_HEADERS",
    json.dumps(session.mcp.headers or {}),
)
print("Google Drive MCP session saved to .env (URL and headers are not displayed).")
