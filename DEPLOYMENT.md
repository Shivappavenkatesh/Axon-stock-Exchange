**Deployment Requirements & Setup**

- **Purpose**: steps and environment settings to reproduce and run this repository (Axon Aone) in a fresh environment, including dependencies, credentials, runtime commands, and operational notes.

**System Requirements**
- **OS**: Linux, macOS or Windows (Windows tested in development environment).
- **Python**: 3.11+ recommended (code used Python 3.14 in workspace); use the system installer or pyenv/uv.
- **Disk**: SQLite file(s) created under project `src/axon_aone/services` by default.

**Repository files to be aware of**
- `src/axon_aone/config.py` — main constants and defaults.
- `src/axon_aone/backtester.py` — deterministic backtester implementation.
- `src/axon_aone/features/trade.py` — trading logic and vaulting.
- `src/axon_aone/services/state_store.py` — SQLite persistence for state and trade log.
- `src/axon_aone/web_server.py` — Flask app, metrics and vault endpoints.
- `test_angel_connection.py` — connection tests (auto-skip when deps/creds missing).

See the code for full list; key modules live under `src/axon_aone/`.

**Python dependencies**
Use the exact requirements in `requirements.txt` (installed into a virtualenv). The file contents are:

```
<contents of requirements.txt>
```

To install in a fresh environment:

```bash
python -m venv .venv
source .venv/bin/activate    # macOS / Linux
.\.venv\Scripts\activate   # Windows PowerShell
pip install --upgrade pip
pip install -r requirements.txt
```

Notes:
- `smartapi-python` (SmartApi) is required for live Angel One broker integration. If you do not plan to run live broker tests, tests will auto-skip.
- `python-telegram-bot` is used for Telegram notifications; a local stub `src/telegram.py` is included for offline test runs.

**Environment variables / Secrets**
The following environment variables are referenced across the codebase. Provide them as appropriate in your environment (e.g., CI secrets, .env file, or process manager):

- `ANGEL_ONE_API_KEY` — Angel One API key
- `ANGEL_ONE_CLIENT_ID` — Angel One client/user id
- `ANGEL_ONE_PIN` — password/PIN for Angel One
- `ANGEL_ONE_TOTP_SECRET` — TOTP secret for 2FA
- `ANGEL_ONE_TEST_SYMBOL`, `ANGEL_ONE_TEST_TOKEN`, `ANGEL_ONE_TEST_QTY` — optional test order values
- `ANGEL_ONE_ENABLE_ORDER_TEST` — set to `1` to allow real test orders (otherwise tests skip/dr run)
- `TELEGRAM_BOT_TOKEN` — token for Telegram bot notifications
- `TELEGRAM_CHAT_ID` — chat id for Telegram notifications

Recommendation: Use a secrets manager (GitHub Secrets, Azure Key Vault, AWS Secrets Manager) for production deployments.

**Database / Persistence**
- The project uses a lightweight SQLite file for state persistence by default (`src/axon_aone/services/state_store.py`). No additional DB server is required for local runs.
- Backups: copy the SQLite file periodically if you need durable historical logs.

**Running tests**

Run all tests locally (virtualenv active):

```bash
pytest -q
```

Tests that require live Angel One credentials or the `smartapi-python` package will auto-skip when dependencies/credentials are absent.

**Running the app & components**

- Web server (development):

```bash
export FLASK_APP=src/axon_aone/web_server.py
flask run --host=0.0.0.0 --port=5000
# or use the run_web.py wrapper in repository root
python run_web.py
```

- Trader / scheduled runner:

```bash
python run_trader.py       # starts scheduler + trading loops (honors config)
```

- Backtester (deterministic replay):

```bash
python scripts/run_backtest.py --symbols SYMBOLS.csv --from YYYY-MM-DD --to YYYY-MM-DD
```

**Prometheus metrics**
- The execution module exposes Prometheus metrics via `prometheus_client` instrumentation; the web server adds `/metrics` endpoint. Configure Prometheus to scrape `http://<host>:5000/metrics`.

**Docker / Kubernetes**
- Dockerfile and `docker-compose.yml` exist for containerized runs. For K8s, see `k8s/` manifests (namespace, secrets, configmap, deployment, service, hpa, pdb).
- When deploying to containers, mount a persistent volume for the SQLite file or replace with an external DB if you need high-availability.

**CI / Automation suggestions**
- In CI (GitHub Actions): create jobs to lint, run `pytest`, build image, and optionally run lightweight smoke tests with mocks.
- Add a job to build and push the Docker image to your registry after tests pass.

**Operational notes & kill switch**
- The system is designed for an individual trader (not a broker). Use `TELEGRAM_*` notifications and the dashboard endpoints to monitor activity.
- Implement an external process monitor (systemd, container restart policy) and use environment variables to enable/disable live trading (`TRADE_MODE` or config toggles in `src/axon_aone/config.py`).

**Key files changed/added in this branch**
- [requirements.txt](requirements.txt)
- [test_angel_connection.py](test_angel_connection.py)
- [src/axon_aone/backtester.py](src/axon_aone/backtester.py)
- [src/axon_aone/features/trade.py](src/axon_aone/features/trade.py)
- [src/axon_aone/services/state_store.py](src/axon_aone/services/state_store.py)
- [src/axon_aone/services/telegram_notify.py](src/axon_aone/services/telegram_notify.py)
- [src/axon_aone/services/vault_manager.py](src/axon_aone/services/vault_manager.py)
- [src/axon_aone/services/monitor.py](src/axon_aone/services/monitor.py)
- [src/axon_aone/web_server.py](src/axon_aone/web_server.py)
- [src/telegram.py](src/telegram.py) (local stub for offline tests)

---

If you want, I can also:
- produce a Docker-compose override for a production-like environment (Prometheus + Grafana + the app), or
- add a `Makefile`/`scripts/bootstrap.sh` to automate venv creation and installs.

Created by automation on March 2, 2026.
