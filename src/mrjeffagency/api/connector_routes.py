"""Local connector bridge for MJA Assistant live tool calls.

Credentials stay on the local MJA server, never inside model prompts. The
Android app asks for tool definitions, executes the tool-call loop, and calls
``/v1/connectors/invoke`` for approved tools.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from mrjeffagency.config.paths import config_dir_path

from .dependencies import require_proxy_auth

router = APIRouter(prefix="/v1/connectors", tags=["mja-connectors"])

_STORE_PATH = config_dir_path() / "connectors.json"
_STATE_PATH = config_dir_path() / "connector_oauth_states.json"
_CALLBACK_BASE = os.getenv("MJA_CONNECTOR_CALLBACK_BASE", "http://127.0.0.1:8083").rstrip("/")
_CALLBACK_URL = f"{_CALLBACK_BASE}/v1/connectors/oauth/callback"

CREDENTIAL_KEYS: dict[str, tuple[str, ...]] = {
    "google_drive": (
        "client_id", "client_secret", "access_token", "refresh_token", "expires_at",
    ),
    "spotify": (
        "client_id", "client_secret", "access_token", "refresh_token", "expires_at",
    ),
    "shopify": ("shop", "access_token"),
    "whatsapp": ("phone_number_id", "access_token"),
}

REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "google_drive": ("access_token",),
    "spotify": ("access_token",),
    "shopify": ("shop", "access_token"),
    "whatsapp": ("phone_number_id", "access_token"),
}

CONNECTOR_NAMES = {
    "google_drive": "Google Drive",
    "spotify": "Spotify",
    "shopify": "Shopify",
    "whatsapp": "WhatsApp by Agent Messenger",
}

OAUTH_CONFIG = {
    "google_drive": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/drive.file",
        "client_id_env": "GOOGLE_DRIVE_CLIENT_ID",
        "client_secret_env": "GOOGLE_DRIVE_CLIENT_SECRET",
    },
    "spotify": {
        "auth_url": "https://accounts.spotify.com/authorize",
        "token_url": "https://accounts.spotify.com/api/token",
        "scope": "playlist-read-private playlist-modify-public playlist-modify-private user-read-email",
        "client_id_env": "SPOTIFY_CLIENT_ID",
        "client_secret_env": "SPOTIFY_CLIENT_SECRET",
    },
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "google_drive_list_files",
            "description": "List files in the connected Google Drive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Optional file name search."},
                    "page_size": {"type": "integer", "description": "Maximum files to return."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "google_drive_create_file",
            "description": "Create a text file in the connected Google Drive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                    "mime_type": {"type": "string", "description": "Defaults to text/plain."},
                },
                "required": ["name", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_search",
            "description": "Search Spotify tracks, artists, albums, or playlists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "type": {"type": "string", "description": "track, artist, album, or playlist."},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_create_playlist",
            "description": "Create a Spotify playlist and optionally add track URIs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "public": {"type": "boolean"},
                    "track_uris": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shopify_list_products",
            "description": "List products from the connected Shopify store.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shopify_create_product",
            "description": "Create a product in the connected Shopify store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body_html": {"type": "string"},
                    "product_type": {"type": "string"},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "whatsapp_send_message",
            "description": "Send a WhatsApp text message through Meta WhatsApp Cloud API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient phone number in E.164 format."},
                    "message": {"type": "string"},
                },
                "required": ["to", "message"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_CONNECTOR = {
    tool["function"]["name"]: name
    for name in CREDENTIAL_KEYS
    for tool in TOOLS
    if tool["function"]["name"].startswith(name.replace("_", "_"))
}


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)


def _credentials() -> dict[str, dict[str, str]]:
    data = _load(_STORE_PATH, {})
    return data if isinstance(data, dict) else {}


def _configured(name: str, store: dict[str, dict[str, str]] | None = None) -> bool:
    store = store if store is not None else _credentials()
    values = store.get(name, {})
    if not isinstance(values, dict):
        return False
    required = REQUIRED_KEYS[name]
    if name in {"google_drive", "spotify"}:
        return bool(values.get("access_token") or values.get("refresh_token"))
    return all(str(values.get(key, "")).strip() for key in required)


def _oauth_setting(name: str, creds: dict[str, str], key: str) -> str:
    env_key = OAUTH_CONFIG[name][key]
    short_key = "client_id" if key == "client_id_env" else "client_secret"
    return str(creds.get(short_key) or os.getenv(env_key, "")).strip()


async def _http(method: str, url: str, **kwargs: Any) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(method, url, **kwargs)
    if response.status_code >= 400:
        detail = response.text[:300].replace("\n", " ")
        raise HTTPException(status_code=502, detail=f"Upstream HTTP {response.status_code}: {detail}")
    try:
        return response.json()
    except ValueError:
        return {"text": response.text[:2000]}


async def _fresh_access_token(name: str) -> str:
    creds = _credentials().get(name, {})
    token = str(creds.get("access_token", "")).strip()
    expires_at = int(str(creds.get("expires_at", "0")).strip() or 0)
    if token and (not expires_at or expires_at > int(time.time()) + 30):
        return token

    refresh = str(creds.get("refresh_token", "")).strip()
    if not refresh:
        raise HTTPException(
            status_code=400,
            detail=f"{CONNECTOR_NAMES[name]} needs login or a valid access token.",
        )

    client_id = _oauth_setting(name, creds, "client_id_env")
    client_secret = _oauth_setting(name, creds, "client_secret_env")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail=f"Set {CONNECTOR_NAMES[name]} OAuth client_id and client_secret first.",
        )

    config = OAUTH_CONFIG[name]
    result = await _http(
        "POST",
        config["token_url"],
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    access = str(result.get("access_token", "")).strip()
    if not access:
        raise HTTPException(status_code=502, detail=f"{CONNECTOR_NAMES[name]} token refresh failed.")

    store = _credentials()
    current = dict(store.get(name, {}))
    current["access_token"] = access
    if result.get("refresh_token"):
        current["refresh_token"] = str(result["refresh_token"])
    current["expires_at"] = str(int(time.time()) + int(result.get("expires_in", 3600)))
    store[name] = current
    _save(_STORE_PATH, store)
    return access


@router.get("")
async def list_connectors(_auth=Depends(require_proxy_auth)) -> dict[str, Any]:
    store = _credentials()
    return {
        "callback_url": _CALLBACK_URL,
        "connectors": [
            {
                "id": name,
                "name": CONNECTOR_NAMES[name],
                "configured": _configured(name, store),
                "tools": [
                    tool["function"]["name"]
                    for tool in TOOLS
                    if TOOL_CONNECTOR[tool["function"]["name"]] == name
                ],
            }
            for name in CREDENTIAL_KEYS
        ],
        "tools": TOOLS,
    }


@router.post("/credentials")
async def save_credentials(
    payload: dict[str, Any] = Body(...),
    _auth=Depends(require_proxy_auth),
) -> dict[str, Any]:
    name = str(payload.get("connector", "")).strip()
    values = payload.get("values", {})
    if name not in CREDENTIAL_KEYS:
        raise HTTPException(status_code=400, detail="Unknown connector")
    if not isinstance(values, dict):
        raise HTTPException(status_code=400, detail="values must be an object")

    store = _credentials()
    current = dict(store.get(name, {}))
    for key, value in values.items():
        if key in CREDENTIAL_KEYS[name] and value is not None:
            text = str(value).strip()
            if text:
                current[key] = text
    store[name] = current
    _save(_STORE_PATH, store)
    return {"connector": name, "configured": _configured(name, store)}


@router.delete("/credentials/{name}")
async def delete_credentials(
    name: str,
    _auth=Depends(require_proxy_auth),
) -> dict[str, Any]:
    if name not in CREDENTIAL_KEYS:
        raise HTTPException(status_code=400, detail="Unknown connector")
    store = _credentials()
    store.pop(name, None)
    _save(_STORE_PATH, store)
    return {"connector": name, "configured": False}


@router.get("/{name}/oauth/start")
async def oauth_start(
    name: str,
    _auth=Depends(require_proxy_auth),
) -> dict[str, str]:
    if name not in OAUTH_CONFIG:
        raise HTTPException(status_code=400, detail=f"{name} does not use OAuth")

    creds = _credentials().get(name, {})
    client_id = _oauth_setting(name, creds, "client_id_env")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Set {CONNECTOR_NAMES[name]} client_id in Connector settings or "
                f"{OAUTH_CONFIG[name]['client_id_env']} on the server."
            ),
        )

    state = secrets.token_urlsafe(24)
    states = _load(_STATE_PATH, {})
    if not isinstance(states, dict):
        states = {}
    states[state] = {"connector": name, "ts": int(time.time())}
    _save(_STATE_PATH, states)

    config = OAUTH_CONFIG[name]
    params = {
        "client_id": client_id,
        "redirect_uri": _CALLBACK_URL,
        "response_type": "code",
        "scope": config["scope"],
        "state": state,
    }
    if name == "google_drive":
        params.update({"access_type": "offline", "prompt": "consent"})
    query = httpx.QueryParams(params)
    return {"url": f"{config['auth_url']}?{query}", "state": state}


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(request: Request) -> HTMLResponse:
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    states = _load(_STATE_PATH, {})
    info = states.pop(state, None) if isinstance(states, dict) else None
    if not info or int(info.get("ts", 0)) < int(time.time()) - 600:
        return HTMLResponse("<h2>MJA connector login failed</h2><p>Invalid or expired state.</p>", status_code=400)
    _save(_STATE_PATH, states)

    name = str(info.get("connector", ""))
    if name not in OAUTH_CONFIG or not code:
        return HTMLResponse("<h2>MJA connector login failed</h2><p>Missing code.</p>", status_code=400)

    config = OAUTH_CONFIG[name]
    creds = _credentials().get(name, {})
    client_id = _oauth_setting(name, creds, "client_id_env")
    client_secret = _oauth_setting(name, creds, "client_secret_env")
    if not client_id or not client_secret:
        return HTMLResponse("<h2>MJA connector login failed</h2><p>Missing OAuth client credentials.</p>", status_code=400)

    try:
        tokens = await _http(
            "POST",
            config["token_url"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _CALLBACK_URL,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
    except HTTPException as error:
        return HTMLResponse(f"<h2>MJA connector login failed</h2><p>{error.detail}</p>", status_code=502)

    store = _credentials()
    current = dict(store.get(name, {}))
    current["access_token"] = str(tokens.get("access_token", ""))
    if tokens.get("refresh_token"):
        current["refresh_token"] = str(tokens["refresh_token"])
    current["expires_at"] = str(int(time.time()) + int(tokens.get("expires_in", 3600)))
    store[name] = current
    _save(_STORE_PATH, store)
    return HTMLResponse(
        f"<h2>{CONNECTOR_NAMES[name]} connected</h2><p>You can close this window and return to MJA Assistant.</p>"
    )


async def _google_drive(tool: str, args: dict[str, Any], name: str) -> dict[str, Any]:
    token = await _fresh_access_token(name)
    headers = {"Authorization": f"Bearer {token}"}
    if tool == "google_drive_list_files":
        params: dict[str, Any] = {
            "pageSize": max(1, min(int(args.get("page_size", 20)), 100)),
            "fields": "files(id,name,mimeType,modifiedTime),nextPageToken",
        }
        if args.get("query"):
            params["q"] = f"name contains '{str(args['query']).replace(chr(39), chr(39) * 2)}'"
        return {"ok": True, "data": await _http("GET", "https://www.googleapis.com/drive/v3/files", headers=headers, params=params)}

    mime = str(args.get("mime_type", "text/plain"))
    content = str(args.get("content", ""))
    metadata = json.dumps({"name": str(args.get("name", "mja-file.txt")), "mimeType": mime})
    files = {
        "metadata": (None, metadata, "application/json"),
        "media": (None, content, mime),
    }
    return {"ok": True, "data": await _http("POST", "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart", headers=headers, files=files)}


async def _spotify(tool: str, args: dict[str, Any], name: str) -> dict[str, Any]:
    token = await _fresh_access_token(name)
    headers = {"Authorization": f"Bearer {token}"}
    if tool == "spotify_search":
        params = {
            "q": str(args.get("query", "")),
            "type": str(args.get("type", "track")),
            "limit": max(1, min(int(args.get("limit", 10)), 50)),
        }
        return {"ok": True, "data": await _http("GET", "https://api.spotify.com/v1/search", headers=headers, params=params)}

    me = await _http("GET", "https://api.spotify.com/v1/me", headers=headers)
    user_id = str(me.get("id", ""))
    if not user_id:
        raise HTTPException(status_code=502, detail="Could not identify Spotify user")
    playlist = await _http(
        "POST",
        f"https://api.spotify.com/v1/users/{user_id}/playlists",
        headers=headers,
        json={
            "name": str(args.get("name", "MJA playlist")),
            "description": str(args.get("description", "Created by MJA Assistant")),
            "public": bool(args.get("public", False)),
        },
    )
    uris = args.get("track_uris")
    if isinstance(uris, list) and uris:
        await _http(
            "POST",
            f"https://api.spotify.com/v1/playlists/{playlist.get('id')}/tracks",
            headers=headers,
            json={"uris": [str(uri) for uri in uris]},
        )
    return {"ok": True, "data": playlist}


async def _shopify(tool: str, args: dict[str, Any], name: str) -> dict[str, Any]:
    creds = _credentials().get(name, {})
    shop = str(creds.get("shop", "")).strip()
    domain = shop if "." in shop else f"{shop}.myshopify.com"
    headers = {"X-Shopify-Access-Token": str(creds.get("access_token", "")), "Content-Type": "application/json"}
    base = f"https://{domain}/admin/api/2025-01"
    if tool == "shopify_list_products":
        params = {"limit": max(1, min(int(args.get("limit", 20)), 250))}
        return {"ok": True, "data": await _http("GET", f"{base}/products.json", headers=headers, params=params)}
    body = {
        "product": {
            "title": str(args.get("title", "Untitled")),
            "body_html": str(args.get("body_html", "")),
            "product_type": str(args.get("product_type", "")),
        }
    }
    return {"ok": True, "data": await _http("POST", f"{base}/products.json", headers=headers, json=body)}


async def _whatsapp(tool: str, args: dict[str, Any], name: str) -> dict[str, Any]:
    creds = _credentials().get(name, {})
    phone_id = str(creds.get("phone_number_id", "")).strip()
    token = str(creds.get("access_token", "")).strip()
    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "messaging_product": "whatsapp",
        "to": str(args.get("to", "")),
        "type": "text",
        "text": {"body": str(args.get("message", ""))},
    }
    return {"ok": True, "data": await _http("POST", url, headers=headers, json=body)}


@router.post("/invoke")
async def invoke(
    payload: dict[str, Any] = Body(...),
    _auth=Depends(require_proxy_auth),
) -> dict[str, Any]:
    tool = str(payload.get("tool", "")).strip()
    args = payload.get("arguments", {})
    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="arguments must be an object")
    name = TOOL_CONNECTOR.get(tool)
    if not name:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

    store = _credentials()
    if not _configured(name, store):
        raise HTTPException(status_code=400, detail=f"{CONNECTOR_NAMES[name]} is not configured")

    if name == "google_drive":
        return await _google_drive(tool, args, name)
    if name == "spotify":
        return await _spotify(tool, args, name)
    if name == "shopify":
        return await _shopify(tool, args, name)
    return await _whatsapp(tool, args, name)
