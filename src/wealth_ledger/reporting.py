"""Localized charts, Markdown and PDF from one presentation model."""

from __future__ import annotations

from .i18n import tr, LabelCatalog, localized, sheet_title, legacy_text, current_context, font_path
from dataclasses import dataclass, field
from contextvars import ContextVar
from functools import wraps
from threading import RLock
import tempfile
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from pathlib import Path
import hashlib
from zoneinfo import ZoneInfo
import os
import json


INK = "#203849"
TEAL = "#238A88"
BLUE = "#567FA6"
GOLD = "#C9953E"
RED = "#B85353"
PALE = "#F2F6F7"
ACCOUNT_COLORS = [TEAL, BLUE, GOLD, "#8471A5", "#729759"]
SNAPSHOT_NAMES = LabelCatalog({'monthly': 'message.aae951aa038b', 'interim': 'message.47f0493157ab', 'ad_hoc': 'message.47f0493157ab', 'baseline': 'message.488eb1e0cca7'})
DATA_STATUS = LabelCatalog({'sources_updated': 'message.e5b756b2fa9e', 'carried_source': 'message.58b2873f1da2', 'mixed_dates': 'message.af01ff686cc5', 'btc_only': 'message.493b1be16178'})


@dataclass
class ReportTable:
    headers: list[str]
    rows: list[list[str]]
    widths: list[float] | None = None


@dataclass
class ReportSection:
    title: str
    introduction: list[str] = field(default_factory=list)
    blocks: list[tuple[str, object]] = field(default_factory=list)


def _decimal(value: str | int | Decimal) -> Decimal:
    return Decimal(str(value))


from .formatting import money as _money, quantity as _quantity, percent as _percent, display_time as _display_time


def _label(value: str) -> str:
    """Omit account-name emoji unsupported by the embedded CJK text font."""
    from .i18n import SourceText
    clean = "".join(char for char in value if ord(char) <= 0xFFFF and char not in "\ufe0f\ufe0e").strip()
    return SourceText(clean) if isinstance(value, SourceText) else clean


def _is_crypto(row: dict) -> bool:
    return row.get("security_type", "").upper() == "CRYPTO"


def _security_label(row: dict, separator: str = " · ") -> str:
    currency = tr('message.142a77c8c976') + row["currency"] if _is_crypto(row) else row["currency"]
    return (legacy_text(row["symbol"]) if _is_crypto(row) else row["symbol"]) + separator + currency


def _native_totals(payload: dict) -> dict[str, Decimal]:
    """Separate trading currencies from the CAD-valued crypto proxy."""
    rows = payload["positions"] + payload["cash_rows"]
    return {currency: sum((_decimal(row["market_native"]) for row in rows
                           if row["currency"] == currency and not _is_crypto(row)), Decimal("0"))
            for currency in ("CAD", "USD")}


def _font_path() -> Path:
    candidates = [os.environ.get("WEALTH_LEDGER_FONT", ""),
                  str(font_path())]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RuntimeError("Set WEALTH_LEDGER_FONT to an embeddable Traditional Chinese TTF font.")


_RENDER_LOCK = RLock()
_CACHE = ContextVar("report_cache", default=None)


def _with_render_cache(function):
    @wraps(function)
    def render(*args, **kwargs):
        with _RENDER_LOCK:
            cache = _CACHE.get()
            if cache is None:
                with tempfile.TemporaryDirectory(prefix="wealth-ledger-chart-cache-") as temporary:
                    return _cached_render(function, Path(temporary), args, kwargs)
            return _cached_render(function, Path(cache), args, kwargs)
    return render


def _cached_render(function, cache, args, kwargs):
    locations = {"MPLCONFIGDIR": cache / "matplotlib", "XDG_CACHE_HOME": cache / "system"}
    previous = {key: os.environ.get(key) for key in locations}
    getters = {}
    try:
        for key, path in locations.items():
            path.mkdir(parents=True, exist_ok=True)
            os.environ[key] = str(path)
        import matplotlib
        # The pinned Matplotlib memoizes these getters in closures, not lru_cache.
        # Scope the public getters under the plotting lock, then restore identities.
        for name in ("get_cachedir", "get_configdir"):
            getters[name] = getattr(matplotlib, name)
            setattr(matplotlib, name, lambda: str(locations["MPLCONFIGDIR"]))
        with matplotlib.rc_context():
            return function(*args, **kwargs)
    finally:
        if getters:
            for name, getter in getters.items():
                setattr(matplotlib, name, getter)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@_with_render_cache
def _charts(payload: dict, directory: Path, font_path: Path) -> dict[str, Path]:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties, fontManager
    from matplotlib.ticker import FuncFormatter
    import numpy as np

    directory.mkdir(parents=True, exist_ok=True)
    fontManager.addfont(str(font_path))
    font_name = FontProperties(fname=str(font_path)).get_name()
    plt.rcParams.update({"font.family":font_name,"font.size":11,"axes.unicode_minus":False,
                         "timezone":"America/Toronto",
                         "axes.labelcolor":INK,"text.color":INK,"xtick.color":INK,"ytick.color":INK,
                         "figure.facecolor":"white","axes.facecolor":"white","savefig.facecolor":"white",
                         "axes.spines.top":False,"axes.spines.right":False,"axes.edgecolor":"#CDD8DD"})
    paths = {}
    accounts = payload["accounts"]
    securities = sorted(payload["securities"],key=lambda row:_decimal(row["market_cad"]),reverse=True)
    total = float(payload["totals"]["total_cad"])
    currency_formatter = FuncFormatter(lambda value, _: f"{value:,.0f}")

    def save(key, figure):
        path = directory/f"{key}.png"
        figure.savefig(path,dpi=190,bbox_inches="tight",pad_inches=0.2)
        plt.close(figure)
        paths[key] = path

    def tidy(axis,title,xlabel=""):
        axis.set_title(title,loc="left",fontsize=15,pad=16)
        axis.set_xlabel(xlabel)
        axis.set_axisbelow(True)
        axis.grid(axis="x",color="#E7EEF0",linewidth=0.8)

    figure,axis = plt.subplots(figsize=(10.5,3.4),constrained_layout=True)
    values = [float(row["total_cad"]) for row in accounts]
    bars = axis.barh([row["account_type"] for row in accounts],values,
                     color=[ACCOUNT_COLORS[i%len(ACCOUNT_COLORS)] for i in range(len(accounts))],height=.55)
    for bar,row in zip(bars,accounts):
        axis.text(bar.get_width()+max(values,default=1)*.018,bar.get_y()+bar.get_height()/2,
                  _money(row["total_cad"]),va="center",fontsize=11)
    axis.set_xlim(0,max(max(values,default=1),1)*1.3)
    axis.invert_yaxis()
    axis.xaxis.set_major_formatter(currency_formatter)
    tidy(axis,tr('message.dcc544ecd640'),tr('message.70c34cd061bc'))
    save("01_account_values",figure)

    figure,axis = plt.subplots(figsize=(10.5,2.9),constrained_layout=True)
    native_totals = _native_totals(payload)
    native_cad = float(native_totals["CAD"])
    native_usd_cad = float(native_totals["USD"] * _decimal(payload["fx"]["usd_cad"]))
    crypto_cad = sum(float(row["market_cad"]) for row in payload["positions"] if _is_crypto(row))
    currency_groups = [(tr('message.a9320bfa2d2c'), native_cad, TEAL), (tr('message.8f5af00dc2fc'), native_usd_cad, BLUE)]
    if payload.get("crypto"):
        currency_groups.append((tr('message.54854a3bf817'), crypto_cad, GOLD))
    left = 0
    for label,value,color in currency_groups:
        axis.barh([tr('message.823bd040ec8b')],[value],left=left,color=color,height=.48,label=label)
        if total and value/total > .06:
            axis.text(left+value/2,0,f"{label}\n{value/total:.2%}",ha="center",va="center",color="white")
        left += value
    axis.set_xlim(0,total*1.01 if total else 1)
    axis.xaxis.set_major_formatter(currency_formatter)
    tidy(axis,tr('message.a0a1b3e1dc0c') if payload.get("crypto") else tr('message.be726af3f80f'),
         tr('message.3101d1754d47') if payload.get("crypto")
         else tr('message.dbee33b267e5'))
    axis.legend(loc="lower center",bbox_to_anchor=(.5,-.55),ncol=len(currency_groups),frameon=False)
    save("02_trading_currency",figure)

    figure,axis = plt.subplots(figsize=(10.5,max(3.7,len(securities)*.4)),constrained_layout=True)
    bars = axis.barh([_security_label(row) for row in securities],
                     [float(row["market_cad"]) for row in securities],color=TEAL,height=.63)
    limit = max(max([float(row["market_cad"]) for row in securities],default=1),1)
    for bar,row in zip(bars,securities):
        axis.text(bar.get_width()+limit*.012,bar.get_y()+bar.get_height()/2,
                  _percent(row["portfolio_weight"]),va="center",fontsize=10)
    axis.set_xlim(0,limit*1.2)
    axis.invert_yaxis()
    axis.xaxis.set_major_formatter(currency_formatter)
    tidy(axis,tr('message.a3b2c8411613') if payload.get("crypto") else tr('message.b1f40dffbe2c'),tr('message.fffb3b2cfe37'))
    save("03_holdings_ranking",figure)

    figure,axis = plt.subplots(figsize=(10.5,max(3.7,len(securities)*.4)),constrained_layout=True)
    labels = [_security_label(row) for row in securities]
    offsets = np.zeros(len(securities))
    for index,account in enumerate(accounts):
        values = [sum(float(p["market_cad"]) for p in payload["positions"]
                      if p["account_id"] == account["account_id"] and
                      (p["symbol"],p["mic"],p["currency"]) == (row["symbol"],row["mic"],row["currency"]))
                  for row in securities]
        axis.barh(labels,values,left=offsets,color=ACCOUNT_COLORS[index%len(ACCOUNT_COLORS)],
                  label=account["account_type"],height=.63)
        offsets += np.array(values)
    axis.invert_yaxis()
    axis.xaxis.set_major_formatter(currency_formatter)
    tidy(axis,tr('message.523eceb9c229'),tr('message.49555a47504d'))
    axis.legend(loc="upper center",bbox_to_anchor=(.5,-.18),ncol=3,frameon=False)
    save("04_holdings_by_account",figure)

    figure,axes = plt.subplots(1,2,figsize=(10.5,4.2),constrained_layout=True)
    for axis,currency in zip(axes,["CAD","USD"]):
        rows = sorted([row for row in securities if row["currency"] == currency and not _is_crypto(row)],
                      key=lambda row:_decimal(row["unrealized_native"]),reverse=True)
        values = [float(row["unrealized_native"]) for row in rows]
        axis.barh([row["symbol"] for row in rows],values,color=[TEAL if v>=0 else RED for v in values],height=.6)
        axis.axvline(0,color=INK,linewidth=.7)
        axis.invert_yaxis()
        axis.xaxis.set_major_formatter(currency_formatter)
        tidy(axis,tr('message.13b043039c3f', value0=currency),tr('message.89d15c204e79', value0=currency))
    save("05_unrealized_native",figure)

    rows = sorted([row for row in securities if row["unrealized_pct"] is not None and not _is_crypto(row)],
                  key=lambda row:_decimal(row["unrealized_pct"]),reverse=True)
    figure,axis = plt.subplots(figsize=(10.5,max(3.7,len(rows)*.4)),constrained_layout=True)
    values = [float(row["unrealized_pct"])*100 for row in rows]
    bars = axis.barh([row["symbol"]+" · "+row["currency"] for row in rows],values,
                     color=[TEAL if value>=0 else RED for value in values],height=.62)
    for bar,row in zip(bars,rows):
        axis.annotate(_percent(row["unrealized_pct"]),(bar.get_width(),bar.get_y()+bar.get_height()/2),
                      xytext=(5 if bar.get_width()>=0 else -5,0),textcoords="offset points",
                      ha="left" if bar.get_width()>=0 else "right",va="center",fontsize=10)
    axis.axvline(0,color=INK,linewidth=.7)
    axis.invert_yaxis()
    axis.margins(x=.2)
    if not rows:
        axis.text(.5,.5,tr('message.ca97ed36bb2a'),transform=axis.transAxes,ha="center",va="center")
    tidy(axis,tr('message.440468e6dca4'),tr('message.eca70ae03f6a'))
    save("06_unrealized_percent",figure)

    rows = payload["instrument_types"]
    figure,axis = plt.subplots(figsize=(10.5,3.25),constrained_layout=True)
    axis.barh([row["label"] for row in rows],[float(row["weight"] or 0)*100 for row in rows],
              color=[ACCOUNT_COLORS[i%len(ACCOUNT_COLORS)] for i in range(len(rows))],height=.55)
    for index,row in enumerate(rows):
        axis.text(float(row["weight"] or 0)*100+.9,index,_percent(row["weight"]),va="center")
    axis.set_xlim(0,max(max([float(row["weight"] or 0)*100 for row in rows],default=1),1)*1.18)
    axis.invert_yaxis()
    tidy(axis,tr('message.d7aba09f30e4'),tr('message.730aa6580900'))
    save("07_instrument_mix",figure)

    matrix = payload["matrix"]
    matrix_rows = matrix["rows"]
    account_ids = [row["account_id"] for row in matrix["accounts"]]
    grid = np.array([[float(row["weights"].get(key,"0") or 0)*100 for key in account_ids] for row in matrix_rows])
    figure,axis = plt.subplots(figsize=(10.5,max(4.2,len(matrix_rows)*.37)),constrained_layout=True)
    image = axis.imshow(grid,cmap="GnBu",aspect="auto",vmin=0,vmax=max(float(grid.max()) if grid.size else 0,1))
    axis.set_xticks(range(len(account_ids)),[_label(row["label"]) for row in matrix["accounts"]])
    crypto_keys = {(row["symbol"], row["currency"]) for row in securities if _is_crypto(row)}
    axis.set_yticks(range(len(matrix_rows)),[
        row["symbol"] + " · " + (tr('message.142a77c8c976') if (row["symbol"], row["currency"]) in crypto_keys else "") + row["currency"]
        for row in matrix_rows])
    for i in range(len(matrix_rows)):
        for j in range(len(account_ids)):
            value = grid[i,j]
            text = (tr('message.190b16ffcdce') if matrix_rows[i]["weights"].get(account_ids[j],"0") is None
                    else "<0.01%" if 0<value<.01 else f"{value:.2f}%")
            axis.text(j,i,text,ha="center",va="center",fontsize=9,
                      color="white" if value>max(float(grid.max()),1)*.55 else INK)
    axis.set_title(tr('message.16f03c83124c'),loc="left",fontsize=15,pad=16)
    axis.set_xlabel(tr('message.c9e71a372f3c'))
    figure.colorbar(image,ax=axis,label=tr('message.9a4946e883db'),shrink=.8)
    save("08_account_weight_heatmap",figure)
    observations = payload["history"]
    complete_observations = [row for row in observations if row["is_complete"]]
    if len({row["as_of"] for row in observations})>=2:
        figure,axes = plt.subplots(3,1,figsize=(10.5,7.5),constrained_layout=True)
        for axis,currency in zip(axes,["CAD","USD","TWD"]):
            key = f"total_{currency.lower()}"
            if payload.get("crypto") and any(not row["is_complete"] for row in observations):
                axis.plot([datetime.fromisoformat(row["as_of"]) for row in observations],
                          [float(row["totals"][key]) for row in observations],
                          color=INK,marker="o",markerfacecolor="white",linestyle="--",linewidth=1.4,
                          label=tr('message.8a162e46dbe2'))
            if complete_observations:
                axis.plot([datetime.fromisoformat(row["as_of"]) for row in complete_observations],
                          [float(row["totals"][key]) for row in complete_observations],
                          color=INK,marker="o",linewidth=2,label=tr('message.8225db024413'))
            for index,account in enumerate(accounts):
                account_history=payload.get("wealthsimple_history",observations) if account.get("source_provider")=="wealthsimple" else observations
                points = [(datetime.fromisoformat(row["as_of"]),float(candidate[key]))
                          for row in account_history for candidate in row["accounts"]
                          if candidate["account_id"] == account["account_id"]]
                if points:
                    axis.plot([point[0] for point in points],[point[1] for point in points],
                              marker="o",markersize=3,color=ACCOUNT_COLORS[index%len(ACCOUNT_COLORS)],
                              label=account["account_type"])
            axis.set_title(tr('message.ddead86ab43e', value0=currency),loc="left",fontsize=13)
            axis.yaxis.set_major_formatter(currency_formatter)
            axis.grid(color="#E7EEF0",linewidth=.8)
            axis.tick_params(axis="x",labelsize=8)
        axes[0].legend(loc="upper left",ncol=2,frameon=False,fontsize=9)
        axes[-1].set_xlabel(tr('message.90d002dd5e40') if payload.get("crypto")
                             else tr('message.c30ae2352c09'))
        save("09_historical_values",figure)
    crypto = payload.get("crypto")
    if crypto:
        monthly = sorted(crypto["monthly"], key=lambda row: row["month"])
        months = [row["month"] for row in monthly]
        figure, axis = plt.subplots(figsize=(10.5,4.3), constrained_layout=True)
        values = [float(row["cumulative_btc_equivalent_qty"]) for row in monthly]
        axis.plot(months, values, color=TEAL, marker="o", linewidth=2)
        if not monthly:
            axis.text(.5,.5,tr('message.27b6fc1fddf5'),transform=axis.transAxes,ha="center",va="center")
        axis.set_title(tr('message.b1554605cccb'), loc="left", fontsize=15, pad=16)
        axis.set_ylabel(tr('message.bfc23e4a4070'))
        axis.set_xlabel(tr('message.7775dd7b6e17'))
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.6f}"))
        axis.grid(axis="y",color="#E7EEF0",linewidth=.8)
        stride = max(1, (len(months)+11)//12)
        axis.set_xticks(range(0,len(months),stride), months[::stride], rotation=35, ha="right")
        save("10_btc_accumulation", figure)

        figure, axis = plt.subplots(figsize=(10.5,4.5), constrained_layout=True)
        indices = np.arange(len(months))
        funding = [float(row["contribution_cad"]) for row in monthly]
        purchases = [float(row["buy_cost_cad"]) for row in monthly]
        axis.bar(indices-.19, funding, width=.38, color=BLUE, label=tr('message.62b852c10855'))
        axis.bar(indices+.19, purchases, width=.38, color=TEAL, label=tr('message.85211ac9360b'))
        axis.set_xticks(indices[::stride], months[::stride], rotation=35, ha="right")
        axis.set_title(tr('message.4e68e5d257b5'), loc="left", fontsize=15, pad=16)
        axis.set_ylabel("CAD")
        axis.yaxis.set_major_formatter(currency_formatter)
        axis.set_xlabel(tr('message.923978b81e8e'))
        axis.grid(axis="y",color="#E7EEF0",linewidth=.8)
        axis.set_axisbelow(True)
        axis.legend(loc="upper left", frameon=False)
        save("11_btc_monthly_contributions", figure)
    if crypto and crypto.get("wallet", {}).get("observations"):
        wallet=crypto["wallet"]
        figure,axis=plt.subplots(figsize=(10.5,4.8),constrained_layout=True)
        purchases=sorted([r for r in crypto["orders"] if r["included_in_totals"] and r["order_type"]=="Buy Bitcoin"], key=lambda r:r["completed_at"])
        total=Decimal(0);dates=[];values=[]
        for purchase in purchases:
            total+=Decimal(purchase["buy_qty_btc"])+Decimal(purchase["buy_qty_lbtc"])
            dates.append(datetime.fromisoformat(purchase["completed_at"]))
            values.append(float(total))
        if dates:
            axis.plot(dates,values,color=TEAL,marker="s",markersize=4,label=tr('message.82ff7a46bb38'))
        observations=wallet["observations"]
        axis.scatter([datetime.fromisoformat(r["as_of"]) for r in observations],
                     [float(r["quantity_btc"]) for r in observations],color=BLUE,label=tr('message.b9a057966d64'),zorder=3)
        anchor=wallet["anchor"]
        axis.plot([datetime.fromisoformat(anchor["as_of"]),datetime.fromisoformat(crypto["meta"]["as_of"])],
                  [float(anchor["quantity_btc"]),float(crypto["btc_equivalent_qty"])],
                  color=GOLD,linestyle="--",marker="o",label=tr('message.2d4102b27e30'))
        axis.set_title(tr('message.554a3964b9ca'),loc="left",fontsize=15,pad=16)
        axis.set_ylabel(tr('message.bfc23e4a4070'))
        axis.set_xlabel(tr('message.3af6d89df6e7'))
        axis.legend(frameon=False,fontsize=9)
        figure.autofmt_xdate()
        save("16_btc_wallet_reconciliation",figure)
    lookthrough = payload.get("lookthrough")
    if lookthrough and lookthrough["top20"]:
        rows = list(reversed(lookthrough["top20"]))
        denominator = float(lookthrough["investment_total_cad"])
        figure,axis = plt.subplots(figsize=(11.5,9.2),constrained_layout=True)
        direct = [float(row["direct_cad"])/denominator*100 for row in rows]
        indirect = [float(row["indirect_cad"])/denominator*100 for row in rows]
        indices = np.arange(len(rows))
        axis.barh(indices,direct,color=BLUE,label=tr('message.7bdb0189b7ee'))
        axis.barh(indices,indirect,left=direct,color=TEAL,label=tr('message.405c6adde567'))
        axis.set_yticks(indices,[row["name"] for row in rows],fontsize=10)
        for index,row in enumerate(rows):
            pct = float(row["investment_weight"])*100
            axis.text(pct+.1,index,f"{pct:.2f}%",va="center",fontsize=9)
        axis.set_xlim(0,max(direct[i]+indirect[i] for i in range(len(rows)))*1.15)
        axis.set_title(tr('message.a461df985d9f'),loc="left",fontsize=15,pad=16)
        axis.set_xlabel(tr('message.bfb2aa1dbde8'))
        axis.grid(axis="x",color="#E7EEF0",linewidth=.8)
        axis.set_axisbelow(True)
        axis.legend(loc="lower right",frameon=False)
        save("12_company_exposure",figure)
    if lookthrough and lookthrough.get("classification"):
        from .classification_reports import CHARTS, DIMENSIONS
        for dimension, summary in lookthrough["classification"]["dimensions"].items():
            rows = summary["rows"]
            if dimension == "country":
                known = [r for r in rows if r["kind"] == "classified_equity"]
                tail = known[15:]
                rows = known[:15]+([{"name":tr('message.944fe54ebd1a'), "investment_weight":str(sum(Decimal(r['investment_weight']) for r in tail))}] if tail else [])+[
                    r for r in rows if r["kind"] != "classified_equity"]
            if not rows:
                continue
            rows = list(reversed(rows))
            figure,axis = plt.subplots(figsize=(11.5,max(5.2,len(rows)*.36+1.6)),constrained_layout=True)
            values = [float(r["investment_weight"] or 0)*100 for r in rows]
            axis.barh(range(len(rows)),values,color=[BLUE if r.get('kind')=='classified_equity' or r['name']==tr('message.944fe54ebd1a') else '#9EADB8' for r in rows])
            axis.set_yticks(range(len(rows)),[r['name'] for r in rows],fontsize=10)
            for index,value in enumerate(values):
                # Tiny signed reconciliation values need readable precision and space.
                label = f"{value:.6f}%" if 0 < abs(value) < .01 else f"{value:.2f}%"
                near_zero = abs(value) < .01
                axis.text(max(value,0)+.2 if near_zero or value>=0 else value-.2,index,label,
                          ha='left' if near_zero or value>=0 else 'right',va='center',fontsize=9)
            axis.set_xlim(min(0,min(values)-1.5),max(1,max(values))*1.18)
            axis.set_title(DIMENSIONS[dimension]+tr('message.9e9d75c0e234'),loc='left',fontsize=15,pad=16)
            axis.set_xlabel(tr('message.ac4a0e42ddca'))
            axis.grid(axis='x',color='#E7EEF0',linewidth=.8);axis.set_axisbelow(True)
            save(CHARTS[dimension],figure)
    return paths


def _holding_table(rows: list[dict], account_column: bool) -> ReportTable:
    headers = ([tr('message.b0f18aa763de')] if account_column else [])+[tr('message.b4ee0f51de55'),tr('message.26c1c5b41973'),tr('message.be547beabfb6'),tr('message.3e9409c24979'),tr('message.ec9554ab6f4f'),tr('message.ff68c70ea858'),tr('message.6eb5191e200e'),tr('message.57c0f0472864')]
    result = [([row["account_type"]] if account_column else [])+[
        f"{row['symbol']} / {row['exchange']}",row["currency"],_quantity(row["quantity"]),_money(row["price"]),
        _money(row["book_native"]),_money(row["market_native"]),_money(row["unrealized_native"]),
        _percent(row["portfolio_weight"] if account_column else row["account_weight"])] for row in rows]
    widths = [1.1,1,.5,.85,.8,1,1,1,.8] if account_column else [1.1,.5,.9,.85,1,1,1,.8]
    return ReportTable(headers,result,widths)


def _crypto_sections(crypto: dict, charts: dict[str, Path]) -> list[ReportSection]:
    """Present order-derived quantities independently from broker native holdings."""
    from .wallet_reports import quantity_basis_label, KNOWN_CHANGES_NOTE
    meta = crypto["meta"]
    overview = ReportSection(tr('message.bba28b110951'),[
        tr('message.6c172e7fdace') + quantity_basis_label(crypto) + (". " if current_context().locale == "en-CA" else "。") + tr(KNOWN_CHANGES_NOTE),
        tr('message.42e0f082d165')])
    overview.blocks.append(("table",ReportTable([tr('message.babe67860684'),tr('message.245eb9a44a4c')],
        [["BTC",_quantity(crypto["qty_btc"])],["LBTC",_quantity(crypto["qty_lbtc"])],
         [tr('message.389694773c3e'),_quantity(crypto["purchased_btc_equivalent_qty"])],
         [tr('message.97191d1a4b6a'),_quantity(crypto["opening_btc_equivalent_qty"])],
         [tr('message.14a8d2360512'),_quantity(crypto["btc_equivalent_qty"])]])))
    overview.blocks.append(("table",ReportTable([tr('message.051bd395e4c8'),"CAD"],
        [[tr('message.569651d9d044'),_money(crypto["total_funding_cad"])],
         [tr('message.687923f71c66'),_money(crypto["total_buy_cost_cad"])],
         [tr('message.292e42482543'),_money(crypto["cash_cad"])]])))
    overview.blocks.append(("paragraph",tr('message.1c12492bc3d9')))
    quantity_status=quantity_basis_label(crypto)
    overview.blocks.append(("paragraph",tr('message.1a16c8595e99', value0=meta['completed_order_count'], value1=meta['pending_order_count'], value2=meta['excluded_after_cutoff_count'], value3=quantity_status)))
    valuation = crypto.get("valuation")
    if valuation:
        from .btc_performance import btc_cost_estimate
        estimate = btc_cost_estimate(crypto)
        price = valuation["price"]
        overview.blocks.append(("subheading",tr('message.3313ca9367d0')))
        overview.blocks.append(("table",ReportTable([tr('message.b0d1421ffecf'),tr('message.be8cc7e75f6f')],
            [[currency,_money(valuation[f"market_{currency.lower()}"])] for currency in ("CAD","USD","TWD")])))
        proxy_enabled = estimate["status"] != "proxy_disabled"
        overview.blocks.append(("subheading", tr('message.df8d65f8ce04') if proxy_enabled else tr('message.7355f08afebe')))
        missing = estimate["unavailable_reason"]
        overview.blocks.append(("table", ReportTable([tr('message.f511a2c8dcbc'), tr('message.b444207314e0')], [
            [tr('message.97d008b79853'), _quantity(estimate["purchase_quantity_btc"])],
            [tr('message.9d9ed2aa01ac'), _money(estimate["average_price_cad_per_btc"]) if estimate["average_price_cad_per_btc"] is not None else missing],
            [tr('message.ab4aaf32040f'), _money(estimate["estimated_cost_cad"]) if estimate["estimated_cost_cad"] is not None else missing],
            [tr('message.5c00f5d9c098'), _money(estimate["estimated_gain_cad"]) if estimate["estimated_gain_cad"] is not None else missing],
            [tr('message.19cbcfc5d23f'), _percent(estimate["estimated_return"]) if estimate["estimated_return"] is not None else missing if estimate["estimated_gain_cad"] is None else tr('message.e6b353a5f1ab')],
        ], [1.7, 2])))
        overview.blocks.append(("paragraph", legacy_text(estimate["note"]) + (tr('message.ba0c787802b0') if proxy_enabled else tr('message.b3e4a98ada96'))))
        cost_note=(tr('message.a215500a9bb4') if valuation.get("cost_status") == "partial_unknown_opening" else tr('message.60c669aba2be') if valuation.get("cost_status") == "unknown_wallet_cost" else tr('message.90c3d8a4978f'))
        if not proxy_enabled:
            cost_note = (tr('message.ee73a6f68fba') if valuation.get("cost_status") in ("partial_unknown_opening", "unknown_wallet_cost") else tr('message.3c1eae0a2d0d')) + tr('message.4c04f87aa18e')
        overview.blocks.append(("paragraph",tr('message.43659913c22c', value0=_money(valuation['unit_price_usd']), value1=_money(valuation['unit_price_cad']))+cost_note))
        overview.blocks.append(("table",ReportTable([tr('message.58cf3accabb3'),tr('message.b335a1500417')],
            [[tr('message.3bdebed010a8'),price["provider"]+" / "+price["pair"]],
             [tr('message.1b8b3b8dff5b'),price["as_of"]],[tr('message.ca288a93b6c8'),price["candle_start"]],
             [tr('message.e26c4f310f2c'),price["candle_end"]],[tr('message.f652cb4c8c06'),_money(price["close"])],
             [tr('message.f9fcd31f55eb'),price["source_url"]],[tr('message.3dcd66361deb'),price["evidence_sha256"]]], [.8,3])))
        overview.blocks.append(("paragraph",tr('message.3fab3d1cdd07')))
    else:
        overview.blocks.append(("paragraph",tr('message.8052058e3e11')))
    opening=crypto.get("opening")
    assumptions = crypto["assumptions"]
    if opening:
        overview.blocks.append(("subheading",tr('message.c69fa6f20c16')))
        overview.blocks.append(("table",ReportTable([tr('message.240466eb61c6'),tr('message.e69a80767b36')],[
            [tr('message.d4ba77b9e0d9'),_quantity(opening["opening_btc_equivalent_qty"])],
            [tr('message.85e04d71e23f'),tr('message.5131c1a4a504')],
            [tr('message.7d519f5981e1'),tr('message.7ef6c58fdb62')],
            [tr('message.50eac54dda66'),tr('message.28d838d593d9')],
            [tr('message.822bcdc0887a'),opening["declared_on"]]], [.8,3])))
        overview.blocks.append(("paragraph",tr('message.a913080707e3')))
    else:
        overview.blocks.append(("subheading",tr('message.33c0141f0e97')))
        overview.blocks.append(("table",ReportTable([tr('message.648263132a87'),tr('message.714a199852e7')],
            [[tr('message.ff4b575e5357'),_quantity(assumptions["btc"])],[tr('message.97789925717e'),_quantity(assumptions["lbtc"])],
             [tr('message.77ff526c500e'),_money(assumptions["cad"])],[tr('message.883bb96a23a8'),str(assumptions["basis"])],
             [tr('message.75e11a75da00'),str(assumptions["confirmed_by"])]], [.8,3])))
        if assumptions.get("cad_basis"):
            overview.blocks.append(("paragraph",tr('message.e2a284aac467')+str(assumptions["cad_basis"])))
    overview.blocks.append(("paragraph",tr('message.3699a6ce412e')))

    from .crypto import monthly_purchase_price
    monthly = ReportSection(tr('message.aa249438c7c1'),[
        tr('message.9e24827be6e3'),
        tr('message.a65d87581141'),
        tr('message.b3535d0d5c91')])
    if "10_btc_accumulation" in charts:
        monthly.blocks.append(("chart",charts["10_btc_accumulation"]))
    monthly.blocks.append(("table",ReportTable([tr('message.5ba4cb3b6738'),tr('message.aa9c4132cb80'),tr('message.a82c9f2aff95'),tr('message.e5e377c9ef30'),tr('message.cd6cc33e7564'),tr('message.68a158f052a7'),tr('message.64076384a26b'),tr('message.16a0f85a6fff')],
        [[row["month"],_money(row["contribution_cad"]),_money(row["buy_cost_cad"]),
          _quantity(row["buy_qty_btc"]),_quantity(row["buy_qty_lbtc"]),
          _quantity(row["cumulative_btc_equivalent_qty"]),_money(row["cash_cad"]),
          _money(monthly_purchase_price(row)) if monthly_purchase_price(row) is not None else tr('message.190b16ffcdce')]
         for row in sorted(crypto["monthly"],key=lambda row:row["month"])], [.7,.8,.85,1,1,1.1,.85,1.1])))
    if "11_btc_monthly_contributions" in charts:
        monthly.blocks.append(("chart",charts["11_btc_monthly_contributions"]))
    monthly.blocks.append(("paragraph",tr('message.00bbbfbe287a')))
    monthly.blocks.append(("subheading",tr('message.965f2a56cafb')))
    monthly.blocks.append(("table",ReportTable([tr('message.24cb4ea0990b'),tr('message.b6268d34c3c6'),"SHA-256"],
        [[row["filename"],str(row["row_count"]),row["sha256"]] for row in crypto["source"]["sources"]], [1.3,.55,2.4])))
    from .wallet_reports import reconciliation_section
    if crypto.get("wallet"):
        overview.introduction.append(tr('message.d7324272c01b'))
    return [overview,monthly,reconciliation_section(crypto,charts)]


def _sections(payload: dict, charts: dict[str, Path]) -> list[ReportSection]:
    meta,totals = payload["meta"],payload["totals"]
    accounts,securities,positions = payload["accounts"],payload["securities"],payload["positions"]
    broker_positions = [row for row in positions if not _is_crypto(row)]
    broker_securities = [row for row in securities if not _is_crypto(row)]
    crypto = payload.get("crypto")
    sections = []
    kind_name = SNAPSHOT_NAMES.get(meta["kind"],meta["kind"])
    overview = ReportSection(tr('message.c7abf421eeb9'),[
        tr('message.9e8fc88db90b', value0=_display_time(meta['as_of']), value1=_display_time(meta['generated_at'])),
        tr('message.58441048a8a5', value0=kind_name, value1=meta['revision'], value2=tr('message.088b27d0ed00') if meta.get('account_coverage_complete', meta['is_complete']) else tr('message.abf099167903')),
        tr('message.548c50e64cbc')])
    overview.blocks.append(("table",ReportTable([tr('message.b0d1421ffecf'),tr('message.1473905ebc79')],[[currency,_money(totals[f"total_{currency.lower()}"])] for currency in ["CAD","USD","TWD"]])))
    overview.blocks.append(("table",ReportTable([tr('message.b0f18aa763de'),tr('message.f3a7e3113505'),tr('message.e27d7ed41293'),tr('message.f3c0c439a1d2'),tr('message.c96460f427df')],[[row["account_type"],_money(row["total_cad"]),_money(row["total_usd"]),_money(row["total_twd"]),_percent(row["portfolio_weight"])] for row in accounts])))
    asset_label=tr('message.964cf28fa196') if crypto else tr('message.360646a6014f')
    overview.blocks.append(("paragraph",tr('message.e34567eed3ef', value0=meta['account_count'], value1=meta['security_count'], value2=asset_label, value3=meta['position_count'], value4=asset_label, value5=meta['cash_row_count'])))
    if crypto:
        overview.blocks.append(("paragraph",tr('message.2384dafac91e')+DATA_STATUS.get(meta.get("data_status"),tr('message.d558ad9eb8c5'))+("." if current_context().locale == "en-CA" else "。")))
        updates=meta.get("source_updates")
        if updates:
            status_names={"provided":tr('message.ca68e9e63735'),"carried_forward":tr('message.58c03ac70438'),"not_available":tr('message.be4f923bcf9f')}
            overview.blocks.append(("table",ReportTable([tr('message.c21db84c0653'),tr('message.3edfc760a520'),tr('message.ecbed83050d5')],[
                ["Wealthsimple",status_names[updates["wealthsimple"]["status"]],updates["wealthsimple"].get("holdings_as_of") or tr('message.c87ff8745498')],
                ["Bull Bitcoin",status_names[updates["bullbitcoin"]["status"]],updates["bullbitcoin"].get("latest_completed_at") or tr('message.eeda3a69dd33')]],[.8,1,2])))
            overview.blocks.append(("paragraph",tr('message.bf571c85b813')))
        overview.blocks.append(("paragraph",(tr('message.ceb3ca685ecf') if meta.get("wealthsimple_as_of") else tr('message.5ddae42bfdc7'))+(tr('message.5042eb64dfe8') if crypto.get("opening") else tr('message.1a9102b97b98'))+tr('message.79cff8d5147a')))
        if meta.get("wealthsimple_as_of"):
            overview.blocks.append(("paragraph",tr('message.e2ad3f2aa195', value0=_display_time(meta['wealthsimple_as_of']))))
        overview.blocks.append(("paragraph",tr('message.ff2096cd12f7')))
    for finding in payload["findings"]:
        overview.blocks.append(("paragraph",finding))
    overview.blocks.append(("chart",charts["01_account_values"]))
    sections.append(overview)

    currencies = ReportSection(tr('message.ec85e420ec04'),[tr('message.e38c8b853ed4')])
    for currency in ["CAD","USD"]:
        rows = sorted([row for row in broker_positions if row["currency"] == currency],key=lambda row:(row["account_type"],row["symbol"]))
        currencies.blocks += [("subheading",tr('message.8247c741a246', value0=currency)),("table",_holding_table(rows,True))]
    native = _native_totals(payload)
    currency_rows = [[tr('message.a9320bfa2d2c'),_money(native["CAD"])],[tr('message.8f5af00dc2fc'),_money(native["USD"])]]
    if crypto:
        crypto_value = sum((_decimal(row["market_cad"]) for row in positions if _is_crypto(row)), Decimal("0"))
        currency_rows.append([tr('message.c15d3b1e55d4'),_money(crypto_value)])
        currencies.blocks.append(("paragraph",tr('message.151f3808705a')))
    currencies.blocks.append(("table",ReportTable([tr('message.4100e90e79b5'),tr('message.8156b95e62a3')],currency_rows)))
    sections.append(currencies)

    account_section = ReportSection(tr('message.8c505cd36927'),[tr('message.e2b626739f3f')])
    for account in accounts:
        if any(_is_crypto(row) for row in positions if row["account_id"] == account["account_id"]):
            account_section.blocks += [("subheading",account["account_type"]),
                ("paragraph",tr('message.75f0df652883'))]
            continue
        rows = sorted([row for row in broker_positions if row["account_id"] == account["account_id"]],key=lambda row:(row["currency"],row["symbol"]))
        account_section.blocks += [("subheading",account["account_type"]),
            ("paragraph",tr('message.f3e9c4e5c018', value0=_money(account['native_cad']), value1=_money(account['native_usd']))),
            ("table",_holding_table(rows,False))]
    sections.append(account_section)

    cost_section = ReportSection(tr('message.34ad08ebe98e'),[tr('message.586988088d37')])
    cost_section.blocks.append(("table",ReportTable([tr('message.360646a6014f'),tr('message.26c1c5b41973'),tr('message.1b7b3478ff82'),tr('message.9681b050ef05'),tr('message.ec9554ab6f4f'),tr('message.ff68c70ea858'),tr('message.6eb5191e200e'),tr('message.7b0f5a11ce79')],[[row["symbol"],row["currency"],_quantity(row["quantity"]),_money(row["avg_cost"],4),_money(row["book_native"]),_money(row["market_native"]),_money(row["unrealized_native"]),_percent(row["unrealized_pct"])] for row in broker_securities],[1,.5,.9,.9,1,1,1,.8])))
    if crypto:
        cost_section.blocks.append(("paragraph",tr('message.32f54732844d')))
    cost_section.blocks.append(("chart",charts["05_unrealized_native"]))
    cost_section.blocks.append(("paragraph",tr('message.5bb90d917029')))
    sections.append(cost_section)

    concentration = payload["concentration"]
    ranking = ReportSection(tr('message.b8ac5ae08408'),[tr('message.72aecb333604')])
    largest = concentration["largest"]
    ranking.blocks.append(("table",ReportTable([tr('message.27a74cb7bf44'),tr('message.931481af9274')],[[tr('message.0bbb2bcefc56')+largest["symbol"] if largest else tr('message.c502cce1359e'),_percent(largest["weight"]) if largest else tr('message.190b16ffcdce')],[tr('message.33697f3cc5e2'),_percent(concentration["top3_weight"])],[tr('message.fc3fe62d6cde'),_percent(concentration["top5_weight"])]])))
    ranking.blocks.append(("chart",charts["03_holdings_ranking"]))
    ranking.blocks.append(("chart",charts["04_holdings_by_account"]))
    has_classification = bool(payload.get("lookthrough", {}).get("classification"))
    allocation_note = tr('message.1677874e5314') if has_classification else tr('message.a4acfb7e8bde')
    ranking.blocks.append(("paragraph",tr('message.ae68289cc647')+allocation_note if payload.get("lookthrough") else tr('message.b2d71d90b7e4')))
    sections.append(ranking)
    if payload.get("lookthrough"):
        from .lookthrough_reports import report_section
        sections.append(report_section(payload,charts))
        if payload['lookthrough'].get('classification'):
            from .classification_reports import report_section as classification_section
            sections.append(classification_section(payload,charts))

    returns = ReportSection(tr('message.af795e96bd58'),[tr('message.e674b5186421')])
    returns.blocks.append(("chart",charts["06_unrealized_percent"]))
    returns.blocks.append(("table",ReportTable([tr('message.ee026a237f21'),tr('message.6640987ad14b'),tr('message.cb6103440751')],
        [[currency,_money(sum((_decimal(row["book_native"]) for row in broker_positions if row["currency"] == currency),Decimal("0"))),
          _money(sum((_decimal(row["unrealized_native"]) for row in broker_positions if row["currency"] == currency),Decimal("0")))]
         for currency in ("CAD","USD")])))
    returns.blocks.append(("paragraph",tr('message.6bfb56f2daca')))
    sections.append(returns)

    matrix = payload["matrix"]
    crypto_keys = {(row["symbol"],row["currency"]) for row in securities if _is_crypto(row)}
    matrix_section = ReportSection(tr('message.a56ed7db700a'),[tr('message.d3d3f0f35bee')])
    matrix_section.blocks.append(("table",ReportTable([tr('message.ea76f31bac58')]+[_label(row["label"]) for row in matrix["accounts"]]+[tr('message.082f9c0d96ee')],
        [[row["symbol"]+" / "+(tr('message.142a77c8c976') if (row["symbol"],row["currency"]) in crypto_keys else "")+row["currency"]]+
         [_money(row["values"].get(account["account_id"],"0")) for account in matrix["accounts"]]+[_money(row["total_cad"])] for row in matrix["rows"]])))
    if crypto:
        matrix_section.blocks.append(("paragraph",tr('message.5530c65fc24b')))
    matrix_section.blocks.append(("chart",charts["08_account_weight_heatmap"]))
    matrix_section.blocks.append(("chart",charts["02_trading_currency"]))
    sections.append(matrix_section)

    cash = ReportSection(tr('message.3315d148654a'),[tr('message.c8b9faea6b4f')])
    cash.blocks.append(("table",ReportTable([tr('message.b0f18aa763de'),tr('message.26c1c5b41973'),tr('message.95a8f6413801'),tr('message.f3a7e3113505'),tr('message.72d7b6d76348'),tr('message.c96460f427df')],[[row["account_type"],row["currency"],_money(row["market_native"]),_money(row["market_cad"],4),_quantity(row["book_cad"]),_percent(row["portfolio_weight"])] for row in payload["cash_rows"]])))
    cash.blocks.append(("paragraph",tr('message.3c878705ba02', value0=_money(totals['cash_cad'], 4), value1=_percent(totals['cash_ratio']))))
    cash.blocks.append(("table",ReportTable([tr('message.72dd6bd5abe8'),tr('message.c59c2ea76818'),tr('message.c96460f427df'),tr('message.0cc371cd04b4')],[[row["label"],_money(row["total_cad"]),_percent(row["weight"]),str(row["position_count"])] for row in payload["instrument_types"]])))
    cash.blocks.append(("chart",charts["07_instrument_mix"]))
    cash.blocks.append(("paragraph",tr('message.b0703d402d54')))
    sections.append(cash)

    if crypto:
        sections.extend(_crypto_sections(crypto,charts))

    history = ReportSection(tr('message.727c6b700878'),[tr('message.dde368149f09', value0=_display_time(meta['baseline_as_of']))])
    missing_months=meta.get("missing_official_months",[])
    if missing_months:
        history.blocks.append(("paragraph",tr('message.3bf7b2b2b758')+"、".join(missing_months)+tr('message.0ad061fe16e3')))
    history.blocks.append(("table",ReportTable([tr('message.3c7b9e41cf97'),tr('message.1588dd8c9e73'),tr('message.f8950d4ecec5'),tr('message.665fa75fabe9'),tr('message.f3a7e3113505'),tr('message.e27d7ed41293'),tr('message.f3c0c439a1d2')],[[_display_time(row["as_of"]),SNAPSHOT_NAMES.get(row["kind"],row["kind"]),str(row["revision"]),DATA_STATUS.get(row.get("data_status"),tr('message.088b27d0ed00') if row["is_complete"] else tr('message.abf099167903')),_money(row["totals"]["total_cad"]),_money(row["totals"]["total_usd"]),_money(row["totals"]["total_twd"])] for row in payload["history"]],[1.7,.65,.4,1.1,1,1,1])))
    if not payload["changes"]["available"]:
        if len(payload["history"]) == 1:
            history.blocks.append(("paragraph",tr('message.bd139a922902')))
        else:
            history.blocks.append(("paragraph",tr('message.6bb67faf880f', value0=payload['changes']['reason'])))
    else:
        history.blocks.append(("paragraph",tr('message.740639bb6a8b')))
    comparisons = payload.get("comparisons",{"previous":payload["changes"]})
    comparison_names = {"previous":tr('message.ea393db88dc4'),"previous_month":tr('message.de9e1b2f587e'),"baseline":tr('message.ffc7559d8733')}
    comparison_rows = []
    for key,comparison in comparisons.items():
        if comparison["available"]:
            for currency in ["CAD","USD","TWD"]:
                values = comparison["totals"][f"total_{currency.lower()}"]
                comparison_rows.append([comparison_names[key],currency,_money(values["previous"]),
                                        _money(values["current"]),_money(values["change"]),_percent(values["change_pct"])])
        elif len(payload["history"])>1:
            history.blocks.append(("paragraph",f"{comparison_names[key]}：{comparison['reason']}"))
    if comparison_rows:
        history.blocks.append(("subheading",tr('message.7bcc981de7da')))
        history.blocks.append(("table",ReportTable([tr('message.02b15045df7b'),tr('message.26c1c5b41973'),tr('message.606937b3a0de'),tr('message.d6501adfa6a6'),tr('message.c6f1be901d39'),tr('message.676b149905d1')],comparison_rows,[1,.45,1,1,1,.7])))
    if payload["changes"]["available"]:
        history.blocks.append(("subheading",tr('message.699c569b364c')))
        history.blocks.append(("table",ReportTable([tr('message.b0f18aa763de'),tr('message.a7097b4c708b'),tr('message.f1ec1ef65833'),tr('message.7864710dd80c'),tr('message.6880bd185e5c')],
            [[_label(row["label"]),_money(row["previous_cad"]),_money(row["current_cad"]),_money(row["change_cad"]),
              _money(_decimal(row["weight_change"])*100)] for row in payload["changes"]["accounts"]])))
        changed = [row for row in payload["changes"]["positions"] if row["status"] != "held"
                   or any(_decimal(row[key] or "0") for key in ["quantity_change","market_change_cad","price_change","weight_change"])]
        if changed:
            change_names = {"new":tr('message.0006d696d8e1'),"removed":tr('message.9b949a5c73ff'),"held":tr('message.0d8e827fa78b')}
            history.blocks.append(("subheading",tr('message.3df420f668a0')))
            history.blocks.append(("table",ReportTable([tr('message.b0f18aa763de'),tr('message.ea76f31bac58'),tr('message.e01b94ddd5d5'),tr('message.f1d9b55661eb'),tr('message.f9ef6dc0aad5'),tr('message.d6d7b0ae53e2'),tr('message.6880bd185e5c')],
                [[_label(row["account_label"]),row["symbol"]+" / "+row["currency"],change_names[row["status"]],
                  _quantity(row["quantity_change"]),_money(row["market_change_cad"]),_money(row["price_change"]),
                  _money(_decimal(row["weight_change"])*100)] for row in changed],[1,.8,.6,.8,1,.8,.8])))
    statuses = {"not_provided":tr('message.be4f923bcf9f'),"partial":tr('message.7645536d5a03'),"complete":tr('message.43a65ee2d99a'),
                "no_external":tr('message.fb8185f49e9e'),"no_external_flows":tr('message.fb8185f49e9e'),"baseline":tr('message.d0c6ee28f8a1'),
                "incomplete_snapshot_or_scope":tr('message.40a5c856b667'),
                "unmatched_transfers":tr('message.fb1df38f6c57'),
                "no_external_conflicts_with_flows":tr('message.05d469ab51b8')}
    for period in payload["periods"]:
        label = tr('message.823bd040ec8b') if period["scope"] == "portfolio" else next((row["account_type"] for row in accounts if row["account_id"] == period["account_id"]),period["account_id"])
        history.blocks.append(("paragraph",tr('message.9659f6529d41', value0=label, value1=period['start_as_of'][:10], value2=period['end_as_of'][:10], value3=statuses.get(period['status'], period['status']))))
        if period["available"]:
            history.blocks.append(("table",ReportTable([tr('message.ac02ab2f3412'),tr('message.55391d947e88'),tr('message.7168008dc83b'),tr('message.466abe576898'),"Modified Dietz","XIRR"],[[_money(period["opening_cad"]),_money(period["closing_cad"]),_money(period["net_flow_cad"]),_money(period["investment_gain_cad"]),_percent(period["modified_dietz"]),_percent(period["xirr"])]])))
    history.blocks.append(("paragraph",tr('message.c9258da17e81')))
    if crypto:
        history.blocks.append(("paragraph",tr('message.e2eca274d0d7')))
        history.blocks.append(("paragraph",tr('message.5f9556d3f804')))
    if payload["cash_flows"]:
        flow_names = {"deposit":tr('message.b1e29d53556c'),"withdrawal":tr('message.d5f71d9bcf29'),"transfer_in":tr('message.d531216f273e'),
                      "transfer_out":tr('message.6ee505d2f0f9'),"income":tr('message.6a044ff0a5dc'),"fee":tr('message.685140186d79'),"internal":tr('message.712c4168c60c')}
        history.blocks.append(("subheading",tr('message.ee9cd0a3c700')))
        history.blocks.append(("table",ReportTable([tr('message.70d0c1b33626'),tr('message.b0f18aa763de'),tr('message.1588dd8c9e73'),tr('message.ee026a237f21'),tr('message.ddf1cb68aa8d'),tr('message.f3a7e3113505'),tr('message.f866d15e7a3a')],
            [[row["date"],_label(row["account_label"]),flow_names.get(row["flow_type"],row["flow_type"]),
              row["currency"],_money(row["amount"]),_money(row["amount_cad"]),
              str(row.get("transfer_id", ""))+" / "+row["source_filename"]] for row in payload["cash_flows"]],
            [.8,1,.8,.45,.8,.8,1.2])))
    sections.append(history)
    if "09_historical_values" in charts:
        growth = ReportSection(tr('message.2813d0b7d773'),[
            tr('message.ad829dcd12e5'),
            tr('message.3b3bdc7ac61f') if crypto
            else tr('message.47a10b05cc4a')])
        growth.blocks.append(("chart",charts["09_historical_values"]))
        sections.append(growth)

    if crypto and crypto.get("wallet"):
        overview.blocks.append(("paragraph",tr('message.57bcc0ef05d5')))
    quality = ReportSection(tr('message.614b9eb2830b'),[tr('message.4a05874a336e')])
    quality.blocks.append(("table",ReportTable([tr('message.cc87498b257e'),tr('message.21e5bce6a622')],[[tr('message.24cb4ea0990b'),payload["source"]["filename"]],[tr('message.ffbb4eaf304d'),str(payload["source"]["row_count"])],["SHA-256",payload["source"]["sha256"]],[tr('message.415f66c1b22d'),str(meta["snapshot_id"])],[tr('message.021995a25164'),tr('message.088b27d0ed00') if meta.get("account_coverage_complete",meta["is_complete"]) else tr('message.5c62c96cd767')],[tr('message.487479db4506'),DATA_STATUS.get(meta.get("data_status"),tr('message.088b27d0ed00') if meta["is_complete"] else tr('message.abf099167903'))]],[.8,3])))
    fx = payload["fx"]
    quality.blocks.append(("subheading",tr('message.2a289b3ab0f5')))
    quality.blocks.append(("table",ReportTable([tr('message.c7d457b3c743'),tr('message.e54b2cea632d'),tr('message.96aa6bf8893f'),tr('message.c21db84c0653')],[["CAD per USD",_money(fx["usd_cad"],4),fx["usd_cad_date"],fx["usd_cad_source"]],["TWD per USD",_money(fx["usd_twd"],4),fx["usd_twd_date"],fx["usd_twd_source"]]],[.8,.6,.7,2.2])))
    quality.blocks.append(("paragraph",tr('message.5e4dc5f5960f') if crypto
                           else tr('message.3b10ef8eff07')))
    quality.blocks.append(("paragraph",tr('message.a78030c8c6cc')))
    quality.blocks.append(("subheading",tr('message.428d14170380')))
    if payload["issues"]:
        severity_names = {"warning":tr('message.4ffef8f3113a'),"error":tr('message.157b2f926735'),"info":tr('message.c36897c8d26a')}
        quality.blocks.append(("table",ReportTable([tr('message.2173a021fd70'),tr('message.9a94b87315ec'),tr('message.e3bf3a629b89')],[[severity_names.get(row["severity"],row["severity"]),row["code"],row["message"]] for row in payload["issues"]],[.45,.9,3])))
    else:
        quality.blocks.append(("paragraph",tr('message.17813ab46933')))
    pending = tr('message.5e38cbb6fdbe') + ("" if has_classification else tr('message.d2b20263caca')) + tr('message.15850b6bada8')
    quality.blocks.append(("paragraph",tr('message.0ada9ca8b7d4')+pending+tr('message.9be53fa8bcbd')))
    sections.append(quality)

    catalog = ReportSection(tr('message.f7f09e8952c7'),[tr('message.bf91338d8778')])
    catalog.blocks.append(("table",ReportTable([tr('message.4f45fc8d4113'),"MIC",tr('message.9c635ea56676'),tr('message.9c99a627d667'),tr('message.72dd6bd5abe8')],[[row["symbol"],row["mic"],(tr('message.142a77c8c976') if _is_crypto(row) else "")+row["currency"],row["name"],row["security_type"]] for row in securities],[.6,.55,.6,2.4,1])))
    catalog.blocks.append(("table",ReportTable([tr('message.27a74cb7bf44'),tr('message.25af8968f7a4')],[[tr('message.121825fecbd5'),tr('message.24d274cf9db5')],[tr('message.10b7e40b8974'),tr('message.9f07dec16511')],[tr('message.aa35b146196e'),tr('message.1dc7a9ee41fb')],[tr('message.c9accc28a583'),tr('message.284fb25591a5')],[tr('message.d326cd1bb59e'),tr('message.6e135f4e1473')],[tr('message.f1d9b55661eb'),tr('message.c8af3654806f')]],[.8,3])))
    sections.append(catalog)
    return sections


def _markdown(sections: list[ReportSection], payload: dict, output: Path) -> None:
    lines = [tr('message.37c71e20e9ee'),"",tr('message.5f8d347aeb4f', value0=_display_time(payload['meta']['as_of'])),""]
    for section in sections:
        lines += [f"## {section.title}",""]
        for paragraph in section.introduction:
            lines += [paragraph,""]
        for kind,block in section.blocks:
            if kind == "table":
                table = block
                clean = lambda text: str(text).replace("|","\\|").replace("\n","<br>")
                lines += ["| "+" | ".join(map(clean,table.headers))+" |",
                          "| "+" | ".join("---" for _ in table.headers)+" |"]
                lines += ["| "+" | ".join(map(clean,row))+" |" for row in table.rows]+[""]
            elif kind == "chart":
                lines += [f"![{section.title}](charts/{block.name})",""]
            elif kind == "subheading":
                lines += [f"### {block}",""]
            else:
                lines += [str(block),""]
    output.write_text("\n".join(lines),encoding="utf-8")


def _pdf(sections: list[ReportSection], payload: dict, output: Path, font_path: Path) -> None:
    from PIL import Image as PillowImage
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

    font_name = "WealthLedger-" + current_context().locale + "-" + hashlib.sha256(font_path.read_bytes()).hexdigest()[:12]
    pdfmetrics.registerFont(TTFont(font_name,str(font_path)))
    page_width,_ = A4
    available_width = page_width-72
    styles = {
        "title":ParagraphStyle("LedgerTitle",fontName=font_name,fontSize=22,leading=28,textColor=colors.HexColor(INK),spaceAfter=13,wordWrap="LTR" if current_context().locale == "en-CA" else "CJK",keepWithNext=True),
        "body":ParagraphStyle("LedgerBody",fontName=font_name,fontSize=9,leading=14,textColor=colors.HexColor(INK),spaceAfter=6,wordWrap="LTR" if current_context().locale == "en-CA" else "CJK"),
        "small":ParagraphStyle("LedgerSmall",fontName=font_name,fontSize=7.2,leading=10,textColor=colors.HexColor(INK),wordWrap="LTR" if current_context().locale == "en-CA" else "CJK"),
        "heading":ParagraphStyle("LedgerHeading",fontName=font_name,fontSize=11,leading=15,textColor=colors.HexColor(TEAL),spaceBefore=8,spaceAfter=7,wordWrap="LTR" if current_context().locale == "en-CA" else "CJK",keepWithNext=True),
    }
    story = []
    for index,section in enumerate(sections):
        if index:
            story.append(PageBreak())
        story.append(Paragraph(f"{index+1:02d}  {escape(section.title)}",styles["title"]))
        for paragraph in section.introduction:
            story.append(Paragraph(escape(paragraph),styles["body"]))
        story.append(Spacer(1,7))
        for kind,block in section.blocks:
            if kind == "table":
                table = block
                weights = table.widths or [1.0]*len(table.headers)
                widths = [available_width*weight/sum(weights) for weight in weights]
                cells = [[Paragraph(escape(str(cell)),styles["small"]) for cell in row] for row in [table.headers]+table.rows]
                widget = Table(cells,colWidths=widths,repeatRows=1,hAlign="LEFT")
                widget.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DFEBEE")),
                    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor(PALE)]),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),5),
                    ("RIGHTPADDING",(0,0),(-1,-1),5),("TOPPADDING",(0,0),(-1,-1),5),
                    ("BOTTOMPADDING",(0,0),(-1,-1),5),("LINEBELOW",(0,0),(-1,0),.6,colors.HexColor("#A8C3CA"))]))
                story += [widget,Spacer(1,10)]
            elif kind == "chart":
                with PillowImage.open(block) as raster:
                    width,height = raster.size
                display_width = available_width
                display_height = height/width*display_width
                if display_height>320:
                    display_height=320
                    display_width=width/height*display_height
                story += [Image(str(block),width=display_width,height=display_height,hAlign="CENTER"),Spacer(1,8)]
            elif kind == "subheading":
                story.append(Paragraph(escape(str(block)),styles["heading"]))
            else:
                story.append(Paragraph(escape(str(block)),styles["body"]))

    def footer(canvas,doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#CBDCDF"))
        canvas.line(36,36,page_width-36,36)
        canvas.setFont(font_name,7.2)
        canvas.setFillColor(colors.HexColor(INK))
        canvas.drawString(36,23,tr('message.c75da514130f'))
        canvas.drawRightString(page_width-36,23,tr('message.7da04b9b3a20', value0=doc.page))
        canvas.restoreState()

    document = SimpleDocTemplate(str(output),pagesize=A4,rightMargin=36,leftMargin=36,
                                  topMargin=34,bottomMargin=48,title=tr('message.8c7463e935f6'),author="Wealth Ledger")
    def canvas_factory(*args, **kwargs):
        from reportlab.pdfgen.canvas import Canvas
        canvas = Canvas(*args, **kwargs)
        from reportlab.pdfbase.pdfdoc import PDFString
        canvas._doc.Catalog.Lang = PDFString(current_context().locale)
        return canvas
    document.build(story,onFirstPage=footer,onLaterPages=footer,canvasmaker=canvas_factory)


@localized
def generate_reports(payload: dict, output_dir: Path, *, cache_directory: Path | None = None) -> dict:
    """Create shared PNG charts, Markdown and a font-embedded PDF report."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    from .i18n import display_payload, current_context
    display = display_payload(payload)
    font = _font_path()
    token = _CACHE.set(cache_directory)
    try:
        chart_paths = _charts(display,output_dir/"charts",font)
    finally:
        _CACHE.reset(token)
    sections = _sections(display,chart_paths)
    for section in sections:
        section.title = legacy_text(section.title)
        section.introduction = [legacy_text(p) for p in section.introduction]
        for kind, block in section.blocks:
            if kind == "table":
                block.headers = [legacy_text(v) for v in block.headers]
                block.rows = [[legacy_text(v) for v in row] for row in block.rows]
        section.blocks = [(kind, legacy_text(block) if isinstance(block, str) and kind != "chart" else block) for kind, block in section.blocks]
    markdown,pdf = output_dir/"report.md",output_dir/"report.pdf"
    _markdown(sections,payload,markdown)
    _pdf(sections,payload,pdf,font)
    supplements = []
    crypto = payload.get("crypto")
    if crypto and crypto.get("opening"):
        audit_path = output_dir / "btc-opening-audit.json"
        audit_path.write_text(json.dumps({
            "schema_version": 1,
            "report_as_of": payload["meta"]["as_of"],
            "original_bull_ledger_assumptions": crypto["assumptions"],
            "effective_pre_bull_opening_declaration": crypto["opening"],
            "quantity_assumptions_status": "superseded_by_separate_pre_bull_opening",
            "cash_assumptions_status": "original_cash_basis_retained",
            "cost_policy": "Opening quantity does not establish acquisition cost or historical contributions."
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        supplements.append(audit_path.name)
    if crypto:
        from .btc_performance import btc_cost_estimate
        estimate_path = output_dir / "btc-cost-estimate.json"
        estimate_path.write_text(json.dumps({
            "schema_version": 1, "report_as_of": payload["meta"]["as_of"],
            "estimate": btc_cost_estimate(crypto),
            "actual_full_cost_status": crypto.get("valuation", {}).get("cost_status"),
            "policy": "Presentation estimate only; never actual opening costs, contributions or realized returns."
        }, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        supplements.append(estimate_path.name)
    return {"markdown":str(markdown),"pdf":str(pdf),"charts":{key:str(path) for key,path in chart_paths.items()},"supplements":supplements,"localization":current_context().metadata()}
