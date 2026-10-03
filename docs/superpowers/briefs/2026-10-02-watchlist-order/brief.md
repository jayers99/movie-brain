# Task brief — Watchlist order (backlog 46)

**Amendment 1.1 — frozen 2026-10-02.** You walked it and kept all four calls ("1"). Codex and Fable checked 1.0 independently (11 + 7 findings, 4 in common; the merged table is in [trial-log.md](trial-log.md)). Stories 9, 10, 11, 13 and 14 changed and 16–21 are new; the mock-up shows only those 11 cards by default. Four calls I made, each on a card for you to overrule: a ▲ ▼ press marks that film (10); ⓘ always opens (11); stars put back in one drawer visit keep their places however you step (14); in a rating box the keys never move a film (20).

**Version 1.0 — frozen 2026-10-02.** You chose variant A on the mock-up [mockup-1.html](mockup-1.html) ("option a") and kept both of my calls ("1"): your order wins over On a list and Watched (story 5), and Undo or a star put back before the drawer closes returns a film to its place (stories 7, 14). Gap check A ran twice (9 findings, then 5 from the fixes); every answer is in [trial-log.md](trial-log.md). From here the brief changes only by amendment. *Where the mock-up and this brief disagree, the brief wins.*

## Your page

### Your rulings (2026-10-02)

1. Watchlist only in this build; My Ranking arrows are a later item.
2. A newly starred film joins at the top.
3. The films already starred start in today's critics' order, so nothing moves on day one.
4. With another chip or a search narrowing the watchlist, the arrows still work and step past the film you can see. *(Your words were "swap"; amended in 1.0 to an insert so only the pressed film changes places — story 4.)*
5. Row arrows only: no drawer buttons, no Alt+arrow keys.
8. *Variant A chosen on the mock-up* ("option a"): each press moves the row at once; variant B stays below only as the record of what you compared.
7. *(added on second sight)* A row click is three-state: open the drawer → close it, mark kept → clear the mark. A fourth click opens again.
6. *(added on first sight of the mock-up)* With the drawer closed and a film marked, plain ↑ ↓ move that film, and the mark stays on it — "I could hit up three times and that movie would move up three". With the drawer open, ↑ ↓ keep stepping the drawer, as today.

*Correction:* this morning I said the watchlist holds 17 films. It holds 9 (`SELECT count(*) FROM watchlist` on the live database at 10 AM); 8 show, because Some Came Running is departed and unrated and the catalogue's own rule hides it.

### The stories

**Works in** says which variant shows each story.

| # | Story | Works in |
|---|---|---|
| 1 | **My watchlist, in my order.** I press Watchlist. The 8 films show in the order I saw yesterday — Intolerance first, Lord of the Flies last — because that is where my order starts. A narrow column of ▲ ▼ sits at the left of each row. Intolerance's ▲ and Lord of the Flies' ▼ are greyed: there is nowhere to go. | A B |
| 2 | **Out of the Past goes first.** I press its ▲ five times; each press moves it one place, past one film. After five it is at the top with the grey mark; the five films it passed each slid down one place, still in their own order. **A:** the row moves at every press, and my pointer follows it up. **B:** I press five times on the spot; the row shows ▲5 and moves five places when my pointer leaves it. | differs |
| 3 | **One too far.** Out of the Past went past Intolerance and I wanted Intolerance first. I press Out of the Past's ▼ once. That is the whole undo — no Undo line, no prompt. | A B |
| 4 | **With a chip on, it steps past what I can see.** Watchlist plus Rated → Unrated by me: 6 films (Intolerance, which I rated 2, and Young Frankenstein, rated 9, drop out). I press ▼ on Out of the Past: it steps past Lord of the Flies, the next film I can see. I turn Rated off: only Out of the Past has moved — the order ends Henry Sugar, Young Frankenstein, Lord of the Flies, Out of the Past, and every other film kept its order. | A B |
| 5 | **On a list keeps my order.** Watchlist plus On a list: 5 films (Intolerance, Moonlight, Capturing the Friedmans, Out of the Past, Young Frankenstein), in MY order — not the list score On a list sorts by today — and the arrows stay. *A call I made; see "Before you say yes".* | A B |
| 6 | **A column sort hides the arrows.** I click the MC header: the list sorts by Metacritic and the ▲ ▼ column disappears. I click MC twice more (ascending, descending, off): my order is back, and so are the arrows. | A B |
| 7 | **Take one off, change my mind.** I open Capturing the Friedmans (4th) and press its ★. It leaves; the drawer moves on to The Wonderful Story of Henry Sugar with "Took Capturing the Friedmans off your watchlist · Undo" (move-on, as shipped). I press Undo: it is back in 4th place, not at the top. | A B |
| 8 | **A new star goes to the top.** Watchlist off. I type ugetsu in the Title filter, open Ugetsu and press ☆. I close the drawer, clear the filter and press Watchlist: 9 films, Ugetsu first, Intolerance second. | A B |
| 9 | **The drawer is open: ↑ ↓ step, they do not move.** Drawer open on Intolerance: the ▲ ▼ column is gone. I press ↓ hoping to move it: the drawer steps to Moonlight, as today; my order is unchanged. I click Shop Around the Corner's row through the grey: the drawer steps to it, as today. I click the grey below the last row: the drawer closes and the mark is on Shop Around the Corner. *(1.1: a click on another dimmed row steps, as the real dashboard does.)* | A |
| 10 | **Keys move the marked film.** Out of the Past carries the grey mark. I press ↑ three times: it moves up three places and the mark stays on it. ↓ moves it back. Pressing a row's ▲ or ▼ with the mouse marks that film too, so the keys carry on with the film I just pressed. With nothing marked, or with a sort or a picked list on, ↑ ↓ scroll as today. *(1.1: an arrow press marks the film.)* | A |
| 11 | **Click, click, click: open, close, let go.** I click Out of the Past: its drawer opens. I click the same spot (its own row, through the grey): the drawer closes, the mark stays. I click the row once more: the mark goes, and ↑ ↓ move nothing. A fourth click opens again. The ⓘ at the end of a row always opens its drawer, marked or not. *This changes the row click on every list (find-my-row's mark, backlog 24).* *(1.1: ⓘ always opens.)* | A |
| 12 | **A picked list hides the arrows.** Watchlist on, I pick My Ranking (763) in the list menu at the right end of the chips: Out of the Past and Young Frankenstein show in My Ranking's order (123rd, 142nd) and the ▲ ▼ column is gone. Back to — all films —: my order and the arrows return. | A B |
| 13 | **A word search hides them; `director:` does not.** Watchlist on, I type *out of the past* in the bar: it ranks its answers, so the arrows go. I clear it: they are back. I type *director:tourneur*: it only narrows, so Out of the Past shows alone with its arrows (both greyed). The bar's line "Showing results for Jacques Tourneur (you typed “tourneur”) undo" appears, as today — that undo is about the name it guessed, never a move. *(1.1: the real correction line.)* | A |
| 14 | **Stars off and on in one drawer visit.** Watchlist off, Title filter *fr*: Capturing the Friedmans and Young Frankenstein. I open Capturing the Friedmans, press ★, ↓ to Young Frankenstein, press ★, ↑ back and put Capturing the Friedmans' star back, ↓ and put Young Frankenstein's back. I close, clear the filter, press Watchlist: they are 4th and 7th, where they were. Put back before the drawer closes — however I stepped (keys or a click through the grey), however many films — a film keeps its place. After the drawer closes, a star is fresh and goes to the top. *(1.1: any number of films, any kind of step.)* | A |
| 15 | **A move that does not save.** With the server down, I press ▲ on Out of the Past: it moves, then goes back with "Could not save the order". When things work, every move is saved at once and survives a reload. | A B |
| 16 | **Watched and Watchlist together.** Watchlist on, I press Watched: Showing 0 — none of my watchlist films has a logged viewing yet. I press Watched round to off: my 8 films and their arrows are back. The day I log a viewing of a starred film, it shows under both chips in MY order, not most-recent-first. *(1.1: pictures story 5's call for Watched.)* | A |
| 17 | **I try to drag a row.** I grab Out of the Past and pull it towards the top: the text highlights and nothing moves. I press its ▲, or mark it and press ↑. *(1.1)* | A |
| 18 | **Straight to the top.** Lord of the Flies is last and I want it next. There is no "to top" button: I press its ▲ once (now it is marked) and ↑ six times. *(1.1)* | A |
| 19 | **The next morning.** I put Out of the Past first. Next morning, on Watchlist, it is still first — every move was saved the moment I made it. Nothing is marked, so ↑ ↓ scroll until I mark a film. *(1.1)* | A |
| 20 | **Typing a rating, rating the marked film.** Watchlist plus Unrated by me, Out of the Past marked. In its rating box ↑ ↓ move nothing — the keys belong to the box. I type 8 and press Enter: it leaves the list and no row on screen is marked; ↑ ↓ scroll. I turn Rated off: Out of the Past is back, still marked, and ↑ moves it again. *(1.1)* | A |
| 21 | **The starred film I cannot see.** With Watchlist on I type *some* in the Title filter: no Some Came Running — it left the Criterion Channel unrated, so the catalogue hides it everywhere, as today. It keeps its place in my order (between Young Frankenstein and Lord of the Flies), and every move steps over it. *(1.1)* | A |

**Outcome.** The watchlist reads top to bottom as what I want to watch next, in my words, not the critics'.

**What wins when things trade off.** One press, one place. The film I move steps past one film I can see; every other film keeps its order relative to the rest (story 4).

### What you decided (2026-10-02)

- **Variant: A (chosen 2026-10-02).**
- **Story 5 — kept ("1").** Today On a list puts list score first and Watched puts last-watched first, ahead of every other rule. I recommend your order wins whenever Watchlist is on, so a chip never hides the arrows. The alternative: those two chips keep their order and the arrows hide while they are on.
- **Stories 7 and 14 — kept ("1"):** Undo, or a star put back in the same drawer, returns a film to its place; only a fresh star goes to the top.
- **Story 4 changed after the gap check:** a move used to be a swap, which let the OTHER film jump over hidden ones. Now only the film you press changes places.
- **Variant B and other clicks:** presses still waiting land first, before a chip, a sort or a row click changes the list; a reload with presses waiting loses them.
- **Where the arrows hide** (stories 6, 12, 13): a column sort, a list picked from the list menu, and a word search in the bar that ranks its answers. In each the list is not in your order. A Title column filter or a `director:` search only narrows, so the arrows stay.

### What deliberately does not ship

My Ranking arrows (ruling 1). Move buttons or move keys in the drawer (ruling 5, story 9). Drag-and-drop. A "to top" button. An Undo line for a move (story 3). Arrows or move keys under a column sort, a picked list or a ranking search (stories 6, 12, 13).

| Behaviour | Status |
|---|---|
| Today's default order of the 8 shown films (Metacritic, then RT, then IMDb, each descending) | read from `/api/films` on the 10 AM copy and sorted as `app.js` `compare()` does with no sort set |
| The counts (5204, 8, 9, 6 under Unrated by me, 5 under On a list) | read from the same copy; the tests re-cast them on their own seed |
| Move-on's label "Took X off your watchlist" and its Undo | the shipped code (`app.js`, the star toggle's `label:`); the Undo restoring the old PLACE is new |
| Variant B's "settle when the pointer leaves" | simulated only; never tried on the real dashboard |
| ↑ ↓ in the open drawer step to the next film | the shipped behaviour, confirmed by the gap checker on the real dashboard (Intolerance → Moonlight) |
| A failed save | simulated by the mock-up's "pretend the server is down" switch; the message mirrors the star's "Could not update watchlist" toast |
| The hidden ninth film's place | not shown on the mock-up (it never renders); see Builder's pages |

## Builder's pages

- **Data.** `watchlist` gains a dense `position` (migration 033, wrapped in BEGIN/COMMIT). The migration seeds positions in today's default order over all 9 rows, including Some Came Running, using the same COALESCE the FilmView uses for Metacritic. A star inserts at position 1 and shifts the rest down; an un-star closes the gap; Undo of an un-star re-inserts at the remembered position.
- **A move** is one write: the client sends the film, the direction and the visible neighbour it steps past; the server takes the film out and re-inserts it just past that neighbour, renumbering densely. Every other film keeps its relative order (story 4). The row moves at once; a failed write re-reads the order from the server (stars and Undo included — never a client-side snapshot) and toasts "Could not save the order" (story 15). A press on a row's ▲ ▼ sets `state.mark` to that film (story 10).
- **Keys** (ruling 6): with the drawer closed, the list in hand order and the marked film in the shown list, plain ↑ ↓ (no modifier, focus not in an input/select/textarea — the rating box included, story 20) move the marked film and keep the mark on it, nudging the list to keep it in view. A marked film that leaves the list keeps its mark (find-my-row) and the keys scroll until it is back. Otherwise ↑ ↓ keep today's behaviour. After a reload nothing is marked (story 19).
- **Star bookkeeping:** a drawer visit runs from opening to closing; steps by ↑ ↓ or by a click through the grey keep it going. Within a visit, every film un-starred remembers the film it sat above; a re-star in the same visit, or the move-on line's Undo, re-inserts it above that film (stories 7, 14) — anchored to a neighbour, not an index, so other stars in between cannot shift it. Any other star inserts at 1.
- **Three-state row click** (ruling 7): a click on the marked row with the drawer closed clears `state.mark` (today nothing ever clears it); any other row click opens as today; the ⓘ button always opens (story 11). A backdrop click on another dimmed row still steps (`moveDrawerTo`, as shipped); on the open film's own row or on no row it closes. Dashboard-wide.
- **Merges:** `merge_film` treats `watchlist` as a one-row table. When the survivor already holds a row, it keeps its own position and the loser's row is deleted (close the gap); when only the loser holds one, the survivor takes the loser's position. Neither case may leave a hole.
- **Read.** `FilmView` carries `watchlist_position`; `compare()` puts it first when Watchlist is on and no column sort, list or ranking search is active — ahead of On a list's canon score and Watched's last-watched (story 5).
- **The arrows** show only under that same condition and while the drawer is closed; the top visible film's ▲ and the bottom visible film's ▼ are disabled.
- **Out of scope here:** `rank_order` and `my-owned-tiers` (My Ranking) — a later item. When it comes, a move must write `rank_order` and then re-save the snapshot, because every Save rebuilds the list from `rank_order`.
