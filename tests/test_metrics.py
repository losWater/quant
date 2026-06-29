import pandas as pd

from quant_factor.metrics import max_drawdown


def test_max_drawdown() -> None:
    nav = pd.Series([1.0, 1.2, 0.9, 1.1])

    assert max_drawdown(nav) == -0.25
