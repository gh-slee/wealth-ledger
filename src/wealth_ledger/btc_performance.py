"""Bull-price cost estimates, separate from actual complete BTC holding costs."""
from decimal import Decimal, localcontext


def btc_cost_estimate(crypto):
    """Apply the completed Bull purchase average to all current BTC equivalents.

    This explicitly selected proxy covers opening quantities and unexplained
    balance differences. It never supplies actual historical costs or returns.
    """
    with localcontext() as context:
        context.prec = 80
        purchased = Decimal(str(crypto["purchased_btc_equivalent_qty"]))
        spend = Decimal(str(crypto["total_buy_cost_cad"]))
        quantity = Decimal(str(crypto["btc_equivalent_qty"]))
        average = spend / purchased if purchased > 0 else None
        cost = quantity * average if average is not None else None
        valuation = crypto.get("valuation", {})
        market = Decimal(str(valuation["market_cad"])) if valuation.get("market_cad") is not None else None
        policy = crypto.get("cost_estimate_policy", "bull_average_proxy")
        if policy not in ("actual_only", "bull_average_proxy"):
            raise ValueError("Unknown BTC reporting cost policy")
        if policy == "actual_only":
            return {"method": "actual_costs_only", "quantity_btc": quantity,
                    "purchase_quantity_btc": purchased, "purchase_spend_cad": spend,
                    "average_price_cad_per_btc": average, "estimated_cost_cad": None,
                    "market_cad": market, "estimated_gain_cad": None, "estimated_return": None,
                    "status": "proxy_disabled", "note": "未啟用 Bull 均價推估；實際成本及損益依完整性條件呈現",
                    "unavailable_reason": "未啟用成本代理；可明確選用 bull_average_proxy"}
        gain = market - cost if market is not None and cost is not None else None
        rate = gain / cost if gain is not None and cost > 0 else None
        return {"method": "bull_average_applied_to_all_btc", "quantity_btc": quantity,
                "purchase_quantity_btc": purchased, "purchase_spend_cad": spend,
                "average_price_cad_per_btc": average, "estimated_cost_cad": cost,
                "market_cad": market, "estimated_gain_cad": gain, "estimated_return": rate,
                "status": "estimated" if gain is not None else "no_completed_purchases" if average is None else "no_valuation",
                "note": "Bull 均價推估全部 BTC；含期初量及未解釋差額，不是實際完整成本",
                "unavailable_reason": None if gain is not None else "未能計算；尚無已完成 Bull 購入，無參考均價" if average is None else "未能計算；尚無估值價格"}
