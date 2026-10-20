"""Charts of valued observations and acquisition activity, never inferred flows."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal as D
import math

from .reporting import _with_render_cache, _charts, TEAL, BLUE, INK
from .source_presentation import label, monthly_purchases


@_with_render_cache
def source_charts(payload, directory, font):
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties
    from .source_projection import ProjectionError
    for row in payload["positions"]+payload["cash_rows"]:
        if not math.isfinite(float(row["market_cad"])):
            raise ProjectionError("source_report_numeric_range")
    directory.mkdir(parents=True,exist_ok=True)
    view=deepcopy(payload)
    view["accounts"]=[row for row in view["accounts"] if row["total_cad"] is not None]
    view["totals"]["total_cad"]=view["totals"]["total_cad"] or "0"
    # None is replaced only in this empty plotting frame, never the report input.
    view["history"]=[]
    result=_charts(view,directory,font)
    plt.rcParams.update({"font.family":FontProperties(fname=str(font)).get_name(),"font.size":10,"axes.unicode_minus":False})
    def save(key,figure):
        path=directory/(key+".png")
        figure.suptitle(label("chart_scope"),fontsize=9)
        figure.savefig(path,dpi=190,bbox_inches="tight",pad_inches=.2);plt.close(figure);result[key]=path
    history=payload["history"]
    if len({row["as_of"] for row in history})>=2:
        figure,axes=plt.subplots(3,1,figsize=(10.5,7.5),constrained_layout=True)
        for axis,unit in zip(axes,("CAD","USD","TWD")):
            axis.plot([datetime.fromisoformat(row["as_of"]) for row in history],
                      [float(row["totals"]["total_"+unit.lower()]) if row["totals"]["total_"+unit.lower()] is not None else math.nan for row in history],marker="o",color=TEAL)
            axis.set_ylabel(unit);axis.grid(alpha=.2)
        axes[0].set_title(label("history"),loc="left")
        save("09_historical_values",figure)
    if payload["source_crypto"]["in_scope"]:
        rows=monthly_purchases(payload)
        for key,field,title,unit in (("17_source_btc_acquisitions","quantity","acquisition_chart","BTC"),("18_source_btc_spending","spend","spending_chart","CAD")):
            figure,axis=plt.subplots(figsize=(10.5,4.3),constrained_layout=True)
            axis.bar([row["month"] for row in rows],[float(row[field]) for row in rows],color=TEAL)
            if not rows:axis.text(.5,.5,label("no_acquisitions"),ha="center",va="center",transform=axis.transAxes)
            axis.set_title(label(title),loc="left");axis.set_ylabel(unit);axis.grid(axis="y",alpha=.2)
            axis.tick_params(axis="x",rotation=35)
            save(key,figure)
        reconciliations=payload["source_projection"]["wallet"]["reconciliations"]
        if reconciliations:
            figure,axis=plt.subplots(figsize=(10.5,4.3),constrained_layout=True)
            known=[row for row in reconciliations if row["residual_btc"] is not None]
            axis.bar([row["balance_id"] for row in known],[float(row["residual_btc"]) for row in known],color=BLUE)
            if not known:axis.text(.5,.5,label("unknown"),ha="center",va="center",transform=axis.transAxes)
            axis.axhline(0,color=INK,linewidth=.6);axis.set_title(label("reconciliation"),loc="left");axis.set_ylabel("BTC")
            save("16_btc_wallet_reconciliation",figure)
    return result
