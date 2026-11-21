import pytest

from research.dd.master_dd_scorecard import evaluate_dd, template_payload


def _all_pass_payload():
    payload = template_payload()
    payload["checks"] = {str(i): "pass" for i in range(1, 26)}
    payload["risks"] = ["debt risk", "regulatory risk", "customer concentration"]
    payload["upside_multiple"] = 12
    return payload


def test_layer_one_failure_blocks_immediately():
    payload = _all_pass_payload()
    payload["checks"]["1"] = "fail"

    result = evaluate_dd("stock", payload)

    assert result["decision"] == "reject"
    assert result["blocked_layer"] == 1
    assert result["auto_fail"] is True
    assert result["position_sizing"]["recommended_position_pct"] == 0.0


def test_missing_risks_triggers_hard_fail():
    payload = _all_pass_payload()
    payload["risks"] = ["single risk only"]

    result = evaluate_dd("etf", payload)

    assert result["decision"] == "reject"
    assert result["auto_fail"] is True
    assert any("Fewer than 3 explicit risks" in reason for reason in result["auto_fail_reasons"])


def test_full_pass_is_investable_with_positive_size():
    payload = _all_pass_payload()

    result = evaluate_dd("bitcoin", payload)

    assert result["decision"] == "investable"
    assert result["blocked_layer"] is None
    assert result["auto_fail"] is False
    assert result["weighted_score"] == 100.0
    assert result["position_sizing"]["recommended_position_pct"] > 0.0


def test_template_payload_has_all_25_checks():
    payload = template_payload()
    assert len(payload["checks"]) == 25
    assert all(str(i) in payload["checks"] for i in range(1, 26))


def test_invalid_asset_raises_value_error():
    payload = _all_pass_payload()
    with pytest.raises(ValueError):
        evaluate_dd("gold", payload)


def test_layer_two_missing_blocks_at_layer_two():
    payload = _all_pass_payload()
    payload["checks"]["4"] = "missing"

    result = evaluate_dd("stock", payload)

    assert result["decision"] == "reject"
    assert result["blocked_layer"] == 2
    layer_two = next(item for item in result["layer_results"] if item["layer"] == 2)
    assert layer_two["status"] == "incomplete"


def test_invalid_check_status_is_treated_as_missing():
    payload = _all_pass_payload()
    payload["checks"]["6"] = "unknown-status"

    result = evaluate_dd("etf", payload)

    assert result["decision"] == "reject"
    assert result["blocked_layer"] == 3
    layer_three = next(item for item in result["layer_results"] if item["layer"] == 3)
    assert "Check 6 missing" in layer_three["issues"]


def test_invalid_upside_multiple_triggers_hard_fail():
    payload = _all_pass_payload()
    payload["upside_multiple"] = "not-a-number"

    result = evaluate_dd("stock", payload)

    assert result["decision"] == "reject"
    assert result["auto_fail"] is True
    assert any("Invalid upside_multiple" in reason for reason in result["auto_fail_reasons"])


def test_low_asymmetry_triggers_hard_fail_even_if_checks_pass():
    payload = _all_pass_payload()
    payload["upside_multiple"] = 4

    result = evaluate_dd("stock", payload)

    assert result["decision"] == "reject"
    assert result["auto_fail"] is True
    assert any("Asymmetry upside < 10x" in reason for reason in result["auto_fail_reasons"])


def test_etf_recommended_size_is_higher_than_stock_for_same_quality_case():
    payload = _all_pass_payload()

    stock = evaluate_dd("stock", payload)
    etf = evaluate_dd("etf", payload)

    assert etf["position_sizing"]["recommended_position_pct"] > stock["position_sizing"]["recommended_position_pct"]


def test_bitcoin_recommended_size_is_lower_than_stock_for_same_quality_case():
    payload = _all_pass_payload()

    stock = evaluate_dd("stock", payload)
    btc = evaluate_dd("bitcoin", payload)

    assert btc["position_sizing"]["recommended_position_pct"] < stock["position_sizing"]["recommended_position_pct"]
