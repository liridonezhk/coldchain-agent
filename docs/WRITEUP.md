# Cold-Chain Inventory Optimization Agent

**A multi-agent system that watches perishable inventory, reasons over conflicting business goals, and knows when to act on its own — and when to stop and ask a human.**

*Track: **Agents for Business** — an agent that attacks a problem with real cost and revenue on the line: perishable inventory loss.*

**Code:** `<your public GitHub repo URL>` · **Video:** `<your YouTube URL>`

---

## The problem

Cold-chain operators — grocery distributors, pharmacy depots, food producers — lose money three ways at the same time, and the three losses pull against each other. Stock **spoils** when it's over-ordered or held too long. Shelves go **empty** when it's under-ordered, costing sales and customer trust. And **operational waste** — over-cooling, panic expedites, emergency reorders — burns cash that careful timing would have saved. Push down one loss and you tend to push up another: order more to avoid stockouts and you spoil more; hold less to avoid spoilage and you stock out.

Crucially, these aren't three separate problems with three separate fixes. They're one continuous balancing act over messy, fast-moving data: inventory counts, expiry windows, refrigeration-temperature feeds, shifting near-term demand, and unreliable supplier timelines — each arriving from a different system, in a different shape, at a different cadence. Today most operators run this on spreadsheets and intuition. Decisions lag the data, and the lag costs money.

## Why this needs an agent

It's fair to ask why this isn't just a forecasting model or a dashboard. A demand forecaster solves one slice. A reorder-point formula solves another. Neither one *decides*. The actual job is continuous synthesis of conflicting signals followed by judgment: what to do, how urgently, and — most importantly — **when it's safe to act autonomously versus when to escalate to a person.**

That decision loop is exactly what an agent is for. It synthesizes heterogeneous, messy inputs that no single solver consumes. It reasons under conflicting objectives. It chooses actions and sequences them by urgency and value. And it knows its own limits, pausing before anything irreversible or expensive. A dashboard shows you numbers; an agent turns a reactive, spreadsheet-driven process into a proactive one that surfaces ranked actions *before* losses lock in — while keeping a human in control of the expensive, irreversible calls.

## What it does

Every cycle, the system reads the current state of the warehouse, has three specialists reason over it, and produces a single **ranked list of actions** — reorders and expedites — sorted by urgency. Cheap, reversible actions execute automatically. Expensive, irreversible ones stop at a human-approval gate.

The demo tells the whole story in two runs. In the **normal cycle**, the system produces a calm list: a couple of small, auto-approved reorders, nothing alarming. Then a **temperature excursion** is injected — a refrigeration unit drifts out of range on a batch of dairy. The monitoring agent catches the breach; the spoiled stock's usable shelf life collapses to zero; the replenishment agent recomputes and finds that product can no longer cover projected demand; and the orchestrator re-ranks the calm list into an urgent one — live, with no human touching anything. The top action is now to expedite a replacement shipment. But that expedite is expensive and irreversible, above the auto-approve cost threshold, so the agent **does not act.** It stops and asks. A human approves, and only then does it execute. Autonomy where it's safe, a gate where it isn't.

## How it works

The system is four agents plus a tool layer, and the intelligence is in the handoff, not in any single piece.

**The MCP server is the tool layer.** Before any agent reasons, there has to be something to look at and act on. A Model Context Protocol server (built with FastMCP, served over stdio) exposes five tools: `get_inventory`, `get_temp_feed`, `get_supplier_status`, and `get_demand` are read-only; `place_order` is the one side-effectful tool — the single door to taking action, and the one with a lock on it. This separation is deliberate: agents can look freely, but there's exactly one guarded path to changing the world.

**The monitoring agent is the eyes.** It reads inventory and the refrigeration temperature feed and emits structured *concerns*. A cold batch that breaches its safe temperature range has its effective shelf life treated as instantly gone — spoiled stock can't be sold. A batch within four days of expiry is flagged as a watch item. It doesn't decide what to do; it raises its hand about risk.

**The demand agent is the forecaster.** For each product it estimates near-term daily pull, primed by the dataset's sales volumes. Deliberately, this is a simple estimator rather than a heavyweight forecaster — the capstone is judged on agent reasoning and coordination, and plausible numbers serve that better than an elaborate model. It does, however, model something real: **holiday demand.** Perishable demand spikes unevenly before big holidays — dairy, produce, meat, and bakery move most — so in the lead-up to New Year, Valentine's, Independence Day, Halloween, Thanksgiving, or Christmas, the agent lifts its estimate for the affected categories. That single change can turn a calm item into an urgent reorder.

**The replenishment agent is the brain.** It takes the monitoring concerns and the demand estimates and does the actual tradeoff, using one legible rule: `coverage = available units ÷ daily demand`, where any batch flagged as spoiled contributes zero units. Coverage under three days triggers a reorder; under one day, the gap is urgent and it proposes an *expedite*. This is where a temperature breach becomes a coverage gap, and a coverage gap becomes a decision.

**The orchestrator is the coordinator and the gatekeeper.** It runs the cycle in order — monitoring, then demand, then replenishment — collects the proposed actions, ranks them by urgency, and enforces the safety rule: any order the tool marked irreversible-and-over-threshold is never auto-executed. It's held as pending approval and surfaced to a person. Cheap, reversible orders pass through automatically.

So the excursion beat is really this chain firing in sequence: *temperature out of range → shelf life zero → available units zero → coverage zero → urgent expedite → cost over the limit → the orchestrator refuses to auto-execute and waits for a human `yes`.* No single component is clever on its own; the judgment emerges from the handoff.

## The four course concepts

- **Multi-agent system (ADK):** an orchestrator coordinating three specialists, each a distinct reasoning job with distinct inputs. Implemented as ADK `LlmAgent`s that reason over the MCP tools, with a deterministic Python mirror for reproducible demos.
- **MCP server:** a dedicated tool layer the agents call for all data and the one action, with the read/write trust boundary that the security story depends on.
- **Security features:** a cost-threshold human-approval gate. Orders above the auto-approve limit are marked irreversible and never execute without a person — enforced deterministically, not left to the model's discretion (in the ADK engine, via a `before_tool_callback` that intercepts `place_order`).
- **Deployability:** each cycle is a single stateless run against the live feed — exactly one scheduled tick. Point it at a scheduler and it runs autonomously, escalating only when the gate trips.

## Real data and design honesty

The system is seeded from the **Grocery Inventory and Sales Dataset** (CC BY 4.0) — 990 products with real names, stock levels, prices, expiry windows, and suppliers, so nothing looks invented. The loader handles the real export's quirks (dollar-formatted prices, address-style warehouse fields, and stale calendar dates) and runs on all ~332 active cold-chain items. On the full data, a refrigeration failure on Parmesan Cheese collapses its cold stock and the ~$933 replacement trips the approval gate — the same story that plays out on the small sample with milk.

Two things are simulated on purpose, and the project is explicit about it: the **refrigeration temperature feed** and the **excursion event**. No public dataset gives you a sensor breach on cue, and wiring a live IoT feed would add integration risk for zero benefit to what's being judged. So inventory is real for credibility, and the sensor feed is simulated for control. `get_temp_feed` is exactly the seam you'd swap for a real deployment — replace that one function with your refrigeration API and the agent logic is unchanged.

## How I built it — the journey

The project started from a single conviction: the demo had to be *honest*. It would be easy to narrate "a multi-agent system" over code that was really one function, so the guiding rule throughout was that the architecture the story claims must be the architecture that runs.

I began by pinning down the narrative spine — the three-way loss, the excursion-to-gate arc — before writing much code, so every component had to earn its place in that arc. The data layer came first, seeded from a real Kaggle inventory dataset for credibility, with the temperature feed and the excursion event deliberately simulated for control. Then the MCP server, so there was a real tool boundary from day one. Then the three specialists and the orchestrator on top of it.

Two decisions shaped the build. First, a **dual-engine design**: the reasoning exists both as deterministic, legible Python and as real ADK `LlmAgent`s over the same MCP tools. This resolved a genuine tension — the recorded demo needs to be reproducible and bulletproof, but the "multi-agent ADK" claim needs to be real. Running either engine with a flag lets the video stay predictable while the agent technology is genuinely wired. Second, I kept the replenishment scoring a **transparent heuristic** rather than a black box, because a judge should be able to follow the reasoning that turns a temperature breach into an urgent, gated action.

The most instructive moments came from testing on the **full 990-row Kaggle dataset**. Three things quietly broke: prices arrived as `"$4.50 "` strings, warehouse fields held street addresses instead of cold-zone labels, and every expiry date was from 2024 and read as already expired. Each forced a better design — robust parsing, inferring refrigeration from product category, and anchoring the simulation's clock to the data. A subtler discovery: because real products span multiple batches, spoiling one carton was invisible; the fix — collapsing a product's whole cold stock on a refrigeration failure — is also simply more true to life. That loop of "run on real data, watch it break, make it more realistic" is where the project earned its credibility. A late addition, holiday-aware demand, came from the same instinct: holidays move perishable demand unevenly, and modeling that lets the agent turn a calm item into an urgent one for a reason a business would recognize.

Throughout, the code is commented for intent, not mechanics, and the README carries the architecture diagram and setup so the project reads as a portfolio piece, not just a prototype.

## Why it's valuable

Every avoided spoiled batch, every prevented stockout, and every panic-expedite that becomes a planned shipment is money. The agent surfaces ranked actions before losses lock in, acts autonomously on the safe ones, and escalates the expensive, irreversible ones to a human — turning a reactive spreadsheet process into a proactive one without handing over the keys. It's a genuine, auditable decision loop with a safety boundary built in, and it runs today on real data with a single command.
