from quant_factor.out_of_time import TEST_START, build_out_of_time_config


def test_out_of_time_config_overrides_dates_and_dirs() -> None:
    config = {
        "data": {
            "start_date": "2018-01-01",
            "end_date": "2023-12-31",
            "raw_dir": "data/raw",
            "processed_dir": "data/processed",
            "provider": "yfinance",
        }
    }

    oot = build_out_of_time_config(config)

    # 评估区间之外(用独立目录、覆盖日期到 2024-2025)，且回看缓冲早于评估起点。
    assert oot["data"]["start_date"] < TEST_START
    assert oot["data"]["end_date"] >= "2025-01-01"
    assert oot["data"]["raw_dir"] != config["data"]["raw_dir"]
    assert oot["data"]["processed_dir"] != config["data"]["processed_dir"]


def test_out_of_time_config_does_not_mutate_original() -> None:
    config = {
        "data": {
            "start_date": "2018-01-01",
            "end_date": "2023-12-31",
            "raw_dir": "data/raw",
            "processed_dir": "data/processed",
        }
    }

    build_out_of_time_config(config)

    # 深拷贝：原 config 不能被改动，否则会污染 2018-2023 的研究流程。
    assert config["data"]["start_date"] == "2018-01-01"
    assert config["data"]["raw_dir"] == "data/raw"
