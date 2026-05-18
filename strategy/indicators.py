"""Vectorized technical indicators. All functions take a pandas Series and return one."""


def ma(close, window):
    """Simple moving average. Returns NaN until `window` observations are available."""
    return close.rolling(window=window, min_periods=window).mean()


def golden_cross(short_ma, long_ma):
    """Boolean Series: True where short_ma crosses ABOVE long_ma at that bar
    (today's short > today's long AND yesterday's short <= yesterday's long).
    """
    return (short_ma > long_ma) & (short_ma.shift(1) <= long_ma.shift(1))


def death_cross(short_ma, long_ma):
    """Boolean Series: True where short_ma crosses BELOW long_ma at that bar."""
    return (short_ma < long_ma) & (short_ma.shift(1) >= long_ma.shift(1))
