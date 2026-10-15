"""Official GICS and issuer-country allocations with auditable coverage."""
from collections import defaultdict
from decimal import Decimal

D = Decimal
VERSION = "official-classification-1"
SECTORS = {
    "Information Technology": "資訊科技", "Communication Services": "通訊服務",
    "Consumer Discretionary": "非必需消費", "Consumer Staples": "必需消費",
    "Financials": "金融", "Health Care": "醫療保健", "Industrials": "工業",
    "Materials": "原材料", "Energy": "能源", "Real Estate": "房地產", "Utilities": "公用事業",
}
# Geographic presentation groups, not economic/developed/emerging-market tiers.
COUNTRY_GROUPS = {
    "北美洲": {"US": "美國", "CA": "加拿大"},
    "拉丁美洲及加勒比海": {"BR": "巴西", "CL": "智利", "CO": "哥倫比亞", "MX": "墨西哥",
                         "AR": "阿根廷", "PE": "秘魯", "KY": "開曼群島", "BM": "百慕達"},
    "歐洲": {"AT": "奧地利", "BE": "比利時", "CH": "瑞士", "CZ": "捷克", "DE": "德國",
            "DK": "丹麥", "ES": "西班牙", "FI": "芬蘭", "FR": "法國", "GB": "英國",
            "GR": "希臘", "HU": "匈牙利", "IE": "愛爾蘭", "IS": "冰島", "IT": "義大利",
            "NL": "荷蘭", "NO": "挪威", "PL": "波蘭", "PT": "葡萄牙", "RO": "羅馬尼亞",
            "RU": "俄羅斯", "SE": "瑞典", "LU": "盧森堡", "EE": "愛沙尼亞", "LT": "立陶宛"},
    "亞洲": {"CN": "中國", "HK": "香港", "ID": "印尼", "IN": "印度", "JP": "日本",
            "KR": "韓國", "MY": "馬來西亞", "PH": "菲律賓", "PK": "巴基斯坦", "SG": "新加坡",
            "TH": "泰國", "TW": "台灣", "VN": "越南", "BD": "孟加拉", "LK": "斯里蘭卡"},
    "中東": {"AE": "阿聯酋", "IL": "以色列", "KW": "科威特", "QA": "卡達", "SA": "沙烏地阿拉伯",
            "TR": "土耳其", "BH": "巴林", "OM": "阿曼"},
    "非洲": {"EG": "埃及", "ZA": "南非", "MA": "摩洛哥", "NG": "奈及利亞", "KE": "肯亞"},
    "大洋洲": {"AU": "澳洲", "NZ": "紐西蘭"},
}
COUNTRIES = {code: (name, group) for group, values in COUNTRY_GROUPS.items() for code, name in values.items()}
COUNTRY_ALIASES = {
    "United States": "US", "United States of America": "US", "Canada": "CA", "Taiwan": "TW",
    "Korea (South)": "KR", "Republic Of Korea": "KR", "Japan": "JP", "China": "CN",
    "Hong Kong": "HK", "United Kingdom": "GB", "Netherlands": "NL", "Switzerland": "CH",
    "France": "FR", "Germany": "DE", "Italy": "IT", "Singapore": "SG", "Australia": "AU",
}
SPECIAL = {"unclassified_equity": "公司股份：未分類", "cash": "ETF 內現金（淨額）",
           "crypto": "比特幣（直接及 ETF）", "bond": "已解析債券", "unknown": "未解析投資工具／餘額",
           "adjustment": "官方權重四捨五入調整"}


def country_code(value):
    value = str(value or "").strip()
    code = COUNTRY_ALIASES.get(value, value.upper())
    return code if code in COUNTRIES else None


def calculate_classification(analysis, components, funds, identities, securities):
    """Classify physical shares; never infer domicile from MIC, currency or ISIN."""
    candidates = defaultdict(lambda: defaultdict(list))
    for fund_id, source in sorted(funds.items()):
        if source.get("status") == "failed":
            continue
        for row in source.get("rows", []):
            if row["kind"] != "equity" or D(row["weight"]) <= 0:
                continue
            company_id, _ = identities.resolve(row)
            if not company_id:
                continue
            values = {"sector": row.get("gics_sector") if row.get("gics_sector") in SECTORS else None,
                      "country": country_code(row.get("country"))}
            for dimension, value in values.items():
                if value:
                    candidates[company_id][dimension].append({"value": value, "fund_id": fund_id,
                        "as_of": source["as_of"], "official_url": source.get("official_url", ""),
                        "status": source["status"]})

    def select(component, dimension):
        own = component.get("source_fund")
        value = component.get("gics_sector") if dimension == "sector" else country_code(component.get("official_country"))
        if dimension == "sector" and value not in SECTORS:
            value = None
        if own and value:
            source = funds[own]
            return value, "own_official_row", [{"value": value, "fund_id": own, "as_of": source["as_of"],
                    "official_url": source.get("official_url", ""), "status": source["status"]}]
        options = candidates[component["company_id"]][dimension]
        if not options:
            return None, "no_official_classification", []
        latest_date = max(option["as_of"] for option in options)
        latest = [option for option in options if option["as_of"] == latest_date]
        if len({option["value"] for option in latest}) != 1:
            return None, "conflicting_latest_official_classification", latest
        return latest[0]["value"], "same_company_latest_official", latest

    totals = {dimension: defaultdict(Decimal) for dimension in ("sector", "country", "region")}
    roots = defaultdict(lambda: {dimension: defaultdict(Decimal) for dimension in totals})
    details, dates = [], {dimension: set() for dimension in totals}
    names = {company["company_id"]: company["name"] for company in analysis["companies"]}
    bases = defaultdict(Decimal)
    for security in securities:
        bases[security["mic"]+":"+security["symbol"]] += D(security["market_cad"])
    for component in components:
        amount = D(component["market_cad"])
        if not amount:
            continue
        root = component["path"][0] if component["root"] == "direct" else component["root"]
        assignments = {}
        for dimension in ("sector", "country"):
            value, method, evidence = select(component, dimension)
            assignments[dimension] = {"value": value, "method": method, "evidence": evidence}
        assignments["region"] = {**assignments["country"],
                                 "value": COUNTRIES[assignments["country"]["value"]][1] if assignments["country"]["value"] else None}
        for dimension, assignment in assignments.items():
            key = assignment["value"] or "unclassified_equity"
            totals[dimension][key] += amount
            roots[root][dimension][key] += amount
            if assignment["value"]:
                dates[dimension].update(e["as_of"] for e in assignment["evidence"])
        details.append({"company_id": component["company_id"], "name": names[component["company_id"]],
                        "root": root, "path": component["path"], "market_cad": str(amount), "assignments": assignments,
                        "source_fund": component.get("source_fund"),
                        "raw_gics_sector": component.get("gics_sector", ""),
                        "raw_icb_sector": component.get("icb_sector", ""),
                        "raw_issuer_sector": component.get("issuer_sector", ""),
                        "raw_official_country": component.get("official_country", "")})
    for fund in analysis["funds"]:
        for kind, value in fund["bucket_cad"].items():
            if kind == "equity" or not D(value):
                continue
            for dimension in totals:
                totals[dimension][kind] += D(value)
                roots[fund["fund_id"]][dimension][kind] += D(value)
    for security in securities:
        if security["security_type"] in {"ETF", "EXCHANGE_TRADED_FUND", "EQUITY"}:
            continue
        key = "crypto" if security["security_type"] == "CRYPTO" else "unknown"
        root = security["mic"]+":"+security["symbol"]
        for dimension in totals:
            totals[dimension][key] += D(security["market_cad"])
            roots[root][dimension][key] += D(security["market_cad"])
    # Unresolved direct company identities remain investment value, not zero.
    for root, base in bases.items():
        for dimension in totals:
            missing = base-sum(roots[root][dimension].values(), D(0))
            if abs(missing) > D("0.00000001"):
                if missing < 0:
                    raise ValueError("Root classification exceeds portfolio value")
                totals[dimension]["unknown"] += missing
                roots[root][dimension]["unknown"] += missing
    denominator, equity = D(analysis["investment_total_cad"]), D(analysis["company_total_cad"])
    summaries = {}

    def label(dimension, key):
        if key in SPECIAL:
            return SPECIAL[key]
        return SECTORS[key] if dimension == "sector" else COUNTRIES[key][0]+"（"+key+"）" if dimension == "country" else key

    for dimension, values in totals.items():
        if abs(sum(values.values(), D(0))-denominator) > D("0.00000001"):
            raise ValueError("Classification allocation does not reconcile")
        known = sum((amount for key, amount in values.items() if key not in SPECIAL), D(0))
        ordered = sorted(values.items(), key=lambda pair: (pair[0] in SPECIAL, -pair[1], pair[0]))
        summaries[dimension] = {
            "classified_cad": str(known), "unclassified_equity_cad": str(values.get("unclassified_equity", 0)),
            "equity_coverage": str(known/equity) if equity else None,
            "investment_coverage": str(known/denominator) if denominator else None,
            "as_of_min": min(dates[dimension]) if dates[dimension] else None,
            "as_of_max": max(dates[dimension]) if dates[dimension] else None,
            "rows": [{"key": key, "name": label(dimension, key), "market_cad": str(amount),
                      "investment_weight": str(amount/denominator) if denominator else None,
                      "equity_weight": str(amount/equity) if equity and key not in SPECIAL else None,
                      "kind": "classified_equity" if key not in SPECIAL else key}
                     for key, amount in ordered if amount],
        }
    root_groups, root_coverage = [], []
    for root, dimensions in sorted(roots.items()):
        eligible = sum((amount for key, amount in dimensions["sector"].items() if key not in SPECIAL or key == "unclassified_equity"), D(0))
        root_coverage.append({"root": root, "market_cad": str(bases[root]), "equity_cad": str(eligible),
                              **{dimension+"_classified_cad": str(sum((a for k,a in values.items() if k not in SPECIAL), D(0)))
                                 for dimension, values in dimensions.items()}})
        for dimension, values in dimensions.items():
            for key, amount in sorted(values.items()):
                if amount:
                    root_groups.append({"root": root, "dimension": dimension, "key": key,
                        "name": label(dimension,key), "weight": str(amount/bases[root]) if bases[root] else "0",
                        "market_cad": str(amount)})
    return {"version": VERSION, "sector_scheme": "GICS", "country_policy": "official_fund_country_not_revenue",
            "region_policy": "documented_geographic_groups_not_market_development_tiers",
            "investment_total_cad": str(denominator), "equity_total_cad": str(equity),
            "dimensions": summaries, "components": details, "root_groups": root_groups,
            "root_coverage": root_coverage,
            "status": "partial" if any(D(s["unclassified_equity_cad"]) for s in summaries.values()) or analysis["status"] != "complete" else "complete"}
