"""The WL-P0-009E spike probe: no key leaks and no request without a key file."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("market_provider_spike", ROOT / "scripts" / "market_provider_spike.py")
spike = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spike)

KEY = "SYNTHETIC-KEY-0123456789"
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)


def _no_network(*args, **kwargs):
    raise AssertionError("the spike test opened a network connection")


class SpikeProbeTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.create_connection", "socket.getaddrinfo"):
            patcher = mock.patch(target, _no_network)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_key_file_sends_no_request(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(spike, "http_get") as get:
            report = spike.run(folder, now=lambda tz: NOW)
        get.assert_not_called()
        self.assertEqual({row["skipped"] for row in report["results"]}, {"no_key_file"})

    def test_key_is_never_in_the_summary(self):
        seen = []

        def fake_get(url, headers=None):
            seen.append((url, headers))
            # A refusal body that echoes the key must still be scrubbed.
            return 429, {"retry-after": "60"}, {"Note": f"limit reached for {KEY}"}

        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "alphavantage.key").write_text(KEY + "\n", encoding="utf-8")
            with mock.patch.object(spike, "http_get", fake_get):
                report = spike.run(folder, only={"alphavantage"}, listings=(("XTSE", "VEQT", "Toronto ETF"),),
                                   now=lambda tz: NOW)
        self.assertTrue(seen)
        self.assertNotIn(KEY, json.dumps(report))
        row = report["results"][0]["listings"][0]
        self.assertEqual(row["latest"]["status"], 429)
        self.assertEqual(row["latest"]["rate"], {"retry-after": "60"})
        self.assertIn("[redacted]", row["latest"]["error"])

    def test_alpha_vantage_toronto_symbol_and_bar_summary(self):
        series = {"Time Series (Daily)": {"2026-11-10": {"4. close": "41.20"}, "2026-11-11": {"4. close": "41.35"}}}
        with mock.patch.object(spike, "http_get", return_value=(200, {}, series)) as get:
            history = spike.AlphaVantage(KEY).history("XTSE", "VEQT")
        self.assertIn("symbol=VEQT.TRT", get.call_args.args[0])
        self.assertEqual(history["bars"], 2)
        self.assertEqual(history["last_day"], "2026-11-11")
        self.assertEqual(history["last_close"], "41.35")

    def test_header_keyed_providers_keep_the_key_out_of_the_url(self):
        for cls in (spike.TwelveData, spike.Finnhub):
            with mock.patch.object(spike, "http_get", return_value=(404, {}, {"message": "not found"})) as get:
                cls(KEY).latest("XNAS", "AAPL")
            self.assertNotIn(KEY, get.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
