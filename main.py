import json
import sys
from typing import Optional, Dict, Any, AsyncIterator
import os
import httpx
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Thread
from dotenv import load_dotenv
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP, Context
import uvicorn

# Load .env file
load_dotenv()

CLIENT_ID = os.getenv("REWARDRALLY_CLIENT_ID")
CLIENT_SECRET = os.getenv("REWARDRALLY_CLIENT_SECRET")
TOKEN_STORE_PATH = os.path.join(os.path.dirname(__file__), ".tokens")

BASE_URL = os.getenv("BASE_URL")
AUTH_URL = f"{BASE_URL}/v1/tokens/accesstoken"
CLIENTS_URL = f"{BASE_URL}/v1/clients"

app = FastAPI(title="RewardRally MCP Auth Handler")

@dataclass
class RewardRallyContext:
    token: str
    http_client: httpx.AsyncClient
    app: FastAPI
    server_thread: Optional[Thread] = None

def save_token(token: str):
    try:
        with open(TOKEN_STORE_PATH, "w") as f:
            f.write(token)
    except Exception as e:
        print(f"Failed to save token: {e}", file=sys.stderr)

def load_token() -> Optional[str]:
    try:
        if os.path.exists(TOKEN_STORE_PATH):
            with open(TOKEN_STORE_PATH, "r") as f:
                return f.read().strip()
    except:
        return None
    return None

async def fetch_access_token() -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(AUTH_URL, json={
            "clientId": CLIENT_ID,
            "clientSecret": CLIENT_SECRET
        })
        resp.raise_for_status()
        if resp.status_code != 200:
            raise Exception(f"Failed to fetch access token: {resp.text}")
        return resp.json()["data"]["access_token"]

@asynccontextmanager
async def rewardrally_lifespan(server: FastMCP) -> AsyncIterator[RewardRallyContext]:
    print("Initializing RewardRally context...", file=sys.stderr)

    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("REWARDRALLY_CLIENT_ID and REWARDRALLY_CLIENT_SECRET must be set in the .env")

    token = load_token()
    valid = False

    http_client = httpx.AsyncClient(headers={"Content-Type": "application/json"})

    if token:
        http_client.headers["Authorization"] = f"Bearer {token}"
        try:
            r = await http_client.get(CLIENTS_URL)
            if r.status_code == 200:
                print("Restored previous session", file=sys.stderr)
                valid = True
        except Exception:
            print("Previous token invalid", file=sys.stderr)

    if not valid:
        print("Fetching new token...", file=sys.stderr)
        token = await fetch_access_token()
        save_token(token)
        http_client.headers["Authorization"] = f"Bearer {token}"
        print("Access token acquired and saved", file=sys.stderr)

    ctx = RewardRallyContext(
        token=token,
        http_client=http_client,
        app=app
    )

    try:
        yield ctx
    finally:
        await http_client.aclose()
        print("Shutting down RewardRally context", file=sys.stderr)

mcp = FastMCP(
    "rewardrally",
    lifespan=rewardrally_lifespan,
    dependencies=["fastapi", "uvicorn", "httpx", "python-dotenv", "mcp-server"],
)

with open("./swagger.json") as f:
    swagger_spec = json.load(f)

# Generate tools dynamically from swagger
for path, methods in swagger_spec.get("paths", {}).items():
    for method, details in methods.items():
        func_name = f"{method}_{path.strip('/').replace('/', '_').replace('{', '').replace('}', '')}"
        summary = details.get("summary", "No summary provided")
        parameters = details.get("parameters", [])

        path_keys = [p["name"] for p in parameters if p.get("in") == "path"]
        body_required = any(p.get("in") == "body" for p in parameters)

        def create_tool(path=path, method=method.upper(), summary=summary, parameters=parameters, func_name=func_name, path_keys=path_keys, body_required=body_required):
            @mcp.tool(name=func_name)
            async def dynamic_tool(ctx: Context, **kwargs) -> Dict[str, Any]:
                rr_ctx = ctx.request_context.lifespan_context
                filled_path = path
                kwargs = kwargs.get("kwargs", {})
                for key in path_keys:
                    if key not in kwargs:
                        raise ValueError(f"Missing required path parameter: {key}")
                    filled_path = filled_path.replace("{" + key + "}", str(kwargs[key]))
                url = f"{BASE_URL}{filled_path}"
                headers = {"Authorization": f"Bearer {rr_ctx.token}"}

                print(f"[URL]: {url}", file=sys.stderr)

                try:
                    if method == "GET":
                        r = await rr_ctx.http_client.get(url, headers=headers)
                    else:
                        payload = kwargs.get("payload") if body_required else None
                        if payload:
                            print(f"[Payload]: {payload}", file=sys.stderr)
                        r = await rr_ctx.http_client.request(method, url, headers=headers, json=payload)

                    r.raise_for_status()
                    return r.json()

                except httpx.HTTPStatusError as e:
                    return {"error": f"HTTP Error: {str(e)}"}
                except Exception as e:
                    return {"error": str(e)}

            dynamic_tool.__doc__ = summary
            dynamic_tool.__name__ = func_name
            return dynamic_tool

        # Register tool in global scope
        globals()[func_name] = create_tool()
if __name__ == "__main__":
    print("Starting RewardRally MCP server...", file=sys.stderr)
    mcp.run()
    # uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=False)
