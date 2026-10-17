# MCP Learning Path Generator

A Streamlit app that creates a day-by-day learning path with Gemini, searches for YouTube learning resources, and can save the result using Google Drive or Notion MCP tools.

**Live app:** [MCP Learning Path Generator](https://mcp-learning-path-new-dg2kph2v6dohq7fmefzn9q.streamlit.app/)

## Requirements

- Python 3.11 or newer
- A Gemini API key with access to a supported model
- A Composio account and connected YouTube and Google Drive integrations

## Run locally

Open a terminal in the project directory and create a virtual environment:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS or Linux, use `python3 -m venv venv` and `source venv/bin/activate` instead.

### Configure Composio MCP

Add your Composio API key to a local `.env` file (this file is ignored by Git):

```dotenv
COMPOSIO_API_KEY=your_composio_api_key
```

Create the combined YouTube and Google Drive session:

```powershell
python create_learning_path_mcp.py
```

Complete any Google/YouTube authorization pages opened by the script. It saves the MCP URLs and authentication headers to `.env`.

Run the app:

```powershell
python -m streamlit run app.py
```

Enter your Gemini API key and the YouTube and Drive MCP URLs in the app sidebar. The app reads the MCP headers from `.env`.

## Deploy on Streamlit Community Cloud

1. Push the project to GitHub. Do not commit `.env` or API credentials.
2. In Streamlit Community Cloud, create an app from the repository and select `app.py` as the entrypoint.
3. Open the deployed app's **Settings → Secrets** and add the MCP headers as root-level TOML strings:

   ```toml
   YOUTUBE_MCP_HEADERS = '{"header-name":"header-value"}'
   GOOGLE_DRIVE_MCP_HEADERS = '{"header-name":"header-value"}'
   ```

   Replace the examples with the corresponding header JSON produced by the session script. Keep the YouTube and Drive credentials from the same Composio session. Do not add them under a TOML section.
4. Save the secrets, then enter the Gemini API key and MCP URLs in the deployed app's sidebar.

If Composio returns HTTP 401, create a fresh session and update the deployed MCP headers and URLs. The session and Composio API key must belong to the same Composio project.

## Security

- Keep `.env` and Streamlit secrets private; never commit credentials to GitHub.
- If a key or MCP header is exposed, revoke or rotate it and update the app configuration.
- `create_learning_path_mcp.py` needs `COMPOSIO_API_KEY` locally to create or refresh the MCP session. The deployed app uses the session headers and does not need that API key for normal runs.
