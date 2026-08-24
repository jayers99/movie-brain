Feature: Rematch pass
  A one-shot, idempotent repair verb: re-run the shared matcher over every TMDB miss
  and reconcile every non-Criterion film's year against TMDB. Collectors never delete.

  Background:
    Given a fresh repository

  Scenario: A missed commerce film is rematched and adopts TMDB's original year
    Given a commerce film "Stop Making Sense" from 2023 marked as a TMDB miss
    And TMDB knows "Stop Making Sense" as id 606 released 1984
    When I run rematch
    Then "Stop Making Sense (1984)" has external id "606" for authority "tmdb"
    And the film "Stop Making Sense" has year 1984
    And the rematch report says 1 rematched and 1 year adopted

  Scenario: Rematch is idempotent
    Given a commerce film "Stop Making Sense" from 2023 marked as a TMDB miss
    And TMDB knows "Stop Making Sense" as id 606 released 1984
    When I run rematch
    And I run rematch again
    Then the second report says 0 rematched and 0 years adopted
    And the tmdb review queue holds 0 "year-collision" entries

  Scenario: A matched non-criterion film with a disagreeing year adopts the TMDB year
    Given a commerce film "Beauty and the Beast" from 2002 already matched to TMDB id 194
    And TMDB movie 194 was released in 1946
    When I run rematch
    Then the film "Beauty and the Beast" has year 1946
    And the rematch report says 1 checked and 1 year adopted

  Scenario: A year adoption that collides queues one merge candidate, even across runs
    Given a commerce film "Nosferatu" from 2024 already matched to TMDB id 653
    And a film "Nosferatu" from 1922 exists
    And TMDB movie 653 was released in 1922
    When I run rematch
    And I run rematch again
    Then the film "Nosferatu" from 2024 still has year 2024
    And the tmdb review queue holds 1 "year-collision" entries

  Scenario: Criterion films are never year-checked
    Given a criterion film "Trio" from 1950 already matched to TMDB id 11
    When I run rematch
    Then the rematch report says 0 checked
    And TMDB movie details were fetched 0 times

  Scenario: A still-unmatched film stays in the no-match queue
    Given a commerce film "Obscurity" from 1999 marked as a TMDB miss
    And TMDB has no results for any search
    When I run rematch
    Then the rematch report says 0 rematched and 1 still missed
    And the tmdb review queue holds 1 "no-match" entries
