"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

# Load env vars. Standard location is the project-root .env; we also check
# .venv/.env because that's the file the editor tends to open, and it's easy to
# paste the key into the wrong one. load_dotenv() defaults to override=False, so
# the first file to define a var wins — root is loaded first and takes precedence.
load_dotenv()  # project-root .env
load_dotenv(os.path.join(os.path.dirname(__file__), ".venv", ".env"))  # fallback

LLM_MODEL = "llama-3.3-70b-versatile"


def _chat(messages: list[dict], temperature: float = 0.7, max_tokens: int = 400) -> str:
    """Send a chat completion to Groq and return the response text."""
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


def _format_item(item: dict) -> str:
    """Render a listing dict into a compact human/LLM-readable line."""
    brand = item.get("brand") or "no brand"
    return (
        f"{item['title']} ({brand}, {item['condition']} condition) — "
        f"${item['price']:.0f} on {item['platform']}. "
        f"Category: {item['category']}. "
        f"Colors: {', '.join(item['colors'])}. "
        f"Style: {', '.join(item['style_tags'])}."
    )


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Tokenize the query into lowercase keywords (drop very short noise words).
    keywords = [w for w in re.findall(r"[a-z0-9']+", description.lower()) if len(w) > 1]

    scored: list[tuple[int, dict]] = []
    for item in listings:
        # 1. Price filter (inclusive).
        if max_price is not None and item["price"] > max_price:
            continue

        # 2. Size filter — case-insensitive substring match so "M" matches "S/M".
        if size is not None and size.strip():
            if size.strip().lower() not in item["size"].lower():
                continue

        # 3. Relevance score: count keyword hits across title, description, tags.
        haystack = " ".join(
            [
                item["title"],
                item["description"],
                " ".join(item["style_tags"]),
                item["category"],
            ]
        ).lower()
        score = sum(1 for kw in keywords if kw in haystack)

        # 4. Drop anything with no keyword overlap.
        if score > 0:
            scored.append((score, item))

    # 5. Sort by score, highest first (stable — preserves dataset order on ties).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = _format_item(new_item)
    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        # Empty-wardrobe branch: general styling advice, no invented pieces.
        prompt = (
            f"A shopper is considering this secondhand piece:\n  {item_desc}\n\n"
            "They have NOT entered any wardrobe items yet. Give general styling "
            "advice for this piece: what categories and colors of clothing it pairs "
            "well with, what vibe/occasions it suits, and one concrete outfit idea "
            "built from common staples. Keep it to 3-4 sentences, friendly and "
            "specific. End with a short nudge to add their wardrobe for personalized looks."
        )
    else:
        wardrobe_lines = "\n".join(
            f"  - {it['name']} ({it['category']}; {', '.join(it.get('colors', []))})"
            + (f" — {it['notes']}" if it.get("notes") else "")
            for it in items
        )
        prompt = (
            f"A shopper is considering this secondhand piece:\n  {item_desc}\n\n"
            f"Here is their actual wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that style the new piece using SPECIFIC items "
            "named from their wardrobe above. Reference pieces by name. Add one quick "
            "styling tip (tuck, roll, layer). Keep it to 3-5 sentences, friendly and concrete."
        )

    try:
        return _chat(
            [
                {
                    "role": "system",
                    "content": "You are FitFindr, a warm, knowledgeable secondhand-fashion stylist.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
    except Exception as exc:  # network/auth/etc — degrade gracefully
        return (
            f"(Couldn't reach the styling model: {exc}) "
            f"As a fallback: {new_item['title']} works well with neutral basics and "
            "denim — build around its main colors and keep the rest simple."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # 1. Guard against an empty / whitespace-only outfit.
    if not outfit or not outfit.strip():
        return (
            "⚠️ Can't write a fit card without an outfit suggestion — "
            "the styling step returned nothing."
        )

    item_desc = _format_item(new_item)
    prompt = (
        f"Write a short, casual social-media caption (Instagram/TikTok OOTD style) "
        f"for a secondhand find.\n\n"
        f"The piece:\n  {item_desc}\n\n"
        f"How it's being styled:\n  {outfit}\n\n"
        "Rules: 2-4 sentences. Sound like a real person posting their fit, NOT a "
        "product description. Mention the item name, its price, and the platform "
        "naturally — once each. Capture the outfit vibe in specific terms. Emojis ok "
        "but don't overdo it. No hashtag wall."
    )

    try:
        return _chat(
            [
                {
                    "role": "system",
                    "content": "You write authentic, casual fashion captions for real social posts.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.9,  # higher temp → captions vary between runs
        )
    except Exception as exc:
        return f"(Couldn't reach the caption model: {exc})"
