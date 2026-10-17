"""MCP connection and learning-path agent setup."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Callable, Optional

import httpx
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

from prompt import user_goal_prompt

load_dotenv()


class AgentSetupError(RuntimeError):
    """Base class for errors safe to show in the Streamlit UI."""


class MissingConfigurationError(AgentSetupError):
    pass


class MCPAuthenticationError(AgentSetupError):
    pass


class MCPConnectionError(AgentSetupError):
    pass


class EmptyMCPToolsError(AgentSetupError):
    pass


class GenerationTimeoutError(AgentSetupError):
    pass


def describe_generation_error(error: Exception) -> str:
    """Return a useful error category without exposing credentials or URLs."""
    errors = [error]
    errors.extend(getattr(error, "exceptions", ()))
    while errors:
        current = errors.pop(0)
        errors.extend(getattr(current, "exceptions", ()))
        cause = current.__cause__ or current.__context__
        if cause is not None:
            errors.append(cause)
        current_type = type(current).__name__
        code = getattr(current, "code", None) or getattr(current, "status_code", None)

        if isinstance(current, MCPAuthenticationError):
            return str(current)
        if isinstance(current, GenerationTimeoutError):
            return str(current)
        if current_type in {"GoogleAuthenticationError", "GooglePermissionDeniedError"} or code in (401, 403):
            return (
                "Gemini rejected the API key or its permissions (HTTP "
                f"{code or '401/403'}). Check the Google AI API key entered in the sidebar, "
                "and confirm the Gemini API is enabled for that key's project."
            )
        if current_type == "GoogleRateLimitError" or code == 429:
            return "Gemini rate limit or quota reached (HTTP 429). Check the project's quota and billing."
        if current_type == "GoogleModelNotFoundError" or code == 404:
            return "Gemini could not find the configured model. Check model availability for this API key."
        if current_type == "GoogleInvalidRequestError" or code == 400:
            return (
                "Gemini rejected the request (HTTP 400). The API key was accepted; "
                "the request or tool schema may need adjustment."
            )
        if isinstance(current, (httpx.ConnectError, httpx.TimeoutException)):
            return "The request could not reach Gemini. Check the network connection and retry."

    return (
        "Generation failed with "
        f"{type(error).__name__}. Check the Streamlit terminal for the traceback; "
        "credential values and MCP URLs are not shown in the app."
    )


def initialize_model(google_api_key: str) -> ChatGoogleGenerativeAI:
    if not google_api_key:
        raise MissingConfigurationError(
            "Google API key is missing. Enter it in the sidebar or set GOOGLE_API_KEY in .env."
        )
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=google_api_key,
    )


def _headers_from_env(name: str) -> Optional[dict[str, str]]:
    raw_headers = os.getenv(name, "").strip()
    if not raw_headers:
        return None
    try:
        headers = json.loads(raw_headers)
    except json.JSONDecodeError as exc:
        raise MissingConfigurationError(
            f"{name} must contain a JSON object copied from session.mcp.headers."
        ) from exc
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in headers.items()
    ):
        raise MissingConfigurationError(
            f"{name} must be a JSON object with string header names and values."
        )
    return headers


def _find_http_status(error: BaseException) -> Optional[int]:
    """Find an HTTP error even when MCP's parallel startup wraps it in a group."""
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code
    nested = getattr(error, "exceptions", ())
    for child in nested:
        status = _find_http_status(child)
        if status is not None:
            return status
    cause = error.__cause__ or error.__context__
    if cause is not None:
        return _find_http_status(cause)
    return None


def _raise_connection_error(error: BaseException) -> None:
    status = _find_http_status(error)
    if status in (401, 403):
        raise MCPAuthenticationError(
            "Composio rejected MCP authentication (HTTP "
            f"{status}). Set the matching session's returned headers in the relevant "
            "*_MCP_HEADERS environment variable, and verify that the session and API "
            "key belong to the same Composio project."
        ) from error
    if status is not None:
        raise MCPConnectionError(
            f"The MCP server returned HTTP {status}. Check that the session URL is current."
        ) from error
    if isinstance(error, (httpx.ConnectError, httpx.TimeoutException)):
        raise MCPConnectionError(
            "Could not reach an MCP server. Check the URL and your network connection."
        ) from error
    raise MCPConnectionError(
        "Could not initialize the MCP servers. Check their URLs, transports, and session configuration."
    ) from error


async def setup_agent_with_tools(
    google_api_key: str,
    youtube_pipedream_url: str,
    drive_pipedream_url: Optional[str] = None,
    notion_pipedream_url: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    youtube_headers: Optional[dict[str, str]] = None,
    drive_headers: Optional[dict[str, str]] = None,
    notion_headers: Optional[dict[str, str]] = None,
) -> Any:
    """Connect the configured MCP servers and build the LangGraph agent."""
    if not youtube_pipedream_url:
        raise MissingConfigurationError("YouTube MCP URL is missing.")
    if progress_callback:
        progress_callback("Setting up agent with tools...")

    tools_config: dict[str, dict[str, Any]] = {}
    seen_connections: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    server_settings = [
        ("youtube", youtube_pipedream_url, youtube_headers or _headers_from_env("YOUTUBE_MCP_HEADERS")),
        ("drive", drive_pipedream_url, drive_headers or _headers_from_env("GOOGLE_DRIVE_MCP_HEADERS")),
        ("notion", notion_pipedream_url, notion_headers or _headers_from_env("NOTION_MCP_HEADERS")),
    ]
    for name, url, headers in server_settings:
        if not url:
            continue
        connection_key = (url, tuple(sorted((headers or {}).items())))
        if connection_key in seen_connections:
            continue
        seen_connections.add(connection_key)
        tools_config[name] = {"url": url, "transport": "streamable_http"}
        if headers:
            # Composio specifies that session.mcp.headers must be forwarded as returned.
            tools_config[name]["headers"] = headers

    if progress_callback:
        progress_callback("Connecting to MCP servers...")
    try:
        mcp_client = MultiServerMCPClient(tools_config, tool_name_prefix=True)
        tools = await mcp_client.get_tools()
    except Exception as exc:
        _raise_connection_error(exc)

    if not tools:
        raise EmptyMCPToolsError(
            "The MCP servers connected but returned no tools. Check that their Composio sessions include the selected toolkits."
        )
    if progress_callback:
        progress_callback(f"Loaded {len(tools)} MCP tools.")

    model = initialize_model(google_api_key)
    agent = create_react_agent(model, tools, prompt=user_goal_prompt)
    if progress_callback:
        progress_callback("Agent setup complete!")
    return agent


def run_agent_sync(
    google_api_key: str,
    youtube_pipedream_url: str,
    drive_pipedream_url: Optional[str] = None,
    notion_pipedream_url: Optional[str] = None,
    user_goal: str = "",
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Any:
    """Synchronous entry point used by the Streamlit form."""
    agent = asyncio.run(
        setup_agent_with_tools(
            google_api_key=google_api_key,
            youtube_pipedream_url=youtube_pipedream_url,
            drive_pipedream_url=drive_pipedream_url,
            notion_pipedream_url=notion_pipedream_url,
            progress_callback=progress_callback,
        )
    )
    if progress_callback:
        progress_callback("Generating your learning path...")

    async def run_streaming() -> Any:
        latest_state = None
        async for state in agent.astream(
            {"messages": [HumanMessage(content=f"Learning goal: {user_goal}")]},
            config={"recursion_limit": 50},
            stream_mode="values",
        ):
            latest_state = state
            if not progress_callback:
                continue
            messages = state.get("messages", [])
            if not messages:
                continue
            last_message = messages[-1]
            tool_calls = getattr(last_message, "tool_calls", None) or []
            if tool_calls:
                for tool_call in tool_calls:
                    tool_name = tool_call.get("name", "MCP tool")
                    progress_callback(f"Using {tool_name}...")
            elif last_message.__class__.__name__ == "ToolMessage":
                progress_callback("Tool finished; continuing the learning path...")

        if latest_state is None:
            raise AgentSetupError("The agent finished without returning a result.")
        return latest_state

    try:
        result = asyncio.run(asyncio.wait_for(run_streaming(), timeout=300))
    except asyncio.TimeoutError as exc:
        raise GenerationTimeoutError(
            "Generation took longer than 5 minutes and was stopped. Try a shorter learning goal or run it again."
        ) from exc
    if progress_callback:
        progress_callback("Learning path generation complete!")
    return result
