"""Frozen publication projections and static asset isolation use synthetic state."""
from contextlib import closing
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

import test_web as foundation
from test_web import AVAILABLE

if AVAILABLE:
    from wealth_ledger.core import import_holdings
    from wealth_ledger.crypto import import_bull_orders
    from wealth_ledger.combined import make_combined_payload
    from wealth_ledger.lookthrough import attach_analysis
    from wealth_ledger.web.jobs import Jobs
    from wealth_ledger.web.api import create_app
    from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def synthetic_payload(project):
    from examples.demo import synthetic_fund
    data = ROOT / "examples/data"
    fx = json.loads((data / "fx.json").read_text())
    opening = json.loads((ROOT / "config/bull-opening.example.json").read_text())
    import_holdings(project, data / "wealthsimple-holdings.csv", "baseline", fx)
    import_bull_orders(project, data / "bull-orders.csv", opening_assumption=opening)
    payload = make_combined_payload(project, as_of=json.loads((data / "btc-price.json").read_text())["as_of"], price_file=data / "btc-price.json", fx=fx)
    attach_analysis(project, payload, fetcher=synthetic_fund)
    return payload


def publish_fixture(store, portfolio, payload, *, status="published"):
    """Register an invented trusted-worker fixture, never an adoption route."""
    jobs = Jobs(store)
    with store.transaction() as conn:
        row = jobs._insert(conn, portfolio, "update", {}, uuid.uuid4().hex, "synthetic-test")
    _, project = store.portfolio(portfolio)
    target = project / "reports" / row["id"] / "data.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(payload))
    artifact = store.register_artifact(portfolio, row["id"], target.relative_to(project).as_posix())
    jobs.state(row["id"], status, result={"valuation_as_of": payload["meta"]["as_of"], "artifact_ids": [artifact]})
    return row["id"], target


@unittest.skipUnless(AVAILABLE, "Optional Web dependencies are not installed")
class PublicationTests(unittest.TestCase):
    setUp = foundation.WebTests.setUp
    bootstrap = foundation.WebTests.bootstrap
    login = foundation.WebTests.login
    mutate = foundation.WebTests.mutate
    portfolio = foundation.WebTests.portfolio

    def prepare(self):
        self.login(); self.pid = self.portfolio()
        _, project = self.store.portfolio(self.pid)
        self.payload = synthetic_payload(project)
        self.report, self.file = publish_fixture(self.store, self.pid, self.payload)
        self.prefix = f"/api/v1/portfolios/{self.pid}/reports"

    def test_read_only_frozen_payload_three_locales_no_network_or_revaluation(self):
        self.prepare()
        before = self.file.read_bytes()
        with patch("urllib.request.urlopen", side_effect=AssertionError("No network on viewing")), \
             patch("wealth_ledger.combined.make_combined_payload", side_effect=AssertionError("No valuation on viewing")):
            views = []
            for locale in ("en-CA", "zh-TW", "zh-CN"):
                response = self.client.get(self.prefix + "/" + self.report, params={"locale": locale})
                self.assertEqual(response.status_code, 200, response.text)
                views.append(response.json())
            self.assertEqual(views[0]["totals"], views[1]["totals"])
            self.assertEqual(views[0]["totals"], views[2]["totals"])
            self.assertEqual(views[0]["as_of"], self.payload["meta"]["as_of"])
            self.assertEqual(views[0]["companies"][0]["rank"], 1)
            self.assertTrue(views[0]["dimensions"]["sector"]["rows"])
            self.assertEqual(views[0]["btc"]["quantity_btc"], self.payload["crypto"]["btc_equivalent_qty"])
            self.assertNotIn(str(self.root), response.text)
            self.assertNotIn("evidence_path", response.text)
        self.assertEqual(before, self.file.read_bytes())

    def test_wallet_only_total_does_not_invent_a_bull_source(self):
        self.login(); pid = self.portfolio("Synthetic wallet-only")
        _, project = self.store.portfolio(pid)
        from wealth_ledger.wallet import add_balance
        data = ROOT / "examples/data"
        cutoff = json.loads((data / "btc-price.json").read_text())["as_of"]
        add_balance(project, "0.01", cutoff, source="example-test-balance")
        payload = make_combined_payload(project, as_of=cutoff, price_file=data / "btc-price.json",
                                        fx=json.loads((data / "fx.json").read_text()))
        report, _ = publish_fixture(self.store, pid, payload)
        response = self.client.get(f"/api/v1/portfolios/{pid}/reports/{report}")
        self.assertEqual(response.status_code, 200, response.text)
        view = response.json()
        self.assertEqual([source["provider"] for source in view["source_dates"]], ["wallet"])
        self.assertEqual(Decimal(view["btc"]["quantity_btc"]), Decimal("0.01"))
        self.assertEqual(view["btc"]["quantity_status"], "user_reported_balance")
        self.assertEqual(view["accounts"][0]["source_provider"], "wallet")
        self.assertNotIn("Bull", view["accounts"][0]["label"])

    def test_scope_pagination_unpublished_auth_and_artifact_integrity(self):
        self.prepare()
        second, _ = publish_fixture(self.store, self.pid, self.payload)
        pending, _ = publish_fixture(self.store, self.pid, self.payload, status="data_committed")
        result = self.client.get(self.prefix, params={"limit": 1}).json()
        self.assertEqual(len(result["reports"]), 1)
        self.assertIsNotNone(result["next_cursor"])
        older = self.client.get(self.prefix, params={"limit": 1, "cursor": result["next_cursor"]}).json()
        self.assertNotEqual(result["reports"][0]["id"], older["reports"][0]["id"])
        self.assertIsNone(older["next_cursor"])
        other = self.portfolio("Other synthetic portfolio")
        self.assertEqual(self.client.get(f"/api/v1/portfolios/{other}/reports/{self.report}").status_code, 404)
        self.assertEqual(self.client.get(self.prefix + "/" + pending).status_code, 404)
        self.assertEqual(self.client.get(self.prefix + "/" + self.report, params={"locale":"unknown"}).status_code, 422)
        self.file.write_text("{}")
        response = self.client.get(self.prefix + "/" + self.report)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn(str(self.root), response.text)
        self.mutate("POST", "/api/v1/auth/logout")
        self.assertEqual(self.client.get(self.prefix).status_code, 401)

    def test_static_routes_cannot_serve_private_paths_maps_or_symlinks(self):
        build = self.root.parent / "build"; (build / "assets").mkdir(parents=True)
        (build / "index.html").write_text('<div id="root"></div>')
        (build / "assets/app.js").write_text("export const synthetic = true;")
        (build / "assets/app.js.map").write_text("synthetic map")
        private = self.root.parent / "private.txt"; private.write_text("invented private marker")
        (build / "assets/link.txt").symlink_to(private)
        with TestClient(create_app(self.settings, frontend_root=build), base_url=foundation.ORIGIN) as client:
            for route in ("/", "/login", "/app", "/app/portfolio/overview"):
                response = client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn("script-src 'self'", response.headers["content-security-policy"])
                self.assertIn("no-store", response.headers["cache-control"])
            self.assertEqual(client.get("/assets/app.js").status_code, 200)
            for route in ("/assets/link.txt", "/assets/app.js.map", "/assets/.env", "/data/private.txt", "/api/missing", "/private.txt"):
                self.assertEqual(client.get(route).status_code, 404, route)
