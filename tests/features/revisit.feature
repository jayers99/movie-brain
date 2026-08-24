Feature: Needs-revisit flag

  Background:
    Given a repository with films "Alpha (1950)" on Criterion and "Alpha (1951)" from commerce

  Scenario: Toggling marks and unmarks a film with an optional note
    When I flag "Alpha (1951)" for revisit with note "year suspect"
    Then "Alpha (1951)" is flagged with note "year suspect"
    When I flag "Alpha (1951)" for revisit with note ""
    Then "Alpha (1951)" is not flagged

  Scenario: Resolving a review clears the flag
    Given "Alpha (1951)" is flagged for revisit
    And an open tmdb "no-match" review for "Alpha (1951)"
    When that review is dismissed
    Then "Alpha (1951)" is not flagged

  Scenario: Merging drops the loser's flag and keeps the survivor's
    Given "Alpha (1951)" is flagged for revisit
    And "Alpha (1950)" is flagged for revisit
    When I merge "Alpha (1951)" into "Alpha (1950)"
    Then "Alpha (1950)" is flagged with note ""
    And the revisit worklist lists only "Alpha (1950)"

  Scenario: A sync never touches the flag
    Given "Alpha (1951)" is flagged for revisit
    When Criterion lists "Alpha (1951)" again
    Then "Alpha (1951)" is flagged with note ""
