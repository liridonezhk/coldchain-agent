"""
Specialist agents (heuristic engine) — monitoring, demand, replenishment.

Each agent is a distinct reasoning job with distinct inputs. The replenishment scoring
is a CLEAR, COMMENTED heuristic — judges want to follow the reasoning, not admire a black
box. This is the DEFAULT, deterministic engine used for the recorded demo; the LLM-driven
ADK counterparts (same jobs, same MCP tools) live in agents/adk_agents.py (`--engine adk`).
"""
from __future__ import annotations
from mcp_server import server as mcp


def monitoring_agent() -> list[dict]:
    """
    Read inventory + the temperature feed and emit structured 'concerns'.
    A concern = something that threatens spoilage/stockout and may need action.
    """
    concerns = []
    temps = mcp.tool_get_temp_feed()
    for item in mcp.tool_get_inventory():
        bid = item["batch_id"]
        if not item["temp_ok"]:
            concerns.append({
                "batch_id": bid, "product": item["product"],
                "type": "TEMP_EXCURSION",
                "detail": f"temp {temps.get(bid)}C out of range; shelf life collapsed",
                "severity": "high",
            })
        elif item["days_to_expiry"] <= 4:
            concerns.append({
                "batch_id": bid, "product": item["product"],
                "type": "NEAR_EXPIRY",
                "detail": f"{item['days_to_expiry']}d to expiry",
                "severity": "medium",
            })
    return concerns


def demand_agent() -> dict[str, int]:
    """
    Estimate near-term daily pull per product.
    Possible extension: enrich one product's demand with an external signal (a weather
    or local-event web search) to demonstrate live tool use.
    """
    products = {i["product"] for i in mcp.tool_get_inventory()}
    return {p: mcp.tool_get_demand(p) for p in products}


def replenishment_agent(concerns: list[dict], demand: dict[str, int]) -> list[dict]:
    """
    The brain: balance spoilage vs. stockout vs. holding cost into proposed actions.

    Heuristic, intentionally legible:
      - coverage_days = available_units / daily_demand
      - a TEMP_EXCURSION zeroes that batch's contribution -> coverage gap -> urgent reorder
      - low coverage => reorder; very low + expedite available => propose expedite (may gate)
    """
    inv = {i["batch_id"]: i for i in mcp.tool_get_inventory()}

    # available units per product, excluding spoiled/excursion batches
    avail: dict[str, int] = {}
    for i in inv.values():
        if i["effective_shelf_days"] > 0:
            avail[i["product"]] = avail.get(i["product"], 0) + i["units"]

    actions = []
    for product, daily in demand.items():
        units = avail.get(product, 0)
        coverage = units / daily if daily else 99
        # Reorder when cover drops under 3 days (perishables need a tight buffer).
        # Below 1 day of cover, the gap is urgent -> propose an expedite (which may gate).
        if coverage < 3:
            expedite = coverage < 1
            order = mcp.tool_place_order(product, units=daily * 5, expedite=expedite)
            actions.append({
                "product": product,
                "reason": f"coverage {coverage:.1f}d (units {units} / demand {daily}/d)",
                "order": order,
                "urgency": "high" if expedite else "medium",
            })
    return actions
