# Axon Trading Web Interface - Quick Start Guide

## 5-Minute Setup

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Configure Database (optional but recommended)

By default the app can run with a simple SQLite database, but for production use you should point it to PostgreSQL:

```bash
export AXON_DATABASE_URL="postgresql+psycopg2://user:pass@localhost:5432/axon"
```

### Step 3: Start the Server

**Windows (PowerShell):**
```powershell
.\start-web.ps1
```

**Linux/Mac:**
```bash
chmod +x start-web.sh
./start-web.sh
```

**Direct Python:**
```bash
python run_web.py
```

### Step 4: Open Browser
Navigate to: **http://localhost:5000**

### Step 5: Log In

The web dashboard is protected by a simple login backed by environment variables:

- `WEB_USERNAME` – required web login username
- `WEB_PASSWORD` – required web login password

Set these before starting the web server (for example, in the same shell):

```bash
export WEB_USERNAME="admin"
export WEB_PASSWORD="changeme"
```

If `WEB_USERNAME` and `WEB_PASSWORD` are not set, login will always fail and the UI will show an error message.

---

## ✨ First Trade in 30 Seconds

1. **Enter Symbol**: Type `RELIANCE` (or any stock symbol)
2. **Set Quantity**: Enter `1`
3. **Choose Side**: Select `BUY`
4. **Choose Mode**: Select `Mock` (paper trading)
5. **Click**: "Place Trade"
6. **Done**: Watch your order appear in real-time!

Note: the web terminal accepts manual quantities, but the scheduler-driven algo no longer trades a hardcoded 1 share. Scheduled entries are now risk-sized automatically.

---

## 📈 Analytics Dashboard

Start the Streamlit dashboard (equity curve, PnL, regime history, allocation, correlations):

```bash
streamlit run dashboard/app.py
```

Then open the URL shown in the terminal (typically http://localhost:8501).

## 🎯 Common Tasks

### Monitor Your Orders
1. Click **"Orders"** tab
2. See all your trades
3. Click any order to view details
4. Cancel pending orders if needed

### View Open Positions
1. Click **"Positions"** tab
2. See what you're currently holding
3. View profit/loss for each position

### Check Portfolio
1. Click **"Portfolio"** tab
2. See total capital and daily P&L
3. Monitor available cash

### Live Trading (For Advanced Users)
1. Set environment variables:
   ```bash
   export ANGEL_ONE_API_KEY="your_api_key"
   export ANGEL_ONE_CLIENT_ID="your_client_id"
   export ANGEL_ONE_PIN="your_pin"
   export ANGEL_ONE_TOTP_SECRET="your_totp_secret"
   ```
2. Click Trade Mode: **"Live"**
3. Place trades (real capital will be used!)

---

## 🔧 Troubleshooting

**"Port 5000 already in use"**
```bash
# Use a different port
python run_web.py --port 8080
```

**"Module not found" error**
```bash
# Make sure you installed requirements
pip install -r requirements.txt
```

**WebSocket connection failed**
1. Check firewall settings
2. Try localhost instead of IP address
3. Clear browser cache (Ctrl+Shift+Delete)

**Orders not appearing**
1. Press F5 to refresh browser
2. Open browser console (F12)
3. Check for error messages

---

## 📊 Interface Overview

### Trading Terminal (Tab 1)
- **Place orders** with BUY/SELL
- Choose **MARKET or LIMIT** orders
- Select **Mock or Live** mode
- View **Quick Stats** below

### Orders (Tab 2)
- **Filter** by symbol or status
- **View details** by clicking rows
- **Cancel orders** before execution
- See complete **execution history**

### Positions (Tab 3)
- **Current holdings** and quantities
- **Entry prices** and current prices
- **Real-time P&L** tracking
- **Percentage returns** for each position

### Portfolio (Tab 4)
- **Total capital** invested
- **Current portfolio value**
- **Available cash**
- **Daily profit/loss**

---

## ⚡ Real-time Features

✅ **WebSocket Updates**
- Orders update instantly
- Positions refresh in real-time
- No need to refresh the page

✅ **Market Status**
- Live market open/closed indicator
- Current market hours display
- Next market opening time

✅ **Auto-Sync**
- Multiple browsers stay in sync
- Real-time data across all connected clients
- Instant status updates

---

## 📋 Trade Modes Explained

### 🟣 Mock Mode (Paper Trading)
- **No real capital used**
- Perfect for learning
- Test strategies risk-free
- See realtime P&L updates

### 🟠 Live Mode (Real Trading)
- **Real capital deployed**
- Requires Angel One credentials
- Actual market execution
- Real P&L impact

---

## 🔐 Security Tips

1. **Paper Trade First**: Always test with Mock mode
2. **Limit Access**: Use `--host 127.0.0.1` for local-only access
3. **Keep Keys Safe**: Never commit API keys to git
4. **Use HTTPS**: Deploy with SSL in production
5. **Validate Inputs**: Always double-check quantities

---

## 🚀 Advanced Usage

### Custom Port
```bash
python run_web.py --port 8080
```

### Debug Mode
```bash
python run_web.py --debug
```

### Listen on All Interfaces
```bash
python run_web.py --host 0.0.0.0 --port 5000
```

### Enable Logging
```bash
python run_web.py --debug 2>&1 | tee server.log
```

---

## 📱 Mobile Access

Works great on mobile too!

1. Find your machine IP: `ipconfig` (Windows) or `ifconfig` (Linux)
2. From phone browser: `http://<your-ip>:5000`
3. Same features, responsive design
4. Touch-friendly interface

---

## 🐛 Common Errors

| Error | Solution |
|-------|----------|
| `Connection refused` | Server not running or wrong port |
| `Module not found` | Run `pip install -r requirements.txt` |
| `WebSocket error` | Check firewall, try localhost |
| `Order not showing` | Refresh page (F5) or restart server |

---

## ✅ Checklist

- [ ] Python 3.8+ installed
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Server running (`python run_web.py`)
- [ ] Browser open to http://localhost:5000
- [ ] First trade placed successfully
- [ ] Order appeared in real-time
- [ ] Position tracking working
- [ ] Portfolio showing correct balance

---

## 📞 Need Help?

1. Check **WEB_INTERFACE_README.md** for detailed docs
2. Review logs in terminal
3. Check browser console (F12)
4. Try restarting the server
5. Reinstall dependencies: `pip install -r requirements.txt --force-reinstall`

---

## 🎓 Next Steps

1. ✅ Place test trades in Mock mode
2. ✅ Monitor positions and orders
3. ✅ Set up live trading (optional)
4. ✅ Monitor your portfolio growth
5. ✅ Run scheduler for automated trading

---

## 🌟 Pro Tips

- **Start Small**: Use Mock mode first to validate fills, targets, and exits before deploying live capital
- **Use Filters**: Filter orders by symbol or date
- **Monitor P&L**: Check portfolio regularly
- **Cancel Early**: Cancel orders if market moves unexpectedly
- **Keep Notes**: Document your trades for analysis

### Scheduler Notes

- The scheduler now scans a broader liquid-symbol universe instead of trading only a fixed short watchlist.
- Candidate symbols are ranked using momentum, VWAP edge, trend persistence, volume expansion, ATR-normalized volatility, and realized trade feedback.
- Live scheduler trades use ATR-based stops and a fixed `+2%` profit target by default.
- Position size is computed from risk budget and available tradable capital, not from a fixed share count.

---

**Happy Trading! 📈**

For more information, see: [WEB_INTERFACE_README.md](WEB_INTERFACE_README.md)
