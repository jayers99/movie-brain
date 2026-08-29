Feature: Filling in years TMDB already knows, for films with none at all

  The commerce-only guard in record_tmdb_match used to protect a Criterion
  film's year from TMDB even when the film had NO year at all, discarding
  the correct TMDB year to protect a NULL. `repair years --from-tmdb` is the
  one-time pass over that backlog: films holding a TMDB id with no year yet,
  filled through the same update_film_year path record_tmdb_match uses, so
  the key recompute and the collision handling are shared, not reimplemented.

  Background:
    Given a film "Army of Shadows" with no year, holding tmdb id 15383

  Scenario: A dry run writes nothing
    Given TMDB reports the year 1969 for tmdb id 15383
    When I fill years from tmdb without applying
    Then the report counts 1 filled
    And the film "Army of Shadows" still has no year

  Scenario: Applying fills the year and marks the film for an OMDb refresh
    Given TMDB reports the year 1969 for tmdb id 15383
    And the film "Army of Shadows" has an OMDb miss on record
    When I fill years from tmdb with apply
    Then the report counts 1 filled
    And the film "Army of Shadows" now has year 1969
    And the film "Army of Shadows" is marked for an OMDb refresh

  Scenario: A film that already has a year is never touched
    Given a film "Le Samourai" (1967) holding tmdb id 967
    And TMDB reports the year 1966 for tmdb id 967
    When I fill years from tmdb with apply
    Then the film "Le Samourai" still has year 1967
    And TMDB was never asked for the year of tmdb id 967

  Scenario: TMDB publishing no year is counted, not guessed
    Given TMDB publishes no year for tmdb id 15383
    When I fill years from tmdb with apply
    Then the report counts 1 no-year
    And the film "Army of Shadows" still has no year

  Scenario: A key collision queues a review row instead of overwriting
    Given a film "Nosferatu" (1922) holding tmdb id 653
    And a film titled "Nosferatu" with no year, holding tmdb id 999, tracked as "Nosferatu (999)"
    And TMDB reports the year 1922 for tmdb id 999
    When I fill years from tmdb with apply
    Then the report counts 1 collision
    And the film "Nosferatu (999)" still has no year
    And an open tmdb review row exists for "Nosferatu (999)" with reason "year-collision"
