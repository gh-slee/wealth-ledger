"""Check ODS formulas and self-contained, non-overlapping PNG chart packaging."""
from decimal import Decimal
from pathlib import Path
import copy
import hashlib
import math
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib
import xml.etree.ElementTree as ET
from test_core import FX, write_holdings, synthetic_rows, row
from wealth_ledger.core import import_holdings, make_payload
from wealth_ledger.workbook import (BASELINE_CHART_KEYS, FONT_NAME, FONT_PACKAGE_PATH,
                                   FONT_MEDIA_TYPE, FONT_PATH, FONT_LICENSE_PATH,
                                   NS, tag, build_workbook, verify_workbook)
from wealth_ledger.validation import validate_formula_caches


class WorkbookTests(unittest.TestCase):
    def setUp(self):
        project = Path(__file__).resolve().parents[1]
        self.temp = tempfile.TemporaryDirectory(prefix="ods-test-")
        self.project = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, rows=None):
        source = write_holdings(self.project / "input.csv", rows)
        import_holdings(self.project, source, "baseline", FX)
        return make_payload(self.project)

    def chart_fixture(self, keys=BASELINE_CHART_KEYS, directory="chart-source", seed=1):
        """Make small valid RGB PNGs with distinct contents using only stdlib."""
        paths = {}
        folder = self.project / directory
        folder.mkdir(parents=True, exist_ok=True)
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        for index, key in enumerate(keys):
            width, height = 160, 60 + index * 4
            color = bytes([(seed + index * 25) % 256, 120, 180])
            pixels = (b"\x00" + color * width) * height
            data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            data += chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
            path = folder / f"{key}.png"
            path.write_bytes(data)
            paths[key] = path
        return paths

    def build(self, rows=None):
        payload = self.payload(rows)
        output = self.project / "portfolio.ods"
        build_workbook(payload, output, chart_images=self.chart_fixture())
        return payload, output

    def test_three_currency_summary_and_all_saved_formulas(self):
        payload, output = self.build()
        self.assertEqual(verify_workbook(output, payload["totals"]["total_cad"])["sheets"], 9)
        result = validate_formula_caches(output)
        self.assertGreater(result["independently_evaluated_formulas"], 100)
        self.assertEqual(result["cache_mismatches"], 0)

    def test_corrupted_formula_cache_is_detected(self):
        _, output = self.build()
        with zipfile.ZipFile(output) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        root = ET.fromstring(files["content.xml"])
        namespace = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
        office = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
        cell = next(cell for cell in root.iter(f"{{{namespace}}}table-cell")
                    if cell.get(f"{{{namespace}}}formula") and cell.get(f"{{{office}}}value") is not None)
        cell.set(f"{{{office}}}value", "9999999")
        files["content.xml"] = ET.tostring(root)
        corrupt = self.project / "corrupt.ods"
        with zipfile.ZipFile(corrupt, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        with self.assertRaises(ValueError):
            validate_formula_caches(corrupt)

    def test_nonpositive_cost_does_not_create_return_ratio(self):
        rows = synthetic_rows()
        rows[0] = row("TFSA", "SYNTH-TFSA", "ETF", "CAD", 10, 12, -10)
        _, output = self.build(rows)
        self.assertEqual(validate_formula_caches(output)["cache_mismatches"], 0)

    def test_cash_only_payload_is_valid(self):
        rows = [row("TFSA", "SYNTH-TFSA", "CAD", "CAD", 100, 1, 100, True)]
        payload, output = self.build(rows)
        self.assertEqual(verify_workbook(output, "100")["total_cad"], "100")
        self.assertEqual(validate_formula_caches(output)["cache_mismatches"], 0)

    def test_embedded_pngs_are_exact_source_bytes_with_manifest_and_no_native_objects(self):
        payload = self.payload()
        images = self.chart_fixture()
        output = self.project / "images.ods"
        metadata = build_workbook(payload, output, images)
        self.assertEqual(metadata["native_charts"], 0)
        self.assertEqual(metadata["embedded_charts"], 8)
        checked = verify_workbook(output)
        self.assertEqual(checked["embedded_images"], 8)
        self.assertEqual(checked["chart_mode"], "embedded_png")
        with zipfile.ZipFile(output) as archive:
            content = ET.fromstring(archive.read("content.xml"))
            manifest = ET.fromstring(archive.read("META-INF/manifest.xml"))
            entries = {entry.get(tag("manifest:full-path")): entry.get(tag("manifest:media-type"))
                       for entry in manifest.findall("manifest:file-entry", NS)}
            self.assertFalse(any(name.startswith("Object ") for name in archive.namelist()))
            self.assertEqual(content.findall(".//draw:object", NS), [])
            references = {node.get(tag("xlink:href")) for node in content.findall(".//draw:image", NS)}
            self.assertEqual(references, {f"Pictures/{key}.png" for key in images})
            for key, path in images.items():
                packaged = f"Pictures/{key}.png"
                self.assertEqual(archive.read(packaged), path.read_bytes())
                self.assertEqual(entries[packaged], "image/png")
                self.assertEqual(checked["chart_hashes"][key], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertGreater(len([node for node in content.findall(".//table:table-cell", NS)
                                    if node.get(tag("table:style-name")) == "heatmap"]), 0)

    def test_chart_frames_preserve_aspect_ratio_and_reserved_rows_do_not_overlap(self):
        _, output = self.build()
        with zipfile.ZipFile(output) as archive:
            root = ET.fromstring(archive.read("content.xml"))
            chart_sheet = next(node for node in root.findall(".//table:table", NS)
                               if node.get(tag("table:name")) == "圖表分析")
            rows = chart_sheet.findall("table:table-row", NS)
            previous_bottom = 0
            count = 0
            for row_index, row_node in enumerate(rows, 1):
                for frame in row_node.findall(".//draw:frame", NS):
                    count += 1
                    self.assertGreater(row_index, previous_bottom + 1)
                    width = Decimal(frame.get(tag("svg:width"))[:-2])
                    height = Decimal(frame.get(tag("svg:height"))[:-2])
                    image_path = frame.find("draw:image", NS).get(tag("xlink:href"))
                    pixel_width, pixel_height = struct.unpack(">II", archive.read(image_path)[16:24])
                    self.assertLess(abs(height / width - Decimal(pixel_height) / pixel_width), Decimal("0.00001"))
                    whole_rows = int(height // Decimal("0.65"))
                    self.assertEqual(frame.get(tag("table:end-cell-address")), f"'圖表分析'.L{row_index + whole_rows}")
                    self.assertEqual(Decimal(frame.get(tag("table:end-y"))[:-2]), height - whole_rows * Decimal("0.65"))
                    previous_bottom = row_index + math.ceil(height / Decimal("0.65"))
                    self.assertLessEqual(previous_bottom, len(rows))
                    for reserved in rows[row_index:previous_bottom]:
                        self.assertEqual(reserved.findall(".//draw:frame", NS), [])
                        self.assertEqual(reserved.findall(".//text:p", NS), [])
            self.assertEqual(count, 8)

    def test_future_history_chart_is_embedded_and_required_for_multiple_dates(self):
        payload = self.payload()
        later = copy.deepcopy(payload["history"][0])
        later["as_of"] = "2026-11-09T22:28:00-05:00"
        payload["history"].append(later)
        output = self.project / "history.ods"
        with self.assertRaisesRegex(ValueError, "09_historical_values"):
            build_workbook(payload, output, self.chart_fixture())
        self.assertFalse(output.exists())
        images = self.chart_fixture((*BASELINE_CHART_KEYS, "09_historical_values"))
        build_workbook(payload, output, images)
        self.assertEqual(verify_workbook(output)["embedded_images"], 9)
        self.assertEqual(validate_formula_caches(output)["cache_mismatches"], 0)

    def test_missing_or_invalid_chart_asset_fails_before_writing_output(self):
        payload = self.payload()
        output = self.project / "invalid.ods"
        images = self.chart_fixture()
        with self.assertRaisesRegex(ValueError, "Missing report chart images"):
            build_workbook(payload, output, {key: value for key, value in images.items() if key != BASELINE_CHART_KEYS[0]})
        self.assertFalse(output.exists())
        image = images[BASELINE_CHART_KEYS[0]]
        image.write_bytes(image.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "Invalid report chart image"):
            build_workbook(payload, output, images)
        self.assertFalse(output.exists())

    def test_default_api_regenerates_charts_on_every_build(self):
        payload = self.payload()
        first = self.chart_fixture(directory="first", seed=1)
        second = self.chart_fixture(directory="second", seed=2)
        output = self.project / "automatic.ods"
        with patch("wealth_ledger.reporting._font_path", return_value=self.project / "font.ttf"), \
             patch("wealth_ledger.reporting._charts", side_effect=[first, second]) as renderer:
            build_workbook(payload, output)
            first_hash = verify_workbook(output)["chart_hashes"][BASELINE_CHART_KEYS[0]]
            build_workbook(payload, output)
            second_hash = verify_workbook(output)["chart_hashes"][BASELINE_CHART_KEYS[0]]
            self.assertEqual(renderer.call_count, 2)
            self.assertNotEqual(first_hash, second_hash)
            self.assertEqual(renderer.call_args.args, (payload, output.parent / "charts", self.project / "font.ttf"))

    def test_broken_image_reference_and_manifest_are_detected(self):
        _, output = self.build()
        with zipfile.ZipFile(output) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        for failure in ["image", "manifest"]:
            changed = dict(files)
            if failure == "image":
                changed.pop(f"Pictures/{BASELINE_CHART_KEYS[0]}.png")
            else:
                manifest = ET.fromstring(changed["META-INF/manifest.xml"])
                entry = next(item for item in manifest.findall("manifest:file-entry", NS)
                             if item.get(tag("manifest:full-path")) == f"Pictures/{BASELINE_CHART_KEYS[0]}.png")
                entry.set(tag("manifest:media-type"), "text/xml")
                changed["META-INF/manifest.xml"] = ET.tostring(manifest)
            corrupted = self.project / f"bad-{failure}.ods"
            with zipfile.ZipFile(corrupted, "w") as archive:
                archive.writestr("mimetype", changed.pop("mimetype"), compress_type=zipfile.ZIP_STORED)
                for name, data in changed.items():
                    archive.writestr(name, data)
            with self.assertRaisesRegex(ValueError, "Missing embedded chart image"):
                verify_workbook(corrupted)

    def test_font_asset_license_references_and_asian_styles_are_self_contained(self):
        _, output = self.build()
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.read(FONT_PACKAGE_PATH), FONT_PATH.read_bytes())
            self.assertEqual(archive.read("Fonts/OFL.txt"), FONT_LICENSE_PATH.read_bytes())
            manifest = ET.fromstring(archive.read("META-INF/manifest.xml"))
            entries = {entry.get(tag("manifest:full-path")): entry.get(tag("manifest:media-type"))
                       for entry in manifest.findall("manifest:file-entry", NS)}
            self.assertEqual(entries[FONT_PACKAGE_PATH], FONT_MEDIA_TYPE)
            self.assertEqual(entries["Fonts/OFL.txt"], "text/plain")
            for name in ["content.xml", "styles.xml"]:
                root = ET.fromstring(archive.read(name))
                faces = root.findall("office:font-face-decls/style:font-face", NS)
                face = next(node for node in faces if node.get(tag("style:name")) == FONT_NAME)
                uri = face.find("svg:font-face-src/svg:font-face-uri", NS)
                self.assertEqual(uri.get(tag("xlink:href")), FONT_PACKAGE_PATH)
                self.assertEqual(uri.get(tag("xlink:type")), "simple")
                self.assertEqual(uri.find("svg:font-face-format", NS).get(tag("svg:string")), "truetype")
                for properties in root.findall(".//style:text-properties", NS):
                    self.assertEqual(properties.get(tag("style:font-name")), FONT_NAME)
                    self.assertEqual(properties.get(tag("style:font-name-asian")), FONT_NAME)
                    self.assertEqual(properties.get(tag("style:font-size-asian")), properties.get(tag("fo:font-size")))
                    self.assertEqual(properties.get(tag("style:language-asian")), "zh")
                    self.assertEqual(properties.get(tag("style:country-asian")), "TW")
        checked = verify_workbook(output)
        self.assertEqual(checked["embedded_font"], FONT_NAME)
        self.assertEqual(checked["font_sha256"], hashlib.sha256(FONT_PATH.read_bytes()).hexdigest())

    def test_missing_font_fails_before_writing_report(self):
        payload = self.payload()
        output = self.project / "missing-font.ods"
        with patch("wealth_ledger.workbook.FONT_PATH", self.project / "missing.ttf"):
            with self.assertRaisesRegex(ValueError, "Missing bundled document font"):
                build_workbook(payload, output, self.chart_fixture())
        self.assertFalse(output.exists())

    def test_removed_embedded_font_is_detected(self):
        _, output = self.build()
        with zipfile.ZipFile(output) as archive:
            files = {name: archive.read(name) for name in archive.namelist() if name != FONT_PACKAGE_PATH}
        corrupted = self.project / "missing-font-package.ods"
        with zipfile.ZipFile(corrupted, "w") as archive:
            archive.writestr("mimetype", files.pop("mimetype"), compress_type=zipfile.ZIP_STORED)
            for name, data in files.items():
                archive.writestr(name, data)
        with self.assertRaisesRegex(ValueError, "Missing embedded document font"):
            verify_workbook(corrupted)


if __name__ == "__main__":
    unittest.main()
