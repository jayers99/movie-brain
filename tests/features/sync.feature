Feature: Daily sync
  Walk the Criterion catalog by mediaid (spec 2026-10-01), then the rest of the night: Metacritic
  promotion, keying, OMDb ratings, TMDB availability, the catch-up chain. One source's weather
  never breaks another: a failed Criterion walk writes nothing for Criterion, the rest still runs,
  and the sync exits 1.

  Background:
    Given a fresh repository
    And the Criterion home page links no dated leaving page

  Scenario: Sync lists the films Criterion carries and fills their ratings (story 1)
    # two films seeded with no listing: both arrive
    Given Criterion lists my films "Trio (1950)" and "Quartet (1948)"
    And OMDb knows every film
    And the resolver keys every film
    When I sync
    Then the exit code is 0
    And 2 films are current
    And 2 films have OMDb ratings
    And films_fetched_at is today
    And the sync reports criterion arrived 2, left 0, to review 0

  Scenario: A film Criterion dropped is departed, kept, and loses its Leaving label (stories 5 and 11)
    # both listed 9 days ago (the frontier); only Nadja is re-stamped
    Given the last walk listed "Some Came Running (1958)" and "Nadja (1994)" 9 days ago
    And "Some Came Running (1958)" is leaving "September 30"
    And Criterion lists my films "Nadja (1994)"
    And OMDb knows every film
    When I sync
    Then the exit code is 0
    And 1 films are current
    And "Some Came Running (1958)" is still in the database
    And "Some Came Running (1958)" is not leaving
    And the sync reports criterion arrived 0, left 1, to review 0

  Scenario: A departed rated film is kept and shown as departed
    Given the last walk listed "Trio (1950)" and "Quartet (1948)" 9 days ago
    And I have rated "Quartet (1948)"
    And Criterion lists my films "Trio (1950)"
    And OMDb knows every film
    When I sync
    Then "Quartet (1948)" is in the dashboard marked departed

  Scenario: A watchlisted film arriving on Criterion fires the one summary notification
    # Trio is re-stamped (no arrival); Barry Lyndon had no listing (one arrival, watchlisted)
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Barry Lyndon (1975)" is on the watchlist
    And Criterion lists my films "Trio (1950)" and "Barry Lyndon (1975)"
    And OMDb knows every film
    When I sync with a notifier
    Then one notification was sent naming "Barry Lyndon on Criterion Channel"
    And the sync reports criterion arrived 1, left 0, to review 0

  Scenario: The Leaving chip gets October's list from the dated leaving page (story 6)
    # the captured playlist names 28 films; Zabriskie Point is the only one we hold
    Given Criterion calls "Zabriskie Point (1970)" "Tg73fdO2"
    And the last walk listed "Zabriskie Point (1970)" and "Nadja (1994)" 2 days ago
    And "Nadja (1994)" is leaving "September 30"
    And Criterion lists my films "Zabriskie Point (1970)" and "Nadja (1994)"
    And the Criterion home page links the October 31 leaving page
    And OMDb knows every film
    When I sync
    Then "Zabriskie Point (1970)" is leaving "October 31"
    And "Nadja (1994)" is not leaving

  Scenario: A leaving page that cannot be read keeps the labels of the films still listed
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is leaving "August 31"
    And Criterion lists my films "Trio (1950)"
    And the Criterion home page answers 500
    And OMDb knows every film
    When I sync
    Then the exit code is 0
    And "Trio (1950)" is leaving "August 31"

  Scenario: A catalog failure writes nothing for Criterion, and the rest of the night still runs (story 8)
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is already keyed to imdb "tt0037800"
    And the Criterion catalog answers 500
    And OMDb knows every film
    When I sync
    Then the exit code is 1
    And the sync reports the Criterion walk failed
    And 1 films are current
    And 1 films have OMDb ratings

  Scenario: A JW Player failure for a new film writes nothing for Criterion, and the rest still runs (story 8)
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is already keyed to imdb "tt0037800"
    And Criterion lists my films "Trio (1950)"
    And Criterion also lists a new film "2 or 3 Things I Know About Her" (1967) as "L5Z3RaiC"
    And JW Player answers 500 for "L5Z3RaiC"
    And the resolver finds nothing
    And OMDb knows every film
    When I sync
    Then the exit code is 1
    And the sync reports the Criterion walk failed
    And 1 films have OMDb ratings
    And there are 0 open criterion reviews
    And the Criterion listing of "Trio (1950)" was last seen 2 days ago

  Scenario: A failure late in the walk's write is caught before the rest of the night runs (story 8)
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is already keyed to imdb "tt0037800"
    And Criterion lists my films "Trio (1950)"
    And OMDb knows every film
    And the walk's write fails at its last step
    When I sync
    Then the exit code is 1
    And when the keying step began, Criterion was exactly as it was before the sync
    And 1 films have OMDb ratings

  Scenario: A series is never a film (Lone Wolf and Cub, story 18)
    # Sword of Vengeance holds only its old link (the episodes now 404): it departs; Trio arrives
    Given the last walk listed "Lone Wolf and Cub: Sword of Vengeance (1972)" 2 days ago under its old link
    And Criterion lists my films "Trio (1950)"
    And the catalog also carries the series "Lone Wolf and Cub" as "rLiSVzkD"
    And OMDb knows every film
    When I sync
    Then no film is titled "Lone Wolf and Cub"
    And there are 0 open criterion reviews
    And the sync reports criterion arrived 1, left 1, to review 0

  Scenario: A new film the resolver cannot place becomes one review row, asked about once (story 7)
    Given Criterion lists my films "Trio (1950)"
    And Criterion also lists a new film "2 or 3 Things I Know About Her" (1967) as "L5Z3RaiC"
    And JW Player serves its captured record for "L5Z3RaiC"
    And the resolver finds nothing
    And OMDb knows every film
    When I sync
    Then there is 1 open criterion "no-match" review for "L5Z3RaiC"
    And the sync reports criterion arrived 1, left 0, to review 1
    When I sync again the next day
    Then there is 1 open criterion "no-match" review for "L5Z3RaiC"
    And JW Player was asked about "L5Z3RaiC" 1 time

  Scenario: --ratings-only skips Criterion
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is already keyed to imdb "tt0037800"
    And OMDb knows every film
    When I sync with --ratings-only
    Then the exit code is 0
    And Criterion was never contacted
    And 1 films have OMDb ratings

  Scenario: The catch-up chain runs at the tail of a sync, after identity, ratings and availability
    Given Criterion lists my films "Trio (1950)" and "Quartet (1948)"
    And OMDb knows every film
    And the resolver keys every film
    When I sync with a catch-up chain
    Then the exit code is 0
    And the catch-up chain ran once, after 2 films had OMDb ratings
    And the sync result carries the catch-up report

  Scenario: A catch-up chain that blows up never changes the sync's outcome
    Given Criterion lists my films "Trio (1950)" and "Quartet (1948)"
    And OMDb knows every film
    And the resolver keys every film
    When I sync with a catch-up chain that fails
    Then the exit code is 0
    And 2 films have OMDb ratings

  Scenario: --ratings-only runs no catch-up
    Given the last walk listed "Trio (1950)" 2 days ago
    And "Trio (1950)" is already keyed to imdb "tt0037800"
    And OMDb knows every film
    When I sync with --ratings-only and a catch-up chain
    Then the exit code is 0
    And the catch-up chain never ran

  Scenario: Enriching after an add skips Criterion but keys, rates and catches up
    Given the last walk listed "Trio (1950)" 2 days ago
    And OMDb knows every film
    And the resolver keys every film
    When I run the after-add enrichment with a catch-up chain
    Then the exit code is 0
    And Criterion was never contacted
    And 1 films have OMDb ratings
    And the catch-up chain ran once, after 1 films had OMDb ratings

  Scenario: --ratings-only without a stored catalog fails
    When I sync with --ratings-only
    Then the exit code is 1

  Scenario: OMDb quota stops lookups but keeps what was fetched
    Given Criterion lists my films "Trio (1950)" and "Quartet (1948)"
    And OMDb answers once then reports the request limit
    And the resolver keys every film
    When I sync
    Then the exit code is 0
    And the quota flag is set
    And 1 films have OMDb ratings

  Scenario: OMDb rejects the key
    Given Criterion lists my films "Trio (1950)"
    And OMDb rejects the API key
    And the resolver keys every film
    When I sync
    Then the exit code is 2

  Scenario: Repeated OMDb failures stop lookups but keep what was fetched
    Given Criterion lists my films "Trio (1950)" and "Quartet (1948)" and "Third (1960)" and "Fourth (1970)" and "Fifth (1980)" and "Sixth (1990)" and "Seventh (2000)"
    And OMDb answers once then errors repeatedly
    And the resolver keys every film
    When I sync
    Then the exit code is 0
    And the failing flag is set
    And 1 films have OMDb ratings

  Scenario: Sync promotes staged Metacritic titles into films
    Given Criterion lists my films "Alpha (1950)"
    And OMDb knows every film
    And the metacritic archive holds "Fresh Find" (2020) scored 95 as "fresh-find"
    When I sync with a metacritic archive
    Then the exit code is 0
    And the repository holds a film for key "fresh find (2020)"

  Scenario: A missing metacritic archive never breaks the sync
    Given Criterion lists my films "Alpha (1950)"
    And OMDb knows every film
    When I sync with a metacritic archive
    Then the exit code is 0

  Scenario: Promoted films get OMDb ratings the same night
    Given Criterion lists my films "Alpha (1950)"
    And OMDb knows every film
    And the resolver keys every film
    And the metacritic archive holds "Fresh Find" (2020) scored 95 as "fresh-find"
    When I sync with a metacritic archive
    Then the film for key "fresh find (2020)" has an OMDb rating
