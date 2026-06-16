# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## What FitFindr Does (one paragraph)

FitFindr is a secondhand-shopping styling agent. The user describes a piece they want
(plus optional size and price ceiling); the agent **searches** a mock multi-platform
listings dataset, **picks** the single best match, **suggests** how to style that piece
using the user's own wardrobe, and **writes** a short, shareable social caption ("fit card")
for the look. Each step feeds the next: search produces the item, the item + wardrobe
produce the outfit, and the outfit + item produce the caption. If the search returns nothing,
the agent stops immediately and tells the user how to broaden their query — it never calls
the downstream styling tools with empty input.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the 40-item mock listings dataset for pieces matching the user's keywords, optional
size, and optional price ceiling. Returns the matches ranked by keyword relevance so the agent
can pick the best one.

**Input parameters:**
- `description` (str): Free-text keywords describing the wanted item, e.g. `"vintage graphic tee"`. Required.
- `size` (str | None): Size to filter by, e.g. `"M"`. Matching is case-insensitive and substring-based, so `"M"` matches a listing sized `"S/M"`. `None` skips size filtering.
- `max_price` (float | None): Inclusive price ceiling in dollars, e.g. `30.0`. `None` skips price filtering.

**What it returns:**
A `list[dict]`, sorted by relevance score (highest first). Each dict is a full listing with the
fields: `id` (str), `title` (str), `description` (str), `category` (str), `style_tags` (list[str]),
`size` (str), `condition` (str), `price` (float), `colors` (list[str]), `brand` (str | None),
`platform` (str). Returns an **empty list `[]`** if nothing matches — never raises.

**What happens if it fails or returns nothing:**
The planning loop detects the empty list, writes a helpful message into `session["error"]`
("No listings matched … try removing the size or raising your price"), and returns the session
early **without** calling `suggest_outfit` or `create_fit_card`.

---

### Tool 2: suggest_outfit

**What it does:**
Given the selected listing and the user's wardrobe, asks the LLM (Groq
`llama-3.3-70b-versatile`) to propose 1–2 complete outfits that style the new piece, naming
specific wardrobe items where possible.

**Input parameters:**
- `new_item` (dict): The listing dict chosen by the agent (the top search result).
- `wardrobe` (dict): A wardrobe dict with an `"items"` key holding a list of wardrobe-item dicts (`id`, `name`, `category`, `colors`, `style_tags`, `notes`). The list **may be empty**.

**What it returns:**
A non-empty `str` of natural-language styling advice. With a populated wardrobe it references the
user's actual pieces by name ("pair with your baggy straight-leg jeans and platform Docs…").
With an empty wardrobe it returns **general** styling advice (what categories/colors pair well,
what vibe the piece suits) instead of inventing items the user doesn't own.

**What happens if it fails or returns nothing:**
The empty-wardrobe case is handled by branching the prompt (general advice, not specific items).
If the LLM call raises (network/auth error), the tool catches it and returns a plain-string
fallback message so the loop can still produce a result rather than crashing.

---

### Tool 3: create_fit_card

**What it does:**
Turns the outfit suggestion and item details into a short, casual, shareable social-media caption
(OOTD style) using the LLM at a higher temperature so repeated calls vary.

**Input parameters:**
- `outfit` (str): The styling text returned by `suggest_outfit()`.
- `new_item` (dict): The listing dict for the thrifted piece (used to mention name, price, platform naturally).

**What it returns:**
A 2–4 sentence `str` suitable as an Instagram/TikTok caption — casual voice, mentions the item
name, price, and platform once each, and captures the outfit vibe. Varies between calls (temp ≈ 0.9).

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool returns a descriptive **error string**
(`"Can't write a fit card without an outfit suggestion."`) rather than calling the LLM or raising.
LLM exceptions are caught and returned as a fallback string.

---

### Additional Tools (if any)

None — the three required tools cover the full interaction.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is a fixed forward pipeline with one early-exit branch. It is driven entirely by the
contents of the `session` dict — each step reads what the previous step wrote.

1. **Parse** the query into `description`, `size`, `max_price` (regex + keyword extraction) and store in `session["parsed"]`.
2. **search_listings(description, size, max_price)** → store in `session["search_results"]`.
   - **Branch:** `if not search_results:` set `session["error"]` to a helpful retry message and **`return session` immediately**. The downstream tools are never called.
   - Else continue.
3. **Select** `session["selected_item"] = search_results[0]` (the highest-relevance match).
4. **suggest_outfit(selected_item, wardrobe)** → store in `session["outfit_suggestion"]`.
5. **create_fit_card(outfit_suggestion, selected_item)** → store in `session["fit_card"]`.
6. **Return** the completed session.

The agent knows it is "done" when it reaches step 6 with `error == None` and all three output
fields populated, **or** when the empty-search branch returns early with `error` set. Behavior
differs by input: an impossible query exits after step 2 with only `error` set; a satisfiable
query runs all three tools.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (built by `_new_session()` in `agent.py`) is the one source of truth for
the whole interaction. There are no globals and no re-prompting of the user mid-run. Each field is
written by exactly one step and read by the next:

| Field | Written by | Read by |
|-------|-----------|---------|
| `query` | caller | parse step |
| `parsed` (`description`/`size`/`max_price`) | parse step | `search_listings` |
| `search_results` | `search_listings` | branch check + selection |
| `selected_item` | selection step | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | caller | `suggest_outfit` |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card` |
| `fit_card` | `create_fit_card` | UI |
| `error` | any failing step | UI (checked first) |

`run_agent()` returns the session; `app.py` reads `error` first and otherwise renders
`selected_item`, `outfit_suggestion`, and `fit_card` into the three panels.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Set `session["error"]` = "No listings matched '<desc>' under those filters. Try removing the size filter, raising your max price, or using broader keywords (e.g. 'tee' instead of 'vintage band tee')." Return early; `fit_card` stays `None`. |
| suggest_outfit | Wardrobe is empty | Don't fail — branch the prompt to give **general** styling advice for the piece (complementary categories, colors, vibe) and a nudge to add wardrobe items for personalized looks. |
| create_fit_card | Outfit input is missing or incomplete | Return the string "⚠️ Can't write a fit card without an outfit suggestion — the styling step returned nothing." instead of calling the LLM or raising. |

(Additionally, both LLM tools wrap the Groq call in try/except and return a readable fallback
string on network/auth errors, so a transient API failure degrades gracefully.)

---

## Architecture

```
                          User query + wardrobe choice
                                      │
                                      ▼
        ┌──────────────────────  run_agent()  ──────────────────────┐
        │                     (the Planning Loop)                    │
        │                                                            │
        │   parse query ──► session["parsed"] = {desc, size, price}  │
        │        │                                                   │
        │        ▼                                                   │
        │   search_listings(desc, size, max_price)                   │
        │        │                                                   │
        │        ├── results == []  ──► session["error"] = "No       │
        │        │                       listings matched…"  ──┐     │
        │        │                                             │     │
        │        │ results == [item, …]                        │     │
        │        ▼                                             │     │
        │   session["selected_item"] = results[0]              │     │
        │        │                                             │     │
        │        ▼                                             │     │
        │   suggest_outfit(selected_item, wardrobe)            │     │
        │     (empty wardrobe ─► general advice branch)        │     │
        │        │                                             │     │
        │        ▼  session["outfit_suggestion"] = "…"         │     │
        │   create_fit_card(outfit_suggestion, selected_item)  │     │
        │     (empty outfit  ─► error-string guard)            │     │
        │        │                                             │     │
        │        ▼  session["fit_card"] = "…"                  │     │
        └────────┼─────────────────────────────────────────────┼────┘
                 │  return session  ◄── error path returns here ┘
                 ▼
        app.py handle_query() reads session:
          error set?  → show error in panel 1, blanks in 2 & 3
          else        → panel 1 = listing, panel 2 = outfit, panel 3 = fit card
```

The whole flow reads and writes the single **session** dict (shown as `session[...]` above),
which is the shared State. The visible error branch terminates the loop early after
`search_listings`.

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**
I'll use **Claude (Claude Code)**. For each tool I paste that tool's block from the **## Tools**
section above (what it does, the typed input parameters, the return contract, the failure mode) and
ask for an implementation in `tools.py` only.
- *search_listings:* I'll require it to use `load_listings()` from `utils/data_loader.py` (not re-read the file), to filter by `max_price` then `size` (case-insensitive substring), then score by keyword overlap of `description` against `title` + `description` + `style_tags`, drop zero-score items, and sort descending. **Verify:** run the three pytest cases (returns results, empty-results, price filter all ≤ max) and 3 manual queries before trusting it.
- *suggest_outfit / create_fit_card:* I'll give the spec block plus the Groq model id (`llama-3.3-70b-versatile`). **Verify:** confirm the empty-wardrobe branch and empty-outfit guard exist by reading the code, then run each on real data and re-run `create_fit_card` 3× to confirm outputs vary.

**Milestone 4 — Planning loop and state management:**
I'll give Claude the **## Architecture** diagram plus the **## Planning Loop** and **## State
Management** sections, and ask it to implement `run_agent()` matching the numbered steps.
**Verify before trusting:** (a) it branches on the `search_results` empty case and returns early;
(b) it writes every value into the `session` dict rather than using locals/globals; (c) it does
**not** call all three tools unconditionally. Then run `python agent.py` and confirm the happy path
fills all fields and the no-results path sets only `error`.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse + Search:**
The loop parses `description="vintage graphic tee"`, `size=None`, `max_price=30.0` and calls
`search_listings("vintage graphic tee", size=None, max_price=30.0)`. It returns the relevance-ranked
matches (e.g. the Y2K Baby Tee — butterfly print, $18, depop, excellent condition — scores highly on
"graphic tee"/"vintage"). The agent stores them in `session["search_results"]` and sets
`session["selected_item"] = results[0]`.

**Step 2 — Suggest outfit:**
With a match in hand, the loop calls `suggest_outfit(selected_item=<the tee>, wardrobe=<example
wardrobe>)`. The LLM returns something like: "Pair this with your baggy straight-leg jeans and chunky
sneakers for an easy Y2K-streetwear fit; layer the oversized flannel open over it on cooler days."
Stored in `session["outfit_suggestion"]`.

**Step 3 — Fit card:**
The loop calls `create_fit_card(outfit=<that suggestion>, new_item=<the tee>)`. The LLM (high temp)
returns a caption like: "found this butterfly baby tee on depop for $18 and it's so me 🦋 styled it
with my baggy jeans + chunky sneakers, full Y2K mode." Stored in `session["fit_card"]`.

**Final output to user:**
The Gradio UI shows three panels — **Top listing** (title, price, platform, condition of the tee),
**Outfit idea** (the styling text), and **Your fit card** (the caption). If instead the search had
returned nothing (e.g. "designer ballgown size XXS under $5"), only the first panel would show the
error message and the other two would be blank.
