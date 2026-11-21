# Quick Reference - Axon Commands

## Broker Credentials Setup

```powershell
# Windows PowerShell
$env:ANGEL_ONE_API_KEY = "your_api_key"
$env:ANGEL_ONE_CLIENT_ID = "your_client_id"
$env:ANGEL_ONE_PIN = "your_pin"
$env:ANGEL_ONE_TOTP_SECRET = "your_totp_secret"
```

```bash
# Linux/Mac
export ANGEL_ONE_API_KEY="your_api_key"
export ANGEL_ONE_CLIENT_ID="your_client_id"
export ANGEL_ONE_PIN="your_pin"
export ANGEL_ONE_TOTP_SECRET="your_totp_secret"
```

## Local Testing & Trading

```bash
# Live connectivity smoke test (skips cleanly if env vars are missing)
python test_angel_connection.py

# Run full test suite
python -m pytest

# Mock mode (paper trading)
python run_trader.py

# Live mode with Angel One
python run_trader.py --angel-one

# Background scheduler
python run_trader.py --schedule --angel-one

# Web interface
python run_web.py

# Streamlit analytics dashboard
streamlit run dashboard/app.py
```

Runtime note:
- `run_trader.py` is the CLI wrapper most users should run.
- `src/axon_aone/orchestration/main.py` is the canonical runtime module.
- `src/axon_aone/main.py` remains as a compatibility wrapper for `python -m axon_aone.main`.

## File Locations

- **Main Code**: src/axon_aone/
- **Capital Engine Core**: src/axon_aone/core/
- **Database Models**: src/axon_aone/db.py
- **Configuration**: src/axon_aone/config.py
- **Canonical Runtime**: src/axon_aone/orchestration/main.py
- **Web Server**: src/axon_aone/web_server.py
- **Dashboard**: dashboard/app.py
- **Connection Test**: test_angel_connection.py

## Getting TOTP Secret

1. Open Angel One Trading App
2. Go to Profile > Settings > TOTP
3. Click Enable/Reset TOTP
4. Copy the **secret key** (base32 format like `YOUR_BASE32_TOTP_SECRET`)
