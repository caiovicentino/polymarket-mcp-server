# 🎬 Demo Video Script - Polymarket MCP Server

Complete script for creating demonstration videos.

---

## Video 1: Complete Walkthrough (8 minutes)

### Title
"Polymarket MCP Server - Complete Setup & Trading Demo"

### Intro (30 seconds)

**[Screen: Project logo]**

**Voiceover:**
"Welcome! In this video, I'll show you how to set up the Polymarket MCP Server and enable Claude to autonomously trade prediction markets. This integration gives Claude 45 powerful tools for market analysis and trading. Let's get started!"

**[Show: Feature highlights slide]**
- 45 comprehensive tools
- Real-time market analysis
- Autonomous trading
- Enterprise safety limits

---

### Part 1: Installation (2 minutes)

**[Screen: Terminal/Desktop]**

**Voiceover:**
"First, let's install the server. I'll demonstrate the easiest method - the GUI Setup Wizard."

**[Show: Terminal commands]**
```bash
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server
python -m venv venv
source venv/bin/activate
pip install -e .
```

**Voiceover:**
"Now we launch the setup wizard:"

**[Show: Command]**
```bash
python setup_wizard.py
```

**[Screen: Setup Wizard Welcome]**

**Voiceover:**
"The wizard guides us through five simple steps. First, we choose our installation type."

**[Show: Installation type selection]**

**Voiceover:**
"I'll select Full Installation to enable trading. For learning, you can choose Demo Mode which doesn't require a wallet."

**[Show: Wallet configuration screen]**

**Voiceover:**
"Next, we configure our Polygon wallet. Never share your private key with anyone. The wizard validates our credentials."

**[Show: Validation success]**

**Voiceover:**
"Great! Credentials validated. Now let's set safety limits."

**[Show: Safety limits screen with sliders]**

**Voiceover:**
"These limits protect your funds. I'll use the Moderate preset: $1000 max per order, $5000 total exposure. You can adjust these based on your risk tolerance."

**[Show: Claude Desktop integration]**

**Voiceover:**
"The wizard automatically configures Claude Desktop. It detects the config file and shows a preview of the changes."

**[Click: Configure Automatically]**

**[Show: Success message]**

**Voiceover:**
"Perfect! Installation complete. Now we restart Claude Desktop to load the server."

---

### Part 2: Market Discovery (2 minutes)

**[Screen: Claude Desktop]**

**Voiceover:**
"Let's explore what we can do. First, let's find trending markets."

**[Type in Claude]**
```
Show me the top 10 trending markets on Polymarket in the last 24 hours
```

**[Show: Claude's response with market list]**

**Voiceover:**
"Excellent! Claude returns the hottest markets with volume, prices, and liquidity. Let's dig deeper into one."

**[Type in Claude]**
```
Analyze the trading opportunity for [market name from list]
```

**[Show: AI analysis with BUY/SELL/HOLD recommendation]**

**Voiceover:**
"The AI analyzes market conditions, volume trends, liquidity, and provides a recommendation with confidence score and risk assessment. This is incredibly powerful for decision-making."

**[Type in Claude]**
```
Show me the orderbook depth for this market
```

**[Show: Orderbook data]**

**Voiceover:**
"We can see all bids and asks, helping us understand market depth and optimal entry points."

---

### Part 3: Making a Trade (2 minutes)

**[Screen: Claude Desktop]**

**Voiceover:**
"Now let's execute our first trade. I'll use natural language - no complex commands needed."

**[Type in Claude]**
```
Buy $100 of YES tokens in [market_id] at $0.65
```

**[Show: Claude processing]**

**Voiceover:**
"Claude validates the order against our safety limits, checks liquidity, and calculates optimal parameters."

**[Show: Confirmation prompt]**

**Voiceover:**
"Since this order is above $100, it asks for confirmation. This is our confirmation threshold working. Let me confirm."

**[Type: yes]**

**[Show: Order execution and confirmation]**

**Voiceover:**
"Order placed! Claude returns the order ID, status, and execution details. We can track this order."

**[Type in Claude]**
```
Show me my open orders
```

**[Show: Open orders list]**

**Voiceover:**
"There's our order. We can also place limit orders that execute later:"

**[Type in Claude]**
```
Place a limit order: sell 200 NO tokens at $0.40 in [market_id], good-til-cancelled
```

**[Show: Limit order placed]**

**Voiceover:**
"Perfect! Our limit order is live and will execute if the price reaches $0.40."

---

### Part 4: Portfolio Management (1 minute)

**[Screen: Claude Desktop]**

**Voiceover:**
"Let's check our portfolio."

**[Type in Claude]**
```
Show me all my current positions
```

**[Show: Positions list with P&L]**

**Voiceover:**
"We see all active positions, entry prices, current values, and unrealized P&L."

**[Type in Claude]**
```
What's my total portfolio value?
```

**[Show: Portfolio summary]**

**Voiceover:**
"Total value, realized profits, unrealized gains - everything at a glance."

**[Type in Claude]**
```
Analyze my portfolio risk and suggest improvements
```

**[Show: Risk analysis]**

**Voiceover:**
"The AI analyzes concentration risk, liquidity risk, and diversification, then suggests optimizations. This helps maintain a balanced portfolio."

---

### Part 5: Real-time Monitoring (30 seconds)

**[Screen: Claude Desktop]**

**Voiceover:**
"Finally, let's set up real-time monitoring."

**[Type in Claude]**
```
Subscribe to price changes for [market_id]
```

**[Show: Subscription confirmed]**

**Voiceover:**
"Now we'll receive live updates whenever prices change. You can monitor multiple markets simultaneously."

**[Show: Live price update notification]**

**Voiceover:**
"There's a price update! The WebSocket connection keeps us informed in real-time."

---

### Conclusion (30 seconds)

**[Screen: Feature summary]**

**Voiceover:**
"We've covered installation, market discovery, trading, portfolio management, and real-time monitoring. The Polymarket MCP Server puts professional-grade prediction market trading at your fingertips through simple conversations with Claude."

**[Show: Links and resources]**

**Resources:**
- GitHub: github.com/joe67-67/polymarket-mcp-server
- Documentation: Full guides in repository
- Community: Yield Hacker, Renda Cripto, Cultura Builder

**Voiceover:**
"Check out the GitHub repository for complete documentation, examples, and community support. Remember to start with small amounts and understand the risks. Happy trading!"

**[Show: Call to action]**
- ⭐ Star the repository
- 📖 Read the documentation
- 💬 Join the community
- 🐦 Follow @caiovicentino

**[End screen]**

---

## Video 2: Quick Installation (3 minutes)

### Title
"Install Polymarket MCP Server in 3 Minutes"

### Script

**Intro (15 seconds):**
"Quick installation guide for Polymarket MCP Server. Three methods: GUI wizard, automated script, or Docker. Let's go!"

**Method 1: GUI Wizard (60 seconds):**
```bash
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server
python -m venv venv
source venv/bin/activate
pip install -e .
python setup_wizard.py
```

[Fast-forward through wizard steps]

**Method 2: Automated Script (45 seconds):**
```bash
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server
chmod +x install.sh
./install.sh
```

[Show script running]

**Method 3: Docker (30 seconds):**
```bash
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server
cp .env.example .env
# Edit .env
docker-compose up -d
```

[Show Docker containers starting]

**Testing (30 seconds):**
[Open Claude Desktop]
"Show me trending markets on Polymarket"

[Show successful response]

**Outro (15 seconds):**
"Done! Choose the method that suits you best. Check the repository for detailed guides."

---

## Video 3: First Trade Tutorial (5 minutes)

### Title
"Your First Polymarket Trade with Claude"

### Script

**Intro (20 seconds):**
"Ready to make your first prediction market trade? I'll walk you through finding a market, analyzing it, and executing a trade safely."

**Part 1: Finding Markets (90 seconds):**

[Claude Desktop]
```
Show me markets about the 2024 presidential election
```

[Show results]

"Let's analyze one:"
```
Analyze the trading opportunity for [specific market]
```

[Show detailed analysis]

"Check liquidity:"
```
What's the liquidity and volume for this market?
```

**Part 2: Understanding the Market (60 seconds):**

```
Show me the current orderbook
```

[Explain bid/ask spread]

```
What's the current price and spread?
```

[Show price data]

"The spread is 2% - acceptable for trading."

**Part 3: Executing the Trade (90 seconds):**

```
Buy $50 of YES tokens at current market price
```

[Show confirmation]

"Notice the safety checks: liquidity verified, within order limit, reasonable spread."

[Confirm]

[Show execution]

"Trade executed! Order filled at $0.68."

**Part 4: Monitoring (40 seconds):**

```
Show me my position in this market
```

[Show position details]

```
Subscribe to price updates for this market
```

[Show real-time updates]

**Outro (20 seconds):**
"That's it! You've placed your first trade. Remember: start small, understand the market, and use safety limits. Good luck!"

---

## Video 4: Safety Configuration (4 minutes)

### Title
"Configuring Safety Limits for Secure Trading"

### Script

**Intro (20 seconds):**
"Learn how to configure safety limits to protect your funds when trading with Claude."

**Part 1: Understanding Safety Limits (60 seconds):**

[Show diagram of safety features]
- Order size limits
- Total exposure caps
- Position limits per market
- Liquidity requirements
- Spread tolerance
- Confirmation thresholds

**Part 2: Setting Conservative Limits (45 seconds):**

[Show .env file]
```env
MAX_ORDER_SIZE_USD=500
MAX_TOTAL_EXPOSURE_USD=2000
MAX_POSITION_SIZE_PER_MARKET=1000
REQUIRE_CONFIRMATION_ABOVE_USD=100
MIN_LIQUIDITY_REQUIRED=10000
MAX_SPREAD_TOLERANCE=0.05
```

"These conservative limits are perfect for beginners."

**Part 3: Using the Setup Wizard (60 seconds):**

[Launch wizard]
[Show safety limits step]
[Demonstrate presets: Conservative, Moderate, Aggressive]
[Adjust individual sliders]
[Show real-time value updates]

**Part 4: Testing Safety Limits (45 seconds):**

[Claude Desktop]
```
Buy $2000 of YES tokens in [market]
```

[Show error: Exceeds MAX_ORDER_SIZE_USD]

"Perfect! The safety limit blocked an order that's too large."

```
Buy $400 of YES tokens in [market]
```

[Show confirmation prompt]

"Order size is OK, but above confirmation threshold, so Claude asks first."

**Part 5: Best Practices (30 seconds):**

1. Start with conservative limits
2. Increase gradually as you gain experience
3. Never disable all safety features
4. Use confirmation for significant amounts
5. Monitor your exposure regularly

**Outro (20 seconds):**
"Safety limits are your first line of defense. Configure them carefully and adjust based on your risk tolerance and experience."

---

## Video 5: Advanced Features (6 minutes)

### Title
"Advanced Trading Features - Polymarket MCP Server"

### Topics Covered:

1. **Batch Orders** (60 seconds)
   - Placing multiple orders at once
   - Order strategies

2. **Smart Trade Execution** (60 seconds)
   - AI-suggested pricing
   - Aggressive/passive/mid strategies

3. **Portfolio Rebalancing** (60 seconds)
   - Automated rebalancing
   - Slippage protection

4. **Real-time WebSocket** (60 seconds)
   - Multiple subscriptions
   - Order status tracking
   - Market resolution alerts

5. **AI Analysis Tools** (90 seconds)
   - Market opportunity analysis
   - Portfolio optimization
   - Risk assessment

6. **Programmatic Usage** (60 seconds)
   - Python API
   - Custom strategies
   - Integration examples

---

## Production Notes

### Equipment Needed:
- Screen recording software (OBS Studio, ScreenFlow, Camtasia)
- Microphone (USB or headset with good quality)
- Video editing software
- Test Polygon wallet with small USDC amount

### Recording Tips:
1. Use 1920x1080 resolution
2. Record terminal at readable font size (14-16pt)
3. Use cursor highlighting
4. Slow down for complex steps
5. Pause between sections for easier editing
6. Record multiple takes of difficult sections

### Editing Checklist:
- [ ] Add intro graphics
- [ ] Insert transitions between sections
- [ ] Add text overlays for key points
- [ ] Include error warnings in red
- [ ] Add success confirmations in green
- [ ] Background music (low volume)
- [ ] Closed captions
- [ ] End screen with links

### Publishing:
- YouTube (primary)
- Twitter (clips)
- GitHub repository (embed)
- Documentation (links)

### Video Thumbnails:
- High contrast
- Large text
- Project logo
- Action screenshot
- Consistent branding

---

## Call to Action Templates

### For all videos:

**Links in Description:**
```
🔗 GitHub Repository: https://github.com/joe67-67/polymarket-mcp-server
📖 Documentation: [link to README]
💬 Discord: [invite link]
🐦 Twitter: @caiovicentino
⭐ Star the repo to support development!
```

**Pinned Comment:**
```
Timestamps:
0:00 - Introduction
0:30 - Installation
2:30 - Market Discovery
4:30 - Making a Trade
6:30 - Portfolio Management
7:30 - Conclusion

Have questions? Drop them below! 👇
```

---

**Made with ❤️ by [Caio Vicentino](https://github.com/caiovicentino)**

*Ready to create amazing demo videos!* 🎬
