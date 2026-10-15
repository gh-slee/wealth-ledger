"""Exchange-rate parser and date policy regression checks."""
from datetime import date
from decimal import Decimal
import unittest
from wealth_ledger.fx import parse_cbc_html, _select, validate_rates


class ExchangeRateTests(unittest.TestCase):
    def test_chart_dates_are_paired_with_rates(self):
        html = "var chartNum = [[31.8,31.875],[1,2]]; var chartDate = [['2026/10/07','2026/10/08'],['x','y']];"
        rows = parse_cbc_html(html)
        self.assertEqual(_select(rows, date(2026, 10, 9)), ("2026-10-08", "31.875"))
        self.assertEqual(_select(rows, date(2026, 10, 7)), ("2026-10-07", "31.8"))

    def test_malformed_chart_fails_without_guessing(self):
        with self.assertRaises(ValueError):
            parse_cbc_html("var chartNum=[[31.8]]; var chartDate=[['2026/10/07','2026/10/08']];")

    def test_future_and_stale_rates_are_rejected(self):
        for day in (date(2026, 10, 10), date(2026, 9, 1)):
            with self.assertRaises(ValueError):
                _select([(day, "1.4")], date(2026, 10, 9))

    def test_invalid_rate_is_rejected(self):
        data = {"usd_cad": "0", "usd_twd": "31.875", "usd_cad_date": "2026-10-09", "usd_twd_date": "2026-10-08", "usd_cad_source": "official", "usd_twd_source": "official"}
        with self.assertRaises(ValueError):
            validate_rates(data, "2026-10-09")


if __name__ == "__main__":
    unittest.main()
