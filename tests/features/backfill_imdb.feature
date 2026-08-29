Feature: Backfilling IMDb ids from the TMDB ids we already hold

  A film holding a TMDB id and no IMDb id cannot be joined to any external
  authority. The backfill asks TMDB for the id it publishes for that exact
  TMDB id and writes it through key_film — writing the IMDb id ALONE, so no
  film's year moves as a side effect of filling in a missing id.

  Background:
    Given a film "Rio Bravo" (1959) holding tmdb id 10767 and no imdb id
    And TMDB publishes imdb id "tt0053221" for tmdb id 10767

  Scenario: A dry run writes nothing
    When I back fill imdb ids without applying
    Then the report counts 1 scanned and 1 backfilled
    And the film "Rio Bravo" still holds no imdb id

  Scenario: Applying writes the imdb id and leaves the tmdb id alone
    When I back fill imdb ids with apply
    Then the film "Rio Bravo" holds imdb id "tt0053221"
    And the film "Rio Bravo" still holds tmdb id 10767

  Scenario: The backfill never asks TMDB for a year, so no commerce film's year can move
    Given the film "Rio Bravo" has no criterion listing
    And TMDB reports the year 1958 for tmdb id 10767
    When I back fill imdb ids with apply
    Then the film "Rio Bravo" still has year 1959
    And TMDB was never asked for the year of tmdb id 10767

  Scenario: An id already held by another film queues a review row instead of overwriting
    Given a film "Rio Bravo (1959)" already holds imdb id "tt0053221"
    When I back fill imdb ids with apply
    Then the report counts 1 held
    And an open tmdb review row exists for "Rio Bravo" with reason "id-conflict"
    And the film "Rio Bravo" still holds no imdb id

  Scenario: TMDB publishing no imdb id is counted, not written
    Given TMDB publishes no imdb id for tmdb id 10767
    When I back fill imdb ids with apply
    Then the report counts 1 no-imdb
    And the film "Rio Bravo" still holds no imdb id

  Scenario: A film whose OMDb record is under a different id is queued for an OMDb refetch
    Given the film "Rio Bravo" has an OMDb record under imdb id "tt9999999"
    When I back fill imdb ids with apply
    Then the film "Rio Bravo" is marked for an OMDb refresh
