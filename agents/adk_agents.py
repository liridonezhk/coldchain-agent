"""
ADK agent layer — the multi-agent system, wired to the MCP server.

This is the "real agents" path. It defines the three specialists and the
orchestrator as ADK ``LlmAgent``s whose tools are served by mcp_server/server.py
over stdio (an ``MCPToolset``). The deterministic heuristic engine in
``agents/specialists.py`` + ``agents/orchestrator.py`` remains the default demo
path; this module is opt-in via ``python -m demo.run --engine adk``.

Why two engines:
  * Heuristic engine — deterministic, no API key, warm and reproducible for the
    recorded 5-minute video. This is what the demo runs by default.
  * ADK engine (this file) — genuine LLM agents reasoning over the MCP tools,
    proving the multi-agent-ADK and MCP-server concepts end-to-end.

The security gate is enforced DETERMINISTICALLY here, not left to the LLM: a
``before_tool_callback`` intercepts every ``place_order`` call, and if the order
is irreversible and over the auto-approve limit it pauses for human approval
before the tool is allowed to run.

----------------------------------------------------------------------------
Running this path (needs network + a model key — can't run in an offline box):

    pip install -r requirements.txt          # installs google-adk + mcp
    export GOOGLE_API_KEY=...                 # Google AI Studio key (default model)
    python -m demo.run --engine adk --cycle excursion

The imports are optional: if google-adk isn't installed, importing this module
still succeeds and ``build_orchestrator()`` raises a clear install message, so
the heuristic demo keeps working untouched.
----------------------------------------------------------------------------
"""
from __future__ import annotations
import os
import sys

# ---------------------------------------------------------------------------
# Model backend (single swap point).
# Default: Gemini (native ADK, simplest path — needs GOOGLE_API_KEY).
# To use Claude instead, install litellm and replace MODEL with the LiteLlm line.
# ---------------------------------------------------------------------------
MODEL = "gemini-2.0-flash"
# from google.adk.models.lite_llm import LiteLlm
# MODEL = LiteLlm(model="anthropic/claude-sonnet-4-5")   # needs ANTHROPIC_API_KEY + litellm

# Path to launch the MCP server as a subprocess (stdio transport).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load THIS project's .env by explicit path, and let it win over stale shell vars.
# Using an explicit path (not find_dotenv) means we never walk UP the tree and pick
# up another project's .env. If python-dotenv isn't installed, plain shell env vars
# still work. Copy .env.example -> .env and fill in your key.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=True)
except ImportError:
    pass


# --- optional ADK imports (heuristic demo runs without google-adk) ---------
try:
    from google.adk.agents import LlmAgent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools.agent_tool import AgentTool
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
    from mcp import StdioServerParameters
    from google.genai import types
    _ADK_AVAILABLE = True
except ImportError:  # google-adk / mcp not installed
    _ADK_AVAILABLE = False


# Reuse the SAME threshold + cost logic the MCP tool uses, so the gate is
# consistent across both engines.
from mcp_server.server import AUTO_APPROVE_LIMIT_USD  # noqa: E402
from data import sim  # noqa: E402

APP_NAME = "coldchain"


# --- the deterministic security gate (ADK before_tool_callback) ------------
def _approval_gate(tool, args, tool_context):
    """
    Intercept every place_order call. If the proposed order is an expedite whose
    cost exceeds AUTO_APPROVE_LIMIT_USD, it is irreversible + over budget: pause
    and ask a human. Returning a dict short-circuits the tool (it never runs);
    returning None lets the call proceed normally.

    The human prompt function is read off tool_context.state["approve_fn"].
    """
    if getattr(tool, "name", "") != "place_order":
        return None
    if not args.get("expedite"):
        return None

    product = args.get("product", "")
    cost = sim.get_supplier_status().get(product, {}).get("expedite_cost", 0)
    if cost <= AUTO_APPROVE_LIMIT_USD:
        return None  # within auto-approve limit — allow

    approve_fn = tool_context.state.get("approve_fn")
    action = {"order": {"product": product, "units": args.get("units"), "cost_usd": cost}}
    if approve_fn and approve_fn(action):
        return None  # human said yes — allow the real tool to execute

    # Blocked: hand the model a structured "paused" result instead of executing.
    return {
        "product": product,
        "units": args.get("units"),
        "cost_usd": cost,
        "irreversible": True,
        "requires_approval": True,
        "status": "PENDING_APPROVAL",
    }


def _mcp_toolset() -> "MCPToolset":
    """Connect to the project's MCP server over stdio (same tools the demo calls)."""
    return MCPToolset(
        connection_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server"],
            cwd=_PROJECT_ROOT,
        )
    )


def build_orchestrator() -> "LlmAgent":
    """
    Build the multi-agent system: three specialists + an orchestrator coordinator,
    all sharing one MCP toolset. The orchestrator delegates to the specialists
    (exposed as AgentTools), then synthesizes and ranks.

    Raises a clear error if google-adk isn't installed.
    """
    if not _ADK_AVAILABLE:
        raise RuntimeError(
            "google-adk is not installed. Run `pip install -r requirements.txt` "
            "and set a model API key (e.g. GOOGLE_API_KEY) to use --engine adk. "
            "The default heuristic engine needs neither."
        )

    tools = _mcp_toolset()

    monitoring = LlmAgent(
        model=MODEL,
        name="monitoring_agent",
        description="Flags spoilage/stockout risks from inventory, expiry, and the temp feed.",
        instruction=(
            "You monitor a cold-chain warehouse. Call get_inventory and get_temp_feed. "
            "Emit a concise list of CONCERNS: any batch whose temperature is out of range "
            "(shelf life collapses to zero) or within 4 days of expiry. For each, give "
            "batch_id, product, the concern type, and a one-line reason."
        ),
        tools=[tools],
    )

    demand = LlmAgent(
        model=MODEL,
        name="demand_agent",
        description="Estimates near-term daily demand per product.",
        instruction=(
            "You estimate near-term demand. For each product in inventory, call get_demand "
            "and report estimated units/day. Keep it terse: product -> units/day."
        ),
        tools=[tools],
    )

    replenishment = LlmAgent(
        model=MODEL,
        name="replenishment_agent",
        description="Proposes reorders, balancing spoilage vs. stockout vs. holding cost.",
        instruction=(
            "You decide reorders. Using the monitoring concerns and demand estimates, compute "
            "coverage_days = available_units / daily_demand, EXCLUDING any batch whose shelf "
            "life has collapsed (temperature excursion). If coverage < 3 days, propose a "
            "reorder via place_order. If coverage < 1 day, propose an EXPEDITE (expedite=True) "
            "and mark it urgent. Always call place_order to register a proposal; never claim an "
            "order executed on your own — the system gates expensive irreversible ones."
        ),
        tools=[tools],
    )

    orchestrator = LlmAgent(
        model=MODEL,
        name="orchestrator",
        description="Coordinates the specialists and ranks the final actions.",
        instruction=(
            "You are the orchestrator for a cold-chain inventory agent. Run the cycle: "
            "1) call monitoring_agent for concerns, 2) call demand_agent for demand, "
            "3) call replenishment_agent for proposed orders. Then output a single RANKED "
            "ACTION LIST ordered by urgency (high -> medium -> low). For each action show: "
            "urgency, product, status, cost, and the one-line reason. Any order marked "
            "PENDING_APPROVAL must be shown as paused, NOT executed."
        ),
        tools=[AgentTool(agent=monitoring), AgentTool(agent=demand), AgentTool(agent=replenishment)],
        before_tool_callback=_approval_gate,
    )
    return orchestrator


async def run_cycle_adk(approve_fn=None, cycle: str = "normal") -> str:
    """
    Run one decision cycle through the ADK agents and return the orchestrator's
    final ranked-action text. `approve_fn(action) -> bool` is the human gate,
    invoked deterministically by _approval_gate on expensive expedites.

    Note: the excursion event must already be injected by the caller (demo.run)
    before this is called, exactly as in the heuristic path.
    """
    if not _ADK_AVAILABLE:
        raise RuntimeError("google-adk not installed; see build_orchestrator().")

    orchestrator = build_orchestrator()
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME, user_id="operator", session_id="cycle"
    )
    # Make the human-approval callback reachable from the tool callback.
    session.state["approve_fn"] = approve_fn

    runner = Runner(agent=orchestrator, app_name=APP_NAME, session_service=session_service)
    prompt = types.Content(
        role="user",
        parts=[types.Part(text=f"Run the {cycle} cycle and produce the ranked action list.")],
    )

    final_text = ""
    async for event in runner.run_async(
        user_id="operator", session_id="cycle", new_message=prompt
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text or ""
    return final_text
