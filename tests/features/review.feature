Feature: match_review rows are resolved by CLI and never come back

  Background:
    Given films "Alpha (1950)" on Criterion and "King Kong (1933)" from commerce

  Scenario: Dismissing a tmdb no-match keeps it out of the next rebuild
    Given an open tmdb "no-match" review for "King Kong (1933)"
    When I resolve it with dismiss
    Then the review is resolved
    And rebuilding the tmdb no-match queue queues nothing for "King Kong (1933)"

  Scenario: Matching a no-match to a TMDB id claims the id and adopts the year
    Given an open tmdb "no-match" review for "King Kong (1933)"
    And TMDB says id 244 was released in 1933
    When I resolve it with tmdb id 244
    Then "King Kong (1933)" has tmdb id "244" and is found

  Scenario: A metacritic remake-suspected slug is created as its own film
    Given the archive staged "King Kong" (2005) as slug "king-kong-2005"
    And an open metacritic "year-gap" review for slug "king-kong-2005"
    When I resolve it with create
    Then a film "King Kong (2005)" exists holding metacritic slug "king-kong-2005"
    And re-running the archive match queues nothing for slug "king-kong-2005"

  Scenario: A metacritic slug is matched to an existing film
    Given the archive staged "Alpha" (1990) as slug "alpha-rr"
    And an open metacritic "year-gap" review for slug "alpha-rr"
    When I resolve it with film "Alpha (1950)"
    Then "Alpha (1950)" holds metacritic slug "alpha-rr"

  Scenario: An apple-tv year-drift is matched to a film and marks it owned
    Given an open apple-tv "year-drift" review for title "Alpha (Restored Version)"
    When I resolve it with film "Alpha (1950)"
    Then "Alpha (1950)" is owned
    And a later owned import of "Alpha (Restored Version)" year 2020 queues nothing

  Scenario: An apple-tv year-drift creates a new owned film
    Given an open apple-tv "year-drift" review for title "Alpha (2020)"
    When I resolve it with create
    Then a film "Alpha (2020)" exists and is owned

  Scenario: A tmdb id-conflict resolved to the holder merges the twins
    Given "Alpha (1950)" holds tmdb id "5"
    And an open tmdb "id-conflict" review for "King Kong (1933)" claiming id "5"
    When I resolve it with film "Alpha (1950)"
    Then "King Kong (1933)" is merged into "Alpha (1950)"

  Scenario: A tmdb id-conflict claiming an imdb id resolved to the holder merges the twins
    Given "Alpha (1950)" holds imdb id "tt0024216"
    And an open tmdb "id-conflict" review for "King Kong (1933)" claiming imdb id "tt0024216"
    When I resolve it with film "Alpha (1950)"
    Then "King Kong (1933)" is merged into "Alpha (1950)"

  Scenario: Invalid combinations are refused
    Given an open tmdb "no-match" review for "King Kong (1933)"
    Then resolving it with create fails
    And resolving it with both dismiss and film "Alpha (1950)" fails

  Scenario: A --film target that is a merged loser resolves to its survivor
    Given the archive staged "Alpha" (1990) as slug "alpha-rr"
    And an open metacritic "year-gap" review for slug "alpha-rr"
    And "King Kong (1933)" is merged into "Alpha (1950)"
    When I resolve it with film "King Kong (1933)"
    Then "Alpha (1950)" holds metacritic slug "alpha-rr"

  Scenario: A --film target that is tombstoned is refused
    Given the archive staged "Alpha" (1990) as slug "alpha-rr"
    And an open metacritic "year-gap" review for slug "alpha-rr"
    And "King Kong (1933)" is tombstoned
    Then resolving it with film "King Kong (1933)" fails

  Scenario: Picking candidate B keys the film to its tt and tmdb id and ratifies an eval row
    Given an open tmdb resolver review for "King Kong (1933)" with candidates A "tt0000001"/1 and B "tt0024216"/244
    And TMDB says id 244 was released in 1933
    When I resolve it with pick "B"
    Then "King Kong (1933)" holds imdb "tt0024216" and tmdb id "244"
    And the eval log has a verified human row for "King Kong (1933)" expecting "tt0024216"

  Scenario: --pick on an OMDb-only candidate finds the tmdb id through TMDB
    Given an open tmdb resolver review for "King Kong (1933)" with candidates A "tt0024216"/0 and B "tt0000001"/1
    And TMDB finds "tt0024216" as id 244 released in 1933
    When I resolve it with pick "A"
    Then "King Kong (1933)" holds imdb "tt0024216" and tmdb id "244"

  Scenario: --tt keys any tmdb no-match row, finding the tmdb id through TMDB
    Given an open tmdb "no-match" review for "King Kong (1933)"
    And TMDB finds "tt0024216" as id 244 released in 1933
    When I resolve it with tt "tt0024216"
    Then "King Kong (1933)" holds imdb "tt0024216" and tmdb id "244"
    And the eval log has a verified human row for "King Kong (1933)" expecting "tt0024216"

  Scenario: --tt without a TMDB client writes only the imdb id and warns
    Given an open tmdb "no-match" review for "King Kong (1933)"
    When I resolve it offline with tt "tt0024216"
    Then "King Kong (1933)" holds imdb "tt0024216" and no tmdb id
    And a warning mentions "tmdb id not resolved"

  Scenario: --none is a standing verified-unkeyed decision
    Given an open tmdb "no-match" review for "King Kong (1933)"
    When I resolve it with none
    Then the review is resolved
    And the eval log has a verified human row for "King Kong (1933)" expecting "NONE"
    And rebuilding the tmdb no-match queue queues nothing for "King Kong (1933)"

  Scenario: --pick on a row without candidates is refused
    Given an open tmdb "no-match" review for "King Kong (1933)"
    Then resolving it with pick "A" fails

  Scenario: A yearless ingestion ratifies a yearless eval row
    Given an open tmdb resolver review for "King Kong (1933)" with a yearless query and candidate A "tt0024216"/244
    When I resolve it with pick "A"
    Then the eval log row for "King Kong (1933)" has no ingested year

  Scenario: --tt refreshes a found-but-wrong OMDb stub
    Given an open tmdb "no-match" review for "King Kong (1933)"
    And "King Kong (1933)" has a found OMDb payload with imdb "ttOLD"
    When I resolve it offline with tt "ttNEW"
    Then "King Kong (1933)" needs an OMDb refresh

  Scenario: --tt matching the existing OMDb imdb id does not force a refresh
    Given an open tmdb "no-match" review for "King Kong (1933)"
    And "King Kong (1933)" has a found OMDb payload with imdb "ttOLD"
    When I resolve it offline with tt "ttOLD"
    Then "King Kong (1933)" does not need an OMDb refresh

  Scenario: --tt on a series keys it by IMDb id alone and marks the kind
    Given a commerce film "Dekalog (1988)"
    And an open tmdb "no-match-reviewed" review for "Dekalog (1988)"
    And TMDB finds "tt0092337" only as a series
    When I resolve it with tt "tt0092337"
    Then "Dekalog (1988)" holds imdb "tt0092337" and no tmdb id
    And the film "Dekalog (1988)" has kind "series"
    And the film "Dekalog (1988)" is not a keying target

  Scenario: --series forces the kind when TMDB knows nothing at all
    Given a commerce film "Dekalog (1988)"
    And an open tmdb "no-match-reviewed" review for "Dekalog (1988)"
    And TMDB finds nothing for "tt0092337"
    When I resolve it with tt "tt0092337" and --series
    Then the film "Dekalog (1988)" has kind "series"

  Scenario: --series is refused when TMDB says the id is a movie
    Given an open tmdb "no-match-reviewed" review for "King Kong (1933)"
    And TMDB finds "tt0024216" as id 244 released in 1933
    When I resolve it with tt "tt0024216" and --series it is refused
    Then the error mentions "TMDB has a movie"

  Scenario: --series is honoured even when TMDB also has a movie stub for the id (Dekalog)
    Given a commerce film "Dekalog (1988)"
    And an open tmdb "no-match-reviewed" review for "Dekalog (1988)"
    And TMDB finds "tt0092337" as id 37452 and also as a series
    When I resolve it with tt "tt0092337" and --series
    Then "Dekalog (1988)" holds imdb "tt0092337" and no tmdb id
    And the film "Dekalog (1988)" has kind "series"
    And no TMDB movie lookup was made for id 37452

  Scenario: --tt survives a TMDB lookup failure by keying imdb-only and warning
    Given an open tmdb "no-match" review for "King Kong (1933)"
    And TMDB fails to look up "tt0024216"
    When I resolve it with tt "tt0024216"
    Then "King Kong (1933)" holds imdb "tt0024216" and no tmdb id
    And a warning mentions "tmdb lookup failed"

  Scenario: A list entry is matched to an existing film
    Given a list "cahiers" with entry 1 "Alpha" by "Ann"
    And an open list "unresolved" review for "cahiers" rank 1
    When I resolve it with film "Alpha (1950)"
    Then list "cahiers" rank 1 is linked to "Alpha (1950)"
    And "Alpha (1950)" holds a list claim "cahiers#1"

  Scenario: A list entry that already sits at another rank refuses --film
    Given a list "cahiers" with entry 1 "Alpha" by "Ann"
    And list "cahiers" entry 2 "Alpha Twin" by "Ann" is already linked to "Alpha (1950)"
    And an open list "unresolved" review for "cahiers" rank 1
    Then resolving it with film "Alpha (1950)" fails

  Scenario: An entry that is already linked refuses --film for a different film
    # One entry can carry TWO open rows: queue_list_review_once dedups on reason + value, so
    # an `unresolved` row and a later `corpus-veto` row for the same rank both stay open.
    # Resolving the second one would silently MOVE the link — add_claim is INSERT OR IGNORE
    # on UNIQUE(authority, value), so the first film keeps the claim for an entry it no
    # longer holds and nothing records the move. This is the one refusal standing between
    # the feature and a wrong link made after the scorecard was printed.
    Given list "cahiers" entry 1 "Alpha" by "Ann" is already linked to "Alpha (1950)"
    And an open list "corpus-veto" review for "cahiers" rank 1
    Then resolving it with film "King Kong (1933)" fails
    And list "cahiers" rank 1 is linked to "Alpha (1950)"

  Scenario: An entry that is already linked refuses --create too
    Given list "cahiers" entry 3 "Nashville" by "Robert Altman" is already linked to "Alpha (1950)"
    And an open list "corpus-veto" review for "cahiers" rank 3
    Then resolving it with create fails
    And list "cahiers" rank 3 is linked to "Alpha (1950)"

  Scenario: A list entry creates a new unkeyed film
    Given a list "cahiers" with entry 5 "Nashville" by "Robert Altman"
    And an open list "unresolved" review for "cahiers" rank 5
    When I resolve it with create
    Then a film "Nashville" exists unkeyed and list "cahiers" rank 5 is linked to it
    And that film holds a list claim "cahiers#5"

  Scenario: A list --create colliding with an existing film's key links to it instead
    Given an unkeyed film "Nashville" with no year exists
    And a list "cahiers" with entry 7 "Nashville" by "Robert Altman"
    And an open list "unresolved" review for "cahiers" rank 7
    When I resolve it with create
    Then list "cahiers" rank 7 is linked to the yearless film "Nashville"

  Scenario: Dismissing a list entry leaves it unlinked forever
    Given a list "cahiers" with entry 9 "Nashville" by "Robert Altman"
    And an open list "unresolved" review for "cahiers" rank 9
    When I resolve it with dismiss
    Then the review is resolved
    And list "cahiers" rank 9 is not linked

  Scenario: --pick/--tt/--none are refused on list rows
    Given a list "cahiers" with entry 1 "Alpha" by "Ann"
    And an open list "unresolved" review for "cahiers" rank 1
    Then resolving it with pick "A" fails mentioning "apply to tmdb rows"

  # An id-disagreement row (supplied-id spec §5) is a `list` row like any other: no film_id,
  # so it drains through the SAME --film/--create/--dismiss verbs an `unresolved` or
  # `corpus-veto` row does — the reason names why the row was queued, not what can close it.

  Scenario: An id-disagreement entry is matched to an existing film
    Given a list "cahiers" with entry 1 "Alpha" by "Ann"
    And an open list "id-disagreement" review for "cahiers" rank 1
    When I resolve it with film "Alpha (1950)"
    Then list "cahiers" rank 1 is linked to "Alpha (1950)"
    And "Alpha (1950)" holds a list claim "cahiers#1"

  Scenario: An id-disagreement entry creates a new unkeyed film
    Given a list "cahiers" with entry 5 "Nashville" by "Robert Altman"
    And an open list "id-disagreement" review for "cahiers" rank 5
    When I resolve it with create
    Then a film "Nashville" exists unkeyed and list "cahiers" rank 5 is linked to it
    And that film holds a list claim "cahiers#5"

  Scenario: Dismissing an id-disagreement entry leaves it unlinked forever
    Given a list "cahiers" with entry 9 "Nashville" by "Robert Altman"
    And an open list "id-disagreement" review for "cahiers" rank 9
    When I resolve it with dismiss
    Then the review is resolved
    And list "cahiers" rank 9 is not linked

  Scenario: --pick/--tt/--none are refused on an id-disagreement row too — it has no film to key
    Given a list "cahiers" with entry 1 "Alpha" by "Ann"
    And an open list "id-disagreement" review for "cahiers" rank 1
    Then resolving it with pick "A" fails mentioning "apply to tmdb rows"
