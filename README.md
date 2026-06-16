# FitFindr 🛍️

FitFindr is a secondhand-shopping styling agent. You describe a piece you want (with optional
size and price); it **searches** a mock multi-platform listings dataset, **picks** the best match,
**suggests** how to style it using your own wardrobe, and **writes** a shareable social caption
("fit card") for the look.

The full design spec, agent diagram, and AI-tool plan live in [planning.md](planning.md).

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # wardrobe format + example/empty wardrobes
├── utils/data_loader.py       # load_listings(), get_example_wardrobe(), get_empty_wardrobe()
├── tools.py                   # the 3 tools: search_listings, suggest_outfit, create_fit_card
├── agent.py                   # run_agent() — the planning loop + query parser + session state
├── app.py                     # Gradio UI (handle_query maps the session to 3 panels)
├── tests/test_tools.py        # pytest: one test per failure mode + core behavior
├── planning.md                # the design spec (read this first)
└── requirements.txt
```

## Setup

```bash
pip install -r requirements.txt
```

Add your Groq API key to a `.env` file in the **project root** (free key at
[console.groq.com](https://console.groq.com)). The two LLM-powered tools read it via
`python-dotenv`:

```
GROQ_API_KEY=your_key_here
```

> Note: `load_dotenv()` looks for `.env` in the project root, not in `.venv/`. The file is gitignored.

## Run

```bash
python app.py          # launch the Gradio UI (open the URL it prints)
python agent.py        # CLI: runs the happy path + the no-results branch
pytest tests/          # run the tool tests (LLM tests auto-skip without a key)
```

---

## Tool Inventory

| Tool | Inputs | Output | Purpose |
|------|--------|--------|---------|
| `search_listings` | `description: str`, `size: str \| None`, `max_price: float \| None` | `list[dict]` (full listings, ranked by relevance; `[]` if none) | Find secondhand pieces matching keywords + filters |
| `suggest_outfit` | `new_item: dict`, `wardrobe: dict` | `str` (styling advice) | Style the found piece using the user's wardrobe (or general advice if empty) |
| `create_fit_card` | `outfit: str`, `new_item: dict` | `str` (2–4 sentence caption) | Turn the look into a casual, shareable social caption |

**`search_listings`** loads the dataset via `load_listings()`, filters by `max_price` (inclusive)
then `size` (case-insensitive substring, so `"M"` matches `"S/M"`), scores each survivor by keyword
overlap of `description` against the title/description/tags/category, drops zero-score items, and
returns the rest sorted by score (highest first). A returned listing dict has: `id`, `title`,
`description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`.

**`suggest_outfit`** and **`create_fit_card`** call Groq's `llama-3.3-70b-versatile`. The fit card
uses a higher temperature (0.9) so repeated calls on the same input vary.

## Planning Loop — what the agent decides

`run_agent(query, wardrobe)` in [agent.py](agent.py) is a fixed forward pipeline with **one
early-exit branch**, driven entirely by the `session` dict:

1. **Parse** the query → `description`, `size`, `max_price` (regex, in `_parse_query`).
2. **`search_listings(...)`** → `session["search_results"]`.
   - **Branch:** if the result is empty, write a helpful retry message to `session["error"]` and
     **return immediately** — the styling tools are never called with empty input.
3. **Select** the top result → `session["selected_item"]`.
4. **`suggest_outfit(selected_item, wardrobe)`** → `session["outfit_suggestion"]`.
5. **`create_fit_card(outfit_suggestion, selected_item)`** → `session["fit_card"]`.
6. **Return** the session.

Behavior genuinely differs by input: an impossible query exits after step 2 with only `error` set;
a satisfiable query runs all three tools. It is *not* a fixed "always call all three" sequence.

The query parser is deterministic regex (no LLM): it pulls a price from phrases like "under $30",
a size only from an explicit "size …" cue or unambiguous tokens (XXS/XS/XL/XXL, numeric shoe sizes)
— bare `s`/`m`/`l` are deliberately **not** matched alone because they collide with words like
"I'm" and "flowy" — and strips wardrobe-context phrases ("I mostly wear …") so they don't pollute
the search keywords.

## State Management

A single `session` dict (built by `_new_session()`) is the one source of truth for an interaction —
no globals, no mid-run re-prompting. Each field is written by one step and read by the next:
`query → parsed → search_results → selected_item → outfit_suggestion → fit_card`, with `error` set
by any failing step. `run_agent()` returns the session; `app.py` checks `error` first, otherwise
renders `selected_item`, `outfit_suggestion`, and `fit_card` into the three UI panels. (Full table
in [planning.md](planning.md#state-management).)

## Error Handling (with examples from testing)

| Tool | Failure mode | What happens |
|------|-------------|--------------|
| `search_listings` | No match | Returns `[]` (never raises); the loop sets `error` and returns early, leaving `fit_card = None`. |
| `suggest_outfit` | Empty wardrobe | Branches to general styling advice instead of inventing items; never crashes. |
| `create_fit_card` | Empty/whitespace outfit | Returns a descriptive ⚠️ error string; never calls the LLM, never raises. |
| both LLM tools | Network/auth error | Caught; returns a readable fallback string so the run still completes. |

**Concrete example — no results.** Query `"designer ballgown size XXS under $5"`:

```
$ python agent.py
...
=== No-results path ===
Error message: No listings matched 'designer ballgown' (size XXS, under $5). Try removing the
size filter, raising your max price, or using broader keywords (e.g. 'tee' instead of 'vintage
band tee').
```

`session["fit_card"]`, `["outfit_suggestion"]`, and `["selected_item"]` all remain `None` — the
styling tools were never called.

**Concrete example — empty outfit guard.**

```
$ python -c "from tools import search_listings, create_fit_card; \
  it=search_listings('vintage graphic tee', None, 50)[0]; print(create_fit_card('', it))"
⚠️ Can't write a fit card without an outfit suggestion — the styling step returned nothing.
```

**Concrete example — empty-wardrobe branch.** With `get_empty_wardrobe()`, `suggest_outfit`
returns general advice and never invents items the user doesn't own:

```
$ python -c "from tools import search_listings, suggest_outfit; \
  from utils.data_loader import get_empty_wardrobe; \
  it=search_listings('vintage graphic tee', None, 50)[0]; print(suggest_outfit(it, get_empty_wardrobe()))"
This adorable Y2K baby tee is perfect for adding a touch of vintage charm ... pairing well with
high-waisted jeans, flowy skirts, and distressed denim shorts ... To see how this tee can be styled
with your unique pieces, consider adding your wardrobe items to get personalized outfit ideas ...
```

**Happy path (all three tools, `python agent.py`):** search picks the *Y2K Baby Tee — $18, depop*,
`suggest_outfit` styles it with the example wardrobe's *baggy straight-leg jeans* and *chunky white
sneakers*, and `create_fit_card` produces e.g. *"Just scored this adorable Y2K Baby Tee for $18 on
Depop and I'm obsessed! Paired it with my baggy straight-leg jeans and chunky white sneakers …"* —
the item name, price, and platform all flow through from the original listing via the session dict.



## How AI Was Used

This project was built with **Claude (Claude Code)** as the implementation assistant, directed by
the spec in `planning.md`. Two concrete instances:

1. **Implementing `search_listings`.** Input given to the AI: the **Tool 1** block from
   `planning.md` (typed inputs, the return contract, and the empty-results failure mode), plus the
   instruction to use `load_listings()` rather than re-reading the file. It produced a
   filter→score→sort implementation. **What I changed/verified:** I confirmed it filtered by all
   three parameters and returned `[]` (not an exception) on no match, then ran the three pytest
   cases plus three manual queries. The scoring originally only looked at the title; I broadened the
   "haystack" to include `description`, `style_tags`, and `category` so relevance ranking actually
   surfaces graphic tees at the top.

2. **Implementing the planning loop + query parser.** Input given to the AI: the **Architecture**
   diagram and the **Planning Loop** + **State Management** sections of `planning.md`. It produced
   `run_agent()` and a regex `_parse_query()`. **What I overrode:** the first parser detected the
   bare "m" in "I'm" as size M and used `str.replace`, which clobbered every "m" in the query
   (turning "mostly" → "ostly"). I rewrote it to (a) only detect bare sizes that are unambiguous
   (XXS/XS/XL/XXL or "size N") and (b) carve out matched spans by position instead of `str.replace`.
   I verified the loop branches on empty search results and returns early rather than calling all
   three tools unconditionally.

## Spec Reflection

The spec held up well: writing the typed inputs/returns and the explicit early-exit branch in
`planning.md` first meant the loop's control flow was decided before any code, and the diagram
translated almost directly into `run_agent()`. The one thing the spec underestimated was query
parsing — `planning.md` treated "parse the query" as a single step, but ambiguous size tokens
(`s`/`m`/`l`) turned out to be the trickiest part of the whole build and needed a real rule
("explicit cue or unambiguous token only"). If I rebuilt it, I'd add a short "input parsing rules"
note to the spec rather than discovering those edge cases during implementation.
