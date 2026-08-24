Feature: Dispositioned films stay out of every collector's way

  Background:
    Given a repository with films "Alpha (1950)" on Criterion and "Alpha (1951)" from commerce

  Scenario: A merged film disappears from the dashboard view but its title still resolves to the survivor
    When I merge "Alpha (1951)" into "Alpha (1950)"
    Then the dashboard lists 1 film titled "Alpha"
    And matching the Metacritic title "Alpha" year 1951 resolves to "Alpha (1950)"

  Scenario: A Criterion re-walk of a merged film's key writes to the survivor
    When I merge "Alpha (1951)" into "Alpha (1950)"
    And Criterion lists "Alpha (1951)" again
    Then "Alpha (1950)" has a criterion listing and "Alpha (1951)" has none

  Scenario: Promotion never resurrects a tombstoned film
    Given a tombstoned film "Bravo (1975)"
    When the Metacritic archive stages "Bravo" (1975) as slug "bravo-1975"
    And the top 10 staged titles are promoted
    Then no film was promoted and slug "bravo-1975" is unclaimed

  Scenario: Owned import marks the survivor, never a tombstone or a merged loser
    When I merge "Alpha (1951)" into "Alpha (1950)"
    And the Apple library contains "Alpha" from 1951
    Then "Alpha (1950)" is owned and "Alpha (1951)" is not

  Scenario: Discovery lookups skip dispositioned films
    Given "Alpha (1951)" is tombstoned
    Then no discovery film needs an OMDb lookup
    And no film needs a TMDB match except "Alpha (1950)"
