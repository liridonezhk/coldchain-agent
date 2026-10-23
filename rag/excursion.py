"""
Temperature-excursion rule lookup: from a disruption event to a cited rule.

    event = {"product": "Whole Milk 2L", "category": "Dairy", "temp_c": 11.5, "hours": 5,
             "setting": "refrigerated storage at a US food distributor"}

1. rule_query(event)   turns the event into a natural-language question. Product class,
                       temperature, duration and setting are all in it, because each one
                       changes which rule applies (milk vs poultry, 9 °C vs -14 °C, 2 h vs 5 h,
                       US vs EU, storage vs transport).
2. search_guidance     retrieves passages (rag/tool.py).
3. extractive_answer   quotes the best-matching rule sentences with [chunk_id] citations,
                       or says the corpus doesn't cover it (rag/grounding.py).

assess() returns all three, so the caller can show exactly which passage drove the decision.
"""
from __future__ import annotations


def rule_query(e: dict) -> str:
    return (f"{e['product']} ({e['category']}) was held at {e['temp_c']} °C for {e['hours']} hours "
            f"during {e['setting']}. What temperature and time limit applies, and must the food "
            f"be discarded?")


def assess(event: dict, encoder=None) -> dict:
    from rag.tool import search_guidance
    from rag.grounding import extractive_answer
    q = rule_query(event)
    result = search_guidance(q, k=5)
    return {"query": q, "retrieval": result, "answer": extractive_answer(q, result, encoder)}
