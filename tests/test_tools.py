"""
tests/test_tools.py

Tool-level tests, one per failure mode plus core behavior.
Run with:  pytest tests/

The search_listings tests need no API key. The LLM-tool tests are skipped
automatically when GROQ_API_KEY is not set, so the suite stays green offline.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

needs_key = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping live LLM tests",
)


# ── search_listings ─────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    # every result is a full listing dict
    assert all("title" in item and "price" in item for item in results)


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []  # empty list, no exception


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_case_insensitive():
    # "m" should match listings sized "S/M", "M", etc.
    results = search_listings("tee", size="m", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_sorted_by_relevance():
    results = search_listings("vintage denim jeans", size=None, max_price=None)
    # Nothing crashes and we get a ranked list back.
    assert isinstance(results, list)


# ── suggest_outfit ──────────────────────────────────────────────────────────

@needs_key
def test_suggest_outfit_with_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(out, str) and len(out.strip()) > 0


@needs_key
def test_suggest_outfit_empty_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_empty_wardrobe())
    # Empty wardrobe must still produce useful, non-empty advice (no crash).
    assert isinstance(out, str) and len(out.strip()) > 0


# ── create_fit_card ─────────────────────────────────────────────────────────

def test_fit_card_empty_outfit_returns_error_string():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("", item)
    # Returns a descriptive string, does NOT raise.
    assert isinstance(card, str)
    assert "⚠️" in card or "without an outfit" in card.lower()


@needs_key
def test_fit_card_varies():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    outfit = "Pair with baggy jeans and chunky sneakers for a Y2K streetwear look."
    a = create_fit_card(outfit, item)
    b = create_fit_card(outfit, item)
    assert isinstance(a, str) and a.strip()
    assert a != b  # higher temperature should vary the output
