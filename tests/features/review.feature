Feature: match_review rows are resolved by CLI and never come back

  Background:
    Given films "Alpha (1950)" on Criterion and "King Kong (1933)" from commerce

  Scenario: Dismissing a tmdb no-match keeps it out of the next rebuild
    Given an open tmdb "no-match" review for "King Kong (1933)"
    When I resolve it with dismiss
    Then the review is resolved
    And rebuilding the tmdb no-match queue queues nothing for "King Kong (1933)"

  Scenario: Matching a no-match to a TMDB id claims the id and adopts the year
    Given an open tmdb "no-match" review for "King Kong (1933)"
    And TMDB says id 244 was released in 1933
    When I resolve it with tmdb id 244
    Then "King Kong (1933)" has tmdb id "244" and is found

  Scenario: A metacritic remake-suspected slug is created as its own film
    Given the archive staged "King Kong" (2005) as slug "king-kong-2005"
    And an open metacritic "year-gap" review for slug "king-kong-2005"
    When I resolve it with create
    Then a film "King Kong (2005)" exists holding metacritic slug "king-kong-2005"
    And re-running the archive match queues nothing for slug "king-kong-2005"

  Scenario: A metacritic slug is matched to an existing film
    Given the archive staged "Alpha" (1990) as slug "alpha-rr"
    And an open metacritic "year-gap" review for slug "alpha-rr"
    When I resolve it with film "Alpha (1950)"
    Then "Alpha (1950)" holds metacritic slug "alpha-rr"

  Scenario: An apple-tv year-drift is matched to a film and marks it owned
    Given an open apple-tv "year-drift" review for title "Alpha (Restored Version)"
    When I resolve it with film "Alpha (1950)"
    Then "Alpha (1950)" is owned
    And a later owned import of "Alpha (Restored Version)" year 2020 queues nothing

  Scenario: An apple-tv year-drift creates a new owned film
    Given an open apple-tv "year-drift" review for title "Alpha (2020)"
    When I resolve it with create
    Then a film "Alpha (2020)" exists and is owned

  Scenario: A tmdb id-conflict resolved to the holder merges the twins
    Given "Alpha (1950)" holds tmdb id "5"
    And an open tmdb "id-conflict" review for "King Kong (1933)" claiming id "5"
    When I resolve it with film "Alpha (1950)"
    Then "King Kong (1933)" is merged into "Alpha (1950)"

  Scenario: Invalid combinations are refused
    Given an open tmdb "no-match" review for "King Kong (1933)"
    Then resolving it with create fails
    And resolving it with both dismiss and film "Alpha (1950)" fails
