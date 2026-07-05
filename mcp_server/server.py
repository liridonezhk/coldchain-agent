"""
MCP server — the data/tool layer the agents call.

This exposes data/sim.py as Model Context Protocol tools. Four read tools are
unrestricted; the ONE side-effectful tool (place_order) carries an `irreversible`
flag and a `requires_approval` flag the orchestrator checks before allowing
execution — this is where the security story lives.

Two ways to consume the same tools:

  * In-process (used by the demo): import the `tool_*` functions or the `TOOLS`
    registry directly. Runs on the standard library alone — no extra deps.
  * Over MCP (used by the ADK agents / any MCP client): run this module as a
    server and connect a client to it:

        python -m mcp_server.server        # serves the tools over stdio

The MCP server is built only if the `mcp` package is installed, so the demo keeps
running on the stdlib even before the agent layer is wired up.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import sim

# Cost above which an order must NOT auto-execute — must pause for human approval.
AUTO_APPROVE_LIMIT_USD = 500


# --- read tools -----------------------------------------------------------
def tool_get_inventory() -> list[dict]:
    """Current inventory: one record per batch with units, expiry, temp status, and effective shelf life."""
    return sim.get_inventory()


def tool_get_temp_feed() -> dict:
    """Latest refrigeration temperature reading (°C) per batch_id."""
    return sim.get_temp_feed()


def tool_get_supplier_status() -> dict:
    """Per-product supplier info: lead times, expedite option, and expedite cost."""
    return sim.get_supplier_status()


def tool_get_demand(product: str) -> int:
    """Estimated near-term daily pull (units/day) for a single product."""
    return sim.get_demand_estimate(product)


# --- side-effectful tool (gated) -----------------------------------------
def tool_place_order(product: str, units: int, expedite: bool = False) -> dict:
    """
    Propose a replenishment order. If an expedite's cost exceeds AUTO_APPROVE_LIMIT_USD,
    the result is marked requires_approval=True and irreversible=True — the orchestrator
    must NOT execute it without a human yes. (Security feature, demoed in Beat 3.)
    """
    supplier = sim.get_supplier_status().get(product, {})
    cost = supplier.get("expedite_cost", 0) if expedite else 0
    requires_approval = expedite and cost > AUTO_APPROVE_LIMIT_USD
    return {
        "product": product,
        "units": units,
        "expedite": expedite,
        "cost_usd": cost,
        "irreversible": expedite,
        "requires_approval": requires_approval,
        "status": "PROPOSED",
    }


# In-process registry (back-compat for direct callers like the demo specialists).
# Maps the public MCP tool name -> implementation.
TOOLS = {
    "get_inventory": tool_get_inventory,
    "get_temp_feed": tool_get_temp_feed,
    "get_supplier_status": tool_get_supplier_status,
    "get_demand": tool_get_demand,
    "place_order": tool_place_order,
}


# --- real MCP server (optional; demo runs without `mcp` installed) --------
try:
    from mcp.server.fastmcp import FastMCP
    _MCP_AVAILABLE = True
except ImportError:  # mcp not installed — in-process callers still work fine
    FastMCP = None  # type: ignore
    _MCP_AVAILABLE = False


def build_server() -> "FastMCP":
    """
    Construct the FastMCP server, registering every entry in TOOLS as an MCP tool
    under its public name. Tool descriptions come from each function's docstring.

    Raises a clear error if `mcp` isn't installed (pip install -r requirements.txt).
    """
    if not _MCP_AVAILABLE:
        raise RuntimeError(
            "The `mcp` package is not installed. Install it with "
            "`pip install -r requirements.txt` to run the MCP server. "
            "(In-process tool calls via TOOLS / tool_* still work without it.)"
        )
    server = FastMCP("coldchain")
    for name, fn in TOOLS.items():
        # FastMCP reads the input schema from type hints and the description from
        # the docstring; we just pin the public tool name.
        server.tool(name=name)(fn)
    return server


if __name__ == "__main__":
    if _MCP_AVAILABLE:
        # Serve the tools over stdio for any MCP client (e.g. the ADK agents).
        build_server().run()
    else:
        # Stdlib smoke test: prove the in-process tool layer responds.
        print("MCP tools available:", list(TOOLS.keys()))
        print("(`mcp` not installed — run `pip install -r requirements.txt` to serve over MCP.)")
        print("Inventory sample:", tool_get_inventory()[0])
