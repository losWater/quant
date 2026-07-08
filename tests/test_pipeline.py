from quant_factor.pipeline import PIPELINE_STEPS, run_pipeline


def test_run_pipeline_executes_steps_in_order(monkeypatch) -> None:
    calls = []

    def fake_data(*args, **kwargs):
        calls.append(("data", kwargs))
        return "data"

    def fake_factors(config):
        calls.append(("factors", {}))
        return "factors"

    def fake_evaluation(config):
        calls.append(("evaluation", {}))
        return "evaluation"

    def fake_diagnostics(config):
        calls.append(("diagnostics", {}))
        return "diagnostics"

    def fake_backtest(config):
        calls.append(("backtest", {}))
        return "backtest"

    def fake_metrics(config):
        calls.append(("metrics", {}))
        return "metrics"

    def fake_exposure(config):
        calls.append(("exposure", {}))
        return "exposure"

    def fake_robustness(config):
        calls.append(("robustness", {}))
        return "robustness"

    def fake_neutralization(config):
        calls.append(("neutralization", {}))
        return "neutralization"

    def fake_rolling_neutral(config):
        calls.append(("rolling_neutral", {}))
        return "rolling_neutral"

    def fake_multi_factor(config):
        calls.append(("multi_factor", {}))
        return "multi_factor"

    monkeypatch.setattr("quant_factor.pipeline.build_price_dataset", fake_data)
    monkeypatch.setattr("quant_factor.pipeline.build_factor_dataset", fake_factors)
    monkeypatch.setattr("quant_factor.pipeline.evaluate_factors", fake_evaluation)
    monkeypatch.setattr("quant_factor.pipeline.build_diagnostics_report", fake_diagnostics)
    monkeypatch.setattr("quant_factor.pipeline.run_backtest", fake_backtest)
    monkeypatch.setattr("quant_factor.pipeline.build_performance_report", fake_metrics)
    monkeypatch.setattr("quant_factor.pipeline.build_exposure_report", fake_exposure)
    monkeypatch.setattr("quant_factor.pipeline.build_robustness_report", fake_robustness)
    monkeypatch.setattr("quant_factor.pipeline.build_neutralization_report", fake_neutralization)
    monkeypatch.setattr(
        "quant_factor.pipeline.build_rolling_neutral_comparison", fake_rolling_neutral
    )
    monkeypatch.setattr("quant_factor.pipeline.build_multi_factor_report", fake_multi_factor)

    outputs = run_pipeline(
        {"data": {}},
        symbols=["000001"],
        limit=1,
        refresh=True,
    )

    assert list(outputs) == PIPELINE_STEPS
    assert [name for name, _ in calls] == PIPELINE_STEPS
    assert calls[0][1]["symbols"] == ["000001"]
    assert calls[0][1]["limit"] == 1
    assert calls[0][1]["refresh"] is True


def test_run_pipeline_can_run_subset(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(
        "quant_factor.pipeline.build_factor_dataset",
        lambda config: calls.append("factors") or "factors",
    )
    monkeypatch.setattr(
        "quant_factor.pipeline.run_backtest",
        lambda config: calls.append("backtest") or "backtest",
    )

    outputs = run_pipeline({"data": {}}, steps=["factors", "backtest"])

    assert calls == ["factors", "backtest"]
    assert list(outputs) == ["factors", "backtest"]
