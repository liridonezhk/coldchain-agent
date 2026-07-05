"""
Demo runner (used live in the video). Two cycles + the approval gate.

  python -m demo.run --cycle normal
  python -m demo.run --cycle excursion

Engine selector (default = heuristic, the deterministic path used for recording):

  python -m demo.run --cycle excursion --engine adk   # real ADK agents over MCP
"""
from __future__ import annotations
import argparse
from agents import orchestrator
from data import sim


def human_gate(action: dict) -> bool:
    o = action["order"]
    print("\n  ⛔ APPROVAL REQUIRED (irreversible, over auto-approve limit)")
    print(f"     Expedite {o['units']} units of {o['product']} — ${o['cost_usd']}")
    return input("     Approve? [y/N] ").strip().lower() == "y"


SHOW_LIMIT = 15  # cap the printed list so large datasets stay readable


def show(ranked):
    print("\n  RANKED ACTIONS" + (f"  ({len(ranked)} total)" if ranked else ""))
    print("  " + "-" * 60)
    for a in ranked[:SHOW_LIMIT]:
        o = a["order"]
        print(f"  [{a['urgency']:>6}] {a['product']:<22.22} {o['status']:<18} "
              f"${o['cost_usd']:<5} — {a['reason']}")
    if len(ranked) > SHOW_LIMIT:
        print(f"  … and {len(ranked) - SHOW_LIMIT} more")
    if not ranked:
        print("  (no actions needed — steady state)")


def run_heuristic(cycle: str):
    """Default engine: deterministic Python specialists + orchestrator."""
    ranked = orchestrator.run_cycle(approve_fn=human_gate)
    show(ranked)


def run_adk(cycle: str):
    """Opt-in engine: real ADK agents reasoning over the MCP server."""
    import asyncio
    from agents import adk_agents
    print("\n  [engine: adk] running multi-agent ADK cycle over the MCP server...")
    try:
        final_text = asyncio.run(adk_agents.run_cycle_adk(approve_fn=human_gate, cycle=cycle))
    except RuntimeError as e:
        print(f"\n  ⚠  {e}\n  (Run without --engine adk to use the default heuristic engine.)")
        return
    print("\n" + (final_text or "  (no final response)"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cycle", choices=["normal", "excursion"], default="normal")
    p.add_argument("--engine", choices=["heuristic", "adk"], default="heuristic",
                   help="heuristic (default, deterministic) or adk (real LLM agents; needs a key)")
    p.add_argument("--as-of", metavar="YYYY-MM-DD",
                   help="override the simulation date (e.g. 2026-07-02) to see holiday demand uplift")
    args = p.parse_args()

    if args.as_of:
        from datetime import datetime as _dt
        sim.set_today(_dt.strptime(args.as_of, "%Y-%m-%d").date())

    holiday = sim.active_holiday()
    if holiday:
        print(f"  🎉 Holiday demand uplift active: {holiday} "
              f"— elevated pull on perishable categories (dairy, produce, meat, bakery).")

    # The excursion event is injected identically regardless of engine.
    if args.cycle == "excursion":
        target = sim.inject_temp_excursion()
        product = next((b["product"] for b in sim.get_inventory()
                        if b["batch_id"] == target), target)
        print(f">>> EVENT: temperature excursion on {target} ({product})")

    if args.engine == "adk":
        run_adk(args.cycle)
    else:
        run_heuristic(args.cycle)


if __name__ == "__main__":
    main()
