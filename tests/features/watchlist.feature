Feature: Watchlist films are refreshed nightly and arrivals are detected

  Background:
    Given a fresh repository
    And the Criterion browse page exposes a token
    And the Criterion catalog has films "Alpha (1950)" and "Bravo (1960)"
    And OMDb knows every film

  Scenario: Watchlist films get a provider refresh even inside the weekly gate
    Given TMDB knows "Alpha (1950)" as id 11
    And TMDB knows "Bravo (1960)" as id 22
    And TMDB streams id 11 on providers 1899 and 11
    And the provider refresh ran 2 days ago
    And "Alpha (1950)" is on the watchlist
    When I sync with a TMDB token
    Then TMDB providers were called exactly 1 times
    And the sync refreshed 1 watchlist films
    And "Alpha (1950)" has an availability transition on "max"

  Scenario: A full-refresh night does not fetch watchlist films twice
    Given TMDB knows "Alpha (1950)" as id 11
    And TMDB knows "Bravo (1960)" as id 22
    And TMDB streams id 11 on providers 1899 and 11
    And "Alpha (1950)" is on the watchlist
    When I sync with a TMDB token
    Then TMDB providers were called exactly 2 times

  Scenario: A re-upsert of still-current service listings records no new transitions
    Given TMDB knows "Alpha (1950)" as id 11
    And TMDB knows "Bravo (1960)" as id 22
    And TMDB streams id 11 on providers 1899 and 11
    And "Alpha (1950)" is on the watchlist
    When I sync with a TMDB token
    And I sync with a TMDB token again the next day
    Then "Alpha (1950)" has 2 availability transitions
