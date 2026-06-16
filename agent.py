"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ──────────────────────────────────────────────────────────────

# Wardrobe-context phrases that shouldn't pollute the search keywords. The user
# often describes what they already own ("I wear baggy jeans") in the same query.
_CONTEXT_MARKERS = re.compile(
    r"\b(i (mostly |usually |typically )?wear|i have|i own|i mostly|to (pair|style|go) with"
    r"|how (would|do) i style|what'?s out there)\b.*",
    re.IGNORECASE,
)


def _parse_query(query: str) -> dict:
    """
    Extract a search description, optional size, and optional max_price from a
    free-text query using regex. Lightweight and deterministic — no LLM needed.
    """
    text = query.strip()
    # Spans (start, end) of everything we extract, so we can carve them out of
    # the description by position — never str.replace, which clobbers every
    # occurrence (e.g. removing "m" would gut "mostly").
    spans: list[tuple[int, int]] = []

    # max_price: "under $30", "below 40", "$25 max", "less than 50"
    max_price = None
    price_match = re.search(
        r"(?:under|below|less than|max(?:imum)?|<=?|up to)\s*\$?\s*(\d+(?:\.\d+)?)"
        r"|\$\s*(\d+(?:\.\d+)?)\s*(?:max|or less|budget)",
        text,
        re.IGNORECASE,
    )
    if price_match:
        max_price = float(price_match.group(1) or price_match.group(2))
        spans.append(price_match.span())

    # size: only via an explicit "size …" cue, or an UNAMBIGUOUS standalone token
    # (xxs/xs/xl/xxl, or a 1-2 digit shoe size). Bare s/m/l are intentionally NOT
    # matched on their own — they collide with words like "I'm", "tops", "flowy".
    size = None
    size_match = re.search(
        r"\bsize[:\s]+([a-z0-9/]+)\b"
        r"|\b(xxs|xs|xl|xxl)\b"
        r"|\b(?:size\s+)(\d{1,2})\b",
        text,
        re.IGNORECASE,
    )
    if size_match:
        size = next(g for g in size_match.groups() if g).upper()
        spans.append(size_match.span())

    # description: carve out the matched spans, then strip wardrobe context + filler.
    spans.sort()
    desc_parts, cursor = [], 0
    for start, end in spans:
        desc_parts.append(text[cursor:start])
        cursor = end
    desc_parts.append(text[cursor:])
    desc = " ".join(desc_parts)
    desc = _CONTEXT_MARKERS.sub(" ", desc)
    # Drop common lead-in filler.
    desc = re.sub(
        r"\b(i'?m|i am|looking for|searching for|i want|i need|find me|show me|a|an|the)\b",
        " ",
        desc,
        flags=re.IGNORECASE,
    )
    desc = re.sub(r"\s+", " ", desc).strip(" ,.-")
    # Strip any dangling preposition left behind by filter removal (e.g. "...jacket in").
    desc = re.sub(r"\b(in|for|to|with|of)\s*$", "", desc, flags=re.IGNORECASE).strip(" ,.-")

    return {"description": desc or text, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — single source of truth for this interaction.
    session = _new_session(query, wardrobe)

    # Guard: empty query.
    if not query or not query.strip():
        session["error"] = "Please describe what you're looking for (e.g. 'vintage graphic tee under $30')."
        return session

    # Step 2: parse the query into search parameters.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: search.
    session["search_results"] = search_listings(
        parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )

    # Branch: no matches → set error and return early WITHOUT styling tools.
    if not session["search_results"]:
        filters = []
        if parsed["size"]:
            filters.append(f"size {parsed['size']}")
        if parsed["max_price"] is not None:
            filters.append(f"under ${parsed['max_price']:.0f}")
        filter_str = f" ({', '.join(filters)})" if filters else ""
        session["error"] = (
            f"No listings matched '{parsed['description']}'{filter_str}. "
            "Try removing the size filter, raising your max price, or using broader "
            "keywords (e.g. 'tee' instead of 'vintage band tee')."
        )
        return session

    # Step 4: select the top (highest-relevance) result.
    session["selected_item"] = session["search_results"][0]

    # Step 5: suggest an outfit from the selected item + wardrobe.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )

    # Step 6: turn the outfit into a shareable fit card.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: done — error stays None.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
