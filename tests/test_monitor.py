import tempfile, unittest
from datetime import datetime
from pathlib import Path
from idxbot.config import load_config
from idxbot import monitor as m

CFG = load_config(Path(__file__).parent.parent / "config.yaml")
def wib(y, mo, d, h, mi): return datetime(y, mo, d, h, mi, tzinfo=m.WIB)

def q(price, prev=1000.0, vol=0.0, avg=1000.0, ts=None):
    return m.Quote("TEST", price, prev, vol, avg, ts or wib(2026, 10, 1, 10, 0), None)


class T(unittest.TestCase):
    def test_sessions(self):
        self.assertTrue(m.in_session(wib(2026, 10, 1, 10, 0), CFG))      # Kamis
        self.assertFalse(m.in_session(wib(2026, 10, 1, 12, 30), CFG))    # jeda siang
        self.assertFalse(m.in_session(wib(2026, 10, 3, 10, 0), CFG))     # Sabtu
        self.assertTrue(m.after_close(wib(2026, 10, 1, 16, 5), CFG))
        self.assertFalse(m.after_close(wib(2026, 10, 3, 16, 5), CFG))

    def test_fraction(self):
        self.assertAlmostEqual(m.session_fraction(wib(2026, 10, 1, 9, 0), CFG), 0.0)
        self.assertAlmostEqual(m.session_fraction(wib(2026, 10, 1, 12, 30), CFG), 180 / 320)
        self.assertAlmostEqual(m.session_fraction(wib(2026, 10, 1, 16, 30), CFG), 1.0)

    def test_rules(self):
        self.assertIsNotNone(m.evaluate(q(1050), {"type": "pct_move", "value": 4}, 1, CFG))
        self.assertIsNone(m.evaluate(q(1030), {"type": "pct_move", "value": 4}, 1, CFG))
        self.assertIsNotNone(m.evaluate(q(990), {"type": "price_below", "value": 1000}, 1, CFG))
        self.assertIsNotNone(m.evaluate(q(1000, vol=3000), {"type": "volume_spike", "value": 2.5}, 1, CFG))
        self.assertIsNone(m.evaluate(q(1000, vol=0, avg=0), {"type": "volume_spike", "value": 2.5}, 1, CFG))
        self.assertIn("ARA", m.evaluate(q(1245), {"type": "near_limit", "value": 1.0}, 1, CFG))
        self.assertIn("ARB", m.evaluate(q(855), {"type": "near_limit", "value": 1.0}, 1, CFG))

    def test_validate(self):
        bad = {"monitor": {"default_rules": [{"type": "nope", "value": 1}], "watchlist": {}}}
        with self.assertRaises(ValueError):
            m.validate(bad)

    def test_cooldown_and_stale(self):
        with tempfile.TemporaryDirectory() as d:
            st = m.State(f"{d}/s.db")
            self.assertTrue(st.due("k", 60, 1000)); st.mark("k", 1000)
            self.assertFalse(st.due("k", 60, 1000 + 59 * 60))
            self.assertTrue(st.due("k", 60, 1000 + 61 * 60))
            now = wib(2026, 10, 1, 10, 0)
            old = q(1100, ts=wib(2026, 9, 30, 15, 0))        # data kemarin
            out = m.run_cycle(CFG, {"TEST": old}, [], now, st)
            self.assertTrue(out and "basi" in out[0])
            self.assertEqual(m.run_cycle(CFG, {"TEST": old}, [], now, st), [])  # peringatan sekali/hari
            st.db.close()  # tutup SQLite sebelum cleanup (Windows file locking)


class TestYahooParse(unittest.TestCase):
    """Parser Yahoo diuji dengan payload tiruan (bentuk respons chart API) -- bukan data nyata."""
    def _payload(self, last_day_present=True):
        import pandas as pd
        days = pd.bdate_range(end="2026-09-30" if last_day_present else "2026-09-29", periods=60)
        ts = [int(pd.Timestamp(d, tz=m.WIB).replace(hour=15).timestamp()) for d in days]
        n = len(ts)
        close = [9000 + i for i in range(n)]
        return {"chart": {"result": [{
            "meta": {"regularMarketPrice": close[-1] + 10, "regularMarketTime": ts[-1]},
            "timestamp": ts,
            "indicators": {"quote": [{"open": close, "high": close, "low": close,
                                      "close": close, "volume": [1_000_000] * (n - 1) + [500_000]}]}}]}}

    def test_parse(self):
        from unittest import mock
        resp = mock.Mock(); resp.raise_for_status = lambda: None
        resp.json = lambda: self._payload()
        with mock.patch.object(m.requests, "get", return_value=resp):
            qt = m._yahoo_quote("BBCA")
        self.assertEqual(qt.prev_close, 9000 + 58)          # close hari sebelum bar terakhir
        self.assertEqual(qt.volume, 500_000)
        self.assertEqual(qt.avg_volume, 1_000_000)
        self.assertEqual(qt.price, 9000 + 59 + 10)
        self.assertEqual(len(qt.bars), 60)


if __name__ == "__main__":
    unittest.main()
