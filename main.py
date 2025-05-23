import sys
from typing import Optional, Dict, Any, List, AsyncIterator
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
APPLICATION_ID = os.getenv("REWARDRALLY_APPLICATION_ID")
TOKEN_STORE_PATH = os.path.join(os.path.dirname(__file__), ".tokens")

BASE_URL = "https://stage-gamificationapi.rewardrally.in"
AUTH_URL = f"{BASE_URL}/v1/tokens/accesstoken"
CLIENTS_URL = f"{BASE_URL}/v1/clients"
USERS_URL = f"{BASE_URL}/v1/users/application/{APPLICATION_ID}"
LEADERBOARD_URL = f"{BASE_URL}/leaderBoard/application/{APPLICATION_ID}/rank/1000"

app = FastAPI(title="RewardRally MCP Auth Handler")

@dataclass
class RewardRallyContext:
    """Holds access token and API client"""
    token: str
    http_client: httpx.AsyncClient
    app: FastAPI
    server_thread: Optional[Thread] = None

def save_token(token: str):
    try:
        with open(TOKEN_STORE_PATH, "w") as f:
            f.write(token)
    except Exception as e:
        print(f"Failed to save token: {e}",file=sys.stderr)

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
    print("Initializing RewardRally context...",file=sys.stderr)
    
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
                print("Restored previous session",file=sys.stderr)
                valid = True
        except Exception:
            print("Previous token invalid",file=sys.stderr)

    if not valid:
        print("Fetching new token...",file=sys.stderr)
        token = await fetch_access_token()
        save_token(token)
        http_client.headers["Authorization"] = f"Bearer {token}"
        print("Access token acquired and saved",file=sys.stderr)

    ctx = RewardRallyContext(
        token=token,
        http_client=http_client,
        app=app
    )

    try:
        yield ctx
    finally:
        await http_client.aclose()
        print("Shutting down RewardRally context",file=sys.stderr)

mcp = FastMCP(
    "rewardrally",
    lifespan=rewardrally_lifespan,
    dependencies=["fastapi", "uvicorn", "httpx", "python-dotenv", "mcp-server"],
)

@mcp.tool()
async def get_clients(ctx: Context) -> Dict[str, Any]:
    """Get list of clients from RewardRally"""
    rr_ctx: RewardRallyContext = ctx.request_context.lifespan_context
    try:
        print(rr_ctx.token,file=sys.stderr)
        r = await rr_ctx.http_client.get(CLIENTS_URL)
        r.raise_for_status()
        if r.status_code != 200:
            raise Exception(f"Failed to fetch clients: {r.text}")
        print(r.json(),file=sys.stderr)
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP Error: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}
@mcp.tool()
async def get_users_by_appid(ctx: Context) -> Dict[str, Any]:
    """Get list of users from RewardRally by app ID"""
    rr_ctx: RewardRallyContext = ctx.request_context.lifespan_context
    try:
        print(rr_ctx.token,file=sys.stderr)
        r = await rr_ctx.http_client.get(USERS_URL)
        r.raise_for_status()
        print(r.json(),file=sys.stderr)
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP Error: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}
@mcp.tool()
async def get_leaderboard(ctx: Context) -> Dict[str, Any]:
    """ Get leaderboard from RewardRally"""
    rr_ctx: RewardRallyContext = ctx.request_context.lifespan_context
    try:
        print(rr_ctx.token,file=sys.stderr)
        r = await rr_ctx.http_client.get(LEADERBOARD_URL)
        r.raise_for_status()
        print(r.json(),file=sys.stderr)
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP Error: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    print("Starting RewardRally MCP server...",file=sys.stderr)
    mcp.run()