"""
FastAPI Web Dashboard for Polymarket MCP Server.

Provides web UI for:
- Configuration management
- Real-time monitoring
- Market discovery and analysis
- Connection testing
- Subscription management
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from pydantic import BaseModel, ValidationError

from ..config import load_config, PolymarketConfig
from ..auth import create_polymarket_client, PolymarketClient
from ..utils import get_rate_limiter, create_safety_limits_from_config, SafetyLimits
from ..tools import market_discovery, market_analysis

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: load config on startup, close websockets on shutdown."""
    await load_mcp_config()
    logger.info("Polymarket MCP Dashboard started")
    try:
        yield
    finally:
        for ws in active_websockets:
            try:
                await ws.close()
            except Exception:
                pass
        logger.info("Dashboard shutdown complete")


# Initialize FastAPI app
app = FastAPI(
    title="Polymarket MCP Dashboard",
    description="Web dashboard for Polymarket MCP Server",
    version="0.1.0",
    lifespan=lifespan,
)

# Template and static file directories
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Global state
config: Optional[PolymarketConfig] = None
client: Optional[PolymarketClient] = None
safety_limits: Optional[SafetyLimits] = None
active_websockets: list[WebSocket] = []

# Statistics tracking
stats = {
    "requests_total": 0,
    "markets_viewed": 0,
    "api_calls": 0,
    "errors": 0,
    "uptime_start": datetime.now(),
}


class ConfigUpdateRequest(BaseModel):
    """Request model for configuration updates"""
    max_order_size_usd: float
    max_total_exposure_usd: float
    max_position_size_per_market: float
    min_liquidity_required: float
    max_spread_tolerance: float
    enable_autonomous_trading: bool
    require_confirmation_above_usd: float
    auto_cancel_on_large_spread: bool


async def load_mcp_config():
    """Load MCP configuration on startup"""
    global config, client, safety_limits

    try:
        logger.info("Loading MCP configuration...")
        config = load_config()

        # Initialize client
        client = create_polymarket_client(
            private_key=config.POLYGON_PRIVATE_KEY,
            address=config.POLYGON_ADDRESS,
            chain_id=config.POLYMARKET_CHAIN_ID,
            api_key=config.POLYMARKET_API_KEY,
            api_secret=config.POLYMARKET_PASSPHRASE,
            passphrase=config.POLYMARKET_PASSPHRASE,
        )

        # Initialize safety limits
        safety_limits = create_safety_limits_from_config(config)

        logger.info(f"Configuration loaded for address: {config.POLYGON_ADDRESS}")

    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        logger.warning("Dashboard running without MCP connection")


# ============================================================================
# HTML Pages
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Dashboard home page"""
    stats["requests_total"] += 1

    # Calculate uptime
    uptime = datetime.now() - stats["uptime_start"]

    # Get MCP status
    mcp_status = {
        "connected": config is not None and client is not None,
        "mode": "FULL" if (client and client.has_api_credentials()) else "READ-ONLY",
        "address": config.POLYGON_ADDRESS if config else "Not configured",
        "chain_id": config.POLYMARKET_CHAIN_ID if config else None,
        "tools_available": 45 if (client and client.has_api_credentials()) else 25,
    }

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "mcp_status": mcp_status,
            "stats": stats,
            "uptime": str(uptime).split('.')[0],  # Remove microseconds
        },
    )


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    """Configuration management page"""
    stats["requests_total"] += 1

    current_config = None
    if config and safety_limits:
        current_config = {
            "safety_limits": {
                "max_order_size_usd": safety_limits.max_order_size_usd,
                "max_total_exposure_usd": safety_limits.max_total_exposure_usd,
                "max_position_size_per_market": safety_limits.max_position_size_per_market,
                "min_liquidity_required": safety_limits.min_liquidity_required,
                "max_spread_tolerance": safety_limits.max_spread_tolerance,
            },
            "trading_controls": {
                "enable_autonomous_trading": config.ENABLE_AUTONOMOUS_TRADING,
                "require_confirmation_above_usd": config.REQUIRE_CONFIRMATION_ABOVE_USD,
                "auto_cancel_on_large_spread": config.AUTO_CANCEL_ON_LARGE_SPREAD,
            },
            "wallet": {
                "address": config.POLYGON_ADDRESS,
                "chain_id": config.POLYMARKET_CHAIN_ID,
            },
            "has_api_credentials": client.has_api_credentials() if client else False,
        }

    return templates.TemplateResponse(
        request,
        "config.html",
        {"config": current_config},
    )


@app.get("/markets", response_class=HTMLResponse)
async def markets_page(request: Request):
    """Markets discovery and analysis page"""
    stats["requests_total"] += 1

    return templates.TemplateResponse(request, "markets.html")


@app.get("/monitoring", response_class=HTMLResponse)
async def monitoring_page(request: Request):
    """System monitoring and analytics page"""
    stats["requests_total"] += 1

    # Get rate limiter status
    rate_limiter = get_rate_limiter()
    rate_status = rate_limiter.get_status() if config else {}

    # System info
    import sys
    import platform

    system_info = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "mcp_version": "0.1.0",
        "uptime": str(datetime.now() - stats["uptime_start"]).split('.')[0],
    }

    return templates.TemplateResponse(
        request,
        "monitoring.html",
        {
            "stats": stats,
            "rate_status": rate_status,
            "system_info": system_info,
        },
    )


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/api/status")
async def get_status():
    """Get MCP connection status"""
    stats["api_calls"] += 1

    if not config or not client:
        return JSONResponse({
            "connected": False,
            "error": "MCP not configured"
        })

    return JSONResponse({
        "connected": True,
        "address": config.POLYGON_ADDRESS,
        "chain_id": config.POLYMARKET_CHAIN_ID,
        "has_api_credentials": client.has_api_credentials(),
        "mode": "FULL" if client.has_api_credentials() else "READ-ONLY",
        "tools_available": 45 if client.has_api_credentials() else 25,
        "rate_limits": get_rate_limiter().get_status(),
    })


@app.get("/api/test-connection")
async def test_connection():
    """Test Polymarket API connection"""
    stats["api_calls"] += 1

    if not client:
        stats["errors"] += 1
        raise HTTPException(status_code=500, detail="MCP client not initialized")

    try:
        # Try to fetch trending markets as connection test
        result = await market_discovery.handle_tool("get_trending_markets", {"limit": 5})

        return JSONResponse({
            "success": True,
            "message": "Connection successful",
            "markets_found": len(result),
        })
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Connection test failed: {e}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.get("/api/markets/trending")
async def get_trending_markets(limit: int = 10):
    """Get trending markets"""
    stats["api_calls"] += 1

    try:
        result = await market_discovery.handle_tool("get_trending_markets", {"limit": limit})
        stats["markets_viewed"] += 1

        # Extract text content from MCP response
        if result and len(result) > 0:
            import json
            data = json.loads(result[0].text)
            return JSONResponse(data)

        return JSONResponse({"markets": []})

    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Failed to get trending markets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/markets/search")
async def search_markets(q: str, limit: int = 20):
    """Search markets by query"""
    stats["api_calls"] += 1

    try:
        result = await market_discovery.handle_tool("search_markets", {
            "query": q,
            "limit": limit
        })
        stats["markets_viewed"] += 1

        if result and len(result) > 0:
            import json
            data = json.loads(result[0].text)
            return JSONResponse(data)

        return JSONResponse({"markets": []})

    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/markets/{market_id}")
async def get_market_details(market_id: str):
    """Get detailed market information"""
    stats["api_calls"] += 1

    try:
        result = await market_analysis.handle_tool("get_market_details", {
            "market_id": market_id
        })

        if result and len(result) > 0:
            import json
            data = json.loads(result[0].text)
            return JSONResponse(data)

        raise HTTPException(status_code=404, detail="Market not found")

    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Failed to get market details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/markets/{market_id}/analyze")
async def analyze_market(market_id: str):
    """Analyze market opportunity"""
    stats["api_calls"] += 1

    try:
        result = await market_analysis.handle_tool("analyze_market_opportunity", {
            "market_id": market_id
        })

        if result and len(result) > 0:
            import json
            data = json.loads(result[0].text)
            return JSONResponse(data)

        raise HTTPException(status_code=404, detail="Market not found")

    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Market analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config")
async def update_config(config_update: ConfigUpdateRequest):
    """Update configuration (saves to .env file)"""
    stats["api_calls"] += 1

    try:
        # Update environment file
        env_file = Path(".env")

        if not env_file.exists():
            stats["errors"] += 1
            raise HTTPException(status_code=404, detail=".env file not found")

        # Read current .env
        env_lines = env_file.read_text().split('\n')
        updated_lines = []

        # Update values
        updates = {
            "MAX_ORDER_SIZE_USD": str(config_update.max_order_size_usd),
            "MAX_TOTAL_EXPOSURE_USD": str(config_update.max_total_exposure_usd),
            "MAX_POSITION_SIZE_PER_MARKET": str(config_update.max_position_size_per_market),
            "MIN_LIQUIDITY_REQUIRED": str(config_update.min_liquidity_required),
            "MAX_SPREAD_TOLERANCE": str(config_update.max_spread_tolerance),
            "ENABLE_AUTONOMOUS_TRADING": str(config_update.enable_autonomous_trading).lower(),
            "REQUIRE_CONFIRMATION_ABOVE_USD": str(config_update.require_confirmation_above_usd),
            "AUTO_CANCEL_ON_LARGE_SPREAD": str(config_update.auto_cancel_on_large_spread).lower(),
        }

        for line in env_lines:
            updated = False
            for key, value in updates.items():
                if line.startswith(f"{key}="):
                    updated_lines.append(f"{key}={value}")
                    updated = True
                    break
            if not updated:
                updated_lines.append(line)

        # Write back
        env_file.write_text('\n'.join(updated_lines))

        # Reload config
        await load_mcp_config()

        return JSONResponse({
            "success": True,
            "message": "Configuration updated successfully. Restart MCP server for changes to take effect."
        })

    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Config update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats():
    """Get dashboard statistics"""
    return JSONResponse({
        **stats,
        "uptime": str(datetime.now() - stats["uptime_start"]).split('.')[0],
        "uptime_seconds": (datetime.now() - stats["uptime_start"]).total_seconds(),
    })


# ============================================================================
# WebSocket for Real-time Updates
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time dashboard updates"""
    await websocket.accept()
    active_websockets.append(websocket)

    try:
        # Send initial status
        await websocket.send_json({
            "type": "status",
            "data": {
                "connected": config is not None,
                "stats": stats,
            }
        })

        # Keep connection alive and send periodic updates
        while True:
            await asyncio.sleep(5)  # Update every 5 seconds

            # Send stats update
            await websocket.send_json({
                "type": "stats_update",
                "data": {
                    "stats": stats,
                    "timestamp": datetime.now().isoformat(),
                }
            })

    except WebSocketDisconnect:
        active_websockets.remove(websocket)
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in active_websockets:
            active_websockets.remove(websocket)


async def broadcast_update(message: dict):
    """Broadcast message to all connected WebSocket clients"""
    disconnected = []
    for ws in active_websockets:
        try:
            await ws.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send to WebSocket: {e}")
            disconnected.append(ws)

    # Remove disconnected clients
    for ws in disconnected:
        active_websockets.remove(ws)


# ============================================================================
# Server Startup
# ============================================================================

def start(host: str = "0.0.0.0", port: int = 8080):
    """Start the web dashboard server"""
    logger.info(f"Starting Polymarket MCP Dashboard on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start()
