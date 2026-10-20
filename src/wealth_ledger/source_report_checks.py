"""Independent semantic presentation checks for source-neutral report bundles."""
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from pypdf import PdfReader
from .i18n import sheet_title
from .source_presentation import label, financial_context
from .formatting import money
from .source_projection import _json
from .source_report import _security_id

NS={"t":"urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "o":"urn:oasis:names:tc:opendocument:xmlns:office:1.0"}


@financial_context
def validate_source_presentation(payload, output):
    """Cross-check source identity/amounts and unavailable fields in every format."""
    root=Path(output)
    md=(root/"report.md").read_text(encoding="utf-8")
    pdf="\n".join(page.extract_text() or "" for page in PdfReader(root/"report.pdf").pages)
    with zipfile.ZipFile(root/"portfolio.ods") as archive:
        xml=ET.fromstring(archive.read("content.xml"))
    sheets={sheet.get("{"+NS["t"]+"}name"):sheet for sheet in xml.findall(".//t:table",NS)}
    checks=0
    def require(value, message):
        nonlocal checks
        if not value:raise ValueError("Source report presentation check failed: "+message)
        checks+=1
    def cells(name,row):
        return sheets[sheet_title(name)].findall("t:table-row",NS)[row-1].findall("t:table-cell",NS)
    def numeric(cell,value,name):
        actual=cell.get("{"+NS["o"]+"}value")
        if value is None:
            require(actual is None and cell.get("{"+NS["t"]+"}formula") is None,name+" unknown became numeric/formula")
            require("".join(cell.itertext())==label("unknown"),name+" unknown not explicit")
        else:require(actual is not None and D(actual)==D(value),name+" amount differs")
    model=payload["source_projection"]
    require(hashlib.sha256(_json({k:v for k,v in model.items() if k!="projection_sha256"}).encode()).hexdigest()==model["projection_sha256"],"projection hash differs")
    require(payload["meta"]["full_portfolio_values"] is None and payload["periods"]==[],"incomplete scope gained full values/returns")
    normalized=lambda text:"".join(text.split())
    for text,name in ((md,"Markdown"),(pdf,"PDF"),("".join(xml.itertext()),"ODS")):
        require(normalized(label("scope_note")) in normalized(text),name+" omits subtotal boundary")
        require(normalized(label("no_performance")) in normalized(text),name+" omits performance boundary")
        edition_note=label("valuation_saved_note") if payload["meta"]["source_report_observation_id"] is not None else label("valuation_preview_note")
        require(normalized(edition_note) in normalized(text),name+" omits saved/preview distinction")
    for col,unit in ((5,"cad"),(6,"usd"),(7,"twd")):
        numeric(cells("overview",7)[col-1],payload["totals"]["total_"+unit],unit+" subtotal")
    records=payload["positions"]+payload["cash_rows"]
    original={(row["account_id"],row["source_id"]):row for row in model["positions"]}
    for index,row in enumerate(records,6):
        for col,key in ((6,"quantity"),(7,"price"),(8,"book_native"),(9,"book_cad"),(10,"market_native"),(11,"unrealized_native"),
                        (12,"market_cad"),(13,"market_usd"),(14,"market_twd"),(15,"avg_cost"),(16,"unrealized_pct")):
            numeric(cells("positions",index)[col-1],row[key],"position "+str(index)+" "+key)
        if row.get("source_id") is not None:
            source=original.get((row["account_id"],row["source_id"]))
            require(source is not None and row["security_id"]==_security_id(source["asset"]),"source identity lost")
            for key,source_key in (("quantity","quantity"),("book_native","cost_native"),("book_cad","cost_cad"),("market_native","market_native")):
                a,b=row[key],source[source_key]
                require(a is None and b is None or a is not None and b is not None and D(a)==D(b),"source "+key+" changed")
            require(row["observed_as_of"]==source["observed_as_of"],"source date refreshed")
        elif row["security_type"]=="CRYPTO":
            require(model["btc"]["quantity_btc"] is not None and D(row["quantity"])==D(model["btc"]["quantity_btc"]),"wallet quantity differs")
            require(row["book_native"] is None and row["unrealized_native"] is None,"actual BTC cost filled by proxy")
        else:
            expected=model["btc"]["legacy_cash_cad_by_account"].get(row["account_id"])
            require(expected is not None and D(expected)>=0 and D(expected)==D(row["market_native"]),"unproven cash value")
    # Reconcile observed conversions independently of ODS formulas/cached totals.
    for unit in ("CAD","USD","TWD"):
        total=payload["totals"]["total_"+unit.lower()]
        expected=D(0)
        for row in records:
            cad=D(row["market_native"])*(D(payload["fx"]["usd_cad"]) if row["currency"]=="USD" else D(1))
            converted=cad if unit=="CAD" else cad/D(payload["fx"]["usd_cad"])*(D(payload["fx"]["usd_twd"]) if unit=="TWD" else D(1))
            require(abs(D(row["market_"+unit.lower()])-converted)<D("1e-60"),unit+" conversion differs")
            expected+=converted
        if total is not None:
            require(abs(D(total)-expected)<D("1e-60"),unit+" observed subtotal differs")
            for text,name in ((md,"Markdown"),(pdf,"PDF")):
                require(normalized(money(total)) in normalized(text),name+" omits "+unit+" subtotal")
    audit=json.loads((root/"source-valuation-audit.json").read_text(encoding="utf-8"))
    require(audit["quantity_cost_scope"]==payload["source_crypto"],"BTC audit differs")
    require(audit["wallet"]==model["wallet"],"wallet audit differs")
    if payload["source_crypto"]["in_scope"]:
        for text,name in ((md,"Markdown"),(pdf,"PDF")):
            require(normalized(label("purchases_note")) in normalized(text),name+" presents purchase spending as contributions")
            require(normalized(label("proxy_note")) in normalized(text),name+" omits proxy boundary")
    return {"status":"passed","checks":checks,"report_model":"source-neutral-1"}
