"""
Simulated data layer (Day 2) — seeded from the Kaggle Grocery Inventory dataset.

Seed source: "Grocery Inventory and Sales Dataset" (CC BY 4.0)
  https://www.kaggle.com/datasets/salahuddinahmedshuvo/grocery-inventory-and-sales-dataset

Why seed from real data but still simulate:
  - Credibility: product names, expiry windows, reorder quantities, and supplier info
    come from a real (if fictional) dataset, so nothing looks invented.
  - Control: the demo needs a temperature-excursion event the agent reacts to live.
    No public dataset gives you that on cue, so the temp feed + event injector are simulated.
  Judges grade the AGENT REASONING, not data realism — this gets credibility AND control.

Two seed files are supported (the full one wins if present):
  - data/seed/grocery_inventory_full.csv    the real ~990-row Kaggle export
  - data/seed/grocery_inventory_sample.csv  a small 6-row sample (used for the recorded demo)
If neither is readable, a baked-in fallback keeps the demo running.

Real-data quirks this loader tolerates (so the full Kaggle CSV is a true drop-in):
  - prices formatted like "$4.50 " (dollar sign + stray spaces),
  - Warehouse_Location holding street addresses instead of "Cold/Frozen" zones — so
    refrigeration is inferred from the product CATEGORY (dairy, seafood, produce, meat...),
  - stale calendar dates (the export is from 2024): the simulation's "today" is anchored to
    the data when the fixed date would make everything look expired.

Keep this layer DUMB: plausible > accurate.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import csv, os, random

random.seed(42)  # deterministic demos

# Fixed reference date for the small sample (keeps the recorded-demo numbers stable).
_FIXED_TODAY = date(2026, 6, 24)
TODAY = _FIXED_TODAY  # may be re-anchored below once the data is loaded

_SEED_DIR = os.path.join(os.path.dirname(__file__), "seed")
# Prefer the full Kaggle export; fall back to the small sample.
SEED_CSV = next(
    (p for p in (os.path.join(_SEED_DIR, "grocery_inventory_full.csv"),
                 os.path.join(_SEED_DIR, "grocery_inventory_sample.csv"))
     if os.path.exists(p)),
    os.path.join(_SEED_DIR, "grocery_inventory_sample.csv"),
)

# Refrigeration is monitored for cold-chain stock. Real exports don't label zones, so we
# infer "cold" from the zone text OR the product category.
_COLD_ZONES = ("cold", "frozen", "chill", "refrig")
_COLD_CATEGORIES = ("dairy", "seafood", "produce", "fruit", "vegetable", "meat", "frozen")
_SAFE_TEMP_MAX_C = 4.0

# Above this expedite cost, an order must pause for human approval (mirrors the MCP server).
# Used only to pick a demo excursion victim whose replacement will actually trip the gate.
_GATE_COST_USD = 500


@dataclass
class Batch:
    batch_id: str
    product: str
    category: str
    units: int
    expiry: date
    reorder_qty: int
    unit_price: float
    sales_volume: int          # used as a demand prior
    supplier: str
    zone: str
    temp_ok: bool = True

    @property
    def is_cold(self) -> bool:
        z, c = self.zone.lower(), self.category.lower()
        return any(k in z for k in _COLD_ZONES) or any(k in c for k in _COLD_CATEGORIES)

    @property
    def days_to_expiry(self) -> int:
        return (self.expiry - TODAY).days

    @property
    def effective_shelf_days(self) -> int:
        # An out-of-range cold batch loses its usable shelf life immediately.
        return 0 if (self.is_cold and not self.temp_ok) else max(self.days_to_expiry, 0)

    @property
    def expedite_cost(self) -> int:
        # Pricier / larger reorders cost more to expedite.
        return round(self.unit_price * max(self.reorder_qty, 1) * 0.8)


def _parse_date(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date()
        except ValueError:
            continue
    return TODAY  # last-resort fallback


def _parse_money(s) -> float:
    """Tolerate '$4.50 ', '1,234.5', '', None."""
    if s is None:
        return 0.0
    s = str(s).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_int(s) -> int:
    try:
        return int(float(str(s).replace(",", "").strip()))
    except (ValueError, AttributeError):
        return 0


def _load_seed() -> list[Batch]:
    """Load seed inventory from the Kaggle-schema CSV; fall back to a baked-in set."""
    if os.path.exists(SEED_CSV):
        try:
            batches = _from_csv(SEED_CSV)
            if batches:
                return batches
        except Exception as e:  # never let a bad CSV break the demo
            print(f"[sim] seed CSV unreadable ({e}); using fallback inventory")
    return _fallback()


def _from_csv(path: str) -> list[Batch]:
    out: list[Batch] = []
    # utf-8-sig strips a BOM if present.
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            # Skip non-active stock (discontinued / backordered) when a Status column exists.
            status = (row.get("Status") or "").strip().lower()
            if status and status != "active":
                continue
            # Tolerate the dataset's real (misspelled) 'Catagory' column or a corrected one.
            category = (row.get("Catagory") or row.get("Category") or "Unknown").strip()
            out.append(Batch(
                batch_id=f"B-{i:03d}",
                product=(row.get("Product_Name") or f"Item {i}").strip(),
                category=category,
                units=_parse_int(row.get("Stock_Quantity")),
                expiry=_parse_date(row.get("Expiration_Date", "")),
                reorder_qty=_parse_int(row.get("Reorder_Quantity")),
                unit_price=_parse_money(row.get("Unit_Price")),
                sales_volume=_parse_int(row.get("Sales_Volume")),
                supplier=(row.get("Supplier_Name") or "Unknown").strip(),
                zone=(row.get("Warehouse_Location") or "Ambient").strip(),
            ))
    return out


def _fallback() -> list[Batch]:
    return [
        Batch("B-001", "Whole Milk 2L",      "Dairy",   500, _parse_date("2026-06-30"), 400, 1.85, 88, "FreshFarm Co",  "Zone-A Cold"),
        Batch("B-002", "Greek Yogurt 500g",  "Dairy",   320, _parse_date("2026-07-03"), 300, 2.40, 41, "FreshFarm Co",  "Zone-A Cold"),
        Batch("B-003", "Cheddar Block 1kg",  "Dairy",   180, _parse_date("2026-07-15"), 150, 6.10, 16, "Hillside Dairy","Zone-A Cold"),
        Batch("B-004", "Strawberries 250g",  "Produce", 240, _parse_date("2026-06-27"), 200, 3.20, 57, "BerryGood Ltd", "Zone-B Cold"),
    ]


def _anchor_today(inv: list[Batch]) -> date:
    """
    Choose the simulation's 'today'. If enough stock still has shelf life against the fixed
    date (the small sample), keep the fixed date so recorded-demo numbers don't move. If the
    data is stale (the 2024 Kaggle export — everything already 'expired'), anchor 'today' to
    a low percentile of the expiry dates so most items are healthy and a few are near-expiry.
    """
    exps = sorted(b.expiry for b in inv)
    if not exps:
        return _FIXED_TODAY
    healthy = sum(1 for e in exps if e >= _FIXED_TODAY)
    if healthy >= max(3, int(0.2 * len(exps))):
        return _FIXED_TODAY
    # Stale export: sit just below the earliest expiries -> a small near-expiry cohort,
    # the rest with real shelf life. (2nd percentile.)
    return exps[int(0.02 * len(exps))] - timedelta(days=1)


INVENTORY: list[Batch] = _load_seed()
TODAY = _anchor_today(INVENTORY)  # re-anchor now that we know the data's calendar
_TEMP_FEED: dict[str, float] = {b.batch_id: 3.2 for b in INVENTORY}


def _pick_excursion_target(inv: list[Batch]) -> str:
    """
    Choose the demo's victim batch. For the excursion to actually expose demand, the batch
    must be the SOLE batch of its product — otherwise sibling batches still cover it and the
    collapse is invisible. Among sole-batch cold stock we prefer one whose expedited
    replacement exceeds the approval threshold (so Beat 3's gate fires), favouring milk/dairy
    for the narrative. Degrade gracefully to any cold batch, then the first batch.
    """
    # The excursion collapses the product's whole cold stock (see inject_temp_excursion),
    # so per-product expedite cost drives whether Beat 3's gate fires.
    cost_by_product: dict[str, int] = {}
    for b in inv:
        if b.is_cold and b.effective_shelf_days > 0:
            cost_by_product[b.product] = max(cost_by_product.get(b.product, 0), b.expedite_cost)

    cold = [b for b in inv if b.is_cold and b.effective_shelf_days > 0]
    milk = [b for b in cold if "milk" in b.product.lower()]
    dairy = [b for b in cold if "dairy" in b.category.lower()]
    over = lambda pool: [b for b in pool if cost_by_product.get(b.product, 0) > _GATE_COST_USD]
    for pool in (
        over(milk), over(dairy), over(cold),   # replacement trips the gate (ideal)
        milk, dairy, cold,                      # any cold stock, any cost
    ):
        if pool:
            # among a viable pool, take the costliest (most dramatic) replacement
            return max(pool, key=lambda b: cost_by_product.get(b.product, 0)).batch_id
    return inv[0].batch_id if inv else "B-001"


_EXCURSION_TARGET = _pick_excursion_target(INVENTORY)


def excursion_target() -> str:
    return _EXCURSION_TARGET


def get_inventory() -> list[dict]:
    return [{
        "batch_id": b.batch_id, "product": b.product, "category": b.category,
        "units": b.units, "days_to_expiry": b.days_to_expiry, "temp_ok": b.temp_ok,
        "is_cold": b.is_cold, "effective_shelf_days": b.effective_shelf_days,
        "unit_price": b.unit_price, "supplier": b.supplier, "zone": b.zone,
    } for b in INVENTORY]


def get_temp_feed() -> dict[str, float]:
    return dict(_TEMP_FEED)


def get_supplier_status() -> dict[str, dict]:
    """Lead times + expedite option per product, derived from seed where possible."""
    status = {}
    for b in INVENTORY:
        status[b.product] = {
            "supplier": b.supplier,
            "lead_days": 4,
            "expedite_days": 1,
            "expedite_cost": b.expedite_cost,
            "reorder_qty": b.reorder_qty,
        }
    return status


# --- holiday-aware demand -------------------------------------------------
# Perishable demand spikes before big holidays, and it spikes unevenly by category
# (dairy, produce, meat, bakery move most). The demand agent lifts its estimate for the
# affected categories during the lead-up window. This stays DORMANT unless 'today' lands
# near a holiday, so the sample and full-dataset default dates are unaffected.
_HOLIDAY_LEAD_DAYS = 7  # uplift kicks in this many days before the holiday


def _thanksgiving(year: int) -> date:
    thursdays = [d for d in range(1, 31) if date(year, 11, d).weekday() == 3]
    return date(year, 11, thursdays[3])  # 4th Thursday of November


# name -> (date-for-year function, {category-keyword: demand multiplier})
_HOLIDAYS = [
    ("New Year",         lambda y: date(y, 1, 1),   {"beverage": 1.6, "seafood": 1.4, "bakery": 1.3}),
    ("Valentine's Day",  lambda y: date(y, 2, 14),  {"bakery": 1.5, "dairy": 1.3, "fruit": 1.3, "produce": 1.3}),
    ("Independence Day", lambda y: date(y, 7, 4),   {"meat": 1.7, "beverage": 1.5, "produce": 1.4, "fruit": 1.4, "bakery": 1.2}),
    ("Halloween",        lambda y: date(y, 10, 31), {"bakery": 1.4, "beverage": 1.2}),
    ("Thanksgiving",     _thanksgiving,             {"produce": 1.6, "fruit": 1.6, "vegetable": 1.6, "dairy": 1.5, "bakery": 1.7, "meat": 1.6, "seafood": 1.3}),
    ("Christmas",        lambda y: date(y, 12, 25), {"dairy": 1.6, "bakery": 1.8, "produce": 1.4, "fruit": 1.4, "meat": 1.6, "seafood": 1.5, "beverage": 1.4}),
]


def holiday_context(today: date | None = None):
    """Return (name, {category-keyword: multiplier}) if near a holiday, else None."""
    today = today or TODAY
    for name, when, mults in _HOLIDAYS:
        for yr in (today.year, today.year + 1):  # cover the Dec -> Jan boundary
            hd = when(yr)
            if hd - timedelta(days=_HOLIDAY_LEAD_DAYS) <= today <= hd:
                return name, mults
    return None


def active_holiday(today: date | None = None) -> str | None:
    ctx = holiday_context(today)
    return ctx[0] if ctx else None


def _holiday_multiplier(category: str) -> float:
    ctx = holiday_context()
    if not ctx:
        return 1.0
    cat = category.lower()
    return max((m for kw, m in ctx[1].items() if kw in cat), default=1.0)


def set_today(d: date) -> None:
    """Override the simulation's reference date (used by --as-of to demo holiday demand)."""
    global TODAY
    TODAY = d


def get_demand_estimate(product: str) -> int:
    """
    Daily pull, primed by the seed Sales_Volume (treated as a recent total) with light noise,
    then lifted by a holiday multiplier for the product's category when 'today' is near a
    holiday (e.g. dairy/meat/produce spike before Thanksgiving). Dormant otherwise.
    """
    base, category = 30, ""
    for b in INVENTORY:
        if b.product == product:
            base = max(int(b.sales_volume / 7), 5)  # weekly volume -> daily-ish
            category = b.category
            break
    base = round(base * _holiday_multiplier(category))
    return max(base + random.randint(-4, 4), 1)


def inject_temp_excursion(batch_id: str | None = None, temp_c: float = 11.5) -> str:
    """
    Scripted demo event: a refrigeration failure takes a product's cold stock out of range.
    Collapses every cold batch of the target batch's product (a real fridge/zone failure hits
    more than one carton), so the coverage gap is real even when a product spans many batches.
    Returns the representative (target) batch_id.
    """
    batch_id = batch_id or _EXCURSION_TARGET
    if temp_c <= _SAFE_TEMP_MAX_C:
        return batch_id
    target = next((b for b in INVENTORY if b.batch_id == batch_id), None)
    product = target.product if target else None
    for b in INVENTORY:
        if b.product == product and b.is_cold:
            _TEMP_FEED[b.batch_id] = temp_c
            b.temp_ok = False
    return batch_id
