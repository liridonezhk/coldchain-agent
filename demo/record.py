"""
One-command demo runner for recording the video.

Runs the whole arc in a single process, pausing between beats so you control the pacing
while you narrate. You never switch commands on camera — just press Enter to advance and
type `y` at the approval gate.

    python -m demo.record

Beat 1: normal cycle (calm).   Beat 2+3: excursion -> re-rank -> approval gate.
Records best on the small sample (deterministic). If the full Kaggle dataset is active,
this prints a heads-up first.
"""
from __future__ import annotations
from demo.run import show, human_gate
from agents import orchestrator
from data import sim

BAR = "=" * 64


def pause(msg="\n  ▶ [Press Enter] "):
    try:
        input(msg)
    except EOFError:
        pass  # allows piping for a dry run


def banner(title: str):
    print("\n" + BAR)
    print(f"  {title}")
    print(BAR)


def main():
    print("\n" + BAR)
    print("  COLD-CHAIN INVENTORY OPTIMIZATION AGENT — live demo")
    print(BAR)

    seed = sim.SEED_CSV.split("/")[-1]
    if "full" in seed:
        print(f"\n  ⚠ Running on the FULL dataset ({len(sim.INVENTORY)} items: {seed}).")
        print("    For the cleanest recording, use the 6-row sample instead —")
        print("    rename data/seed/grocery_inventory_full.csv aside and re-run.")
    else:
        print(f"\n  Data: {seed} ({len(sim.INVENTORY)} items).")

    pause("\n  ▶ [Press Enter to run BEAT 1 — the normal cycle] ")

    banner("BEAT 1 — NORMAL CYCLE  (steady state)")
    print("  Monitoring reads inventory + temps · Demand estimates pull ·")
    print("  Replenishment weighs spoilage vs. stockout vs. cost · Orchestrator ranks.")
    ranked = orchestrator.run_cycle(approve_fn=human_gate)
    show(ranked)

    pause("\n  ▶ [Press Enter to inject the temperature excursion — BEAT 2] ")

    banner("BEAT 2 — THE EXCURSION  (a fridge drifts out of range)")
    target = sim.inject_temp_excursion()
    product = next((b["product"] for b in sim.get_inventory()
                    if b["batch_id"] == target), target)
    print(f"  >>> EVENT: temperature excursion on {target} ({product})")
    print("  Monitoring catches the breach · that batch's shelf life collapses ·")
    print("  Replenishment recomputes · the top action is now urgent AND expensive.")
    print("\n  BEAT 3 — THE GATE: the agent stops and asks before it acts.")
    ranked = orchestrator.run_cycle(approve_fn=human_gate)
    show(ranked)

    banner("RECAP")
    print("  Multi-agent ADK orchestration · MCP server tool layer ·")
    print("  cost-threshold approval gate · scheduled autonomous run.")
    print("  Code + setup in the repo. Thanks for watching.\n")


if __name__ == "__main__":
    main()
