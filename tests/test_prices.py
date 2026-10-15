"""Reference price cutoff and reproducibility checks with offline evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from wealth_ledger.prices import select_candle, validate_quote, resolve_btc_price

AS_OF = "2026-10-10T02:28:00Z"


class PriceTests(unittest.TestCase):
    def test_last_completed_candle_rejects_future_interval(self):
        rows=[[1791599280,1,3,1,2,1],[1791599220,1,3,1,1.5,1]]
        quote=select_candle(rows,AS_OF)
        self.assertEqual(quote["close"],"1.5")
        self.assertEqual(quote["candle_end"],"2026-10-10T02:28:00+00:00")
        with self.assertRaisesRegex(ValueError,"No completed"):
            select_candle(rows[:1],AS_OF)

    def test_stale_and_invalid_prices_fail(self):
        for rows in ([[1791598800,1,3,1,2,1]],[[1791599220,1,3,1,0,1]],[[1791599220,1,3,1,"NaN",1]]):
            with self.assertRaises(ValueError):
                select_candle(rows,AS_OF)

    def test_cache_is_offline_and_tamper_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            evidence=root/"data/prices/evidence/offline.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_bytes(b"[]")
            quote={"provider":"offline-test","pair":"BTC-USD","as_of":AS_OF,
                   "source_url":"https://example.test/quote","close":"100000",
                   "candle_start":"2026-10-10T02:27:00Z","candle_end":AS_OF,
                   "evidence_path":str(evidence.relative_to(root)),
                   "evidence_sha256":hashlib.sha256(b"[]").hexdigest()}
            (root/"data/prices/btc-usd-2026-10-10T022800+0000.json").write_text(json.dumps(quote), encoding="utf-8")
            with patch("wealth_ledger.prices.urlopen",side_effect=AssertionError("Must stay offline")):
                self.assertEqual(resolve_btc_price(root,AS_OF),quote)
                evidence.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError,"evidence"):
                    resolve_btc_price(root,AS_OF)
            with self.assertRaisesRegex(ValueError,"different"):
                validate_quote(quote,"2026-10-10T02:29:00Z")
