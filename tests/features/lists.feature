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
    And the scorecard has no supplied-id tally line
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

  Scenario: gate 3 vetoes on a catalog film titled like the WINNER, not like the listed title
    # The phase-1 half of the same shape. The import creates nothing either way, so widening
    # its veto only moves this entry from would-create to blocked — but it moves it onto the
    # rehearsal card the owner authorises FROM, instead of promising a creation that phase 2
    # would then refuse. `films.key` would not have caught it: 1938 vs the winner's 1937.
    Given a film "Grand Illusion" (1938)
    And the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir" titled "Grand Illusion"
    And the list entry 68 is "La Grande Illusion" by "Jean Renoir"
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 0, blocked 1, error 0
    And entry 68 is unlinked
    And there is one open list review row for "cahiers-100#68" with reason "corpus-veto"
    And that review detail mentions "#1 'Grand Illusion' (1938)"
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

  Scenario: a catalog film titled like the WINNER, not like the listed title, still vetoes
    # The reviewer's traced twin: a legacy unkeyed row holds no ids (gates 1/2/2b all miss),
    # and it is titled nothing like the curator's entry, so a veto asked only about the LISTED
    # forms misses it too. `films.key` is the last backstop and it only refuses when title AND
    # year match — 1938 vs the winner's 1937 slips past. The veto must ask what the catalog
    # will GAIN, which is the winner's own title. It appears AFTER the import here: phase 1's
    # veto asks the same question now, so a look-alike present at import time is queued there
    # and this entry would never reach the create worklist at all.
    Given the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir" titled "Grand Illusion"
    And I imported the list with --apply for entry 68 "La Grande Illusion" by "Jean Renoir"
    And a film "Grand Illusion" (1938)
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 0, blocked 1, error 0
    And there is one open list review row for "cahiers-100#68" with reason "corpus-veto"
    And that review detail mentions "#1 'Grand Illusion' (1938)"
    And entry 68 is unlinked
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
    # The gates read the catalog ONCE, before the loop, so a film written after that read is
    # invisible to gate 3 and holds no ids for gates 1/2/2b — `films.key` is all that is left.
    # That race is the only way past gate 3 now that the veto also asks the WINNER's title:
    # a key collision means the same lower-cased title and year, which `norm_title` can only
    # fold further, so any collision against a film the index HAS is caught one gate earlier.
    And a film "Le Plaisir" (1952) appears mid-run, after the gates read the catalog
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 0, blocked 1, error 0
    And there is one open list review row for "cahiers-100#34" with reason "key-collision"
    And that review detail mentions "'le plaisir (1952)' is held by #1"
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
    And the scorecard line for entry 68 contains "→ WOULD-CREATE tt0028950"
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

  Scenario: a second rank landing on a creation this run could not key still blocks
    Given the candidate pool has "Greed" → tt0016654/613 1924 by "Erich von Stroheim"
    And the candidate pool has "Avarice" → tt0016654/613 1924 by "Erich von Stroheim"
    And the list entry 11 is "Greed" by "Erich von Stroheim"
    And the list entry 90 is "Avarice" by "Erich von Stroheim"
    And I imported the list with --apply
    # keying fails, so the new film carries no ids for gates 1/2/2b, and it is indexed under
    # the winner's title, not "Avarice" — the verdict's tt is the only surviving identity
    And tmdb lookups fail
    When I create films with --apply
    Then the create report says created 1, keyed 0, linked 0, blocked 1, error 0
    And exactly 1 film exists
    And entry 11 is linked to "Greed"
    And entry 90 is unlinked
    And there is one open list review row for "cahiers-100#90" with reason "duplicate-entry"
    And that review detail mentions "already linked at rank 11"

  Scenario: a gate 2b lookup failure refuses to create — the holder is unknown, not disproved
    Given the candidate pool has "Intolerance" → tt0006864 1916 by "David Wark Griffith" known only to OMDb
    And I imported the list with --apply for entry 69 "Intolerance" by "David Wark Griffith"
    And tmdb lookups fail
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 0, blocked 0, error 1
    And entry 69 is unlinked
    And there are no open list review rows
    And no film was created

  Scenario: a tombstoned holder found by gate 1 blocks the creation verb too
    Given the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And I imported the list with --apply for entry 69 "Intolerance" by "David Wark Griffith"
    And a film "Intolerance" (1916) holding imdb "tt0006864"
    And the film "Intolerance" is tombstoned
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 0, blocked 1, error 0
    And there is one open list review row for "cahiers-100#69" with reason "tombstoned-holder"
    And that review detail mentions "tombstoned #1"
    And entry 69 is unlinked
    And no film was created

  Scenario: creating with no TMDB token refuses the whole run rather than minting unguarded
    # gate 2b is not optional: without it `find_holder` answers "no holder" for every
    # OMDb-only winner and this verb would mint a twin beside a film TMDB could have found.
    Given the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir"
    And I imported the list with --apply for entry 68 "La Grande Illusion" by "Jean Renoir"
    And there is no TMDB token
    When I create films with --apply
    Then the create report exits 1
    And the create report considered 0 entries
    And no film was created

  # --- supplied IMDb ids (spec 2026-08-28-list-supplied-ids §5) -----------------------------
  # A list carrying ids is EXTERNAL GROUND TRUTH, so the resolver is run anyway and the two
  # answers are compared: the headline of such an import is the agreement rate, not the link
  # count. A supplied id settles WHICH work an entry is; it says nothing about whether the
  # catalog already holds that work, which is the only question the gates answer — so every
  # gate below runs exactly as it does with no id at all, and an agreement is never ratified
  # into the eval CSV.

  Scenario: an agreeing id links exactly where the same entry with no id links
    Given a film "Intolerance" (1916) directed by "David Wark Griffith" holding imdb "tt0006864"
    And the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And the list entry 69 is "Intolerance" by "David Wark Griffith" with id "tt0006864"
    When I import the list with --apply
    Then the report says linked 1, would-create 0, review 0, blocked 0, error 0
    And entry 69 is linked to "Intolerance"
    And the scorecard line for entry 69 contains "via imdb tt0006864"
    And the scorecard line for entry 69 contains "[id agrees]"
    And the id tally says agree 1, disagree 0, supplied 0, of 1 with ids
    And the same entries with their ids removed land on the same film
    And the eval CSV is byte-identical

  Scenario: a disagreeing id links nothing and creates nothing — two sources at odds need a human
    # The catalog HOLDS the resolver's tt, so today's gate 1 would link this entry outright.
    # The disagreement stops even that: a curator's id can be wrong, and so can the resolver.
    Given a film "Intolerance" (1916) holding imdb "tt0006864"
    And the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And the list entry 69 is "Intolerance" by "David Wark Griffith" with id "tt9999999"
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 1, blocked 0, error 0
    And entry 69 is unlinked
    And there is one open list review row for "cahiers-100#69" with reason "id-disagreement"
    And that review detail mentions "resolver tt0006864 [director corroborated] vs listed tt9999999"
    And the id tally says agree 0, disagree 1, supplied 0, of 1 with ids
    And no film was created
    And the eval CSV is byte-identical

  Scenario: an id settles an entry the resolver could not, and the gates then link it
    Given a film "Vertigo" (1958) holding imdb "tt0052357"
    And the candidate pool has nothing for "Vertigo"
    And the list entry 8 is "Vertigo" by "Alfred Hitchcock" with id "tt0052357"
    When I import the list with --apply
    Then the report says linked 1, would-create 0, review 0, blocked 0, error 0
    And entry 8 is linked to "Vertigo"
    And the scorecard line for entry 8 contains "via imdb tt0052357"
    And the scorecard line for entry 8 contains "[no candidates]"
    And the scorecard line for entry 8 contains "[id supplied]"
    And the id tally says agree 0, disagree 0, supplied 1, of 1 with ids
    And there are no open list review rows

  Scenario: a supplied id no gate can place is a would-create, and the import still creates nothing
    Given the candidate pool has nothing for "Vertigo"
    And the list entry 8 is "Vertigo" by "Alfred Hitchcock" with id "tt0052357"
    When I import the list with --apply
    Then the report says linked 0, would-create 1, review 0, blocked 0, error 0
    And the scorecard line for entry 8 contains "→ WOULD-CREATE tt0052357"
    And the scorecard line for entry 8 contains "[id supplied]"
    And entry 8 is unlinked
    And there are no open list review rows
    And no film was created

  Scenario: gate 3 still vetoes an entry whose id was supplied — a gate is never skipped for an id
    # THE invariant of this feature. A supplied id shortens the argument about which work this
    # is; it says nothing about whether the catalog already holds that work. Gates 1/2/2b/3 are
    # the only thing standing between this import and a duplicate film, and an id-bearing row
    # is no more exempt from them than any other. Optimising this away is how the first
    # duplicate gets made.
    Given a film "La Grande Illusion" (1937)
    And the candidate pool has nothing for "La Grande Illusion"
    And the list entry 68 is "La Grande Illusion" by "Jean Renoir" with id "tt0028950"
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 0, blocked 1, error 0
    And entry 68 is unlinked
    And there is one open list review row for "cahiers-100#68" with reason "corpus-veto"
    And that review detail mentions "#1 'La Grande Illusion' (1937)"
    And the scorecard line for entry 68 contains "corpus-veto"
    And the scorecard line for entry 68 contains "[id supplied]"
    And no film was created

  Scenario: a supplied id whose work is tombstoned still blocks — gate 1 runs on that path too
    Given a film "Intolerance" (1916) holding imdb "tt0006864"
    And the film "Intolerance" is tombstoned
    And the candidate pool has nothing for "Intolerance"
    And the list entry 69 is "Intolerance" by "David Wark Griffith" with id "tt0006864"
    When I import the list with --apply
    Then the report says linked 0, would-create 0, review 0, blocked 1, error 0
    And entry 69 is unlinked
    And there is one open list review row for "cahiers-100#69" with reason "tombstoned-holder"
    And no film was created

  Scenario: the agreement tally is the headline of a supplied-id import
    Given a film "Intolerance" (1916) directed by "David Wark Griffith" holding imdb "tt0006864"
    And the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And the candidate pool has "Greed" → tt0016654/613 1924 by "Erich von Stroheim"
    And the candidate pool has nothing for "Vertigo"
    And the list entry 69 is "Intolerance" by "David Wark Griffith" with id "tt0006864"
    And the list entry 11 is "Greed" by "Erich von Stroheim" with id "tt9999999"
    And the list entry 8 is "Vertigo" by "Alfred Hitchcock" with id "tt0052357"
    When I import the list with --apply
    Then the id tally says agree 1, disagree 1, supplied 1, of 3 with ids
    And the scorecard tally line is "resolver vs supplied id:  agree 1 · disagree 1 · resolver had no verdict 1  (of 3 compared)"

  Scenario: an entry carrying no id is not counted in the tally of a list that mixes both
    Given the candidate pool has "Greed" → tt0016654/613 1924 by "Erich von Stroheim"
    And the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And the list entry 11 is "Greed" by "Erich von Stroheim" with id "tt0016654"
    And the list entry 69 is "Intolerance" by "David Wark Griffith"
    When I import the list with --apply
    Then the report says linked 0, would-create 2, review 0, blocked 0, error 0
    And the id tally says agree 1, disagree 0, supplied 0, of 1 with ids
    And the scorecard line for entry 69 contains "→ WOULD-CREATE tt0006864"
    And no film was created

  Scenario: an already-linked id-bearing entry never reaches reconcile, so the tally line is absent
    # Re-import is idempotent: an entry with a stored film_id is skipped BEFORE the fetcher is
    # touched, so it never reaches `reconcile` and cannot be scored — the tally line answers
    # only for entries actually compared, never for entries merely carrying an id in the file.
    Given a film "Intolerance" (1916) directed by "David Wark Griffith" holding imdb "tt0006864"
    And the candidate pool has "Intolerance" → tt0006864/3059 1916 by "David Wark Griffith"
    And I imported the list with --apply for entry 69 "Intolerance" by "David Wark Griffith" with id "tt0006864"
    When I import the list with --apply
    Then the report says linked 1, would-create 0, review 0, blocked 0, error 0
    And the id tally says agree 0, disagree 0, supplied 0, of 0 with ids
    And the scorecard has no supplied-id tally line

  Scenario: an id the re-resolved verdict now contradicts blocks the creation
    # Phase 2 re-resolves and re-reconciles every entry: phase 1's agreement is never trusted,
    # the same re-derive-at-resolution-time rule the gates already follow.
    Given the candidate pool has "La Grande Illusion" → tt0028950/6821 1937 by "Jean Renoir"
    And I imported the list with --apply for entry 68 "La Grande Illusion" by "Jean Renoir" with id "tt0028950"
    And the candidate pool has "La Grande Illusion" → tt7777777/777 1937 by "Jean Renoir"
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 0, blocked 1, error 0
    And there is one open list review row for "cahiers-100#68" with reason "id-disagreement"
    And that review detail mentions "resolver tt7777777"
    And entry 68 is unlinked
    And no film was created
    And the eval CSV is byte-identical

  Scenario: a supplied id the resolver could not confirm mints the film the gates all missed
    Given the candidate pool has nothing for "Vertigo"
    And I imported the list with --apply for entry 8 "Vertigo" by "Alfred Hitchcock" with id "tt0052357"
    When I create films with --apply
    Then the create report says created 1, keyed 1, linked 0, blocked 0, error 0
    And exactly 1 film exists
    And entry 8 is linked to "Vertigo"
    And the film "Vertigo" holds imdb "tt0052357"
    And the id tally says agree 0, disagree 0, supplied 1, of 1 with ids
    And the eval CSV is byte-identical

  Scenario: gate 3 vetoes the creating verb too when the id was supplied
    Given the candidate pool has nothing for "Vertigo"
    And I imported the list with --apply for entry 8 "Vertigo" by "Alfred Hitchcock" with id "tt0052357"
    And a film "Vertigo" (1958)
    When I create films with --apply
    Then the create report says created 0, keyed 0, linked 0, blocked 1, error 0
    And there is one open list review row for "cahiers-100#8" with reason "corpus-veto"
    And entry 8 is unlinked
    And no film was created

  Scenario: a supplied id among the resolver's own candidates hands gate 2 THAT candidate's tmdb id
    # The shape the id column exists to settle: an ambiguous tie in which the curator's id names
    # one of the tied works. `_gate_verdict` re-points the review verdict at the supplied tt and
    # `_winner` selects on tt — never `ranked[0]`, which here is the OTHER work. Simplify
    # `_winner` to `ranked[0]` and this entry silently links to the wrong film.
    Given a film "Le Plaisir" (1962) holding tmdb "2"
    And the candidate pool has "Pleasure" → tt1/1 1952 titled "House of Pleasure" and tt2/2 1962 titled "Le Plaisir"
    And the list entry 34 is "Pleasure" by "Max Ophüls" with id "tt2"
    When I import the list with --apply
    Then the report says linked 1, would-create 0, review 0, blocked 0, error 0
    And entry 34 is linked to "Le Plaisir"
    And the scorecard line for entry 34 contains "via tmdb 2"
    And the scorecard line for entry 34 contains "[weak]"
    And the scorecard line for entry 34 contains "[id supplied]"
    And gate 2b was never asked
    And the id tally says agree 0, disagree 0, supplied 1, of 1 with ids

  Scenario: phase 2 mints a supplied-id entry under THAT candidate's title and year
    # The creating half of the same branch: title, year and tmdb id all come from the candidate
    # the SUPPLIED id names, so the row the catalog gains describes the work the curator meant.
    # `ranked[0]` here is 'House of Pleasure' (1952) — a different work entirely.
    Given the candidate pool has "Pleasure" → tt1/1 1952 titled "House of Pleasure" and tt2/2 1962 titled "Le Plaisir"
    And I imported the list with --apply for entry 34 "Pleasure" by "Max Ophüls" with id "tt2"
    When I create films with --apply
    Then the create report says created 1, keyed 1, linked 0, blocked 0, error 0
    And exactly 1 film exists
    And the film "Le Plaisir" is dated 1962 and directed by "Max Ophüls"
    And the film "Le Plaisir" holds imdb "tt2" and tmdb "2"
    And entry 34 is linked to "Le Plaisir"
    And the film "Le Plaisir" carries a list claim "cahiers-100#34" ingested as "Pleasure"
    And the id tally says agree 0, disagree 0, supplied 1, of 1 with ids
    And the eval CSV is byte-identical
