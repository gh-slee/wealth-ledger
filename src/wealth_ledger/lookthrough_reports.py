"""Presentation adapters for frozen company exposure calculations."""
from .i18n import tr, LabelCatalog, localized, sheet_title, legacy_text
from decimal import Decimal
import csv
import json

D = Decimal
STATUS = LabelCatalog({'ok': 'message.ec6113cdd4b2', 'stale': 'message.4bc203f39be5', 'failed': 'message.5b0c3d8622b8'})


def report_section(payload, charts):
    from .reporting import ReportSection, ReportTable, _money, _percent, _display_time
    data = payload["lookthrough"]
    replay = data["mode"] == "frozen_replay"
    section = ReportSection(tr('message.0ebee0b54095'), [
        tr('message.8d6e42bc8fad'),
        tr('message.20bf5dba5b8f', value0=_money(data['investment_total_cad']), value1=_money(data['company_total_cad'])),
        tr('message.e6bc037e400f', value0=_display_time(data['valuation_as_of']), value1=_display_time(data['calculated_at']), value2=data['run_id']) + (tr('message.d2ad94f357ca') if replay else tr('message.d5784ae9eea7')),
        tr('message.167f89bc302e')])
    section.blocks.append(("table", ReportTable(
        [tr('message.6570a98f2850'), tr('message.e06ff957ed48'), tr('message.b2776fc5657f'), tr('message.5b59d8f5d4d8'), tr('message.082f9c0d96ee'), tr('message.395944499c18'), tr('message.caefe2c14215'), tr('message.e3bf1f92eea5')],
        [[rank,row["name"],_money(row["direct_cad"]),_money(row["indirect_cad"]),_money(row["total_cad"]),
          _percent(row["investment_weight"]),_percent(row["asset_weight"]),_percent(row["company_weight"])] for rank,row in enumerate(data["top20"],1)],
        [.4,1.8,.9,1,1,.8,.8,.8])))
    if not data["top20"]:
        section.blocks.append(("paragraph", tr('message.85645d3a1ebc')))
    if "12_company_exposure" in charts:
        section.blocks.append(("chart", charts["12_company_exposure"]))
    section.blocks.append(("paragraph", tr('message.449440fb1013', value0=_percent(data['top20_weight']))))
    section.blocks.append(("subheading", tr('message.135d4f229631')))
    section.blocks.append(("table", ReportTable([tr('message.7c00e566bc0b'), tr('message.597b02542e05'), tr('message.1767ec1d3de6'), tr('message.07883961e628'), tr('message.9bec9878c74a'), tr('message.a5bae8e5e5d5')],
        [[row["fund_id"].split(":")[1],row["as_of"] or tr('message.e7954a2f3ace'),_percent(row["company_weight"]),
          _percent(row["noncompany_weight"]),_percent(row["unknown_weight"]),STATUS[row["status"]]] for row in data["funds"]],
        [.7,.85,.65,.7,.7,1.6])))
    labels = {"cash":tr('message.2bf0d59571cd'), "crypto":tr('message.b7641f292ee2'), "bond":tr('message.e069de50e2f0'), "unknown":tr('message.dda2326775bd'), "adjustment":tr('message.a1fbcdab9427')}
    section.blocks.append(("table", ReportTable([tr('message.0a8b850a2c7b'), tr('message.f3a7e3113505'), tr('message.395944499c18')],
        [[tr('message.87d51669cd0d'),_money(data["company_total_cad"]),_percent(D(data["company_total_cad"])/D(data["investment_total_cad"])) if D(data["investment_total_cad"]) else tr('message.190b16ffcdce')]] +
        [[labels[k],_money(v,4),_percent(D(v)/D(data["investment_total_cad"])) if D(data["investment_total_cad"]) else tr('message.190b16ffcdce')] for k,v in data["noncompany"].items()])))
    section.blocks.append(("paragraph", tr('message.d2afcf3fc2e7')))
    section.blocks.append(("subheading", tr('message.a9ae4c2582cd')))
    for source in data["sources"]:
        section.blocks.append(("paragraph", f"{source['fund_id']} · {legacy_text(source.get('issuer',''))} · {source.get('as_of',tr('message.e7954a2f3ace'))} · {STATUS[source['status']]} · {source.get('official_url',tr('message.415f612d2a98'))}"))
        if source.get("mode") == "issuer_delayered":
            section.blocks.append(("paragraph", tr('message.d8c421001e02')))
        elif source.get("mode") == "disclosed_top_holdings":
            section.blocks.append(("paragraph", tr('message.57d18e1fe1ff')))
        section.blocks.append(("paragraph", tr('message.dcae6293b928', value0=len(source.get('evidence', [])))))
    if data["issues"]:
        section.blocks.append(("paragraph", "；".join(data["issues"])))
    return section


def write_exports(payload, directory):
    data = payload["lookthrough"]
    rate, twd = D(payload["fx"]["usd_cad"]), D(payload["fx"]["usd_twd"])
    (directory / "fund-sources.json").write_text(json.dumps(data["sources"],ensure_ascii=False,indent=2)+"\n", encoding="utf-8")
    with (directory / "unresolved-exposure.csv").open("w",newline="",encoding="utf-8-sig") as handle:
        writer=csv.DictWriter(handle,["root","path","name","market_cad"])
        writer.writeheader()
        for row in data["unresolved_positions"]:
            writer.writerow({**row,"path":" → ".join(row["path"])})
    with (directory / "company-exposure.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        headers = ["company_id","name","direct_cad","indirect_cad","total_cad","total_usd","total_twd",
                   "investment_weight","asset_weight","company_weight","by_fund","source_names","methods"]
        writer = csv.DictWriter(handle, headers)
        writer.writeheader()
        for row in data["companies"]:
            amount = D(row["total_cad"])
            writer.writerow({**{key: row[key] for key in headers if key in row},
                             "total_usd": str(amount/rate), "total_twd": str(amount/rate*twd),
                             **{key: json.dumps(row[key],ensure_ascii=False) for key in ("by_fund","source_names","methods")}})
    if data.get("classification"):
        from .classification_reports import write_exports as write_classification_exports
        write_classification_exports(payload,directory)


def workbook_table(payload, sheet, sum_formula, overview, total_row, ref, interval):
    """Append editable source weights and formula-driven company totals."""
    data = payload["lookthrough"]
    start = max(row for row,col in sheet.cells) + 4
    sheet.section(start, tr('message.85bbf7b7b960'))
    sheet.row(start+1,[tr('message.be48748a1d96')], style="note")
    sheet.row(start+2,[tr('message.911fd80edb50', value0=data['calculated_at'], value1=data['run_id']) + (tr('message.f7d420eeba05') if data['mode']=='frozen_replay' else tr('message.5db43f3759a2'))],style="note")
    denom_row = start+4
    sheet.row(denom_row,[tr('message.5a3ceb23e841'),D(data["investment_total_cad"])])
    sheet.put(denom_row,3,D(data["investment_total_cad"]),"+".join(sum_formula(16,[(4,t)]) for t in sorted({p['security_type'] for p in payload['positions'] if p['security_type']!='CURRENCY'})),"calc_money")
    sheet.row(denom_row+1,[tr('message.20564ce77d16'),D(data["company_total_cad"])])
    sheet.put(denom_row+1,3,D(data["company_total_cad"]),style="input_money")
    header = start+8
    sheet.header(header,[tr('message.6570a98f2850'), tr('message.e06ff957ed48'), tr('message.b2776fc5657f'), tr('message.5b59d8f5d4d8'), tr('message.082f9c0d96ee'), tr('message.325e01bc5e13'), tr('message.b627425ea9f5'), tr('message.395944499c18'), tr('message.caefe2c14215'), tr('message.e3bf1f92eea5')],col=1)
    summary_end = header+len(data["top20"])
    source_header = summary_end+5
    sheet.section(source_header-1,tr('message.4129555b4b8b'))
    sheet.header(source_header,[tr('message.55414c7d060a'), tr('message.e06ff957ed48'), tr('message.678abfdbf137'), tr('message.ed96ac1cdf71'), tr('message.49fa8ceb65b0'), tr('message.000a97cf83e4'), tr('message.4693ce6e2a61')])
    detail_end = source_header+len(data["top20_components"])
    company_names = {r['company_id']:r['name'] for r in data['top20']}
    for row,component in enumerate(data['top20_components'],source_header+1):
        root = component['root']
        sheet.row(row,[component['company_id'],company_names[component['company_id']],root])
        sheet.put(row,3,company_names[component['company_id']],style='wrapped_body')
        sheet.put(row,5,D(component['weight']),style="input_percent")
        if root == 'direct':
            mic,symbol = component['path'][0].split(':',1)
            base = D(component['market_cad'])
        else:
            mic,symbol = root.split(':',1)
            base = next(D(f['market_cad']) for f in data['funds'] if f['fund_id']==root)
        sheet.put(row,6,base,sum_formula(16,[(3,symbol),(6,mic)]),"calc_money")
        sheet.put(row,7,D(component['market_cad']),f"{ref(sheet.name,row,5)}*{ref(sheet.name,row,6)}","calc_money")
        sheet.put(row,8,' → '.join(component['path']))
    for row,company in enumerate(data['top20'],header+1):
        sheet.put(row,1,row-header)
        sheet.put(row,2,company['name'])
        formula = lambda direct: 'SUMIFS('+interval(sheet.name,source_header+1,detail_end,7)+';'+interval(sheet.name,source_header+1,detail_end,2)+';"'+company['company_id']+'";'+interval(sheet.name,source_header+1,detail_end,4)+';"'+('direct' if direct else '<>direct')+'")'
        sheet.put(row,3,D(company['direct_cad']),formula(True),"calc_money")
        sheet.put(row,4,D(company['indirect_cad']),formula(False),"calc_money")
        amount = D(company['total_cad'])
        sheet.put(row,5,amount,f"{ref(sheet.name,row,3)}+{ref(sheet.name,row,4)}","calc_money")
        sheet.put(row,6,amount/D(payload['fx']['usd_cad']),f"{ref(sheet.name,row,5)}/{ref('rates_notes', 6, 3, True)}","calc_money")
        sheet.put(row,7,amount/D(payload['fx']['usd_cad'])*D(payload['fx']['usd_twd']),f"{ref(sheet.name,row,6)}*{ref('rates_notes', 7, 3, True)}","calc_money")
        sheet.put(row,8,D(company['investment_weight']) if company['investment_weight'] else 'n.a.',f"IF({ref(sheet.name,denom_row,3,True)}=0;\"n.a.\";{ref(sheet.name,row,5)}/{ref(sheet.name,denom_row,3,True)})","calc_exposure_percent")
        sheet.put(row,9,D(company['asset_weight']) if company['asset_weight'] else 'n.a.',f"IF({ref(overview.name,total_row,5,True)}=0;\"n.a.\";{ref(sheet.name,row,5)}/{ref(overview.name,total_row,5,True)})","calc_exposure_percent")
        sheet.put(row,10,D(company['company_weight']) if company['company_weight'] else 'n.a.',f"IF({ref(sheet.name,denom_row+1,3,True)}=0;\"n.a.\";{ref(sheet.name,row,5)}/{ref(sheet.name,denom_row+1,3,True)})","calc_exposure_percent")
    coverage = detail_end+4
    sheet.section(coverage-1,tr('message.0a93e35365fa'))
    sheet.header(coverage,["ETF", tr('message.fa51c2b8cf15'), tr('message.4c20968571ff'), tr('message.77d42a6141cd'), tr('message.7fb077fdef51'), tr('message.30fa227df0e0'), tr('message.ab451c4f0e46')])
    for row,fund in enumerate(data['funds'],coverage+1):
        sheet.row(row,[fund['fund_id'],fund['as_of'] or tr('message.e7954a2f3ace')])
        for col,key in [(4,'company_weight'),(5,'noncompany_weight'),(6,'unknown_weight'),(7,'adjustment_weight')]:
            sheet.put(row,col,D(fund[key]),style='input_percent')
        sheet.put(row,8,STATUS[fund['status']])
    company_formula = [sum_formula(16,[(4,'EQUITY')])]
    for index,fund in enumerate(data['funds'],coverage+1):
        mic,symbol = fund['fund_id'].split(':',1)
        company_formula.append('('+sum_formula(16,[(3,symbol),(6,mic)])+')*'+ref(sheet.name,index,4))
    sheet.put(denom_row+1,3,D(data['company_total_cad']),'+'.join(company_formula),'calc_money')
    provenance = coverage+len(data['funds'])+4
    sheet.section(provenance-1,tr('message.a3602855ffb1'))
    sheet.header(provenance,[tr('message.d6c2c44f956c'), tr('message.af114603e3f8'), tr('message.fa51c2b8cf15'), tr('message.782f3071c2fe'), tr('message.ab451c4f0e46'), tr('message.abafa72eca1a')])
    for row,source in enumerate(data['sources'],provenance+1):
        retrieved=source.get('retrieved_at','')
        if retrieved:
            retrieved=retrieved[:16].replace('T',' ')+' UTC'
        sheet.row(row,[source['fund_id'],legacy_text(source.get('issuer','')),source.get('as_of',tr('message.e7954a2f3ace')),retrieved,STATUS[source['status']],source.get('official_url',tr('message.fe82069ad60e'))])
        sheet.put(row,3,legacy_text(source.get('issuer','')),style='wrapped_body')
        sheet.put(row,5,retrieved,style='wrapped_body')
    reconciliation = provenance+len(data['sources'])+4
    sheet.section(reconciliation-1,tr('message.75e8a1ad3207'))
    sheet.header(reconciliation,[tr('message.4100e90e79b5'), tr('message.f3a7e3113505')])
    for row,(kind,value) in enumerate(data['noncompany'].items(),reconciliation+1):
        sheet.row(row,[kind])
        sheet.put(row,3,D(value),style='input_money')
    sheet.widths[1] = 1.2
    sheet.widths[2] = 7
    sheet.widths[8] = 6
    if data.get("classification"):
        from .classification_reports import workbook_tables
        workbook_tables(payload,sheet,sum_formula,ref,interval)
