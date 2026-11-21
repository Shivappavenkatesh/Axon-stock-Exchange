from pathlib import Path
from unittest.mock import patch

from axon_aone.services.daily_deepdive import DailyDeepDiveLogger


def test_daily_deepdive_record_and_finalize(tmp_path: Path):
    logger = DailyDeepDiveLogger(report_dir=str(tmp_path))

    metrics = {
        "buy_signals": 3,
        "entry_attempts": 2,
        "entry_filled": 1,
        "entry_rejected": 1,
        "exit_attempts": 1,
        "exit_filled": 1,
        "exit_rejected": 0,
        "kill_switch_triggers": 0,
        "exception_count": 0,
        "skip_reasons": {"risk_engine_block": 2},
        "reject_reasons": {"entry:ERROR": 1},
        "realized_pnl": 420.5,
        "vaulted_profit": 252.3,
        "slippage_alerts": 1,
        "avg_slippage_bps": 32.4,
        "portfolio_heat": 0.04,
    }
    state = {
        "total_capital": 100000,
        "tradable_capital": 95000,
        "daily_pnl": 1200,
        "weekly_pnl": 1800,
        "investment_bucket": 252.3,
        "vault_capital": 252.3,
        "open_trades": [{"symbol": "ABC"}],
    }

    day_json = logger.record_iteration(metrics=metrics, state=state, mode="mock")
    assert day_json.exists()

    with patch("axon_aone.services.daily_deepdive.send_telegram_message") as mock_tg:
        paths = logger.finalize_day(mode="mock")
    assert mock_tg.called
    assert paths["json"].exists()
    assert paths["md"].exists()

    payload = paths["json"].read_text(encoding="utf-8")
    assert "what_went_good" in payload
    assert "what_went_bad" in payload
    assert "risk_engine_block" in payload
    assert "execution_quality" in payload
    assert "vaulted_profit" in payload
