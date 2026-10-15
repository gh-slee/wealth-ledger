#!/usr/bin/env python3
"""Generate README artwork exclusively from the approved offline synthetic demo."""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageOps, PngImagePlugin

PROJECT = Path(__file__).resolve().parents[1]
SYNTHETIC_INPUT_SHA256 = {
    "wealthsimple-holdings.csv": "e526cda804a2ec8ee119dbf2296b0efeaf9b1fa50e4b2478ceb4090a7e9fa192",
    "bull-orders.csv": "8c1473bf4f9620f6cca4cc727e87a78b2330928aa6add06c386881ae57cfa286",
    "btc-price.json": "d2e23324f337afed0ce89f66498230a7ef354d30013c2cc3b8f4f2e68678641f",
    "fx.json": "527af0fd8def5bcc0076703e54fab4eb82dc3950d4c2c754a21197afca9d1b4a",
}


def render(output: Path) -> dict:
    for name, expected in SYNTHETIC_INPUT_SHA256.items():
        if hashlib.sha256((PROJECT / "examples/data" / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Synthetic example changed; review its contents and hashes before generating public artwork")
    specification = importlib.util.spec_from_file_location("wealth_ledger_readme_demo", PROJECT / "examples/demo.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    font_path = PROJECT / "assets/fonts/NotoSansTC-Regular.ttf"
    font = lambda size: ImageFont.truetype(str(font_path), size)
    ink, muted, teal = "#18384B", "#536B7B", "#208C8A"
    canvas = Image.new("RGB", (1600, 1060), "#F1F5F7")
    draw = ImageDraw.Draw(canvas)
    draw.text((56, 34), "WEALTH LEDGER  /  REPORT PREVIEW", fill=muted, font=font(18))
    draw.text((56, 70), "Holdings, history, and the companies behind your ETFs.", fill=ink, font=font(35))
    draw.rounded_rectangle((1270, 30, 1544, 68), radius=16, fill="#FFF0D1")
    draw.text((1289, 35), "SYNTHETIC DATA ONLY", fill="#875C1B", font=font(18))
    with tempfile.TemporaryDirectory(prefix="wealth-ledger-readme-") as temporary:
        bundle = Path(temporary) / "demo"
        result = module.run_demo(bundle, "actual_only", locale="en-CA")
        if result["data_kind"] != "synthetic_offline_demo_only" or result["input_sha256"] != SYNTHETIC_INPUT_SHA256:
            raise ValueError("Public artwork must use the approved synthetic demonstration")
        payload = json.loads((bundle / "data.json").read_text(encoding="utf-8"))
        for index, currency in enumerate(("CAD", "USD", "TWD")):
            left = 56 + index * 504
            draw.rounded_rectangle((left, 143, left + 480, 266), radius=17, fill="white", outline="#DCE6EB")
            draw.text((left + 24, 160), f"PORTFOLIO VALUE  /  {currency}", fill=muted, font=font(16))
            draw.text((left + 24, 186), f"{Decimal(payload['totals']['total_' + currency.lower()]):,.2f}", fill=ink, font=font(43))
        draw.text((58, 278), "Same assets in three valuation currencies. Figures and reference prices are invented.", fill=muted, font=font(18))
        panels = [
            ("01_account_values", (56, 322, 788, 601)),
            ("13_sector_exposure", (56, 624, 788, 966)),
            ("12_company_exposure", (812, 322, 1544, 966)),
        ]
        for key, bounds in panels:
            left, top, right, bottom = bounds
            draw.rounded_rectangle(bounds, radius=18, fill="white", outline="#DCE6EB")
            with Image.open(bundle / "charts" / (key + ".png")) as image:
                scaled = ImageOps.contain(image.convert("RGB"), (right-left-32, bottom-top-32), Image.Resampling.LANCZOS)
                canvas.paste(scaled, (left+(right-left-scaled.width)//2, top+(bottom-top-scaled.height)//2))
        draw.text((58, 995), "ODS spreadsheets  /  Markdown  /  PDF  /  PNG charts", fill=teal, font=font(22))
        draw.text((58, 1026), "Generated offline from repository examples. No real portfolio or live issuer data is shown.", fill=muted, font=font(16))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Description", "Wealth Ledger offline synthetic demonstration; invented data only.")
    canvas.save(output, pnginfo=metadata, optimize=True)
    return {"output": str(output), "data_kind": "synthetic_offline_demo_only", "dimensions": list(canvas.size), "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "assets/readme/report-preview.png")
    args = parser.parse_args()
    try:
        result = render(args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
