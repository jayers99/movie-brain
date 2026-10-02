# Task brief — Watchlist order (backlog 46)

**Version 0.9 — draft 2026-10-02, before your review.** Your five rulings from the grill this morning, made into stories on your real catalogue (a copy taken at 10 AM today: 5204 films showing, 8 watchlist films showing, 9 in the table). The mock-up [mockup-1.html](mockup-1.html) has two variants that differ in ONE thing — what happens under your pointer when you press an arrow several times (story 2). *Where the mock-up and this brief disagree, the brief wins.*

## Your page

### Your rulings (2026-10-02)

1. Watchlist only in this build; My Ranking arrows are a later item.
2. A newly starred film joins at the top.
3. The films already starred start in today's critics' order, so nothing moves on day one.
4. With another chip or a search narrowing the watchlist, the arrows still work and swap with the film you can see.
5. Row arrows only: no drawer buttons, no Alt+arrow keys.

*Correction:* this morning I said the watchlist holds 17 films. It holds 9 (`SELECT count(*) FROM watchlist` on the live database at 10 AM); 8 show, because Some Came Running is departed and unrated and the catalogue's own rule hides it.

### The stories

**Works in** says which variant shows each story.

| # | Story | Works in |
|---|---|---|
| 1 | **My watchlist, in my order.** I press Watchlist. The 8 films show in the order I saw yesterday — Intolerance first, Lord of the Flies last — because that is where my order starts. A narrow column of ▲ ▼ sits at the left of each row. Intolerance's ▲ and Lord of the Flies' ▼ are greyed: there is nowhere to go. | A B |
| 2 | **Out of the Past goes first.** I press its ▲ five times; each press moves it one place, past one film. After five it is at the top with the grey mark, and Intolerance has slid to second. **A:** the row moves at every press, and my pointer follows it up. **B:** I press five times on the spot; the row shows ▲5 and moves five places when my pointer leaves it. | differs |
| 3 | **One too far.** Out of the Past went past Intolerance and I wanted Intolerance first. I press Out of the Past's ▼ once. That is the whole undo — no Undo line, no prompt. | A B |
| 4 | **With a chip on, it jumps what I cannot see.** Watchlist plus Rated → Unrated by me: 6 films (Intolerance, which I rated 2, and Young Frankenstein, rated 9, drop out). I press ▼ on Out of the Past: it swaps with Lord of the Flies, the next film I can see. I turn Rated off: Young Frankenstein, hidden between them, has not moved — the order ends Henry Sugar, Lord of the Flies, Young Frankenstein, Out of the Past. | A B |
| 5 | **On a list keeps my order.** Watchlist plus On a list: 5 films (Intolerance, Moonlight, Capturing the Friedmans, Out of the Past, Young Frankenstein), in MY order — not the list score On a list sorts by today — and the arrows stay. *A call I made; see "Before you say yes".* | A B |
| 6 | **A column sort hides the arrows.** I click the MC header: the list sorts by Metacritic and the ▲ ▼ column disappears. I click MC twice more (ascending, descending, off): my order is back, and so are the arrows. | A B |
| 7 | **Take one off, change my mind.** I open Capturing the Friedmans (4th) and press its ★. It leaves; the drawer moves on to The Wonderful Story of Henry Sugar with "Took Capturing the Friedmans off your watchlist · Undo" (move-on, as shipped). I press Undo: it is back in 4th place, not at the top. | A B |
| 8 | **A new star goes to the top.** Watchlist off. I type ugetsu in the Title filter, open Ugetsu and press ☆. I close the drawer, clear the filter and press Watchlist: 9 films, Ugetsu first, Intolerance second. | A B |
| 9 | **The drawer is open: no arrows.** With the drawer open the grey covers the list and the ▲ ▼ column is gone; there are no move buttons in the drawer and no keys. I close the drawer to reorder. | A B |

**Outcome.** The watchlist reads top to bottom as what I want to watch next, in my words, not the critics'.

**What wins when things trade off.** One press, one place. The film I moved is the only thing that moves; nothing else on the page changes.

### Before you say yes

- **Which variant** (A or B) is the open choice.
- **Story 5 is my call, not yours.** Today On a list puts list score first and Watched puts last-watched first, ahead of every other rule. I recommend your order wins whenever Watchlist is on, so a chip never hides the arrows. The alternative: those two chips keep their order and the arrows hide while they are on.
- **Story 7 is my call too:** Undo puts a film back in its place; only a fresh star goes to the top.
- **Where the arrows hide** (story 6 and two more): a column sort, a list picked from the list menu, and a word search in the bar that ranks its answers. In each the list is not in your order. A Title column filter or a `director:` search only narrows, so the arrows stay.

### What deliberately does not ship

My Ranking arrows (ruling 1). Arrows or keys in the drawer (ruling 5, story 9). Drag-and-drop. A "to top" button. An Undo line for a move (story 3). Arrows under a column sort, a picked list or a ranking search (story 6).

| Behaviour | Status |
|---|---|
| Today's default order of the 8 shown films (Metacritic, then RT, then IMDb, each descending) | read from `/api/films` on the 10 AM copy and sorted as `app.js` `compare()` does with no sort set |
| The counts (5204, 8, 9, 6 under Unrated by me, 5 under On a list) | read from the same copy; the tests re-cast them on their own seed |
| Move-on's label "Took X off your watchlist" and its Undo | the shipped code (`app.js`, the star toggle's `label:`); the Undo restoring the old PLACE is new |
| Variant B's "settle when the pointer leaves" | simulated only; never tried on the real dashboard |
| The hidden ninth film's place | not shown on the mock-up (it never renders); see Builder's pages |

## Builder's pages

- **Data.** `watchlist` gains a dense `position` (migration 033, wrapped in BEGIN/COMMIT). The migration seeds positions in today's default order over all 9 rows, including Some Came Running, using the same COALESCE the FilmView uses for Metacritic. A star inserts at position 1 and shifts the rest down; an un-star closes the gap; Undo of an un-star re-inserts at the remembered position.
- **A move** is one write: swap the two films' positions. The client sends the film and the visible neighbour it swaps with; a film hidden between them keeps its position (story 4).
- **Read.** `FilmView` carries `watchlist_position`; `compare()` puts it first when Watchlist is on and no column sort, list or ranking search is active — ahead of On a list's canon score and Watched's last-watched (story 5).
- **The arrows** show only under that same condition and while the drawer is closed; the top visible film's ▲ and the bottom visible film's ▼ are disabled.
- **Out of scope here:** `rank_order` and `my-owned-tiers` (My Ranking) — a later item. When it comes, a move must write `rank_order` and then re-save the snapshot, because every Save rebuilds the list from `rank_order`.
