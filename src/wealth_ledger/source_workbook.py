"""Source-neutral financial tables using the shared validated ODF package."""
from decimal import Decimal as D
import math
import unicodedata

from .i18n import sheet_title, display_payload
from .source_presentation import sections, label
from .workbook import (Sheet, BASE_SHEETS, ImageFrame, ROW_HEIGHT_CM,
                       resolve_chart_images, write_package, ref, interval, address, CHART_TITLES)


def _lines(text, width=36):
    line = ""
    length = 0
    for char in text:
        size = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        if char == "\n" or length+size > width:
            yield line
            line, length = "", 0
        if char != "\n":
            line += char
            length += size
    if line:
        yield line


def build_source_workbook(payload, output_path, chart_images):
    payload = display_payload(payload)
    images = resolve_chart_images(payload, output_path, chart_images)
    names = list(BASE_SHEETS)
    if payload["source_crypto"]["in_scope"]:
        names.extend(("btc_tracking", "btc_reconciliation"))
    sheets = {key:Sheet(sheet_title(key)) for key in names}
    for sheet in sheets.values():
        sheet.title(payload["meta"]["as_of"])
        sheet.widths.update({1:.5,2:7,**{col:4.5 for col in range(3,22)}})
        sheet.frozen_rows = 5
    rates = sheets["rates_notes"]
    for row,key,text in ((6,"usd_cad","CAD / USD"),(7,"usd_twd","TWD / USD")):
        rates.put(row,2,text); rates.put(row,3,D(payload["fx"][key]),style="input_rate")
    quote = payload["source_crypto"].get("price")
    rates.put(8,2,"BTC / USD"); rates.put(8,3,D(quote["close"]) if quote else label("unknown"),style="input_money")
    rates.put(9,2,"CAD / TWD");rates.put(9,3,D(payload["fx"]["usd_twd"])/D(payload["fx"]["usd_cad"]),ref("rates_notes",7,3)+"/"+ref("rates_notes",6,3),"calc_money")
    raw = sheets["positions"]
    keys = ("account","account_id","symbol","currency","quantity","unit_price","cost","cost_cad","value","unrealized","CAD","USD","TWD","avg_cost","return","account_weight","weight","security_id","as_of")
    raw.header(5,[key if key in {"CAD","USD","TWD"} else label(key) for key in keys])
    records = payload["positions"]+payload["cash_rows"]
    end = max(6,len(records)+5)
    for index,row in enumerate(records,6):
        raw.row(index,[row["account_label"],row["account_id"],row["symbol"],row["currency"]])
        for col,key,style in ((6,"quantity","btc_quantity" if row["security_type"]=="CRYPTO" else "quantity"),(7,"price","money"),
                              (8,"book_native","money"),(9,"book_cad","money"),(10,"market_native","money"),(11,"unrealized_native","money")):
            value=D(row[key]) if row[key] is not None else None
            raw.put(index,col,value if value is not None else label("unknown"),style=style if value is not None else "warning")
        if row["security_type"]=="CRYPTO":
            raw.put(index,7,D(row["price"]),ref("rates_notes",8,3)+"*"+ref("rates_notes",6,3),"money")
            raw.put(index,10,D(row["market_native"]),ref("positions",index,6)+"*"+ref("positions",index,7),"money")
        for col,key,formula in ((12,"market_cad",f'IF({ref("positions",index,5)}="USD";{ref("positions",index,10)}*{ref("rates_notes",6,3)};{ref("positions",index,10)})'),
                                (13,"market_usd",ref("positions",index,12)+"/"+ref("rates_notes",6,3)),
                                (14,"market_twd",ref("positions",index,13)+"*"+ref("rates_notes",7,3))):
            raw.put(index,col,D(row[key]),formula,"calc_money")
        for col,key,formula,style in ((15,"avg_cost",ref("positions",index,8)+"/"+ref("positions",index,6),"money"),
            (16,"unrealized_pct",ref("positions",index,11)+"/"+ref("positions",index,8),"percent"),
            (17,"account_weight",ref("positions",index,12)+"/SUMIFS("+interval("positions",6,end,12)+";"+interval("positions",6,end,3)+";"+ref("positions",index,3)+")","percent"),
            (18,"portfolio_weight",ref("positions",index,12)+"/"+ref("overview",7,5),"percent")):
            raw.put(index,col,D(row[key]) if row[key] is not None else label("unknown"),formula if row[key] is not None else None,style if row[key] is not None else "warning")
        raw.put(index,19,row["security_id"]);raw.put(index,20,row.get("observed_as_of"))
    overview=sheets["overview"]
    overview.header(6,[label("measure"),"", "", "CAD", "USD", "TWD"])
    overview.put(7,2,label("observed_subtotal"),style="section")
    for col,key,source in ((5,"total_cad",12),(6,"total_usd",13),(7,"total_twd",14)):
        value=payload["totals"][key]
        overview.put(7,col,D(value) if value is not None else label("unknown"),"SUM("+interval("positions",6,end,source)+")" if value is not None else None,"total_money" if value is not None else "warning")
    cursors={key:10 if key in {"overview","rates_notes"} else 6 for key in names}
    for key,section in sections(payload,chart_images or {image.key:output_path.parent/"charts"/(image.key+".png") for image in images}):
        sheet=sheets[key]; cursor=cursors[key]
        sheet.section(cursor,section.title);cursor+=2
        for text in section.introduction:
            for line in _lines(text):
                sheet.put(cursor,2,line,style="note");cursor+=1
            cursor+=1
        for kind,block in section.blocks:
            if kind=="chart":
                continue
            if kind=="table":
                sheet.header(cursor,block.headers);cursor+=1
                for index,row in enumerate(block.rows):
                    for col,text in enumerate(row,2):
                        metric=getattr(block,"source_values",{}).get((index,col-2))
                        if metric is not None:
                            value=metric.value
                            sheet.put(cursor,col,value if value is not None else label("unknown"),metric.formula,
                                      metric.style if value is not None else "warning")
                        else:
                            sheet.put(cursor,col,str(text),style="wrapped_body" if len(str(text))>32 else "body")
                    cursor+=1
                cursor+=2
            else:
                for line in _lines(str(block)):
                    sheet.put(cursor,2,line,style="section" if kind=="subheading" else "note");cursor+=1
                cursor+=1
        cursors[key]=cursor+2
    chart_sheet=sheets["charts"]
    cursor=cursors["charts"]
    for index,image in enumerate(images,1):
        chart_sheet.section(cursor,CHART_TITLES[image.key]); anchor=cursor+2
        width=D(28);height=(width*image.pixel_height/image.pixel_width).quantize(D("0.0001"))
        whole=int(height//ROW_HEIGHT_CM);remainder=height-whole*ROW_HEIGHT_CM
        chart_sheet.put(anchor,2)
        chart_sheet.cells[anchor,2].frames.append(ImageFrame(image,width,height,address(chart_sheet.name,anchor+whole,12),remainder,index))
        bottom=anchor+math.ceil(height/ROW_HEIGHT_CM);chart_sheet.put(bottom,12);cursor=bottom+3
    total=payload["totals"]["total_cad"]
    return write_package(sheets,images,output_path,D(total) if total is not None else None,len(records),heatmaps=0,report_model="source-neutral-1")
