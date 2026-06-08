"""Forward-return helpers with executable N+1 signal timing."""


def add_n_plus_one_returns(df, horizons):
    """Add horizon returns using open[t+1] entry and close[t+h] exit.

    The input must be ordered by ``ts_code`` and ``trade_date``. A horizon of
    one represents buying at the next session's open and marking the position
    at that same session's close.
    """
    grouped = df.groupby("ts_code", sort=False)
    entry_open = grouped["open"].shift(-1)
    ret_cols = []
    for horizon in horizons:
        future_close = grouped["close"].shift(-horizon)
        column = f"ret_{horizon}d"
        df[column] = (future_close - entry_open) / entry_open
        ret_cols.append(column)
    return ret_cols
