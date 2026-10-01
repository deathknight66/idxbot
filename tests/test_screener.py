"""Tes untuk modul screener dan sources. Tidak membutuhkan koneksi internet."""
import unittest
from unittest import mock
from pathlib import Path

import numpy as np
import pandas as pd


class TestIDXAPIClient(unittest.TestCase):
    """Tes IDXClient dengan respons tiruan."""

    def _mock_goapi_response(self, data):
        resp = mock.Mock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"status": "success", "data": data}
        return resp

    def test_company_profile(self):
        from idxbot.sources.idx_api import IDXClient
        data = {
            "name": "Bank Central Asia Tbk",
            "listing_date": "2000-05-31",
            "sector": "Financials",
            "sub_sector": "Banks",
            "board": "utama",
            "shares_outstanding": 24408459900,
            "market_cap": 1200000000000000,
            "last_price": 9500,
        }
        with mock.patch("idxbot.sources.idx_api.requests.get",
                         return_value=self._mock_goapi_response(data)):
            client = IDXClient(api_key="test-key", delay=0)
            profile = client.company_profile("BBCA")
        self.assertEqual(profile.symbol, "BBCA")
        self.assertEqual(profile.name, "Bank Central Asia Tbk")
        self.assertEqual(profile.sector, "Financials")
        self.assertEqual(profile.last_price, 9500)

    def test_stock_prices(self):
        from idxbot.sources.idx_api import IDXClient
        data = [
            {"symbol": "BBCA", "open": 9400, "high": 9550, "low": 9350,
             "close": 9500, "volume": 15000000, "previous": 9400, "percent": 1.06,
             "date": "2026-10-01"},
        ]
        with mock.patch("idxbot.sources.idx_api.requests.get",
                         return_value=self._mock_goapi_response(data)):
            client = IDXClient(api_key="test-key", delay=0)
            prices = client.stock_prices(["BBCA"])
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0].symbol, "BBCA")
        self.assertEqual(prices[0].close, 9500)
        self.assertEqual(prices[0].volume, 15000000)

    def test_no_api_key_fallback(self):
        from idxbot.sources.idx_api import IDXClient
        client = IDXClient(api_key="", delay=0)
        self.assertEqual(client.api_key, "")

    def test_top_gainers(self):
        from idxbot.sources.idx_api import IDXClient
        data = [{"symbol": "ADRO", "percent": 5.2}]
        with mock.patch("idxbot.sources.idx_api.requests.get",
                         return_value=self._mock_goapi_response(data)):
            client = IDXClient(api_key="test-key", delay=0)
            result = client.top_gainers()
        self.assertEqual(len(result), 1)


class TestTradingViewScreener(unittest.TestCase):
    """Tes TVScreener tanpa koneksi ke TradingView."""

    def _mock_analysis(self, recommendation="BUY", rsi=45.0, macd=10.0):
        a = mock.Mock()
        a.summary = {"RECOMMENDATION": recommendation, "BUY": 12, "SELL": 5, "NEUTRAL": 9}
        a.indicators = {
            "RSI": rsi, "MACD.macd": macd, "MACD.signal": macd - 2,
            "EMA20": 9300, "SMA50": 9100, "SMA200": 8500,
            "BB.upper": 9700, "BB.lower": 8900,
            "ADX": 28.5, "ATR": 150, "Stoch.K": 55.0, "Stoch.D": 50.0,
            "close": 9450, "volume": 12000000,
        }
        a.oscillators = {}
        a.moving_averages = {}
        return a

    @mock.patch("idxbot.sources.tradingview.HAS_TV", True)
    def test_get_analysis(self):
        from idxbot.sources.tradingview import TVScreener
        with mock.patch("idxbot.sources.tradingview.TA_Handler") as MockHandler:
            MockHandler.return_value.get_analysis.return_value = self._mock_analysis()
            tv = TVScreener(exchange="IDX", delay=0)
            result = tv.get_analysis("BBCA")
        self.assertEqual(result.symbol, "BBCA")
        self.assertEqual(result.recommendation, "BUY")
        self.assertAlmostEqual(result.rsi, 45.0)
        self.assertEqual(result.close, 9450)

    @mock.patch("idxbot.sources.tradingview.HAS_TV", True)
    def test_screen_by_recommendation(self):
        from idxbot.sources.tradingview import TVScreener
        mock_analyses = [
            self._mock_analysis("BUY"),
            self._mock_analysis("SELL"),
            self._mock_analysis("STRONG_BUY"),
        ]
        with mock.patch("idxbot.sources.tradingview.TA_Handler") as MockHandler:
            MockHandler.return_value.get_analysis.side_effect = mock_analyses
            tv = TVScreener(exchange="IDX", delay=0)
            buys = tv.screen_by_recommendation(["A", "B", "C"], "BUY")
        self.assertEqual(len(buys), 2)  # BUY + STRONG_BUY

    @mock.patch("idxbot.sources.tradingview.HAS_TV", True)
    def test_top_by_rsi(self):
        from idxbot.sources.tradingview import TVScreener
        analyses = [
            self._mock_analysis("SELL", rsi=25.0),
            self._mock_analysis("NEUTRAL", rsi=50.0),
            self._mock_analysis("BUY", rsi=75.0),
        ]
        with mock.patch("idxbot.sources.tradingview.TA_Handler") as MockHandler:
            MockHandler.return_value.get_analysis.side_effect = analyses
            tv = TVScreener(exchange="IDX", delay=0)
            rsi = tv.top_by_rsi(["A", "B", "C"])
        self.assertEqual(len(rsi["oversold"]), 1)
        self.assertEqual(len(rsi["overbought"]), 1)
        self.assertEqual(len(rsi["neutral"]), 1)


class TestScreener(unittest.TestCase):
    """Tes Screener gabungan."""

    def _sample_data(self):
        idx_dates = pd.bdate_range("2025-01-01", periods=100)
        rng = np.random.default_rng(42)
        close = 9000 + np.cumsum(rng.normal(0, 50, 100))
        return {
            "BBCA": pd.DataFrame({
                "Open": close * 0.99, "High": close * 1.01,
                "Low": close * 0.98, "Close": close,
                "Volume": rng.integers(5_000_000, 20_000_000, 100),
            }, index=idx_dates)
        }

    def _sample_cfg(self):
        from idxbot.config import load_config
        return load_config(Path(__file__).parent.parent / "config.yaml")

    def test_internal_signals(self):
        from idxbot.screener import Screener
        data = self._sample_data()
        cfg = self._sample_cfg()
        sc = Screener(cfg, data)
        signals = sc.internal_signals(data)
        self.assertIn("BBCA", signals)
        self.assertIn(signals["BBCA"]["signal"], (0, 1))

    def test_format_report(self):
        from idxbot.screener import Screener
        data = self._sample_data()
        cfg = self._sample_cfg()
        sc = Screener(cfg, data)
        # Without TV/IDX (they won't be available in test)
        report = sc.format_report(data)
        self.assertIn("SCREENER IDX", report)
        self.assertIn("BBCA", report)

    def test_score_calculation(self):
        from idxbot.screener import _calc_score, StockOpportunity
        opp = StockOpportunity(
            symbol="TEST", close=9000,
            tv_recommendation="BUY", rsi=25.0,
            internal_signal=1, signal_changed=True,
            adx=30.0, macd=5.0,
        )
        score = _calc_score(opp)
        self.assertGreater(score, 0)  # should be positive (all bullish signals)

        opp_bearish = StockOpportunity(
            symbol="TEST", close=9000,
            tv_recommendation="STRONG_SELL", rsi=80.0,
            internal_signal=0,
        )
        score_b = _calc_score(opp_bearish)
        self.assertLess(score_b, score)  # bearish should score lower


if __name__ == "__main__":
    unittest.main()
