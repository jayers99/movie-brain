Feature: TMDB availability
  A tripwired sync step: key new films through the thumbprint resolver, refresh US watch
  providers weekly into listings, and never let a TMDB failure touch the Criterion or OMDb
  results.

  Background:
    Given a fresh repository
    And the Criterion browse page exposes a token
    And the Criterion catalog has films "Trio (1950)"
    And OMDb knows every film

  Scenario: The Criterion walk records a claim for every film it lists
    When I sync
    Then "Trio (1950)" has a "criterion" claim titled "Trio" for year 1950

  Scenario: A new film is keyed by the resolver and its ids stored
    Given the resolver pool has "Trio" → tt0037800/11 1950 by "Someone"
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    Then "Trio (1950)" has external id "11" for authority "tmdb"
    And "Trio (1950)" has external id "tt0037800" for authority "imdb"
    And the sync matched 1 TMDB films
    And the tmdb review queue holds 0 entries

  Scenario: An ambiguous film becomes a durable A/B/C review row, never a guess
    Given the resolver pool has "Trio" ambiguous between tt0037800/11 1950 and tt0037801/12 1952
    When I sync with a TMDB token
    Then the tmdb review queue holds a "no-match-reviewed" entry
    And the review detail offers candidates "tt0037800" and "tt0037801"
    When I sync with a TMDB token again the next day
    Then the tmdb review queue holds 1 "no-match-reviewed" entries

  Scenario: A film the resolver cannot key at all still gets one durable row
    Given the resolver pool is empty
    When I sync with a TMDB token
    Then the tmdb review queue holds a "no-match-reviewed" entry
    And the tmdb review queue holds 0 "no-match" entries

  Scenario: Provider refresh writes listings but never the criterion source
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    Then "Trio (1950)" is currently listed on "max"
    And "Trio (1950)" has 1 non-criterion listings

  Scenario: Provider 2 in buy records an Apple TV Store row, unknown ids are ignored
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB offers id 11 to buy on providers 2 and 1825
    When I sync with a TMDB token
    Then "Trio (1950)" is currently listed on "apple-tv-store"
    And "Trio (1950)" has 1 non-criterion listings

  Scenario: A fresh weekly stamp skips the provider refresh
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB streams id 11 on providers 1899 and 258
    And the provider refresh ran 2 days ago
    And TMDB already checked "Trio (1950)" as id 11 once
    When I sync with a TMDB token
    Then TMDB providers were called exactly 0 times

  Scenario: A dropped service goes stale, never deleted
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    And TMDB stops streaming id 11 anywhere
    And I sync with a TMDB token 8 days later
    Then "Trio (1950)" still has a listing row for "max"

  Scenario: No TMDB token skips the step
    When I sync
    Then the exit code is 0
    And the sync matched 0 TMDB films

  Scenario: --ratings-only skips the TMDB step even with a token
    Given the repository already holds "Trio (1950)" walked 1 days ago
    When I sync with a TMDB token and --ratings-only
    Then the exit code is 0
    And the sync matched 0 TMDB films

  Scenario: TMDB auth failure leaves the rest of the sync intact
    Given TMDB rejects the token
    When I sync with a TMDB token
    Then the exit code is 0
    And 0 films have OMDb ratings
    And the sync matched 0 TMDB films

  Scenario: Two films matching the same TMDB id queue the second for review
    Given the Criterion catalog has films "Trio (1950)" and "Quartet (1948)"
    And TMDB knows "Trio (1950)" as id 11
    And TMDB knows "Quartet (1948)" as id 11
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    Then "Trio (1950)" has external id "11" for authority "tmdb"
    And the tmdb review queue holds 1 entries
    And the exit code is 0
    And TMDB providers were called exactly 1 times

  Scenario: Repeated resolver failures stop keying and leave the rest of the sync intact
    Given the Criterion catalog has films "Trio (1950)" and "Quartet (1948)" and "Third (1960)" and "Fourth (1970)" and "Fifth (1980)" and "Sixth (1990)"
    And the resolver fails on every lookup
    When I sync with a TMDB token
    Then the exit code is 0
    And the sync matched 0 TMDB films
    And the tmdb review queue holds 0 entries
    And 0 films have OMDb ratings

  Scenario: A film's first provider check is baseline, not an arrival
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    Then no availability transition is recorded

  Scenario: A service appearing on a later check is an arrival
    Given TMDB knows "Trio (1950)" as id 11
    When I sync with a TMDB token
    Given TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token 8 days later
    Then an availability transition for "max" is recorded

  Scenario: A commerce film adopts TMDB's original year through the resolver
    Given a commerce film "Stop Making Sense" from 2023
    And the resolver pool has "Stop Making Sense" → tt0088178/606 1984 by ""
    When I sync with a TMDB token
    Then the film "Stop Making Sense" has year 1984 and key "stop making sense (1984)"

  Scenario: Year write-back that collides with an existing key queues year-collision
    Given a commerce film "Nosferatu" from 2024
    And the Criterion catalog has films "Nosferatu (1922)"
    And TMDB knows "Nosferatu" as id 653 released 1922
    When I sync with a TMDB token
    Then the film "Nosferatu" from 2024 still has year 2024
    And the tmdb review queue holds a "year-collision" entry
    When I sync with a TMDB token again the next day
    Then the tmdb review queue holds 1 "year-collision" entries

  Scenario: A criterion film never gets a year write-back
    Given TMDB knows "Trio" as id 11 released 1949
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    Then the film "Trio" from 1950 still has year 1950

  Scenario: A tt another film already holds queues id-conflict, never a second claim
    Given a commerce film "Trio" from 1952
    And the film "Trio (1952)" already holds imdb "tt0037800"
    And the resolver pool has "Trio" → tt0037800/11 1950 by "Someone"
    When I sync with a TMDB token
    Then the tmdb review queue holds a "id-conflict" entry

  Scenario: A film keyed by the resolver is found in OMDb by its id in the same run
    Given OMDb answers only lookups by IMDb id
    And the resolver pool has "Trio" → tt0037800/11 1950 by "Someone"
    When I sync with a TMDB token
    Then "Trio (1950)" has an OMDb rating
    And "Trio (1950)" has external id "tt0037800" for authority "imdb"

  Scenario: A TMDB-linked film with no IMDb id gets no OMDb record
    Given TMDB already checked "Trio (1950)" as id 11 once
    And TMDB reports id 11 as having no IMDb id
    When I sync with a TMDB token
    Then "Trio (1950)" has no OMDb rating
    And "Trio (1950)" has no external id for authority "imdb"

  Scenario: An unkeyed film is never looked up by title
    Given the resolver pool is empty
    And OMDb answers only lookups by IMDb id
    When I sync with a TMDB token
    Then "Trio (1950)" has no OMDb rating
    And OMDb was never asked by title

  Scenario: A film keyed tonight gets its OMDb record tonight
    Given the resolver pool has "Trio" → tt0037800/11 1950 by "Someone"
    And OMDb answers only lookups by IMDb id
    When I sync with a TMDB token
    Then "Trio (1950)" has an OMDb rating
