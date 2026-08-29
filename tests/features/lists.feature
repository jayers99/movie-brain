Feature: Curated lists — the import links and asks; only the create verb ever mints a film

  Both verbs are an accuracy test of the T1-T5 identity stack (seed §0) and duplicate films
  are the failure they must not produce, so every gate that cannot PROVE a link refuses and
  queues a review row. Phase 1 never creates on any path; phase 2 re-runs every gate at the
  moment it creates, because the world may have moved since the import.

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
    And the scorecard line for entry 68 contains "→ WOULD-CREATE tt0028950"
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

  Scenario: a gate 2b lookup failure is an error, not a would-create
    Given the candidate pool has "Intolerance" → tt0006864 1916 by "David Wark Griffith" known only to OMDb
    And tmdb lookups fail
    And the list entry 69 is "Intolerance" by "David Wark Griffith"
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 0, blocked 0, error 1
    And entry 69 is unlinked
    And there are no open list review rows
    And no film was created

  Scenario: one entry blowing up unexpectedly never aborts the run
    Given the candidate pool blows up for "Vertigo"
    And the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir"
    And the list entry 8 is "Vertigo" by "Alfred Hitchcock"
    And the list entry 68 is "La Grande Illusion" by "Jean Renoir"
    When I import the list with --apply
    Then the report says linked 0, would-create 1, review 0, blocked 0, error 1
    And entry 8 is unlinked
    And there are no open list review rows
    And no film was created

  Scenario: creation mints the film under the WINNER's title and year, links it and keys it
    Given the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir" titled "Grand Illusion"
    And I imported the list with --apply for entry 68 "La Grande Illusion" by "Jean Renoir"
    When I create films with --apply
    Then the create report considered 1 entry
    And the create report says created 1, keyed 1, linked 0, blocked 0, error 0
    And exactly 1 film exists
    And the film "Grand Illusion" is dated 1937 and directed by "Jean Renoir"
    And the film "Grand Illusion" holds imdb "tt0028950" and tmdb "6821"
    And entry 68 is linked to "Grand Illusion"
    And the film "Grand Illusion" carries a list claim "cahiers-100#68" ingested as "La Grande Illusion"
    And there are no open list review rows
    And the eval CSV is byte-identical

  Scenario: a holder that appeared since the import is linked, and nothing is created
    Given the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir"
    And I imported the list with --apply for entry 68 "La Grande Illusion" by "Jean Renoir"
    And a film "Grand Illusion" (1937) holding imdb "tt0028950"
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 1, blocked 0, error 0
    And entry 68 is linked to "Grand Illusion"
    And the film "Grand Illusion" carries a list claim "cahiers-100#68" ingested as "La Grande Illusion"
    And no film was created

  Scenario: a look-alike that appeared since the import vetoes creation
    Given the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir"
    And I imported the list with --apply for entry 68 "La Grande Illusion" by "Jean Renoir"
    And a film "La Grande Illusion" (1937)
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 0, blocked 1, error 0
    And there is one open list review row for "cahiers-100#68" with reason "corpus-veto"
    And entry 68 is unlinked
    And no film was created

  Scenario: an entry that no longer resolves blocks and queues instead of guessing
    Given the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir"
    And I imported the list with --apply for entry 68 "La Grande Illusion" by "Jean Renoir"
    And the candidate pool has "La Grande Illusion" → tt1/1 1937 and tt2/2 1937
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 0, blocked 1, error 0
    And there is one open list review row for "cahiers-100#68" with reason "unresolved"
    And no film was created

  Scenario: a tombstoned key blocks creation — the list is not a resurrection request
    Given the candidate pool has "Pleasure" → tt0044943/60426 1952 by "Max Ophüls" titled "Le Plaisir"
    And I imported the list with --apply for entry 34 "Pleasure" by "Max Ophüls"
    And a film "Le Plaisir" (1952)
    And the film "Le Plaisir" is tombstoned
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 0, blocked 1, error 0
    And there is one open list review row for "cahiers-100#34" with reason "tombstoned-holder"
    And that review detail mentions "key 'le plaisir (1952)' is tombstoned"
    And entry 34 is unlinked
    And no film was created

  Scenario: a films.key collision blocks and queues — the colliding film is never adopted
    Given the candidate pool has "Pleasure" → tt0044943/60426 1952 by "Max Ophüls" titled "Le Plaisir"
    And I imported the list with --apply for entry 34 "Pleasure" by "Max Ophüls"
    # gate 3 misses: nothing in the catalog resembles the LISTED title "Pleasure"
    And a film "Le Plaisir" (1952)
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 0, blocked 1, error 0
    And there is one open list review row for "cahiers-100#34" with reason "key-collision"
    And that review detail mentions "'le plaisir (1952)' is held by #1 'Le Plaisir' (1952)"
    And entry 34 is unlinked
    And no film was created

  Scenario: a second rank landing on this run's own creation blocks instead of double-linking
    Given the candidate pool has "Greed" → tt0016654/613 1924 by "Erich von Stroheim"
    And the candidate pool has "Avarice" → tt0016654/613 1924 by "Erich von Stroheim"
    And the list entry 11 is "Greed" by "Erich von Stroheim"
    And the list entry 90 is "Avarice" by "Erich von Stroheim"
    And I imported the list with --apply
    When I create films with --apply
    Then the create report says created 1, keyed 1, linked 0, blocked 1, error 0
    And exactly 1 film exists
    And entry 11 is linked to "Greed"
    And entry 90 is unlinked
    And there is one open list review row for "cahiers-100#90" with reason "duplicate-entry"
    And that review detail mentions "already linked at rank 11"

  Scenario: a rank whose review row is still open is not in the create worklist
    Given the candidate pool has "Pleasure" → tt1/1 1952 and tt2/2 1952
    And I imported the list with --apply for entry 34 "Pleasure" by "Max Ophüls"
    When I create films with --apply
    Then the create report considered 0 entries
    And the create report says created 0, keyed 0, linked 0, blocked 0, error 0
    And no film was created

  Scenario: a rank whose review row was resolved is not in the create worklist either
    Given the candidate pool has "Pleasure" → tt1/1 1952 and tt2/2 1952
    And I imported the list with --apply for entry 34 "Pleasure" by "Max Ophüls"
    And the "cahiers-100#34" review row is resolved
    When I create films with --apply
    Then the create report considered 0 entries
    And the create report says created 0, keyed 0, linked 0, blocked 0, error 0
    And no film was created

  Scenario: a create dry run writes nothing at all
    Given the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir" titled "Grand Illusion"
    And the candidate pool has "Greed" → tt0016654/613 1924 by "Erich von Stroheim"
    And the list entry 11 is "Greed" by "Erich von Stroheim"
    And the list entry 68 is "La Grande Illusion" by "Jean Renoir"
    And I imported the list with --apply
    And a film "Greed" (1924)
    When I create films without --apply
    Then the create report says created 1, keyed 0, linked 0, blocked 1, error 0
    And no film was created
    And entry 68 is unlinked
    And there are no list claims
    And there are no open list review rows

  Scenario: a keying failure still leaves the film created — the next sync retries it
    Given the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir" titled "Grand Illusion"
    And I imported the list with --apply for entry 68 "La Grande Illusion" by "Jean Renoir"
    And tmdb lookups fail
    When I create films with --apply
    Then the create report says created 1, keyed 0, linked 0, blocked 0, error 0
    And exactly 1 film exists
    And entry 68 is linked to "Grand Illusion"
    And the film "Grand Illusion" holds no imdb id

  Scenario: creating on a list that was never imported fails the run rather than guessing
    When I create films for "no-such-list"
    Then the create report exits 1
    And the create report considered 0 entries
    And no film was created
