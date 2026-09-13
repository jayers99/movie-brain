Feature: The ranking pool — who the ranker asks and seeds

  Background:
    Given owned films rated "Ten" 10, "Nine" 9, "Eight" 8, "Seven" 7, "Six" 6
    And an owned unrated film "Uno"

  Scenario: A rated film the owner does not own seeds into its tier on the first read and is never asked
    Given a started tiering session
    And a film "Stream" rated 8, not owned
    Then "Stream" is placed in tier 3 as a seed
    And "Stream" is not in the queue

  Scenario: Low scores keep a film out, owned or not
    Given an owned film "Meh" rated 4
    And an owned film "Nope" rated 0
    And a film "Cold" rated 5, not owned
    When I start a tiering session
    Then none of "Meh", "Nope", "Cold" is placed or queued
    And the proposal still reads

  Scenario: A film rated after the session started seeds on the next read
    Given a started tiering session
    And a film "Late" not owned
    When "Late" is rated 9
    Then "Late" is placed in tier 2 as a seed

  Scenario: A marked unrated film is asked, and unmarking removes it
    Given a started tiering session
    And a film "Pick" not owned
    When "Pick" is marked Rank this
    Then "Pick" is in the queue
    When "Pick" is unmarked
    Then "Pick" is not in the queue

  Scenario: A marked film with a low score stays out
    Given a started tiering session
    And a film "Marked4" rated 4, not owned
    When "Marked4" is marked Rank this
    Then "Marked4" is not in the queue

  Scenario: The proposal's fallback offers a marked film
    Given "Seven" is re-rated 8
    And a film "Pick" not owned
    When "Pick" is marked Rank this
    Then tier 4's choices include "Pick"

  Scenario: A newly seeded ten joins tier 1's order queue
    Given a started tiering session
    And a film "Top" rated 10, not owned
    Then the tier 1 order has 1 film and 1 remaining
