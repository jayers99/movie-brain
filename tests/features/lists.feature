Feature: Curated lists phase 1 — the import links and asks, and never mints a film

  The import is an accuracy test of the T1-T5 identity stack (seed §0) and duplicate films
  are the failure it must not produce, so every gate that cannot PROVE a link refuses and
  queues a review row. Creation is a separate, confirmed verb; nothing here creates a film.

  Background:
    Given the list "cahiers-100" curated by "Cahiers du Cinéma" (2008)

  Scenario: gate 1 links the entry to the film already holding the imdb id
    Given a film "Intolerance" (1916) directed by "David Wark Griffith" holding imdb "tt0006864"
    And the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And the list entry 69 is "Intolerance" by "David Wark Griffith"
    When I import the list with --apply
    Then the report says linked 1, would-create 0, review 0, blocked 0, error 0
    And entry 69 is linked to "Intolerance"
    And the film "Intolerance" carries a list claim "cahiers-100#69" ingested as "Intolerance"
    And the scorecard line for entry 69 contains "→ LINKED"
    And the scorecard line for entry 69 contains "'Intolerance' (1916) dir David Wark Griffith"
    And the scorecard line for entry 69 contains "via imdb tt0006864"
    And no film was created

  Scenario: gate 2 links through the winning candidate's tmdb id
    Given a film "Intolerance" (1916) holding tmdb "3059"
    And the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And the list entry 69 is "Intolerance" by "David Wark Griffith"
    When I import the list with --apply
    Then the report says linked 1, would-create 0, review 0, blocked 0, error 0
    And entry 69 is linked to "Intolerance"
    And the scorecard line for entry 69 contains "via tmdb 3059"

  Scenario: gate 2b links through find_by_imdb when the winner is known only to OMDb
    Given a film "Intolerance" (1916) holding tmdb "3059"
    And the candidate pool has "Intolerance" → tt0006864 1916 by "David Wark Griffith" known only to OMDb
    And tmdb maps "tt0006864" to 3059
    And the list entry 69 is "Intolerance" by "David Wark Griffith"
    When I import the list with --apply
    Then the report says linked 1, would-create 0, review 0, blocked 0, error 0
    And entry 69 is linked to "Intolerance"
    And the scorecard line for entry 69 contains "via tmdb(find 3059)"

  Scenario: a corpus look-alike vetoes creation and queues a review row
    Given a film "Greed" (1924)
    And the candidate pool has "Greed" → tt0016654/613 1924 by "Erich von Stroheim"
    And the list entry 11 is "Greed" by "Erich von Stroheim"
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 0, blocked 1, error 0
    And entry 11 is unlinked
    And there is one open list review row for "cahiers-100#11" with reason "corpus-veto"
    And that review detail mentions "Greed"
    And no film was created

  Scenario: a second rank resolving to an already-linked film blocks as a duplicate entry
    Given a film "Greed" (1924) holding imdb "tt0016654"
    And the candidate pool has "Greed" → tt0016654/613 1924 by "Erich von Stroheim"
    And the candidate pool has "Avarice" → tt0016654/613 1924 by "Erich von Stroheim"
    And the list entry 11 is "Greed" by "Erich von Stroheim"
    And the list entry 90 is "Avarice" by "Erich von Stroheim"
    When I import the list with --apply
    Then the report says linked 1, would-create 0, review 0, blocked 1, error 0
    And entry 11 is linked to "Greed"
    And entry 90 is unlinked
    And there is one open list review row for "cahiers-100#90" with reason "duplicate-entry"
    And that review detail mentions "already linked at rank 11"

  Scenario: a tombstoned holder blocks — the list is not a resurrection request
    Given a film "Intolerance" (1916) holding imdb "tt0006864"
    And the film "Intolerance" is tombstoned
    And the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And the list entry 69 is "Intolerance" by "David Wark Griffith"
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 0, blocked 1, error 0
    And entry 69 is unlinked
    And there is one open list review row for "cahiers-100#69" with reason "tombstoned-holder"
    And no film was created

  Scenario: a resolver review verdict queues one unresolved row carrying its candidates
    Given the candidate pool has "Pleasure" → tt1/1 1952 and tt2/2 1952
    And the list entry 34 is "Pleasure" by "Max Ophüls"
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 1, blocked 0, error 0
    And entry 34 is unlinked
    And there is one open list review row for "cahiers-100#34" with reason "unresolved"
    And that review detail mentions "A tt1"
    And that review detail mentions "B tt2"
    And no film was created

  Scenario: two entries sharing a reason each keep their own row — dedup is on value, not film_id
    Given the candidate pool has "Pleasure" → tt1/1 1952 and tt2/2 1952
    And the candidate pool has "Tabu" → tt3/3 1931 and tt4/4 1931
    And the list entry 34 is "Pleasure" by "Max Ophüls"
    And the list entry 82 is "Tabu" by "Friedrich Wilhelm Murnau"
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 2, blocked 0, error 0
    And there are 2 open list review rows

  Scenario: a resolved review row is a standing decision and is never re-queued
    Given the candidate pool has "Pleasure" → tt1/1 1952 and tt2/2 1952
    And the list entry 34 is "Pleasure" by "Max Ophüls"
    And I imported the list with --apply
    And the "cahiers-100#34" review row is resolved
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 1, blocked 0, error 0
    And there are no open list review rows

  Scenario: an entry whose every lookup fails is an error, not a durable review row
    Given the candidate pool is offline for "Vertigo"
    And the list entry 8 is "Vertigo" by "Alfred Hitchcock"
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 0, blocked 0, error 1
    And entry 8 is unlinked
    And there are no open list review rows

  Scenario: every gate missing is reported would-create, and still nothing is created
    Given the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir"
    And the list entry 68 is "La Grande Illusion" by "Jean Renoir"
    When I import the list with --apply
    Then the report says linked 0, would-create 1, review 0, blocked 0, error 0
    And entry 68 is unlinked
    And there are no open list review rows
    And the scorecard line for entry 68 contains "→ WOULD-CREATE  tt0028950"
    And no film was created

  Scenario: a dry run writes nothing at all
    Given a film "Intolerance" (1916) holding imdb "tt0006864"
    And the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And the candidate pool has "Pleasure" → tt1/1 1952 and tt2/2 1952
    And the list entry 34 is "Pleasure" by "Max Ophüls"
    And the list entry 69 is "Intolerance" by "David Wark Griffith"
    When I import the list without --apply
    Then the report says linked 1, would-create 0, review 1, blocked 0, error 0
    And the list registry is empty
    And there are no list entries
    And there are no open list review rows
    And there are no list claims
    And no film was created

  Scenario: a re-import is idempotent and asks the resolver nothing about a linked entry
    Given a film "Intolerance" (1916) holding imdb "tt0006864"
    And the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And the candidate pool has "Pleasure" → tt1/1 1952 and tt2/2 1952
    And the list entry 34 is "Pleasure" by "Max Ophüls"
    And the list entry 69 is "Intolerance" by "David Wark Griffith"
    And I imported the list with --apply
    When I import the list with --apply
    Then the report says linked 1, would-create 0, review 1, blocked 0, error 0
    And entry 69 is linked to "Intolerance"
    And there is one open list review row for "cahiers-100#34" with reason "unresolved"
    And the resolver was not asked about "Intolerance" on the second run
    And the film "Intolerance" carries a list claim "cahiers-100#69" ingested as "Intolerance"
    And no film was created
