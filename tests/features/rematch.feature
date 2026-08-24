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

  Scenario: A pass-A match that collides on write-back queues one merge candidate, even across runs
    Given a commerce film "Nosferatu" from 2024 marked as a TMDB miss
    And a film "Nosferatu" from 1922 exists
    And TMDB knows "Nosferatu" as id 653 released 1922
    When I run rematch
    Then "Nosferatu (2024)" has external id "653" for authority "tmdb"
    And the film "Nosferatu" from 2024 still has year 2024
    And the tmdb review queue holds 1 "year-collision" entries
    And the rematch report says 1 rematched and 1 collision queued
    And TMDB movie 653 was released in 1922
    When I run rematch again
    Then the second report says 0 rematched
    And the tmdb review queue holds 1 "year-collision" entries

  Scenario: Two commerce films resolving to the same TMDB id queue one id-conflict, even across runs
    Given a commerce film "Twin One" from 2020 marked as a TMDB miss
    And a commerce film "Twin Two" from 2021 marked as a TMDB miss
    And TMDB knows "Twin One" as id 42 released 2020
    And TMDB knows "Twin Two" as id 42 released 2021
    When I run rematch
    Then "Twin One (2020)" has external id "42" for authority "tmdb"
    And the rematch report says 1 rematched and 1 id conflicts
    And the tmdb review queue holds 1 "id-conflict" entries
    And the tmdb review queue holds 0 "no-match" entries
    When I run rematch again
    Then the tmdb review queue holds 1 "id-conflict" entries

  Scenario: TMDB auth failure during year reconciliation exits immediately
    Given a commerce film "Beauty and the Beast" from 2002 already matched to TMDB id 194
    And TMDB rejects the token
    When I run rematch
    Then the rematch exit code is 2
