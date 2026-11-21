import csv
import os
import sys
import requests

# Add src to path to import config
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from axon_aone.config import TRACKED_SYMBOLS

# Angel One / SmartAPI scrip master JSON URL
SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
# Path to config.py
CONFIG_PATH = os.path.join(ROOT_DIR, 'src/axon_aone/config.py')


def fetch_scrip_master(url: str):
    """Fetch Angel One scrip master JSON from the given URL."""
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _extract_rows(data):
    """Extract a list of instrument rows from the scrip master JSON.

    Handles both list and {..: [list]} top-level structures.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def parse_tokens(master_json, symbols, preferred_exchange: str = "NSE"):
    """Parse scrip master and build symbol -> token map for a given exchange.

    Angel One's scrip master contains rows for multiple segments (NSE, BSE, NFO, etc.)
    with the same symbol. We only want the token for the cash NSE segment because
    the trading code calls getLtpData with exchange="NSE".
    """

    rows = _extract_rows(master_json)
    token_map = {}
    symbols_set = set(symbols)
    preferred_exchange = (preferred_exchange or "").upper()

    for row in rows:
        if not isinstance(row, dict):
            continue

        # Try common Angel One field names
        symbol = (
            row.get("symbol")
            or row.get("tradingsymbol")
            or row.get("symbolname")
        )
        if not symbol or symbol not in symbols_set:
            continue

        exch = (
            row.get("exch_seg")
            or row.get("exchange")
            or row.get("segment")
        )
        if preferred_exchange and exch and exch.upper() != preferred_exchange:
            # Skip non-NSE rows (e.g. BSE/NFO) so tokens match exchange="NSE"
            continue

        token = (
            row.get("token")
            or row.get("symboltoken")
            or row.get("exchange_token")
        )
        if not token:
            continue

        # If multiple rows match, the first NSE one wins; that's fine.
        if symbol not in token_map:
            token_map[symbol] = str(token)

    return token_map

def update_config_py(config_path, token_map):
    with open(config_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    in_map = False
    for line in lines:
        if not in_map and line.strip().startswith('EXCHANGE_TOKEN_MAP = {'):
            in_map = True
            new_lines.append('EXCHANGE_TOKEN_MAP = {\n')
            for sym in TRACKED_SYMBOLS:
                tok = token_map.get(sym, '""')
                new_lines.append(f'    "{sym}": "{tok}",\n')
            new_lines.append('}\n')
            continue
        if in_map:
            if line.strip().endswith('}'):  # End of old map
                in_map = False
            continue  # Skip old map lines
        new_lines.append(line)

    with open(config_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

if __name__ == "__main__":
    print("Fetching Angel One scrip master JSON...")
    master_json = fetch_scrip_master(SCRIP_MASTER_URL)
    print("Parsing tokens...")
    token_map = parse_tokens(master_json, TRACKED_SYMBOLS)
    print("Updating config.py...")
    update_config_py(CONFIG_PATH, token_map)
    print("EXCHANGE_TOKEN_MAP updated:")
    for k, v in token_map.items():
        print(f"  {k}: {v}")
