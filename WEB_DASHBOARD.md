# Polymarket MCP Web Dashboard

A modern, real-time web dashboard for managing and monitoring the Polymarket MCP Server. Built with FastAPI, featuring a dark theme UI with WebSocket support for live updates.

## Features

### 1. Dashboard Home
- **MCP Status Monitor**: Real-time connection status (Connected/Disconnected)
- **Quick Statistics**:
  - Operation mode (FULL/READ-ONLY/DEMO)
  - Available tools count (25 or 45)
  - API call statistics
  - Uptime tracking
- **Trending Markets**: Live feed of top markets
- **Quick Actions**: One-click access to common operations
- **WebSocket Status**: Real-time connection indicator

### 2. Configuration Management
- **Wallet Information**:
  - Address display with copy-to-clipboard
  - Chain ID (Polygon Mainnet/Amoy Testnet)
  - API credentials status
- **Safety Limits** (Interactive Sliders):
  - Max Order Size (USD): $100 - $10,000
  - Max Total Exposure (USD): $1,000 - $50,000
  - Max Position Per Market (USD): $500 - $20,000
  - Min Liquidity Required (USD): $1,000 - $100,000
  - Max Spread Tolerance: 1% - 20%
- **Trading Controls**:
  - Enable/Disable Autonomous Trading
  - Confirmation Threshold: $100 - $5,000
  - Auto-Cancel on Large Spread
- **Live Preview**: See changes before saving
- **Test Configuration**: Verify settings work before applying

### 3. Market Discovery
- **Advanced Search**:
  - Full-text search across market questions
  - Real-time suggestions
  - Enter key support
- **Quick Filters**:
  - Trending markets
  - Politics category
  - Sports markets
  - Crypto markets
  - Closing soon
- **Market Table**:
  - Question/Title
  - YES/NO prices with color coding
  - 24h volume
  - Liquidity
  - Spread percentage
  - Action buttons (Analyze/Details)
- **Auto-Refresh**: Markets update every 30 seconds
- **Market Details Modal**:
  - Full market information
  - Description and metadata
  - Quick analyze button
  - Live price data

### 4. Market Analysis
- **AI-Powered Analysis**:
  - Trading recommendation (BUY/HOLD/SELL)
  - Risk assessment
  - Confidence score with visual progress bar
  - Key factors affecting the market
- **Real-time Pricing**:
  - Current bid/ask
  - Spread calculation
  - Volume metrics

### 5. System Monitoring
- **System Information**:
  - Python version
  - Platform details
  - MCP version
  - Uptime tracking
- **Performance Statistics**:
  - Total requests
  - API calls made
  - Markets viewed
  - Error count
- **Rate Limit Monitoring**:
  - Per-category rate limits
  - Visual progress bars
  - Remaining requests
- **Activity Charts** (Chart.js):
  - Request rate over time (line chart)
  - API usage patterns (bar chart)
  - Real-time updates every 5 seconds
- **Activity Log**:
  - Recent operations
  - Error tracking
  - Timestamp display

## Installation

### 1. Install Dependencies

```bash
cd /Users/caiovicentino/Desktop/poly/polymarket-mcp
pip install -e .
```

This will install:
- `fastapi>=0.104.0` - Web framework
- `uvicorn>=0.24.0` - ASGI server
- `jinja2>=3.1.0` - Template engine

### 2. Verify Installation

Check that the entry point is available:

```bash
which polymarket-web
```

## Usage

### Starting the Web Dashboard

#### Option 1: Using the Entry Point (Recommended)

```bash
polymarket-web
```

#### Option 2: Python Module

```bash
python -m polymarket_mcp.web.app
```

#### Option 3: Direct Script

```bash
python src/polymarket_mcp/web/app.py
```

### Custom Host and Port

Edit `src/polymarket_mcp/web/app.py` and modify the `start()` function call:

```python
def start(host: str | None = None, port: int | None = None):
    """Start the web dashboard server (loopback by default)."""
```

Or set the `WEB_HOST`/`WEB_PORT` environment variables instead of editing the source — `start()` reads `WEB_HOST` (default `127.0.0.1`) and logs a warning if it is bound off loopback:

```python
if __name__ == "__main__":
    start(host="localhost", port=3000)
```

### Accessing the Dashboard

Once started, open your browser to:

```
http://localhost:8080
```

## API Endpoints

### Status & Health

- `GET /api/status` - Get MCP connection status
- `GET /api/test-connection` - Test Polymarket API connection
- `GET /api/stats` - Get dashboard statistics

### Markets

- `GET /api/markets/trending?limit=10` - Get trending markets
- `GET /api/markets/search?q=query&limit=20` - Search markets
- `GET /api/markets/closing-soon?limit=20&hours=24` - Get markets closing soon
- `GET /api/markets/{market_id}` - Get market details
- `GET /api/markets/{market_id}/analyze` - Analyze market opportunity

### Configuration

- `POST /api/config` - Update configuration (saves to .env)

Request body:
```json
{
  "max_order_size_usd": 1000.0,
  "max_total_exposure_usd": 5000.0,
  "max_position_size_per_market": 2000.0,
  "min_liquidity_required": 10000.0,
  "max_spread_tolerance": 0.05,
  "enable_autonomous_trading": true,
  "require_confirmation_above_usd": 500.0,
  "auto_cancel_on_large_spread": true
}
```

### WebSocket

- `WebSocket /ws` - Real-time updates

Message types:
```javascript
// Status update
{
  "type": "status",
  "data": {
    "connected": true,
    "stats": {...}
  }
}

// Stats update (every 5 seconds)
{
  "type": "stats_update",
  "data": {
    "stats": {...},
    "timestamp": "2025-01-11T..."
  }
}

// Market update
{
  "type": "market_update",
  "data": {...}
}

// Notification
{
  "type": "notification",
  "data": {
    "message": "...",
    "type": "success|error|warning|info"
  }
}
```

## Architecture

### Backend (FastAPI)

```
/web/
├── app.py              # Main FastAPI application
├── __init__.py         # Package initialization
├── static/
│   ├── css/
│   │   └── style.css   # Dark theme styling
│   └── js/
│       └── app.js      # Client-side JavaScript
└── templates/
    ├── index.html      # Dashboard home
    ├── config.html     # Configuration management
    ├── markets.html    # Market discovery
    └── monitoring.html # System monitoring
```

### Frontend Stack

- **HTML5**: Semantic markup
- **CSS3**: Custom dark theme with CSS variables
- **Vanilla JavaScript**: No frameworks, lightweight
- **Chart.js**: Real-time charts and graphs
- **WebSockets**: Live updates

### State Management

- **Backend State**:
  - Global MCP configuration
  - Client instance
  - Safety limits
  - Active WebSocket connections
  - Statistics tracking

- **Frontend State**:
  - Local Storage for preferences
  - In-memory caching
  - WebSocket connection management

## Security Considerations

### Current Implementation

- **CORS**: Currently allows all origins for development
- **Authentication**: None (local development only)
- **Credentials**: Never sent to client-side
- **Rate Limiting**: Not implemented
- **Input Validation**: Pydantic models on backend

### Production Recommendations

1. **Enable HTTPS**:
```python
import ssl
uvicorn.run(
    app,
    host="0.0.0.0",
    port=443,
    ssl_keyfile="/path/to/key.pem",
    ssl_certfile="/path/to/cert.pem"
)
```

> **Warning:** the dashboard has **no authentication** — exposing it beyond
> loopback (even with TLS) hands control of the trading limits to anyone who
> reaches the port. Prefer a loopback tunnel (e.g. SSH port-forward) until
> authentication is actually added (the snippet below is illustrative).

2. **Add Authentication**:
```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    # Implement authentication logic
    pass

@app.get("/api/protected", dependencies=[Depends(verify_credentials)])
async def protected_route():
    pass
```

3. **Configure CORS**:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

4. **Add Rate Limiting**:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/markets/trending")
@limiter.limit("10/minute")
async def get_trending(request: Request):
    pass
```

## Development

### Running in Development Mode

```bash
# With auto-reload
uvicorn polymarket_mcp.web.app:app --reload --host 127.0.0.1 --port 8080
```

> **Note:** the dashboard has no authentication and `POST /api/config` can
> rewrite the trading safety limits — keep it bound to `127.0.0.1` unless you
> are on a trusted, isolated network.

### Debugging

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Testing

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/test_web_app_offline.py -v
```

## Customization

### Theme Colors

Edit `/static/css/style.css`:

```css
:root {
    --primary: #3b82f6;        /* Blue */
    --success: #10b981;        /* Green */
    --warning: #f59e0b;        /* Orange */
    --error: #ef4444;          /* Red */
    /* ... more colors ... */
}
```

### Adding New Pages

1. Create HTML template in `/templates/`
2. Add route in `app.py`:
```python
@app.get("/my-page", response_class=HTMLResponse)
async def my_page(request: Request):
    return templates.TemplateResponse("my_page.html", {
        "request": request,
    })
```
3. Add navigation link in navbar

### Custom API Endpoints

```python
@app.get("/api/my-endpoint")
async def my_endpoint():
    try:
        # Your logic here
        return JSONResponse({"success": True, "data": {...}})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

## Troubleshooting

### Dashboard Won't Start

**Problem**: `ModuleNotFoundError: No module named 'fastapi'`

**Solution**:
```bash
pip install -e .
```

### MCP Not Connected

**Problem**: Dashboard shows "Disconnected"

**Solution**:
1. Check `.env` file exists with credentials
2. Verify `POLYGON_PRIVATE_KEY` and `POLYGON_ADDRESS` are set
3. Check logs for configuration errors

### WebSocket Connection Failed

**Problem**: "WebSocket disconnected" in console

**Solution**:
1. Ensure no firewall blocking WebSocket connections
2. Check browser console for errors
3. Verify server is running on correct port

### Markets Not Loading

**Problem**: "Failed to load markets"

**Solution**:
1. Test connection: Click "Test Connection" button
2. Check Polymarket API is accessible
3. Verify rate limits not exceeded
4. Check server logs for API errors

### Configuration Changes Not Saving

**Problem**: Config updates don't persist

**Solution**:
1. Verify `.env` file is writable
2. Check file permissions
3. Restart MCP server after changes
4. Check server logs for write errors

## Performance

### Optimization Tips

1. **Enable Caching**:
```python
from functools import lru_cache

@lru_cache(maxsize=128)
async def get_cached_markets():
    return await get_trending_markets()
```

2. **Connection Pooling**:
Already implemented in MCP client

3. **Compression**:
```python
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
```

4. **Static File Caching**:
Configure browser caching for CSS/JS

### Monitoring Performance

- Check `/api/stats` for request counts
- Monitor WebSocket connection count
- Track API response times in logs

## Screenshots

```
┌─────────────────────────────────────────────────────────────┐
│ Polymarket MCP              [●] Connected                   │
│ Dashboard | Config | Markets | Monitoring                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ MCP Status   │  │ Statistics   │                        │
│  │ Mode: FULL   │  │ Requests: 42 │                        │
│  │ Tools: 45    │  │ Markets: 15  │                        │
│  └──────────────┘  └──────────────┘                        │
│                                                              │
│  [Test Connection] [Browse Markets] [Configure]             │
│                                                              │
│  Trending Markets                                           │
│  ┌────────────────────────────────────────────────────┐    │
│  │ Will Trump win 2024?          75% / 25%  Vol: $2M  │    │
│  │ Bitcoin above $100k in 2025?  45% / 55%  Vol: $1M  │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Future Enhancements

- [ ] User authentication and sessions
- [ ] Portfolio tracking dashboard
- [ ] Trading history visualization
- [ ] Custom alert configuration
- [ ] Multi-language support
- [ ] Mobile app (React Native)
- [ ] Advanced charting (TradingView integration)
- [ ] Export data to CSV/JSON
- [ ] Telegram/Discord notifications
- [ ] Dark/Light theme toggle

## License

Same as Polymarket MCP Server (see LICENSE file)

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review server logs
3. Check GitHub issues
4. Open new issue with logs and details

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create feature branch
3. Test changes thoroughly
4. Submit pull request with description

---

**Dashboard Version**: 0.2.0
**Last Updated**: January 2025
**Built with**: FastAPI, Vanilla JS, Chart.js
**Data source**: live Polymarket API (read-only) when connected
**Tests**: offline suite `tests/test_web_app_offline.py` — hermetic fakes at module seams, no network (repo-wide test strategy in TESTING.md)
