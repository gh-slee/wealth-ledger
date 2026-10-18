"""Create a portable ODF spreadsheet directly from the ledger report payload.

ODS packaging uses the Python standard library. Formula cells include numeric
caches. Charts are embedded PNG images refreshed by the reporting renderer;
worksheet tables and formulas remain editable independently of the images.
"""
from __future__ import annotations

from .i18n import tr, LabelCatalog, localized, sheet_title, legacy_text, current_context
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from collections.abc import Mapping
from .workspace import CODE_ROOT

import hashlib
import json
import math
import struct
import zlib
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "chart": "urn:oasis:names:tc:opendocument:xmlns:chart:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "number": "urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0",
    "manifest": "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)
OF = "urn:oasis:names:tc:opendocument:xmlns:of:1.2"
MIME = "application/vnd.oasis.opendocument.spreadsheet"
INK = "#243B53"
CHART_TITLES = LabelCatalog({'01_account_values': 'message.feca6f3d2124', '02_trading_currency': 'message.e00157582927', '03_holdings_ranking': 'message.4e21128e500b', '04_holdings_by_account': 'message.3adb37c830ef', '05_unrealized_native': 'message.d6e579a4c691', '06_unrealized_percent': 'message.8011c979537c', '07_instrument_mix': 'message.1daa0525a3c8', '08_account_weight_heatmap': 'message.386cb258cdbb', '09_historical_values': 'message.76d4f7bf5033', '10_btc_accumulation': 'message.c74b05ca3c98', '11_btc_monthly_contributions': 'message.f12bb15c412b', '12_company_exposure': 'message.21aed5578b03', '13_sector_exposure': 'message.b74d7ca4ec91', '14_country_exposure': 'message.e33341e79550', '15_region_exposure': 'message.2eb711c20acf', '16_btc_wallet_reconciliation': 'message.554a3964b9ca'})
BASELINE_CHART_KEYS = tuple(CHART_TITLES)[:8]
CRYPTO_CHART_KEYS = ("10_btc_accumulation", "11_btc_monthly_contributions")
BASE_SHEETS = ('overview', 'currency_holdings', 'account_holdings', 'portfolio_analysis', 'charts', 'history', 'cash_flows', 'positions', 'rates_notes')
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ROW_HEIGHT_CM = Decimal("0.65")
FONT_NAME = "Noto Sans TC"
FONT_PACKAGE_PATH = "Fonts/NotoSansTC-Regular.ttf"
FONT_MEDIA_TYPE = "application/x-font-ttf"
FONT_PATH = CODE_ROOT / "assets/fonts/NotoSansTC-Regular.ttf"
FONT_LICENSE_PATH = CODE_ROOT / "assets/fonts/OFL.txt"


def tag(name: str) -> str:
    prefix, local = name.split(":", 1)
    return f"{{{NS[prefix]}}}{local}"


def element(parent, name, attributes=None, text=None):
    node = ET.SubElement(parent, tag(name), {tag(k): str(v) for k, v in (attributes or {}).items()})
    if text is not None:
        node.text = str(text)
    return node


def document_font_path():
    from .i18n import current_context, font_path
    return font_path() if current_context().locale == "zh-CN" else FONT_PATH


def document_font_license():
    from .i18n import current_context, font_license_path
    return font_license_path() if current_context().locale == "zh-CN" else FONT_LICENSE_PATH


def document_font_family():
    from .i18n import font_family
    return font_family()


def document_font_package():
    from .i18n import font_package_path
    return font_package_path()


def font_declarations(parent):
    """Declare the same package font for Latin and Asian script styles."""
    declarations = element(parent, "office:font-face-decls")
    face = element(declarations, "style:font-face", {
        "style:name": document_font_family(), "svg:font-family": document_font_family(),
        "style:font-family-generic": "swiss", "style:font-pitch": "variable",
        "svg:font-style": "normal", "svg:font-weight": "normal"})
    source = element(face, "svg:font-face-src")
    uri = element(source, "svg:font-face-uri", {"xlink:type": "simple", "xlink:href": document_font_package()})
    element(uri, "svg:font-face-format", {"svg:string": "truetype"})


def font_embedding_permissions(data: bytes):
    """Validate a TrueType container and its OS/2 document embedding flags."""
    if len(data) < 12 or data[:4] != b"\x00\x01\x00\x00":
        raise ValueError("Bundled document font is not a TrueType sfnt")
    table_count = struct.unpack_from(">H", data, 4)[0]
    if len(data) < 12 + table_count * 16:
        raise ValueError("Truncated document font table directory")
    for index in range(table_count):
        name, _, offset, length = struct.unpack_from(">4sIII", data, 12 + index * 16)
        if offset + length > len(data):
            raise ValueError("Truncated document font table")
        if name == b"OS/2":
            if length < 10:
                raise ValueError("Invalid document font OS/2 table")
            flags = struct.unpack_from(">H", data, offset + 8)[0]
            # Editable investment workbooks require unrestricted or editable use.
            if flags & (0x0002 | 0x0200) or flags & 0x0004 and not flags & 0x0008:
                raise ValueError("Document font does not permit editable outline embedding")
            return flags
    raise ValueError("Document font is missing embedding permission metadata")


def load_document_font():
    """Read repository assets without relying on any installed system font."""
    try:
        data = document_font_path().read_bytes()
        license_data = document_font_license().read_bytes()
    except OSError as error:
        raise ValueError("Missing bundled document font or OFL license in assets/fonts") from error
    font_embedding_permissions(data)
    if b"SIL OPEN FONT LICENSE" not in license_data:
        raise ValueError("Missing document font redistribution license")
    return data, license_data


def decimal(value) -> Decimal:
    return Decimal(str(value if value not in (None, "") else 0))


def number(value):
    return None if value in (None, "") else decimal(value)


def column(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def address(sheet: str, row: int, col: int, absolute=False) -> str:
    sheet = sheet_title(sheet)
    escaped = sheet.replace("'", "''")
    marker = "$" if absolute else ""
    return f"'{escaped}'.{marker}{column(col)}{marker}{row}"


def ref(sheet: str, row: int, col: int, absolute=False) -> str:
    return f"[{address(sheet, row, col, absolute)}]"


def interval(sheet: str, start: int, end: int, col: int) -> str:
    return f"[{address(sheet, start, col, True)}:{address(sheet, end, col, True)}]"


def literal(value) -> str:
    return '"' + str(legacy_text(value)).replace('"', '""') + '"'


@dataclass
class Cell:
    value: object = None
    formula: str | None = None
    style: str = "body"
    frames: list = field(default_factory=list)


@dataclass(frozen=True)
class ChartImage:
    key: str
    data: bytes
    pixel_width: int
    pixel_height: int

    @property
    def package_path(self):
        return f"Pictures/{self.key}.png"


@dataclass(frozen=True)
class ImageFrame:
    image: ChartImage
    width_cm: Decimal
    height_cm: Decimal
    end_cell: str
    end_y_cm: Decimal
    index: int


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Validate PNG framing and chunk checksums without external image tools."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Chart image is not a PNG")
    offset, width, height, seen_data, complete = 8, 0, 0, False, False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("Truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + length + 12
        if end > len(data):
            raise ValueError("Truncated PNG data")
        chunk_type = data[offset + 4:offset + 8]
        chunk_data = data[offset + 8:offset + 8 + length]
        checksum = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != checksum:
            raise ValueError("PNG checksum failed")
        if offset == 8:
            if chunk_type != b"IHDR" or length != 13:
                raise ValueError("PNG missing first IHDR chunk")
            width, height = struct.unpack_from(">II", chunk_data)
            if not width or not height or width * height > 100_000_000:
                raise ValueError("Invalid chart image dimensions")
        elif chunk_type == b"IHDR":
            raise ValueError("Duplicate PNG IHDR chunk")
        if chunk_type == b"IDAT":
            seen_data = True
        if chunk_type == b"IEND":
            if length or end != len(data):
                raise ValueError("Invalid PNG end chunk")
            complete = True
            break
        offset = end
    if not complete or not seen_data:
        raise ValueError("Incomplete chart PNG")
    return width, height


def resolve_chart_images(payload: dict, output_path: Path, chart_images=None) -> list[ChartImage]:
    """Require complete current chart assets; lazily render when not supplied."""
    if chart_images is None:
        from .reporting import _charts, _font_path
        chart_images = _charts(payload, output_path.parent / "charts", _font_path())
    if not isinstance(chart_images, Mapping):
        raise ValueError("chart_images must map chart keys to PNG file paths")
    required = list(BASELINE_CHART_KEYS)
    if len({item["as_of"] for item in payload.get("history", [])}) >= 2:
        required.append("09_historical_values")
    if payload.get("crypto") is not None:
        required.extend(CRYPTO_CHART_KEYS)
        if payload["crypto"].get("wallet",{}).get("observations"):
            required.append("16_btc_wallet_reconciliation")
    if payload.get("lookthrough",{}).get("top20"):
        required.append("12_company_exposure")
    if payload.get('lookthrough',{}).get('classification'):
        from .classification_reports import CHARTS
        required.extend(key for dimension,key in CHARTS.items()
                        if payload['lookthrough']['classification']['dimensions'][dimension]['rows'])
    missing = [key for key in required if key not in chart_images]
    if missing:
        raise ValueError("Missing report chart images: " + ", ".join(missing))
    images = []
    for key in CHART_TITLES:
        if key not in chart_images:
            continue
        try:
            data = Path(chart_images[key]).read_bytes()
            width, height = png_dimensions(data)
        except (OSError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid report chart image {key}: {error}") from error
        images.append(ChartImage(key, data, width, height))
    return images


@dataclass
class Sheet:
    name: str
    cells: dict = field(default_factory=dict)
    widths: dict = field(default_factory=dict)
    frozen_rows: int = 0
    frozen_columns: int = 0

    def put(self, row, col, value=None, formula=None, style="body"):
        self.cells[row, col] = Cell(legacy_text(value), formula, style)

    def row(self, row, values, col=2, style="body"):
        for offset, value in enumerate(values):
            self.put(row, col + offset, value, style=style)

    def header(self, row, labels, col=2):
        self.row(row, labels, col, "header")

    def title(self, as_of):
        self.put(2, 2, tr('message.8de78309882b') if self.name == tr('message.c7abf421eeb9') else self.name, style="title")
        self.put(4, 2, tr('message.14bd8458f6df', value0=as_of), style="note")

    def section(self, row, text):
        self.put(row, 2, text, style="section")

    def extent(self):
        return max((r for r, _ in self.cells), default=1), max((c for _, c in self.cells), default=1)


def add_style(parent, name, family, attributes=None, **properties):
    style = element(parent, "style:style", {"style:name": name, "style:family": family, **(attributes or {})})
    order = {"style_table_cell_properties": 0, "style_paragraph_properties": 1, "style_text_properties": 2}
    for property_name, property_attributes in sorted(properties.items(), key=lambda item: order.get(item[0], 0)):
        element(style, property_name.replace("_", ":", 1).replace("_", "-"), property_attributes)
    return style


def number_styles(parent):
    for name, precision in [("Money", 2), ("Quantity", 4), ("BtcQuantity", 8), ("Rate", 4), ("Integer", 0)]:
        style = element(parent, "number:number-style", {"style:name": name})
        element(style, "number:number", {"number:decimal-places": precision, "number:min-integer-digits": 1, "number:grouping": "true"})
    for name, precision in [("Percent", 1), ("SmallPercent", 6), ("ExposurePercent", 2), ("WeightPercent", 4)]:
        style = element(parent, "number:percentage-style", {"style:name": name})
        element(style, "number:number", {"number:decimal-places": precision, "number:min-integer-digits": 1})
        element(style, "number:text", text="%")
    style = element(parent, "number:date-style", {"style:name": "Date", "number:automatic-order": "false"})
    for node, text in [("number:year", None), ("number:text", "-"), ("number:month", None), ("number:text", "-"), ("number:day", None)]:
        element(style, node, {"number:style": "long"} if text is None else {}, text)


def common_styles(parent):
    number_styles(parent)
    language, country = current_context().locale.split("-", 1)
    text_props = {
        "style:font-name": document_font_family(), "style:font-name-asian": document_font_family(),
        "style:font-style-name": "Regular", "style:font-style-name-asian": "Regular",
        "fo:font-size": "11pt", "style:font-size-asian": "11pt",
        "style:language-asian": language, "style:country-asian": country, "fo:language": language, "fo:country": country, "fo:color": INK}
    cell_props = {"style:vertical-align": "middle", "fo:padding": "0.08cm", "fo:wrap-option": "no-wrap"}
    for name, props in {
        "body": {}, "money": {"style:data-style-name": "Money"}, "quantity": {"style:data-style-name": "Quantity"},
        "btc_quantity": {"style:data-style-name": "BtcQuantity"}, "input_btc_quantity": {"style:data-style-name": "BtcQuantity"},
        "percent": {"style:data-style-name": "Percent"}, "small_percent": {"style:data-style-name": "SmallPercent"},
        "date": {"style:data-style-name": "Date"}, "rate": {"style:data-style-name": "Rate"},
        "integer": {"style:data-style-name": "Integer"}, "input_money": {"style:data-style-name": "Money"},
        "input_quantity": {"style:data-style-name": "Quantity"}, "input_rate": {"style:data-style-name": "Rate"},
        "calc_money": {"style:data-style-name": "Money"}, "calc_percent": {"style:data-style-name": "Percent"},
        "header": {}, "title": {}, "note": {}, "section": {}, "total_money": {"style:data-style-name": "Money"},
        "warning": {}, "wrapped_body": {},
        "input_percent": {"style:data-style-name":"WeightPercent"},
        "calc_exposure_percent": {"style:data-style-name":"ExposurePercent"},
        "calc_small_exposure_percent": {"style:data-style-name":"SmallPercent"},
    }.items():
        font = dict(text_props)
        cell = dict(cell_props)
        paragraph = {"fo:text-align": "end" if "money" in name or "percent" in name or "quantity" in name or name in {"integer", "rate", "input_rate"} else "start"}
        if name.startswith("input"):
            font["fo:color"] = "#2164BB"
        if name.startswith("calc"):
            font["fo:color"] = "#1F7655"
        if name == "wrapped_body":
            cell["fo:wrap-option"] = "wrap"
        if name == "header":
            cell["fo:background-color"] = INK
            font.update({"fo:color": "#FFFFFF", "fo:font-weight": "bold"})
            font["style:font-weight-asian"] = "bold"
            paragraph["fo:text-align"] = "center"
        if name == "title":
            font.update({"fo:font-size": "16pt", "style:font-size-asian": "16pt",
                         "fo:font-weight": "bold", "style:font-weight-asian": "bold"})
        if name == "note":
            font.update({"fo:font-style": "italic", "fo:color": "#526578"})
        if name == "section":
            font["fo:font-weight"] = "bold"
            font["style:font-weight-asian"] = "bold"
            cell["fo:background-color"] = "#EEF3F8"
        if name == "total_money":
            font["fo:font-weight"] = "bold"
            font["style:font-weight-asian"] = "bold"
            cell["fo:border-top"] = "0.02cm solid #9AAFC0"
        if name == "warning":
            font["fo:color"] = "#A93E3E"
            cell["fo:background-color"] = "#FCE8E6"
        add_style(parent, name, "table-cell", props, style_text_properties=font, style_table_cell_properties=cell, style_paragraph_properties=paragraph)
    for level in range(11):
        t = level / 10
        low, high = (244, 247, 250), (54, 104, 160)
        fill = "#" + "".join(f"{round(a + (b - a) * t):02x}" for a, b in zip(low, high))
        add_style(parent, f"heat{level}", "table-cell", {"style:data-style-name": "Percent"},
                  style_table_cell_properties={**cell_props, "fo:background-color": fill},
                  style_text_properties={**text_props, "fo:color": "#FFFFFF" if level >= 7 else INK},
                  style_paragraph_properties={"fo:text-align": "end"})
    heatmap = add_style(parent, "heatmap", "table-cell", {"style:data-style-name": "Percent"},
                        style_table_cell_properties=cell_props, style_paragraph_properties={"fo:text-align": "end"},
                        style_text_properties=text_props)
    for level in range(10):
        element(heatmap, "style:map", {"style:condition": f"value()<={0.06 * (level + 0.5):.3f}", "style:apply-style-name": f"heat{level}"})
    element(heatmap, "style:map", {"style:condition": "value()>0.570", "style:apply-style-name": "heat10"})
    add_style(parent, "row", "table-row", style_table_row_properties={"style:row-height": "0.65cm", "style:use-optimal-row-height": "false"})
    add_style(parent, "row_tall", "table-row", style_table_row_properties={"style:row-height":"1.5cm", "style:use-optimal-row-height":"false"})
    add_style(parent, "row_header", "table-row", style_table_row_properties={"style:row-height": "0.9cm"})
    add_style(parent, "table", "table", style_table_properties={"table:display": "true"})


def cell_xml(parent, cell: Cell):
    attributes = {"table:style-name": cell.style}
    if cell.formula:
        attributes["table:formula"] = "of:=" + cell.formula
    value = cell.value
    if isinstance(value, (Decimal, int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise ValueError("Non-finite spreadsheet value")
        attributes.update({"office:value-type": "float", "office:value": str(value)})
        display = str(value)
    elif isinstance(value, bool):
        attributes.update({"office:value-type": "boolean", "office:boolean-value": str(value).lower()})
        display = str(value)
    elif isinstance(value, date):
        attributes.update({"office:value-type": "date", "office:date-value": value.isoformat()})
        display = value.isoformat()
    elif value is not None:
        attributes.update({"office:value-type": "string", "office:string-value": str(value)})
        display = str(value)
    else:
        display = ""
    node = element(parent, "table:table-cell", attributes)
    if display:
        element(node, "text:p", text=display)
    for frame in cell.frames:
        drawing = element(node, "draw:frame", {
            "draw:name": frame.image.key, "draw:z-index": frame.index,
            "svg:width": f"{frame.width_cm}cm", "svg:height": f"{frame.height_cm}cm",
            "svg:x": "0cm", "svg:y": "0cm", "table:end-cell-address": frame.end_cell,
            "table:end-x": "0cm", "table:end-y": f"{frame.end_y_cm}cm"})
        element(drawing, "draw:image", {
            "xlink:href": frame.image.package_path, "xlink:type": "simple",
            "xlink:show": "embed", "xlink:actuate": "onLoad"})
        element(drawing, "svg:title", text=CHART_TITLES[frame.image.key])
        element(drawing, "svg:desc", text=tr('message.7da00772e44b'))
    return node


def xml_bytes(root):
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


@localized
def build_workbook(payload: dict, output_path: Path, chart_images=None) -> dict:
    """Write editable tables and formulas with self-contained static chart PNGs.

    Pass the chart mapping returned by reporting.generate_reports to avoid a
    second render. Without it, current charts are regenerated using matplotlib.
    Neither path invokes a local office application.
    """
    with localcontext() as context:
        context.prec = 80
        return _build_workbook(payload, Path(output_path), chart_images)


def _build_workbook(payload: dict, output_path: Path, chart_images=None) -> dict:
    from .i18n import display_payload
    payload = display_payload(payload)
    output_path = Path(output_path)
    font_data, font_license = load_document_font()
    images = resolve_chart_images(payload, output_path, chart_images)
    crypto = payload.get("crypto")
    names = list(BASE_SHEETS)
    if crypto is not None:
        names.insert(5, "btc_tracking")
        names.insert(6, "btc_reconciliation")
    sheets = {name: Sheet(sheet_title(name)) for name in names}
    meta, fx = payload["meta"], payload["fx"]
    for sheet in sheets.values():
        sheet.title(meta["as_of"])
    r, s = decimal(fx["usd_cad"]), decimal(fx["usd_twd"])
    if r <= 0 or s <= 0:
        raise ValueError("Exchange rates must be positive")
    positions = [*payload["positions"], *payload.get("cash_rows", [])]
    if not positions:
        raise ValueError("No positions")
    cash = [p for p in positions if p["security_type"] == "CURRENCY"]
    securities = [p for p in positions if p["security_type"] != "CURRENCY"]
    crypto_positions = [p for p in securities if p["security_type"] == "CRYPTO"]
    native_securities = [p for p in securities if p["security_type"] != "CRYPTO"]
    if crypto_positions and crypto is None:
        raise ValueError("CRYPTO positions require a crypto tracking view")
    if any(p["currency"] != "CAD" for p in crypto_positions):
        raise ValueError("CRYPTO positions must use CAD as the valuation currency")
    label = lambda p: tr('message.f06049970c68') if crypto and p["account_id"]==crypto["meta"]["account_id"] else p.get("account_label", p.get("account_type", tr('message.607089b311be')))
    order = lambda name: next((i for i, prefix in enumerate(["TFSA", "RRSP", "Non-registered"]) if name.startswith(prefix)), 99)
    accounts = sorted({label(p) for p in positions}, key=lambda name: (order(name), name))
    value_cad = lambda p: decimal(p["market_native"]) * (r if p["currency"] == "USD" else 1)
    total_cad = sum((value_cad(p) for p in positions), Decimal(0))
    if abs(total_cad - decimal(payload["totals"]["total_cad"])) > Decimal("0.01"):
        raise ValueError("Workbook total differs from report payload")
    end_source = len(positions) + 5
    source_range = lambda col: interval('positions', 6, end_source, col)
    sum_formula = lambda col, criteria: "SUMIFS(" + ";".join([source_range(col), *sum(([source_range(c), literal(v)] for c, v in criteria), [])]) + ")"
    source_rows = {}
    src = sheets['positions']
    src.header(5, [tr('message.b0f18aa763de'), tr('message.78b5efd1ac10'), tr('message.4f45fc8d4113'), tr('message.9dc89ac7e0e5'), tr('message.26c1c5b41973'), "MIC", tr('message.a5274f381305'), tr('message.be547beabfb6'), tr('message.3e9409c24979'), tr('message.ec9554ab6f4f'), tr('message.f184d8001cfc'), tr('message.ff68c70ea858'), tr('message.1bb4d99c0340'), tr('message.9681b050ef05'), tr('message.2ae87208315e'), tr('message.f3a7e3113505'), tr('message.e27d7ed41293'), tr('message.f3c0c439a1d2'), tr('message.e554ff6ecaae'), tr('message.5ce2c9b6bad4')], 1)
    if crypto is not None:
        src.put(5, 5, tr('message.701122b9f776'), style="header")
        src.put(5, 10, tr('message.166726d7943d'), style="header")
        src.put(5, 12, tr('message.bee6258e1218'), style="header")
        src.put(5, 13, tr('message.e7953617ae35'), style="header")
        src.put(5, 21, tr('message.6ac3ce818f27'), style="header")
    src.frozen_rows, src.frozen_columns = 5, 3
    for index, p in enumerate(positions, 6):
        source_rows[id(p)] = index
        account_total = sum((value_cad(other) for other in positions if label(other) == label(p)), Decimal(0))
        raw = [label(p), p["account_id"], p["symbol"], p["security_type"], p["currency"], p.get("mic", ""), p.get("name", ""),
               decimal(p["quantity"]), decimal(p["price"]), decimal(p["book_native"]), decimal(p["book_cad"]), decimal(p["market_native"]), decimal(p["unrealized_native"])]
        for col, value in enumerate(raw, 1):
            style = "input_btc_quantity" if col == 8 and p["security_type"] == "CRYPTO" else "input_quantity" if col in (8, 9) else "input_money" if col >= 10 else "body"
            src.put(index, col, value, style=style)
        if crypto is not None:
            src.put(index, 21, tr('message.86789ba2a1d8') if p["security_type"] == "CRYPTO" else tr('message.6f3045fd7db8'))
        unknown_cost=p.get("cost_status") in ("partial_unknown_opening","unknown_wallet_cost")
        market = value_cad(p)
        is_cash = p["security_type"] == "CURRENCY"
        qty, cost = decimal(p["quantity"]), decimal(p["book_native"])
        src.put(index, 14, "n.a." if is_cash or not qty else cost / qty, f"IF({ref(src.name,index,4)}=\"CURRENCY\";\"n.a.\";IF({ref(src.name,index,8)}=0;\"n.a.\";{ref(src.name,index,10)}/{ref(src.name,index,8)}))", "money")
        src.put(index, 15, "n.a." if is_cash or cost <= 0 else decimal(p["unrealized_native"]) / cost, f"IF({ref(src.name,index,4)}=\"CURRENCY\";\"n.a.\";IF({ref(src.name,index,10)}<=0;\"n.a.\";{ref(src.name,index,13)}/{ref(src.name,index,10)}))", "percent")
        if unknown_cost:
            for col in (10,11,13,14,15):
                src.put(index,col,tr('message.4d8c1c5b4283'),style="warning")
            src.put(index,21,tr('message.b3b4484d27e7'))
        src.put(index, 16, market, f"IF({ref(src.name,index,5)}=\"USD\";{ref(src.name,index,12)}*{ref('rates_notes', 6, 3, True)};{ref(src.name,index,12)})", "calc_money")
        src.put(index, 17, market / r, f"{ref(src.name,index,16)}/{ref('rates_notes', 6, 3, True)}", "calc_money")
        src.put(index, 18, market / r * s, f"{ref(src.name,index,17)}*{ref('rates_notes', 7, 3, True)}", "calc_money")
        src.put(index, 19, market / account_total if account_total else "n.a.", f"IF({sum_formula(16,[(1,label(p))])}=0;\"n.a.\";{ref(src.name,index,16)}/{sum_formula(16,[(1,label(p))])})", "calc_percent")
        src.put(index, 20, market / total_cad if total_cad else "n.a.", f"IF(SUM({source_range(16)})=0;\"n.a.\";{ref(src.name,index,16)}/SUM({source_range(16)}))", "calc_percent")
    src.widths.update({1: 4.6, 2: 4.5, 4: 5.3, 7: 8, **{i: 4.0 for i in range(8, 21)}})
    if crypto is not None:
        src.widths[21] = 9

    settings = sheets['rates_notes']
    settings.header(5, [tr('message.2f3d55988b6d'), tr('message.b444207314e0'), tr('message.3d278ad9bb05'), tr('message.f4aa7ec53e29')])
    for row, key, text in [(6, "usd_cad", "CAD / USD"), (7, "usd_twd", "TWD / USD")]:
        settings.put(row, 2, text)
        settings.put(row, 3, decimal(fx[key]), style="input_rate")
        settings.put(row, 4, date.fromisoformat(fx[key + "_date"]), style="date")
        settings.put(row, 5, fx[key + "_source"])
    settings.section(10, tr('message.024c112e6f03'))
    notes = [
        tr('message.8e3264339d9a'),
        tr('message.22b83bc4ca0d'),
        tr('message.06226c7c70ba'),
        tr('message.56e9527824d6'),
        tr('message.81d0d0e27b00'),
        tr('message.d1991271c9d7'),
        tr('message.7d895d92c19a'),
        tr('message.a4e0dcfbd8b6'),
        tr('message.39769ad67965'),
    ]
    if crypto is not None:
        notes += [tr('message.95cb6def8ffb'),
                  tr('message.f94b7b4145c6'),
                  tr('message.a57fc750b529')]
    for row, text in enumerate(notes, 11):
        settings.put(row, 2, text, style="note")
    settings.section(23, tr('message.742fc76ab278'))
    for row, issue in enumerate(payload.get("issues", []), 24):
        account = next((a["label"] for a in payload.get("accounts", []) if a["account_id"] == issue.get("account_id")), "") if isinstance(issue, dict) else ""
        text = issue.get("message", str(issue)) if isinstance(issue, dict) else str(issue)
        settings.put(row, 2, f"{account} {text}".strip(), style="warning")
    provenance_row=25+len(payload.get("issues",[]))
    settings.put(provenance_row, 2, "Wealthsimple CSV")
    settings.put(provenance_row, 3, payload["source"]["filename"])
    settings.put(provenance_row+1, 2, tr('message.c0f29e6dd645'))
    settings.put(provenance_row+1, 3, len(positions), style="integer")
    settings.put(provenance_row+2, 2, tr('message.cac4005e9a6e'))
    settings.put(provenance_row+2, 3, len(securities), style="integer")
    settings.widths.update({2: 4.5, 3: 4.5, 4: 4, 5: 7})

    overview = sheets['overview']
    if meta.get("is_complete") is False:
        overview.put(5, 2, tr('message.859944864ef8'), style="warning")
    overview.header(6, [tr('message.b0f18aa763de'), tr('message.77733b4895c7'), tr('message.ba78cfe0d063'), tr('message.f3a7e3113505'), tr('message.e27d7ed41293'), tr('message.f3c0c439a1d2')])
    if crypto is not None:
        overview.put(6, 8, tr('message.9789c06c2966'), style="header")
    account_rows = {}
    for row, account in enumerate(accounts, 7):
        account_rows[account] = row
        overview.put(row, 2, account)
        matched = [p for p in positions if label(p) == account]
        for currency, col in [("CAD", 3), ("USD", 4)]:
            overview.put(row, col, sum((decimal(p["market_native"]) for p in matched if p["currency"] == currency and p["security_type"] != "CRYPTO"), Decimal(0)), sum_formula(12, [(1, account), (5, currency), (4, "<>CRYPTO")]), "money")
        for col in [5, 6, 7]:
            amount = sum((value_cad(p) for p in matched), Decimal(0))
            amount = amount if col == 5 else amount / r if col == 6 else amount / r * s
            overview.put(row, col, amount, sum_formula(col + 11, [(1, account)]), "money")
        if crypto is not None:
            overview.put(row, 8, sum((value_cad(p) for p in matched if p["security_type"] == "CRYPTO"), Decimal(0)),
                         sum_formula(16, [(1, account), (4, "CRYPTO")]), "money")
    total_row = len(accounts) + 7
    overview.put(total_row, 2, tr('message.c17b99db2744'), style="section")
    for col in range(3, 9 if crypto is not None else 8):
        amount = sum((decimal(overview.cells[row, col].value) for row in range(7, total_row)), Decimal(0))
        overview.put(total_row, col, amount, f"SUM({interval(overview.name,7,total_row-1,col)})", "total_money")
    overview.put(total_row + 2, 2, tr('message.9550424d4fb2'), style="note")
    if crypto is not None:
        overview.put(total_row + 3, 2, tr('message.c45c74ed2bcd'), style="note")
    cash_header = total_row + 6
    overview.section(cash_header - 1, tr('message.3a1fb32234bb'))
    overview.header(cash_header, [tr('message.b0f18aa763de'), tr('message.be860e5fe9e0'), tr('message.8df88af30db4'), tr('message.f3a7e3113505')])
    for row, account in enumerate(accounts, cash_header + 1):
        overview.put(row, 2, account)
        for currency, col in [("CAD", 3), ("USD", 4)]:
            matched = [p for p in cash if label(p) == account and p["currency"] == currency]
            overview.put(row, col, sum((decimal(p["market_native"]) for p in matched), Decimal(0)), sum_formula(12, [(1, account), (5, currency), (4, "CURRENCY")]), "money")
        overview.put(row, 5, sum((value_cad(p) for p in cash if label(p) == account), Decimal(0)), sum_formula(16, [(1, account), (4, "CURRENCY")]), "money")
    findings_row = cash_header + len(accounts) + 4
    overview.section(findings_row, tr('message.6c08b72c3186'))
    for row, text in enumerate(payload.get("findings", []), findings_row + 1):
        overview.put(row, 2, text, style="note")
    updates=meta.get("source_updates")
    if updates:
        update_row=findings_row+len(payload.get("findings",[]))+3
        overview.section(update_row,tr('message.dcc0177c7744'))
        overview.header(update_row+1,[tr('message.c21db84c0653'),tr('message.3edfc760a520'),tr('message.ecbed83050d5')])
        update_labels={"provided":tr('message.ca68e9e63735'),"carried_forward":tr('message.58c03ac70438'),"not_available":tr('message.be4f923bcf9f')}
        overview.row(update_row+2,["Wealthsimple",update_labels[updates["wealthsimple"]["status"]],updates["wealthsimple"].get("holdings_as_of") or tr('message.c87ff8745498')])
        overview.row(update_row+3,["Bull Bitcoin",update_labels[updates["bullbitcoin"]["status"]],updates["bullbitcoin"].get("latest_completed_at") or tr('message.eeda3a69dd33')])
        overview.put(update_row+5,2,tr('message.139fb4b44eb1'),style="note")
    overview.widths.update({2: 5, **{i: 4.5 for i in range(3, 8)}})
    if crypto is not None:
        overview.widths[8] = 5.5

    def position_table(sheet, selected, start, title):
        sheet.section(start, title)
        sheet.header(start + 1, [tr('message.b0f18aa763de'), tr('message.4f45fc8d4113'), tr('message.26c1c5b41973'), tr('message.be547beabfb6'), tr('message.9681b050ef05'), tr('message.ec9554ab6f4f'), tr('message.ff68c70ea858'), tr('message.6eb5191e200e'), tr('message.6c39883a2a1e'), tr('message.f3a7e3113505'), tr('message.5ce2c9b6bad4')])
        for row, p in enumerate(selected, start + 2):
            source_row = source_rows[id(p)]
            for col, source_col in enumerate([1, 3, 5, 8, 14, 10, 12, 13, 15, 16, 20], 2):
                cell = src.cells[source_row, source_col]
                sheet.put(row, col, cell.value, ref(src.name, source_row, source_col), "percent" if col in (10, 12) else "quantity" if col == 5 else "money" if col >= 6 else "body")
        last = start + 1 + len(selected)
        row = last + 1
        for currency in sorted({p["currency"] for p in selected}):
            matched = [p for p in selected if p["currency"] == currency]
            sheet.put(row, 2, tr('message.22aa6dc44bb2', value0=currency), style="section")
            sheet.put(row, 4, currency)
            for col, key in [(7, "book_native"), (8, "market_native"), (9, "unrealized_native")]:
                value = sum((decimal(p[key]) for p in matched), Decimal(0))
                formula = f"SUMIFS({interval(sheet.name,start+2,last,col)};{interval(sheet.name,start+2,last,4)};{ref(sheet.name,row,4)})"
                sheet.put(row, col, value, formula, "total_money")
            cost, pl = sheet.cells[row, 7].value, sheet.cells[row, 9].value
            sheet.put(row, 10, pl / cost if cost > 0 else "n.a.", f"IF({ref(sheet.name,row,7)}<=0;\"n.a.\";{ref(sheet.name,row,9)}/{ref(sheet.name,row,7)})", "percent")
            sheet.put(row, 11, sum((value_cad(p) for p in matched), Decimal(0)), f"SUMIFS({interval(sheet.name,start+2,last,11)};{interval(sheet.name,start+2,last,4)};{ref(sheet.name,row,4)})", "total_money")
            row += 1
        return row + 3

    currency_sheet, account_sheet = sheets['currency_holdings'], sheets['account_holdings']
    cursor = 6
    for currency in ["CAD", "USD"]:
        selected = [p for p in native_securities if p["currency"] == currency]
        if selected:
            cursor = position_table(currency_sheet, selected, cursor, tr('message.4adeeea3a377', value0=currency))
    currency_sheet.put(cursor, 2, tr('message.11d7aa6b6c09'), style="note")
    if crypto is not None:
        currency_sheet.put(cursor + 1, 2, tr('message.a9d174b35bfc'), style="note")
    cursor = 6
    for account in accounts:
        selected = [p for p in native_securities if label(p) == account]
        if selected:
            cursor = position_table(account_sheet, selected, cursor, tr('message.8247c741a246', value0=account))
    account_sheet.put(cursor, 2, tr('message.483e06512648'), style="note")
    if crypto is not None:
        account_sheet.put(cursor + 1, 2, tr('message.3f7afa0e3c0a'), style="note")
    for sheet in [currency_sheet, account_sheet]:
        sheet.frozen_rows, sheet.frozen_columns = 7, 3
        sheet.widths.update({2: 5, **{i: 4.1 for i in range(3, 13)}})

    groups = {}
    for p in securities:
        key = (p["symbol"], p.get("mic", ""), p["currency"])
        groups.setdefault(key, []).append(p)
    security_groups = sorted(groups.items(), key=lambda item: sum((value_cad(p) for p in item[1]), Decimal(0)), reverse=True)
    analysis = sheets['portfolio_analysis']
    analysis.header(6, [tr('message.4f45fc8d4113'), tr('message.26c1c5b41973'), tr('message.be547beabfb6'), tr('message.9681b050ef05'), tr('message.ec9554ab6f4f'), tr('message.ff68c70ea858'), tr('message.6eb5191e200e'), tr('message.6c39883a2a1e'), tr('message.f3a7e3113505'), tr('message.5ce2c9b6bad4'), "MIC", tr('message.286fbbd69f80')])
    if crypto is not None:
        analysis.put(6, 3, tr('message.701122b9f776'), style="header")
        analysis.put(6, 6, tr('message.166726d7943d'), style="header")
        analysis.put(6, 7, tr('message.bee6258e1218'), style="header")
    security_last = 6 + len(security_groups)
    for row, ((symbol, mic, currency), matched) in enumerate(security_groups, 7):
        analysis.put(row, 2, symbol)
        is_crypto = any(p["security_type"] == "CRYPTO" for p in matched)
        analysis.put(row, 3, tr('message.130e22fe4cbf', value0=currency) if is_crypto else currency)
        analysis.put(row, 12, mic)
        criteria = [(3, symbol), (6, mic), (5, currency)]
        for col, source_col, key in [(4, 8, "quantity"), (6, 10, "book_native"), (7, 12, "market_native"), (8, 13, "unrealized_native")]:
            analysis.put(row, col, sum((decimal(p[key]) for p in matched), Decimal(0)), sum_formula(source_col, criteria), "btc_quantity" if col == 4 and is_crypto else "quantity" if col == 4 else "money")
        qty, cost, pl = (analysis.cells[row, c].value for c in [4, 6, 8])
        analysis.put(row, 5, cost / qty if qty else "n.a.", f"IF({ref(analysis.name,row,4)}=0;\"n.a.\";{ref(analysis.name,row,6)}/{ref(analysis.name,row,4)})", "money")
        analysis.put(row, 9, pl / cost if cost > 0 else "n.a.", f"IF({ref(analysis.name,row,6)}<=0;\"n.a.\";{ref(analysis.name,row,8)}/{ref(analysis.name,row,6)})", "percent")
        if any(p.get("cost_status") in ("partial_unknown_opening","unknown_wallet_cost") for p in matched):
            for col in (5,6,8,9):
                analysis.put(row,col,tr('message.4d8c1c5b4283'),style="warning")
        amount = sum((value_cad(p) for p in matched), Decimal(0))
        analysis.put(row, 10, amount, sum_formula(16, criteria), "money")
        analysis.put(row, 11, amount / total_cad if total_cad else "n.a.", f'IF({ref(overview.name,total_row,5,True)}=0;"n.a.";{ref(analysis.name,row,10)}/{ref(overview.name,total_row,5,True)})', "percent")
        rank = row - 6
        formula = f"COUNTIFS({interval(analysis.name,7,security_last,10)};\">\"&{ref(analysis.name,row,10)})+COUNTIFS({interval(analysis.name,7,row,10)};{ref(analysis.name,row,10)})"
        analysis.put(row, 13, rank, formula, "integer")
    concentration = security_last + 3
    analysis.section(concentration, tr('message.08551f98eb01'))
    analysis.header(concentration + 1, [tr('message.27a74cb7bf44'), tr('message.f3a7e3113505'), tr('message.cad76c9679d5')])
    for offset, count in enumerate([1, 3, 5], 2):
        row = concentration + offset
        amount = sum((sum((value_cad(p) for p in ps), Decimal(0)) for _, ps in security_groups[:count]), Decimal(0))
        formula = "+".join(f"LARGE({interval(analysis.name,7,security_last,10)};{i})" for i in range(1, min(count, len(security_groups)) + 1)) or "0"
        analysis.put(row, 2, tr('message.dad270ef4307', value0=count))
        analysis.put(row, 3, amount, formula, "money")
        analysis.put(row, 4, amount / total_cad if total_cad else "n.a.", f'IF({ref(overview.name,total_row,5,True)}=0;"n.a.";{ref(analysis.name,row,3)}/{ref(overview.name,total_row,5,True)})', "percent")
    matrix_header = concentration + 8
    analysis.section(matrix_header - 1, tr('message.bc4fcb95b20c'))
    analysis.header(matrix_header, [tr('message.360646a6014f'), *accounts, tr('message.01fc1c55333c')])
    for row, ((symbol, mic, currency), matched) in enumerate(security_groups, matrix_header + 1):
        analysis.put(row, 2, symbol)
        for col, account in enumerate(accounts, 3):
            amount = sum((value_cad(p) for p in matched if label(p) == account), Decimal(0))
            analysis.put(row, col, amount, sum_formula(16, [(1, account), (3, symbol), (6, mic), (5, currency)]), "money")
        analysis.put(row, len(accounts) + 3, sum((value_cad(p) for p in matched), Decimal(0)), f"SUM([{address(analysis.name,row,3,True)}:{address(analysis.name,row,len(accounts)+2,True)}])", "money")
    weight_header = matrix_header + len(security_groups) + 4
    analysis.section(weight_header - 1, tr('message.304024e0284a'))
    analysis.header(weight_header, [tr('message.360646a6014f'), *accounts])
    for offset, ((symbol, _, _), matched) in enumerate(security_groups, 1):
        row = weight_header + offset
        analysis.put(row, 2, symbol)
        for col, account in enumerate(accounts, 3):
            account_total = sum((value_cad(p) for p in positions if label(p) == account), Decimal(0))
            ratio = sum((value_cad(p) for p in matched if label(p) == account), Decimal(0)) / account_total if account_total else "n.a."
            formula = f"IF({ref(overview.name,account_rows[account],5)}=0;\"n.a.\";{ref(analysis.name,matrix_header+offset,col)}/{ref(overview.name,account_rows[account],5)})"
            analysis.put(row, col, ratio, formula, "heatmap")
    type_header = weight_header + len(security_groups) + 4
    analysis.section(type_header - 1, tr('message.84baa6c2459f'))
    analysis.header(type_header, [tr('message.72dd6bd5abe8'), tr('message.f3a7e3113505'), tr('message.cad76c9679d5')])
    type_groups = [(tr('message.a76c4924753a'), ["EQUITY"]), ("ETF", ["ETF", "EXCHANGE_TRADED_FUND"]), (tr('message.abfcd7a55281'), ["CURRENCY"])]
    if crypto is not None:
        type_groups.append((tr('message.926c68df9c1e'), ["CRYPTO"]))
    instrument_total = Decimal(0)
    for row, (text, codes) in enumerate(type_groups, type_header + 1):
        amount = sum((value_cad(p) for p in positions if p["security_type"] in codes), Decimal(0))
        instrument_total += amount
        analysis.put(row, 2, text)
        analysis.put(row, 3, amount, "+".join(sum_formula(16, [(4, code)]) for code in codes), "money")
        analysis.put(row, 4, amount / total_cad if total_cad else "n.a.", f'IF({ref(overview.name,total_row,5,True)}=0;"n.a.";{ref(analysis.name,row,3)}/{ref(overview.name,total_row,5,True)})', "small_percent" if text == tr('message.abfcd7a55281') else "percent")
    if abs(instrument_total - total_cad) > Decimal("0.01"):
        raise ValueError("Unmapped instrument type or inconsistent valuation")
    if payload.get("lookthrough"):
        from .lookthrough_reports import workbook_table
        workbook_table(payload,analysis,sum_formula,overview,total_row,ref,interval)
    analysis.frozen_rows, analysis.frozen_columns = 6, 3
    analysis.widths.update({**{c: 4 for c in range(2, 14)}, 2: 7 if payload.get("lookthrough") else 4.5})

    if crypto is not None:
        btc_sheet = sheets['btc_tracking']
        from .wallet_reports import build_sheet, quantity_basis_label
        build_sheet(sheets['btc_reconciliation'], crypto)
        btc_meta = crypto.get("meta", {})
        valuation = crypto.get("valuation", {})
        assumptions = crypto.get("assumptions", {})
        btc_sheet.put(5, 2, tr('message.a0c5682d7643'), style="warning")
        btc_sheet.section(6, tr('message.6e46b75e0118'))
        btc_sheet.header(7, [tr('message.0943908e8c16'), tr('message.b444207314e0'), tr('message.21afece3bf23')])
        btc_qty = sum((decimal(p["quantity"]) for p in crypto_positions), Decimal(0))
        btc_market = sum((value_cad(p) for p in crypto_positions), Decimal(0))
        from .btc_performance import btc_cost_estimate
        estimate = btc_cost_estimate(crypto)
        summary = [
            (8, tr('message.1a00a0ad55fc'), btc_qty, sum_formula(8, [(4, "CRYPTO")]), "btc_quantity", tr('message.f0612e1372e7')),
            (9, tr('message.7734b46775ae'), estimate["estimated_cost_cad"],
             f'{ref(btc_sheet.name,8,3)}*{ref(btc_sheet.name,31,3)}', "money", tr('message.a431734adf1c')),
            (10, tr('message.34a169f79ab2'), number(valuation.get("unit_price_cad")), None, "money", "CAD / BTC"),
            (11, tr('message.34a169f79ab2'), number(valuation.get("unit_price_usd")), None, "money", "USD / BTC"),
            (12, tr('message.fa02f26c5685'), btc_market, sum_formula(16, [(4, "CRYPTO")]), "money", "CAD"),
            (13, tr('message.fa02f26c5685'), btc_market / r, sum_formula(17, [(4, "CRYPTO")]), "money", tr('message.e27d7ed41293')),
            (14, tr('message.fa02f26c5685'), btc_market / r * s, sum_formula(18, [(4, "CRYPTO")]), "money", tr('message.f3c0c439a1d2')),
            (15, tr('message.e99cfafa5321'), estimate["estimated_gain_cad"],
             f'{ref(btc_sheet.name,12,3)}-{ref(btc_sheet.name,9,3)}', "money", tr('message.c6ad5f4d642c')),
            (16, tr('message.19cbcfc5d23f'), estimate["estimated_return"] if estimate["estimated_return"] is not None else "n.a.",
             f'IF({ref(btc_sheet.name,9,3)}<=0;"n.a.";{ref(btc_sheet.name,15,3)}/{ref(btc_sheet.name,9,3)})', "calc_exposure_percent", tr('message.99d3df010adc')),
            (17, tr('message.569651d9d044'), number(crypto.get("total_funding_cad")), None, "money", tr('message.c0f93f09dc91')),
            (18, tr('message.687923f71c66'), number(crypto.get("total_buy_cost_cad")), None, "money", tr('message.32a73e0e71d2')),
            (19, tr('message.c27950326ce8'), number(crypto.get("cash_cad")), None, "money", tr('message.8f5b2939e88d')),
        ]
        summary=[(row,text,estimate["unavailable_reason"],None,"warning",tr('message.0bf2ab5fcef9') if estimate["status"]=="proxy_disabled" else tr('message.2d947f0ec655'))
                 if row in (9,15,16) and (estimate["estimated_cost_cad"] is None if row==9 else estimate["estimated_gain_cad"] is None)
                 else (row,text,value,formula,style,units) for row,text,value,formula,style,units in summary]
        for row, text, value, formula, style, units in summary:
            btc_sheet.put(row, 2, text, style="wrapped_body" if row in (9,15,16) else "body")
            btc_sheet.put(row, 3, value if value is not None else "n.a.", formula, style)
            btc_sheet.put(row, 4, units, style="wrapped_body" if row in (9,15,16) else "body")
        btc_sheet.put(20, 2, tr('message.df43ef9c1f95'))
        btc_sheet.put(20, 3, tr('message.d91a071e21db') if estimate["status"]=="proxy_disabled" else tr('message.11bb3ef00853'), style="wrapped_body")
        btc_sheet.put(20, 4, tr('message.0f81e7cb985c') if estimate["status"]=="proxy_disabled" else tr('message.07a1a9a6b236'), style="wrapped_body")
        btc_sheet.put(21, 2, tr('message.e311c5dc3d4a'))
        btc_sheet.put(21, 3, quantity_basis_label(crypto), style="wrapped_body")
        btc_sheet.put(21, 4, tr('message.d86f3e3929c9'), style="wrapped_body")
        btc_sheet.put(22, 2, tr('message.74a52228edd4'))
        btc_sheet.put(22, 3, number(btc_meta.get("completed_order_count")), style="integer")
        btc_sheet.put(23, 2, tr('message.696d0c1f2ff8'))
        btc_sheet.put(23, 3, f"{btc_meta.get('pending_order_count', 0)} / {btc_meta.get('excluded_after_cutoff_count', 0)}")
        btc_sheet.put(23, 4, tr('message.f09c5ad7f59d'))
        btc_sheet.put(24, 2, tr('message.9a09d6355113'))
        btc_sheet.put(24, 3, tr('message.dcfbac959fa5'), style="wrapped_body")
        btc_sheet.put(24, 4, tr('message.a516220595db'), style="wrapped_body")
        btc_sheet.section(25, tr('message.7acd6bc65bdc'))
        btc_sheet.header(26, [tr('message.28a8206db458'), tr('message.e00fbcb9d3ae'), tr('message.6d3c9336bf4c')])
        for row, key, name in [(27, "qty_btc", "BTC"), (28, "qty_lbtc", "LBTC")]:
            btc_sheet.put(row, 2, name)
            btc_sheet.put(row, 3, number(crypto.get(key)) if crypto.get(key) is not None else "n.a.", style="btc_quantity")
            btc_sheet.put(row, 4, tr('message.ea547b86f4ca'))
        delivered = decimal(crypto.get("qty_btc")) + decimal(crypto.get("qty_lbtc"))
        btc_sheet.put(29, 2, tr('message.9b1846494b90'))
        btc_sheet.put(29, 3, delivered, f"SUM({interval(btc_sheet.name,27,28,3)})", "btc_quantity")
        btc_sheet.put(31, 2, tr('message.1fef8f9a0f6a'))
        btc_sheet.put(31, 3, estimate["average_price_cad_per_btc"] if estimate["average_price_cad_per_btc"] is not None else "n.a.",
                      f'IF({ref(btc_sheet.name,29,3)}<=0;"n.a.";{ref(btc_sheet.name,18,3)}/{ref(btc_sheet.name,29,3)})', "money")
        btc_sheet.put(31, 4, tr('message.acd0e0e1932f'))
        btc_sheet.put(29, 4, tr('message.0097370a63cc'))
        if crypto.get("opening"):
            btc_sheet.put(30,2,tr('message.babe6716fe98'))
            btc_sheet.put(30,3,number(crypto["opening_btc_equivalent_qty"]),style="btc_quantity")
            btc_sheet.put(30,4,tr('message.c3762c03d697'))
        opening = crypto.get("opening")
        if opening:
            btc_sheet.section(32, tr('message.c69fa6f20c16'))
            btc_sheet.header(33, [tr('message.240466eb61c6'), tr('message.18426a6cf929'), tr('message.46eb93f2df6a')])
            btc_sheet.put(34, 2, tr('message.d4ba77b9e0d9'))
            btc_sheet.put(34, 3, number(opening["opening_btc_equivalent_qty"]), style="btc_quantity")
            btc_sheet.put(34, 4, tr('message.185906961361'))
            for row, label, reason in [(35, tr('message.7ef625cc2d31'), tr('message.dc10dcd77bc5')),
                                       (36, tr('message.3405ec7c060e'), tr('message.220fe9608a20'))]:
                btc_sheet.put(row, 2, label)
                btc_sheet.put(row, 3, tr('message.756762e293f2'), style="warning")
                btc_sheet.put(row, 4, reason, style="wrapped_body")
            btc_sheet.put(38, 2, tr('message.822bcdc0887a'))
            btc_sheet.put(38, 3, opening["declared_on"])
            btc_sheet.put(39, 2, tr('message.3b1688ed8e7b'))
            btc_sheet.put(39, 3, tr('message.637e38909f5e'), style="wrapped_body")
        else:
            btc_sheet.section(32, tr('message.7b8c03d144b0'))
            btc_sheet.header(33, [tr('message.28f660534af5'), tr('message.4b5f14f5c30c'), tr('message.c2f5d21d8018')])
            for row, key, units in [(34, "btc", "BTC"), (35, "lbtc", "LBTC"), (36, "cad", "CAD")]:
                btc_sheet.put(row, 2, tr('message.ae5ed7a74df2') + units)
                btc_sheet.put(row, 3, number(assumptions.get(key)) if assumptions.get(key) is not None else tr('message.756762e293f2'), style="money" if key == "cad" else "btc_quantity")
                btc_sheet.put(row, 4, units)
            btc_sheet.put(38, 2, tr('message.883bb96a23a8'))
            btc_sheet.put(38, 3, assumptions.get("basis", tr('message.756762e293f2')))
            btc_sheet.put(39, 2, tr('message.75e11a75da00'))
            btc_sheet.put(39, 3, assumptions.get("confirmed_by", tr('message.756762e293f2')))
        from .crypto import monthly_purchase_price
        btc_sheet.widths[10] = 6
        btc_sheet.section(42, tr('message.ff1534df28cf'))
        btc_sheet.header(43, [tr('message.a27822d13506'), tr('message.aa9c4132cb80'), tr('message.1bda037fe7a9'), tr('message.efea72f42820'), tr('message.5398f44f163b'), tr('message.dc07f42846a8'), tr('message.68a158f052a7'), tr('message.2185697144d0'), tr('message.a4deecddf23b')])
        monthly = crypto.get("monthly", [])
        for row, item in enumerate(monthly, 44):
            values = [item.get("month", ""), *[number(item.get(key)) if item.get(key) is not None else "n.a." for key in
                      ["contribution_cad", "buy_cost_cad", "buy_qty_btc", "buy_qty_lbtc", "buy_btc_equivalent_qty", "cumulative_btc_equivalent_qty", "cash_cad"]]]
            for col, value in enumerate(values, 2):
                btc_sheet.put(row, col, value, style="btc_quantity" if col in [5, 6, 7, 8] else "money" if col in [3, 4, 9] else "body")
            price = monthly_purchase_price(item)
            formula = f'IF({ref(btc_sheet.name,row,7)}=0;"n.a.";{ref(btc_sheet.name,row,4)}/{ref(btc_sheet.name,row,7)})'
            btc_sheet.put(row,10,price if price is not None else "n.a.",formula,style="money")
        btc_sheet.put(45+len(monthly),2,tr('message.25204bdfe362'),style="note")
        audit_row = 47 + len(monthly)
        btc_sheet.put(audit_row, 2, tr('message.009c907f13ae'), style="warning")
        btc_sheet.section(audit_row + 3, tr('message.2d9cb13887b8'))
        price = valuation.get("price", {})
        for row, text, key in [(audit_row+4, tr('message.7568757440fe'), "provider"), (audit_row+5, tr('message.320644da1eae'), "pair"),
                               (audit_row+6, tr('message.8dfe61d211da'), "as_of"), (audit_row+7, tr('message.63d4edae1574'), "candle_start"),
                               (audit_row+8, tr('message.66d959b6a755'), "candle_end"), (audit_row+9, tr('message.fc32438a95e3'), "source_url"),
                               (audit_row+10, tr('message.05d3aa2014b2'), "evidence_sha256")]:
            btc_sheet.put(row, 2, text)
            btc_sheet.put(row, 3, price.get(key, tr('message.756762e293f2')))
        btc_sheet.section(audit_row + 13, tr('message.32913ca8d6d1'))
        btc_sheet.header(audit_row + 14, [tr('message.24cb4ea0990b'), tr('message.9ca6ca83293d'), tr('message.2aaaf732fe1a'), "SHA-256"])
        sources = crypto.get("source", {}).get("sources", [])
        for row, item in enumerate(sources, audit_row + 15):
            btc_sheet.row(row, [item.get("filename", ""), number(item.get("row_count")), tr('message.dd55c6c25912') if item.get("integrity_ok") else tr('message.97a0616a06d8'), item.get("sha256", "")])
        issues_row = audit_row + len(sources) + 18
        for row, issue in enumerate(crypto.get("issues", []), issues_row):
            btc_sheet.put(row, 2, issue.get("message", str(issue)) if isinstance(issue, dict) else str(issue), style="warning")
        if crypto.get("opening"):
            opening=crypto["opening"]
            row = issues_row + len(crypto.get("issues", [])) + 2
            btc_sheet.section(row,tr('message.001a7a1ea29b'))
            for offset,(text,value) in enumerate([
                (tr('message.933eda607c9d'),opening["reported_total_btc_equivalent"]),
                (tr('message.f12015d05a97'),opening["reference_purchased_btc_equivalent"]),
                (tr('message.25c7f51c170f'),opening["opening_btc_equivalent_qty"]),
                (tr('message.822bcdc0887a'),opening["declared_on"]),(tr('message.f84b8d767b42'),opening["reference_as_of"]),
                (tr('message.467bf4dadd8a'),tr('message.7f2cbb0eaed3')),
                *[(tr('message.61b11d0b8add') if i else tr('message.5e21185d523c'), opening["basis"][i:i+32]) for i in range(0,len(opening["basis"]),32)],
                (tr('message.a9495a8f3085'),opening["source_sha256"])],2):
                btc_sheet.put(row+offset,2,text)
                btc_sheet.put(row+offset,3,value,style="wrapped_body" if text.startswith(tr('message.5e21185d523c')) else "body")
        btc_sheet.widths.update({2: 7, 3: 5, 4: 6, **{col: 5 for col in range(5, 10)}})
        btc_sheet.frozen_rows, btc_sheet.frozen_columns = 7, 2

    chart_sheet = sheets['charts']
    chart_sheet.put(5, 2, tr('message.d5c3ec981594'), style="note")
    chart_sheet.widths.update({col: 2.8 for col in range(2, 13)})
    chart_sheet.frozen_rows = 5
    chart_row = 7
    for index, image in enumerate(images, 1):
        chart_sheet.section(chart_row, CHART_TITLES[image.key])
        anchor_row = chart_row + 2
        width = Decimal("28")
        height = width * image.pixel_height / image.pixel_width
        # Round only the physical frame size; preserve all financial values.
        height = height.quantize(Decimal("0.0001"))
        whole_rows = int(height // ROW_HEIGHT_CM)
        remainder = height - whole_rows * ROW_HEIGHT_CM
        chart_sheet.put(anchor_row, 2)
        chart_sheet.cells[anchor_row, 2].frames.append(ImageFrame(
            image, width, height, address(chart_sheet.name, anchor_row + whole_rows, 12), remainder, index))
        # Materialize the entire reserved rectangle so every reader has room.
        bottom_row = anchor_row + math.ceil(height / ROW_HEIGHT_CM)
        chart_sheet.put(bottom_row, 12)
        chart_row = bottom_row + 3
    chart_sheet.section(chart_row, tr('message.a4d681a05742'))
    chart_sheet.header(chart_row + 2, [tr('message.360646a6014f'), *accounts])
    for offset in range(1, len(security_groups) + 1):
        for col in range(2, len(accounts) + 3):
            source_cell = analysis.cells[weight_header + offset, col]
            chart_sheet.put(chart_row + 2 + offset, col, source_cell.value,
                            ref(analysis.name, weight_header + offset, col), source_cell.style)
    chart_sheet.put(chart_row + len(security_groups) + 5, 2,
                    tr('message.bb8be487369d'), style="note")

    history = sheets['history']
    if meta.get("missing_official_months"):
        history.put(5,2,tr('message.caefde9cb3fd')+"、".join(meta["missing_official_months"])+tr('message.174ecb3a41e4'),style="warning")
    history.header(6,[tr('message.9666008a620d'),tr('message.2d2d6dd587de'),tr('message.f3a7e3113505'),tr('message.e27d7ed41293'),tr('message.f3c0c439a1d2'),tr('message.3c8fba0c82f7'),tr('message.665fa75fabe9')])
    data_status={"sources_updated":tr('message.2a5baf64fc76'),"carried_source":tr('message.63b22047b188'),"mixed_dates":tr('message.53db5fd18d97'),"btc_only":tr('message.493b1be16178')}
    for row, item in enumerate(payload.get("history",[]),7):
        totals = item["totals"]
        kind = {"baseline":tr('message.488eb1e0cca7'),"monthly":tr('message.fce49dc5bfe1'),"interim":tr('message.783839e13af6')}.get(item["kind"],item["kind"])
        values = [date.fromisoformat(item["as_of"][:10]),kind,*[decimal(totals[key]) for key in ["total_cad","total_usd","total_twd"]],len(item["accounts"]),data_status.get(item.get("data_status"),tr('message.088b27d0ed00') if item["is_complete"] else tr('message.abf099167903'))]
        for col,value in enumerate(values,2):
            history.put(row,col,value,style="date" if col==2 else "money" if col in [4,5,6] else "body")
    hrow = 10 + len(payload.get("history",[]))
    history.section(hrow,tr('message.dd261a20e5d4'))
    for row,text in enumerate([
        tr('message.2d7b0224c6da') if len(payload.get("history",[]))<2 else tr('message.9f53f9fd81b3'),
        tr('message.b740b4b016b4'),
        tr('message.91a7b2c6533e'),
        tr('message.bf5447a54058'),
    ],hrow+1): history.put(row,2,text,style="note")
    history.section(hrow+7,tr('message.fd15f72bf768'))
    history.header(hrow+8,[tr('message.cc0784b2a461'),tr('message.1f62bdddcd36'),tr('message.a9629476f9cc'),tr('message.429592e3ce95'),tr('message.466abe576898'),"Modified Dietz","XIRR"])
    periods = payload.get("periods",[])
    if not periods:
        history.row(hrow+9,[tr('message.573d8ca1b9b4'),tr('message.27d6cd1304d1'),"n.a.","n.a.","n.a.","n.a.","n.a."])
    status_labels = {"not_provided":tr('message.756762e293f2'), "partial":tr('message.7645536d5a03'), "complete":tr('message.088b27d0ed00'), "no_external":tr('message.b37744f7845b'), "incomplete_snapshot_or_scope":tr('message.452bfd36171a'), "unmatched_transfers":tr('message.180f509eb8c7'), "no_external_conflicts_with_flows":tr('message.4147bae47e96')}
    account_labels = {item["account_id"]:item["label"] for item in payload.get("accounts",[])}
    for row,item in enumerate(periods,hrow+9):
        scope = tr('message.462631f9093e') if item.get("scope")=="portfolio" else account_labels.get(item.get("account_id"),tr('message.b0f18aa763de'))
        period_label = tr('message.81c5df871bb9', value0=item.get('start_as_of', item.get('start_date', ''))[:10], value1=item.get('end_as_of', item.get('end_date', ''))[:10], value2=scope)
        opening, closing = number(item.get("opening_cad")), number(item.get("closing_cad"))
        change = closing - opening if opening is not None and closing is not None else "n.a."
        status = item.get("status","not_provided")
        values=[item.get("label",period_label),status_labels.get(status,status),change,*[number(item.get(k)) if item.get(k) is not None else "n.a." for k in ["net_flow_cad","investment_gain_cad","modified_dietz","xirr"]]]
        for col,value in enumerate(values,2): history.put(row,col,value,style="percent" if col in [7,8] else "money" if col in [4,5,6] else "body")
    history.frozen_rows=6
    flows = sheets['cash_flows']
    flows.header(6,[tr('message.70d0c1b33626'),tr('message.b0f18aa763de'),tr('message.1588dd8c9e73'),tr('message.26c1c5b41973'),tr('message.28f9075eda15'),tr('message.f3a7e3113505'),tr('message.e0492d386d84'),tr('message.85914d54439f')])
    flow_rows=payload.get("cash_flows",[])
    for row,item in enumerate(flow_rows,7):
        flow_type = item.get("flow_type",item.get("type",""))
        flow_label = {"deposit":tr('message.3d5fbc3d2216'),"withdrawal":tr('message.306738277341'),"transfer_in":tr('message.d531216f273e'),"transfer_out":tr('message.6ee505d2f0f9'),"income":tr('message.117d8f914d8e'),"fee":tr('message.014f66a7e607'),"internal":tr('message.d58e963c38e2')}.get(flow_type,flow_type)
        values=[date.fromisoformat(item.get("date",item.get("flow_date"))[:10]),item.get("account_label",item.get("account_type","")),flow_label,item.get("currency",""),number(item.get("amount",item.get("amount_native"))),number(item.get("amount_cad",item.get("cad_value"))),item.get("transfer_id",item.get("pair_id","")),item.get("note","")]
        for col,value in enumerate(values,2): flows.put(row,col,value,style="date" if col==2 else "money" if col in [6,7] else "body")
    if not flow_rows: flows.put(8,2,tr('message.03aa8976fa28'),style="warning")
    flows.section(max(13,len(flow_rows)+10),tr('message.9ca6fc1b9285'))
    flows.put(max(14,len(flow_rows)+11),2,tr('message.0e188eedcb57'),style="note")
    flows.put(max(15,len(flow_rows)+12),2,tr('message.b93d54730928'),style="note")
    flows.put(max(16,len(flow_rows)+13),2,tr('message.2f5bee7c7103'),style="note")
    flows.frozen_rows=6

    root = ET.Element(tag("office:document-content"),{tag("office:version"):"1.2","xmlns:of":OF})
    font_declarations(root)
    auto=element(root,"office:automatic-styles")
    common_styles(auto)
    column_styles={}
    for sheet in sheets.values():
        for col in range(1,max(sheet.extent()[1],12)+1):
            width=sheet.widths.get(col,0.5 if col==1 else 4)
            if width not in column_styles:
                name=f"col{len(column_styles)+1}"
                column_styles[width]=name
                add_style(auto,name,"table-column",style_table_column_properties={"style:column-width":f"{width}cm"})
    body=element(root,"office:body")
    spreadsheet=element(body,"office:spreadsheet")
    element(spreadsheet,"table:calculation-settings",{"table:automatic-find-labels":"false","table:use-regular-expressions":"false","table:use-wildcards":"true"})
    for sheet in sheets.values():
        table=element(spreadsheet,"table:table",{"table:name":sheet.name,"table:style-name":"table"})
        end_row,end_col=sheet.extent()
        end_col=max(end_col,12)
        for col in range(1,end_col+1):
            element(table,"table:table-column",{"table:style-name":column_styles[sheet.widths.get(col,0.5 if col==1 else 4)]})
        for row in range(1,end_row+1):
            header_row=any(sheet.cells.get((row,c),Cell()).style=="header" for c in range(1,end_col+1))
            node=element(table,"table:table-row",{"table:style-name":"row_header" if header_row else "row_tall" if any(sheet.cells.get((row,c),Cell()).style=="wrapped_body" for c in range(1,end_col+1)) else "row"})
            for col in range(1,end_col+1): cell_xml(node,sheet.cells.get((row,col),Cell()))
    styles=ET.Element(tag("office:document-styles"),{tag("office:version"):"1.2"})
    font_declarations(styles)
    common_styles(element(styles,"office:styles"))
    settings_root=ET.Element(tag("office:document-settings"),{tag("office:version"):"1.2"})
    configuration=element(settings_root,"office:settings")
    view=element(configuration,"config:config-item-set",{"config:name":"ooo:view-settings"})
    views=element(view,"config:config-item-map-indexed",{"config:name":"Views"})
    entry=element(views,"config:config-item-map-entry")
    element(entry,"config:config-item",{"config:name":"ActiveTable","config:type":"string"},sheet_title(names[0]))
    table_views=element(entry,"config:config-item-map-named",{"config:name":"Tables"})
    for sheet in sheets.values():
        entry=element(table_views,"config:config-item-map-entry",{"config:name":sheet.name})
        for key,type_,value in [("ShowGrid","boolean","false"),("HorizontalSplitMode","short",2 if sheet.frozen_columns else 0),("VerticalSplitMode","short",2 if sheet.frozen_rows else 0),("HorizontalSplitPosition","int",sheet.frozen_columns),("VerticalSplitPosition","int",sheet.frozen_rows),("ZoomValue","int",85)]:
            element(entry,"config:config-item",{"config:name":key,"config:type":type_},value)
    meta_root=ET.Element(tag("office:document-meta"),{tag("office:version"):"1.2"})
    metadata=element(meta_root,"office:meta")
    element(metadata,"meta:generator",text="Wealth Ledger portable ODS exporter")
    element(metadata,"meta:user-defined",{"meta:name":"report_locale","meta:value-type":"string"},current_context().locale)
    manifest=ET.Element(tag("manifest:manifest"),{tag("manifest:version"):"1.2"})
    element(manifest,"manifest:file-entry",{"manifest:full-path":"/","manifest:media-type":MIME,"manifest:version":"1.2"})
    files={"content.xml":xml_bytes(root),"styles.xml":xml_bytes(styles),"settings.xml":xml_bytes(settings_root),"meta.xml":xml_bytes(meta_root)}
    for name in files:
        element(manifest, "manifest:file-entry", {"manifest:full-path": name, "manifest:media-type": "text/xml"})
    for image in images:
        files[image.package_path] = image.data
        element(manifest, "manifest:file-entry", {"manifest:full-path": image.package_path,
                                                  "manifest:media-type": "image/png"})
    files[document_font_package()] = font_data
    files["Fonts/OFL.txt"] = font_license
    element(manifest, "manifest:file-entry", {"manifest:full-path": document_font_package(),
                                              "manifest:media-type": FONT_MEDIA_TYPE})
    element(manifest, "manifest:file-entry", {"manifest:full-path": "Fonts/OFL.txt",
                                              "manifest:media-type": "text/plain"})
    files["META-INF/manifest.xml"]=xml_bytes(manifest)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output_path,"w",compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("mimetype",MIME,compress_type=zipfile.ZIP_STORED)
        for name,data in files.items(): package.writestr(name,data)
    verify_workbook(output_path,total_cad)
    return {"path":str(output_path),"sheets":len(sheets),"native_charts":0,"embedded_charts":len(images),"heatmaps":2,"position_count":len(positions),"total_cad":str(total_cad),"chart_hashes":{image.key:hashlib.sha256(image.data).hexdigest() for image in images},"embedded_font":document_font_family(),"font_sha256":hashlib.sha256(font_data).hexdigest(),"runtime_dependencies":"Python standard library for ODS packaging; project matplotlib for chart rendering"}


@localized
def verify_workbook(path: Path, expected_cad=None) -> dict:
    """Validate packaging, formulas, totals, and self-contained image charts."""
    with zipfile.ZipFile(path) as package:
        if package.namelist()[0]!="mimetype" or package.getinfo("mimetype").compress_type!=zipfile.ZIP_STORED or package.read("mimetype").decode()!=MIME:
            raise ValueError("Invalid ODS package mimetype")
        roots={name:ET.fromstring(package.read(name)) for name in package.namelist() if name.endswith(".xml")}
        content=roots["content.xml"]
        tables=content.findall(".//table:table",NS)
        table_names={table.attrib[tag("table:name")] for table in tables}
        expected_sheets={sheet_title(name) for name in BASE_SHEETS}
        if tr('message.b73b53a54517') in table_names:
            expected_sheets.add(tr('message.b73b53a54517'))
        if tr('message.81a4766e262f') in table_names:
            expected_sheets.add(tr('message.81a4766e262f'))
        if table_names!=expected_sheets or len(tables)!=len(expected_sheets):
            raise ValueError("Missing or duplicated workbook sheets")
        declared_styles = {node.get(tag("style:name")) for name in ("content.xml","styles.xml")
                           for node in roots[name].findall(".//style:style",NS)}
        for node in content.iter():
            name = node.get(tag("table:style-name"))
            if name and name not in declared_styles:
                raise ValueError(f"Undefined workbook style: {name}")
        formulas=0
        for cell in content.findall(".//table:table-cell",NS):
            formula=cell.attrib.get(tag("table:formula"))
            if formula:
                formulas+=1
                if not formula.startswith("of:="): raise ValueError("Invalid formula namespace")
                if cell.attrib.get(tag("office:value-type")) not in {"float","string"}: raise ValueError("Missing formula cache")
                if any(error in cell.attrib.get(tag("office:string-value"),"") for error in ["#REF!","#DIV/0!","#VALUE!","#NAME?","#N/A"]): raise ValueError("Cached formula error")
        if any(name.startswith("Object ") for name in package.namelist()) or content.findall(".//draw:object",NS):
            raise ValueError("Unsupported native chart objects remain in workbook")
        manifest={entry.attrib[tag("manifest:full-path")]:entry.attrib[tag("manifest:media-type")]
                  for entry in roots["META-INF/manifest.xml"].findall("manifest:file-entry",NS)}
        if document_font_package() not in package.namelist() or manifest.get(document_font_package())!=FONT_MEDIA_TYPE:
            raise ValueError("Missing embedded document font or TrueType manifest entry")
        font_data=package.read(document_font_package())
        font_embedding_permissions(font_data)
        if manifest.get("Fonts/OFL.txt")!="text/plain" or b"SIL OPEN FONT LICENSE" not in package.read("Fonts/OFL.txt"):
            raise ValueError("Missing embedded font license")
        for name in ["content.xml","styles.xml"]:
            declarations=roots[name].find("office:font-face-decls",NS)
            if declarations is None:
                raise ValueError("Missing document font declarations")
            face=next((item for item in declarations.findall("style:font-face",NS)
                       if item.get(tag("style:name"))==document_font_family()),None)
            uri=None if face is None else face.find("svg:font-face-src/svg:font-face-uri",NS)
            if uri is None or uri.get(tag("xlink:href"))!=document_font_package() or uri.get(tag("xlink:type"))!="simple":
                raise ValueError("Document font does not reference the embedded package asset")
            format_node=uri.find("svg:font-face-format",NS)
            if format_node is None or format_node.get(tag("svg:string"))!="truetype":
                raise ValueError("Invalid embedded document font format")
            for text_properties in roots[name].findall(".//style:text-properties",NS):
                if text_properties.get(tag("style:font-name"))!=document_font_family() or text_properties.get(tag("style:font-name-asian"))!=document_font_family():
                    raise ValueError("Worksheet style lacks the embedded Latin or Asian font")
                if text_properties.get(tag("style:font-size-asian"))!=text_properties.get(tag("fo:font-size")):
                    raise ValueError("Worksheet style Asian font size is inconsistent")
        image_nodes=content.findall(".//draw:image",NS)
        image_paths=[]
        image_hashes={}
        for image_node in image_nodes:
            image_path=image_node.attrib.get(tag("xlink:href"),"")
            if image_path not in {f"Pictures/{key}.png" for key in CHART_TITLES}:
                raise ValueError("Chart image reference is not a supported embedded package path")
            if image_path not in package.namelist() or manifest.get(image_path)!="image/png":
                raise ValueError("Missing embedded chart image or PNG manifest entry")
            if image_node.attrib.get(tag("xlink:type"))!="simple" or image_node.attrib.get(tag("xlink:show"))!="embed":
                raise ValueError("Invalid embedded chart image link")
            data=package.read(image_path)
            png_dimensions(data)
            image_paths.append(image_path)
            image_hashes[Path(image_path).stem]=hashlib.sha256(data).hexdigest()
        if len(image_paths)!=len(set(image_paths)) or not all(f"Pictures/{key}.png" in image_paths for key in BASELINE_CHART_KEYS):
            raise ValueError("Incomplete or duplicated image chart set")
        if tr('message.b73b53a54517') in table_names and not all(f"Pictures/{key}.png" in image_paths for key in CRYPTO_CHART_KEYS):
            raise ValueError("Missing embedded bitcoin tracking charts")
        packaged_images={name for name in package.namelist() if name.startswith("Pictures/")}
        if packaged_images!=set(image_paths):
            raise ValueError("Unreferenced embedded chart image")
        overview=next(table for table in tables if table.attrib[tag("table:name")]==tr('message.c7abf421eeb9'))
        total=None
        for row in overview.findall("table:table-row",NS):
            cells=row.findall("table:table-cell",NS)
            if len(cells)>4 and cells[1].attrib.get(tag("office:string-value"))==tr('message.c17b99db2744'):
                total=Decimal(cells[4].attrib[tag("office:value")])
        if total is None or expected_cad is not None and abs(total-decimal(expected_cad))>Decimal("0.01"): raise ValueError("Saved workbook total failed")
        return {"sheets":len(tables),"charts":len(image_paths),"embedded_images":len(image_paths),
                "native_charts":0,"chart_mode":"embedded_png","chart_hashes":image_hashes,
                "embedded_font":document_font_family(),"font_sha256":hashlib.sha256(font_data).hexdigest(),
                "formula_cells":formulas,"total_cad":str(total)}


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description="Generate a portable ODS investment report")
    parser.add_argument("payload",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    print(json.dumps(build_workbook(json.loads(args.payload.read_text(encoding="utf-8")),args.output),ensure_ascii=False))
