Feature: Import criterion-ratings data
  Bring catalog, ratings cache, payloads and my ratings into SQLite once.

  Background:
    Given a legacy data dir with catalog "Trio (1950)" and "Quartet (1948)" fetched 2026-08-10 leaving Trio "August 31"
    And the legacy cache rates Trio 7.1/90 English and marks Quartet not found
    And a legacy payload file exists for Trio
    And legacy annotations rate Trio 8 and "Ghost (1999)" 5

  Scenario: Everything maps over
    When I import the legacy dir
    Then the report counts 2 films, 2 omdb rows, 1 payloads, 1 ratings
    And the report lists unmatched key "ghost (1999)"
    And Trio's view shows imdb 7.1, rt 90, leaving "August 31", first_seen 2026-08-10, my rating 8
    And Trio's payload contains "Trio"
    And Quartet is unmatched and not pending
    And films_fetched_at is 2026-08-10

  Scenario: Import is idempotent
    When I import the legacy dir
    And I import the legacy dir
    Then the report counts 2 films, 2 omdb rows, 1 payloads, 1 ratings
    And 2 films are current

  Scenario: Found rows without a language key are flagged for refresh
    Given the legacy cache entry for Trio has no language key
    When I import the legacy dir
    Then Trio needs an OMDb lookup

  Scenario: Missing catalog fails loudly
    Given the legacy catalog file is removed
    Then importing raises FileNotFoundError
