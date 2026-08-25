Feature: TMDB availability
  A tripwired sync step: match films to TMDB once, refresh US watch providers weekly
  into listings, and never let a TMDB failure touch the Criterion or OMDb results.

  Background:
    Given a fresh repository
    And the Criterion browse page exposes a token
    And the Criterion catalog has films "Trio (1950)"
    And OMDb knows every film

  Scenario: A new film is matched once and its TMDB id cached
    Given TMDB knows "Trio (1950)" as id 11
    And TMDB streams id 11 on providers 1899 and 258
    When I sync with a TMDB token
    Then "Trio (1950)" has external id "11" for authority "tmdb"
    And the sync matched 1 TMDB films
    When I sync with a TMDB token again the next day
    Then TMDB search was called exactly 1 times

  Scenario: An unmatched film goes to the review queue and is not retried
    Given TMDB has no results for any search
    When I sync with a TMDB token
    Then the tmdb review queue holds 1 entries
    And the exit code is 0
    When I sync with a TMDB token again the next day
    # 2 = the title search plus its year retry on day one; day two searches nothing
    Then TMDB search was called exactly 2 times

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
    And TMDB search was called exactly 0 times

  Scenario: --ratings-only skips the TMDB step even with a token
    Given the repository already holds "Trio (1950)" walked 1 days ago
    When I sync with a TMDB token and --ratings-only
    Then the exit code is 0
    And TMDB search was called exactly 0 times

  Scenario: TMDB auth failure leaves the rest of the sync intact
    Given TMDB rejects the token
    When I sync with a TMDB token
    Then the exit code is 0
    And 1 films have OMDb ratings
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
    When I sync with a TMDB token again the next day
    Then TMDB search was called exactly 2 times

  Scenario: Repeated TMDB search failures stop the step and keep the stamp unwritten
    Given the Criterion catalog has films "Trio (1950)" and "Quartet (1948)" and "Third (1960)" and "Fourth (1970)" and "Fifth (1980)" and "Sixth (1990)"
    And TMDB errors on every search
    When I sync with a TMDB token
    Then the exit code is 0
    And the provider refresh stamp is unset

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

  Scenario: A commerce film with a re-release year matches the original and adopts its year
    Given a commerce film "Stop Making Sense" from 2023
    And TMDB knows "Stop Making Sense" as id 606 released 1984
    When I sync with a TMDB token
    Then "Stop Making Sense (1984)" has external id "606" for authority "tmdb"
    And the film "Stop Making Sense" has year 1984 and key "stop making sense (1984)"
    # 3 = Trio's title search + its year retry (Criterion year is trusted) + one search for
    # the commerce film: a commerce year may be a re-release, so it never gets the retry
    And TMDB search was called exactly 3 times

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

  Scenario: Two films whose TMDB search both resolve to the same id — the second queues id-conflict
    Given a commerce film "Trio" from 1952
    And the Criterion catalog has films "Trio (1950)"
    And TMDB knows "Trio" as id 11 released 1950
    When I sync with a TMDB token
    Then the tmdb review queue holds a "id-conflict" entry
