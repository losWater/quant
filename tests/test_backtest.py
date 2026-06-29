from quant_factor.backtest import transaction_cost


def test_transaction_cost_includes_commission_tax_and_slippage() -> None:
    cost = transaction_cost(
        turnover=1.0,
        buy_commission_rate=0.0003,
        sell_commission_rate=0.0003,
        stamp_tax_rate=0.001,
        slippage_rate=0.001,
    )

    assert cost == 0.0026
