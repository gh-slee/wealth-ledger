"""Report tables, ODS formula schedules and CSV audits for classifications."""
from .i18n import tr, LabelCatalog, localized, sheet_title, legacy_text
from decimal import Decimal
import csv
import json

D = Decimal
DIMENSIONS = LabelCatalog({'sector': 'message.6807602f240e', 'country': 'message.df858b498276', 'region': 'message.2152450be99b'})
CHARTS = {"sector": "13_sector_exposure", "country": "14_country_exposure", "region": "15_region_exposure"}


def report_section(payload, charts):
    from .reporting import ReportSection, ReportTable, _money, _percent
    data = payload["lookthrough"]["classification"]
    section = ReportSection(tr('message.5215b9ea0623'), [
        tr('message.67ef13924168'),
        tr('message.4f819d23f97e'),
        tr('message.2eb29518d129'),
        tr('message.b2fc1238e03d')])
    section.blocks.append(("table", ReportTable([tr('message.4100e90e79b5'), tr('message.1f2367e77a15'), tr('message.225a21c077f5'), tr('message.089846d6dc33')],
        [[DIMENSIONS[k], _percent(v["equity_coverage"]), _percent(v["investment_coverage"]),
          (v["as_of_min"]+tr('message.8727f227e2c6')+v["as_of_max"]) if v["as_of_min"] else tr('message.e7954a2f3ace')] for k,v in data["dimensions"].items()],
        [1,1,1,1.6])))
    for dimension, summary in data["dimensions"].items():
        section.blocks.append(("subheading", DIMENSIONS[dimension]+tr('message.148d195e21b0')))
        rows = summary["rows"]
        if dimension == "country":
            known = [r for r in rows if r["kind"] == "classified_equity"]
            tail = known[15:]
            rows = known[:15]+([{"name":tr('message.3c6e0a6c0395'),
                   "market_cad":str(sum(D(r['market_cad']) for r in tail)),
                   "investment_weight":str(sum(D(r['investment_weight']) for r in tail)),
                   "equity_weight":str(sum(D(r['equity_weight']) for r in tail))}] if tail else [])+[
                   r for r in rows if r["kind"] != "classified_equity"]
        section.blocks.append(("table", ReportTable([tr('message.b4d250d23bed'), tr('message.f3a7e3113505'), tr('message.225a21c077f5'), tr('message.e3bf1f92eea5')],
            [[r["name"],_money(r["market_cad"]),_percent(r["investment_weight"]),_percent(r["equity_weight"])] for r in rows],
            [2.2,1,1,1])))
        if CHARTS[dimension] in charts:
            section.blocks.append(("chart", charts[CHARTS[dimension]]))
    section.blocks.append(("subheading", tr('message.c7b722441be3')))
    section.blocks.append(("table", ReportTable([tr('message.44a5d0ec88e0'), tr('message.75a28c327ce8'), tr('message.a09ee22eb0ef'), tr('message.c48cf15bba20'), tr('message.f73132cae9ad')],
        [[r["root"],_money(r["equity_cad"]), *[_percent(D(r[k+"_classified_cad"])/D(r["equity_cad"])) if D(r["equity_cad"]) else tr('message.190b16ffcdce')
                                               for k in DIMENSIONS]] for r in data["root_coverage"]],[1.2,1,1,1,1])))
    section.blocks.append(("paragraph", tr('message.1744badd0367')))
    return section


def write_exports(payload, directory):
    data = payload["lookthrough"]["classification"]
    usd, twd = D(payload['fx']['usd_cad']), D(payload['fx']['usd_twd'])
    with (directory/'allocation-exposure.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        fields = ['dimension','key','name','kind','market_cad','market_usd','market_twd','investment_weight','equity_weight']
        writer=csv.DictWriter(handle,fields);writer.writeheader()
        for dimension, summary in data['dimensions'].items():
            for row in summary['rows']:
                amount=D(row['market_cad'])
                writer.writerow({'dimension':dimension,**row,'market_usd':str(amount/usd),'market_twd':str(amount/usd*twd)})
    with (directory/'classification-detail.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        raw_fields=['source_fund','raw_gics_sector','raw_icb_sector','raw_issuer_sector','raw_official_country']
        fields=['company_id','name','root','path','market_cad','sector','country','region',*raw_fields,'assignments']
        writer=csv.DictWriter(handle,fields);writer.writeheader()
        for row in data['components']:
            writer.writerow({**{k:row[k] for k in ('company_id','name','root','market_cad')},'path':' → '.join(row['path']),
                **{k:row[k] for k in raw_fields},
                **{k:row['assignments'][k]['value'] or '' for k in DIMENSIONS},
                'assignments':json.dumps(row['assignments'],ensure_ascii=False)})


def workbook_tables(payload, sheet, sum_formula, ref, interval):
    """Aggregate frozen classification coefficients linked to source CAD totals."""
    from .workbook import literal
    data = payload['lookthrough']['classification']
    start=max(row for row,col in sheet.cells)+4
    sheet.section(start,tr('message.3d45a06fdf88'))
    sheet.row(start+1,[tr('message.eb7bb8bd8f40')],style='note')
    sheet.row(start+2,[tr('message.1c6d8691afb7')],style='note')
    summaries=[]
    row=start+4
    for dimension, summary in data['dimensions'].items():
        sheet.section(row,DIMENSIONS[dimension]+tr('message.148d195e21b0'))
        percent=f"{D(summary['equity_coverage'])*100:.2f}%" if summary['equity_coverage'] is not None else 'n.a.'
        sheet.row(row+1,[tr('message.16116d9a8ecf', value0=percent, value1=summary['as_of_min'] or tr('message.e7954a2f3ace'), value2=summary['as_of_max'] or tr('message.e7954a2f3ace'))],style='note')
        sheet.header(row+3,[tr('message.b4d250d23bed'),tr('message.f3a7e3113505'),tr('message.e27d7ed41293'),tr('message.f3c0c439a1d2'),tr('message.225a21c077f5'),tr('message.e3bf1f92eea5')])
        for target,item in enumerate(summary['rows'],row+4):
            sheet.put(target,2,item['name'])
            summaries.append((target,dimension,item))
        row += len(summary['rows'])+7
    coverage=row
    sheet.section(coverage,tr('message.2eae0bc030ac'))
    sheet.header(coverage+1,[tr('message.44a5d0ec88e0'),tr('message.75a28c327ce8'),tr('message.a09ee22eb0ef'),tr('message.c48cf15bba20'),tr('message.f73132cae9ad')])
    for target,root in enumerate(data['root_coverage'],coverage+2):
        sheet.row(target,[root['root']])
        sheet.put(target,3,D(root['equity_cad']),style='input_money')
        for col,dim in enumerate(DIMENSIONS,4):
            sheet.put(target,col,D(root[dim+'_classified_cad'])/D(root['equity_cad']) if D(root['equity_cad']) else 'n.a.',style='input_percent')
    detail=coverage+len(data['root_coverage'])+5
    sheet.section(detail,tr('message.0db9456842a1'))
    sheet.header(detail+1,[tr('message.40586d89c95e'),tr('message.b976541193fa'),tr('message.cfd683f5a1a2'),tr('message.b4d250d23bed'),tr('message.dafe4c911eb0'),tr('message.d358a75d46c9'),tr('message.4714c2aae156')])
    begin=detail+2;end=begin+len(data['root_groups'])-1
    for target,group in enumerate(data['root_groups'],begin):
        sheet.row(target,[group['root'],group['dimension'],group['key'],group['name']])
        sheet.put(target,6,D(group['weight']),style='input_percent')
        mic,symbol=group['root'].split(':',1)
        base=next(D(r['market_cad']) for r in data['root_coverage'] if r['root']==group['root'])
        sheet.put(target,7,base,sum_formula(16,[(3,symbol),(6,mic)]),'calc_money')
        sheet.put(target,8,D(group['market_cad']),ref(sheet.name,target,6)+'*'+ref(sheet.name,target,7),'calc_money')
    denominator=sum_formula(16,[(4,'<>CURRENCY')])
    eligible=D(data['equity_total_cad'])
    def equity_sum(extra=()):
        conditions=[(3,'sector'),*[(4,'<>'+key) for key in ('cash','crypto','bond','unknown','adjustment')],*extra]
        return 'SUMIFS('+interval(sheet.name,begin,end,8)+''.join(';'+interval(sheet.name,begin,end,col)+';'+literal(value) for col,value in conditions)+')' if end>=begin else '0'
    for target,dimension,item in summaries:
        formula='SUMIFS('+interval(sheet.name,begin,end,8)+';'+interval(sheet.name,begin,end,3)+';"'+dimension+'";'+interval(sheet.name,begin,end,4)+';"'+item['key']+'")' if end>=begin else '0'
        amount=D(item['market_cad'])
        percent_style = 'calc_small_exposure_percent' if item['investment_weight'] and 0 < abs(D(item['investment_weight'])) < D('.0001') else 'calc_exposure_percent'
        sheet.put(target,3,amount,formula,'calc_money')
        sheet.put(target,4,amount/D(payload['fx']['usd_cad']),ref(sheet.name,target,3)+'/'+ref('rates_notes', 6, 3, True),'calc_money')
        sheet.put(target,5,amount/D(payload['fx']['usd_cad'])*D(payload['fx']['usd_twd']),ref(sheet.name,target,4)+'*'+ref('rates_notes', 7, 3, True),'calc_money')
        sheet.put(target,6,D(item['investment_weight']) if item['investment_weight'] else 'n.a.',f'IF(({denominator})=0;"n.a.";{ref(sheet.name,target,3)}/({denominator}))',percent_style)
        if item['equity_weight'] is not None:
            sheet.put(target,7,D(item['equity_weight']),f'IF({ref(sheet.name,start+3,3,True)}=0;"n.a.";{ref(sheet.name,target,3)}/{ref(sheet.name,start+3,3,True)})',percent_style)
        else:
            sheet.put(target,7,'n.a.')
    sheet.row(start+3,[tr('message.7e9380234da5')])
    sheet.put(start+3,3,eligible,equity_sum(),'calc_money')
    for target,root in enumerate(data['root_coverage'],coverage+2):
        sheet.put(target,3,D(root['equity_cad']),equity_sum([(2,root['root'])]),'calc_money')
