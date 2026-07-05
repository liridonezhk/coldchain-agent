"""
Orchestrator (heuristic engine) — the coordinator that owns the tradeoff and the safety gate.

Collects specialist outputs, produces a ranked action list, and ENFORCES the
human-approval gate on any action flagged requires_approval (Beat 3).

This is the DEFAULT, deterministic engine: no API key, warm and reproducible for the
recorded demo. The LLM-driven counterpart lives in agents/adk_agents.py (`--engine adk`),
where an ADK orchestration agent does the same synthesis/ranking over the MCP tools.
"""
from __future__ import annotations
from agents import specialists

URGENCY_RANK = {"high": 0, "medium": 1, "low": 2}


def run_cycle(approve_fn=None) -> list[dict]:
    """
    One full decision cycle.
    `approve_fn(action) -> bool` is the human-in-the-loop gate. If None, gated actions
    are surfaced as PENDING_APPROVAL and never auto-executed.
    """
    concerns = specialists.monitoring_agent()
    demand = specialists.demand_agent()
    actions = specialists.replenishment_agent(concerns, demand)

    ranked = sorted(actions, key=lambda a: URGENCY_RANK.get(a["urgency"], 9))

    for a in ranked:
        order = a["order"]
        if order.get("requires_approval"):
            # SECURITY GATE: irreversible + over cost threshold -> never auto-execute.
            if approve_fn and approve_fn(a):
                order["status"] = "APPROVED_EXECUTED"
            else:
                order["status"] = "PENDING_APPROVAL"
        else:
            order["status"] = "AUTO_EXECUTED"

    return ranked


if __name__ == "__main__":
    for a in run_cycle():
        o = a["order"]
        print(f"[{a['urgency']:>6}] {a['product']:<8} {o['status']:<18} "
              f"${o['cost_usd']:<5} — {a['reason']}")
