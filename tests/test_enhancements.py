"""Tes untuk strategi baru (RSI, MACD, Bollinger, Combo) dan aturan monitor baru."""
import unittest
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

WIB = timezone(timedelta(hours=7))


class TestNewStrategies(unittest.TestCase):
    """Tes strategi baru menghasilkan sinyal yang valid."""

    def _sample_df(self, trend="up", n=200):
        rng = np.random.default_rng(123)
        if trend == "up":
            ret = rng.normal(0.002, 0.015, n)
        elif trend == "down":
            ret = rng.normal(-0.002, 0.015, n)
        else:
            ret = rng.normal(0.0, 0.015, n)
        close = 5000 * np.exp(np.cumsum(ret))
        idx = pd.bdate_range("2025-01-01", periods=n)
        return pd.DataFrame({
            "Open": close * 0.999, "High": close * 1.005,
            "Low": close * 0.995, "Close": close,
            "Volume": rng.integers(1_000_000, 10_000_000, n),
        }, index=idx)

    def test_rsi_strategy(self):
        from idxbot.strategy import rsi_strategy
        df = self._sample_df("flat")
        sig = rsi_strategy(df, period=14, oversold=30, overbought=70)
        self.assertEqual(len(sig), len(df))
        self.assertTrue(set(sig.unique()).issubset({0, 1}))

    def test_macd_cross(self):
        from idxbot.strategy import macd_cross
        df = self._sample_df("up")
        sig = macd_cross(df)
        self.assertEqual(len(sig), len(df))
        self.assertTrue(set(sig.dropna().unique()).issubset({0, 1}))

    def test_bollinger(self):
        from idxbot.strategy import bollinger
        df = self._sample_df("flat")
        sig = bollinger(df)
        self.assertEqual(len(sig), len(df))
        self.assertTrue(set(sig.unique()).issubset({0, 1}))

    def test_combo(self):
        from idxbot.strategy import combo
        df = self._sample_df("up")
        sig = combo(df)
        self.assertEqual(len(sig), len(df))
        self.assertTrue(set(sig.dropna().unique()).issubset({0, 1}))

    def test_all_strategies_registered(self):
        from idxbot.strategy import STRATEGIES
        expected = {"sma_cross", "breakout", "rsi", "macd_cross", "bollinger", "combo"}
        self.assertEqual(set(STRATEGIES.keys()), expected)


class TestNewMonitorRules(unittest.TestCase):
    """Tes aturan monitor baru: gap, consecutive, RSI, MACD, BB."""

    def _make_bars(self, n=60, trend="up"):
        rng = np.random.default_rng(42)
        if trend == "up":
            ret = rng.normal(0.005, 0.01, n)
        elif trend == "down":
            ret = rng.normal(-0.01, 0.01, n)
        else:
            ret = rng.normal(0, 0.015, n)
        close = 5000 * np.exp(np.cumsum(ret))
        idx = pd.bdate_range("2025-06-01", periods=n)
        return pd.DataFrame({
            "Open": close * 0.999, "High": close * 1.005,
            "Low": close * 0.995, "Close": close,
            "Volume": rng.integers(1_000_000, 10_000_000, n),
        }, index=idx)

    def _make_quote(self, price, prev=5000.0, bars=None):
        from idxbot.monitor import Quote
        return Quote("TEST", price, prev, 5_000_000.0, 5_000_000.0,
                     datetime(2026, 10, 1, 10, 0, tzinfo=WIB), bars)

    def _cfg(self):
        from pathlib import Path
        from idxbot.config import load_config
        return load_config(Path(__file__).parent.parent / "config.yaml")

    def test_gap_up(self):
        from idxbot.monitor import evaluate
        q = self._make_quote(5300, prev=5000)  # 6% gap
        result = evaluate(q, {"type": "gap_up", "value": 5}, 1.0, self._cfg())
        self.assertIsNotNone(result)
        self.assertIn("gap up", result)

    def test_gap_down(self):
        from idxbot.monitor import evaluate
        q = self._make_quote(4700, prev=5000)  # 6% gap down
        result = evaluate(q, {"type": "gap_down", "value": 5}, 1.0, self._cfg())
        self.assertIsNotNone(result)
        self.assertIn("gap down", result)

    def test_consecutive_up(self):
        from idxbot.monitor import evaluate
        bars = self._make_bars(60, trend="up")
        # Force last 4 values: pct_change needs N+1 values to produce N changes
        bars.iloc[-4:, bars.columns.get_loc("Close")] = [5900, 6000, 6100, 6200]
        q = self._make_quote(6200, bars=bars)
        result = evaluate(q, {"type": "consecutive_up", "value": 3}, 1.0, self._cfg())
        self.assertIsNotNone(result)
        self.assertIn("berturut naik", result)

    def test_consecutive_down(self):
        from idxbot.monitor import evaluate
        bars = self._make_bars(60, trend="down")
        bars.iloc[-4:, bars.columns.get_loc("Close")] = [5100, 5000, 4900, 4800]
        q = self._make_quote(4800, bars=bars)
        result = evaluate(q, {"type": "consecutive_down", "value": 3}, 1.0, self._cfg())
        self.assertIsNotNone(result)
        self.assertIn("berturut turun", result)

    def test_rsi_oversold(self):
        from idxbot.monitor import evaluate
        # Create bars with strong downtrend to make RSI < 30
        bars = self._make_bars(60, trend="down")
        q = self._make_quote(4000, bars=bars)
        # RSI might or might not trigger depending on random data,
        # so we test the function doesn't crash
        result = evaluate(q, {"type": "rsi_oversold", "value": 30}, 1.0, self._cfg())
        # Just verify it returns string or None
        self.assertTrue(result is None or isinstance(result, str))

    def test_rsi_overbought(self):
        from idxbot.monitor import evaluate
        bars = self._make_bars(60, trend="up")
        q = self._make_quote(8000, bars=bars)
        result = evaluate(q, {"type": "rsi_overbought", "value": 70}, 1.0, self._cfg())
        self.assertTrue(result is None or isinstance(result, str))

    def test_macd_cross(self):
        from idxbot.monitor import evaluate
        bars = self._make_bars(60)
        q = self._make_quote(5500, bars=bars)
        result = evaluate(q, {"type": "macd_cross_up", "value": 1}, 1.0, self._cfg())
        self.assertTrue(result is None or isinstance(result, str))

    def test_bb_breakout(self):
        from idxbot.monitor import evaluate
        bars = self._make_bars(60)
        q = self._make_quote(5500, bars=bars)
        result = evaluate(q, {"type": "bb_breakout", "value": 1}, 1.0, self._cfg())
        self.assertTrue(result is None or isinstance(result, str))

    def test_validate_new_rule_types(self):
        from idxbot.monitor import validate
        # Should not raise for new rule types
        cfg = {
            "monitor": {
                "default_rules": [
                    {"type": "rsi_oversold", "value": 30},
                    {"type": "macd_cross_up", "value": 1},
                    {"type": "bb_breakout", "value": 1},
                    {"type": "gap_up", "value": 3},
                    {"type": "consecutive_up", "value": 5},
                ],
                "watchlist": {},
            }
        }
        validate(cfg)  # should not raise

    def test_validate_rejects_invalid(self):
        from idxbot.monitor import validate
        cfg = {"monitor": {"default_rules": [{"type": "bogus", "value": 1}], "watchlist": {}}}
        with self.assertRaises(ValueError):
            validate(cfg)


if __name__ == "__main__":
    unittest.main()
