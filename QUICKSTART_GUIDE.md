# ⚡ Quick Start Guide - Polymarket MCP Server

Get started in 5 minutes with the easiest installation path.

---

## 🚀 Fastest Path to Success

### Step 1: Install (2 minutes)

```bash
# Clone the repository
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install
pip install -e .
```

### Step 2: Run Setup Wizard (3 minutes)

```bash
python setup_wizard.py
```

**Follow the wizard:**
1. Click "Next" on welcome screen
2. Choose "Demo Mode" or "Full Installation"
3. If Full: Enter wallet credentials and validate
4. Adjust safety limits (or use preset)
5. Click "Configure Automatically" for Claude Desktop
6. Done!

### Step 3: Restart Claude Desktop

Close Claude Desktop completely and reopen it.

### Step 4: Test It!

In Claude Desktop, type:
```
Show me the top trending markets on Polymarket
```

**Success!** You should see market data. 🎉

---

## 📖 What to Do Next

### Learn the Basics
- Read [README.md](README.md) for feature overview
- Check [FAQ.md](FAQ.md) for common questions
- Review [VISUAL_INSTALL_GUIDE.md](VISUAL_INSTALL_GUIDE.md) for detailed setup

### Try These Commands

**Market Discovery:**
```
"Find markets about the 2024 presidential election"
"Show me crypto prediction markets"
"What sports markets are closing soon?"
```

**Market Analysis:**
```
"Analyze the trading opportunity for [market name]"
"Show me the orderbook for [market]"
"What's the current spread?"
```

**Trading (Full Mode only):**
```
"Buy $50 of YES tokens at market price"
"Place a limit order to sell 100 NO at $0.45"
"Show me my open orders"
```

**Portfolio (Full Mode only):**
```
"Show me all my positions"
"What's my total portfolio value?"
"Analyze my portfolio risk"
```

---

## 🎯 Demo Mode vs Full Mode

### Demo Mode (No wallet needed)
✅ Perfect for learning
✅ Market discovery and search
✅ Real-time analysis
✅ AI-powered insights
❌ Cannot trade

### Full Mode (Requires wallet)
✅ Everything in Demo Mode
✅ Place orders and trades
✅ Manage portfolio
✅ Real-time position tracking
⚠️ Real money - start small!

**Switch modes anytime:** Just run `python setup_wizard.py` again

---

## 🆘 Troubleshooting

### Wizard won't start
```bash
# Install tkinter if needed
pip install tk

# Or use automated script instead
./install.sh
```

### Claude Desktop doesn't see server
1. Check config file exists (wizard shows path)
2. Restart Claude Desktop completely (Quit → Reopen)
3. Check logs: `~/Library/Logs/Claude/` (macOS)

### Validation errors
- Private key: Remove 0x prefix, must be 64 hex characters
- Address: Must start with 0x, must be 42 characters
- See [FAQ.md](FAQ.md) for more solutions

---

## 📚 Documentation Map

**Choose your path:**

```
New User
    │
    ├─ Quick Start (you are here)
    ├─ Visual Install Guide (detailed with diagrams)
    └─ FAQ (common questions)

Trader
    │
    ├─ README (features overview)
    ├─ Usage Examples (trading examples)
    └─ Safety Guide (risk management)

Developer
    │
    ├─ Tools Reference (API docs)
    ├─ Architecture (system design)
    └─ Contributing Guide (how to help)
```

**Full documentation index:**
- [README.md](README.md) - Main overview
- [VISUAL_INSTALL_GUIDE.md](VISUAL_INSTALL_GUIDE.md) - Installation with diagrams
- [FAQ.md](FAQ.md) - 80+ questions answered
- [INSTALLATION_COMPARISON.md](INSTALLATION_COMPARISON.md) - Compare methods
- [DEMO_VIDEO_SCRIPT.md](DEMO_VIDEO_SCRIPT.md) - Video tutorial scripts
- [TOOLS_REFERENCE.md](TOOLS_REFERENCE.md) - Complete API documentation

---

## 🎬 Video Tutorials (Coming Soon)

Watch these tutorials for visual walkthroughs:
- Complete Setup (8 min)
- First Trade (5 min)
- Safety Configuration (4 min)

Subscribe for updates: [YouTube Channel](#)

---

## 💡 Pro Tips

**Start Safe:**
- Use Demo Mode first to learn
- Start with small amounts ($10-50)
- Set conservative safety limits
- Understand the market before trading

**Learn Progressively:**
1. Week 1: Demo mode, explore markets
2. Week 2: Small trades ($10-50)
3. Week 3: Increase to $100-500
4. Week 4: Optimize your strategy

**Use Safety Features:**
- Set `REQUIRE_CONFIRMATION_ABOVE_USD=100`
- Keep `MAX_ORDER_SIZE_USD` low initially
- Monitor your `MAX_TOTAL_EXPOSURE_USD`
- Review positions daily

---

## 🤝 Get Help

**Stuck? We're here to help:**

1. **Check FAQ**: [FAQ.md](FAQ.md) has 80+ solutions
2. **Read docs**: Detailed guides for every scenario
3. **GitHub Issues**: Report bugs or ask questions
4. **Community**: Join Discord/Telegram for support
5. **Email**: Contact through GitHub profile

---

## 🌟 What Makes This Great

✨ **5-minute setup** - Fastest in the industry
🎨 **Beautiful GUI** - No terminal needed
🔒 **Security-first** - Your keys stay safe
📖 **Amazing docs** - 2,900+ lines of guides
🤖 **AI-powered** - Claude does the heavy lifting
🛡️ **Safety limits** - Protect your funds
🌍 **Cross-platform** - Works everywhere
📊 **Real-time** - WebSocket price feeds
💼 **Professional** - Enterprise-grade tools
❤️ **Open source** - Free forever

---

## 🎯 Your First Hour Checklist

- [ ] Install with setup wizard
- [ ] Configure safety limits
- [ ] Integrate with Claude Desktop
- [ ] Test market discovery
- [ ] Analyze a trending market
- [ ] (Full mode) Make small test trade ($10)
- [ ] Check portfolio
- [ ] Subscribe to price updates
- [ ] Read FAQ for tips
- [ ] Join community

---

## 🚀 Ready to Start?

```bash
# Let's go!
python setup_wizard.py
```

**Questions?** Check [FAQ.md](FAQ.md) or open an issue.

**Happy trading!** 📈

---

**Made with ❤️ by [Caio Vicentino](https://github.com/caiovicentino)**

*Get started in 5 minutes!* ⚡
