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

  Scenario: A --film target that is a merged loser resolves to its survivor
    Given the archive staged "Alpha" (1990) as slug "alpha-rr"
    And an open metacritic "year-gap" review for slug "alpha-rr"
    And "King Kong (1933)" is merged into "Alpha (1950)"
    When I resolve it with film "King Kong (1933)"
    Then "Alpha (1950)" holds metacritic slug "alpha-rr"

  Scenario: A --film target that is tombstoned is refused
    Given the archive staged "Alpha" (1990) as slug "alpha-rr"
    And an open metacritic "year-gap" review for slug "alpha-rr"
    And "King Kong (1933)" is tombstoned
    Then resolving it with film "King Kong (1933)" fails

  Scenario: Picking candidate B keys the film to its tt and tmdb id and ratifies an eval row
    Given an open tmdb resolver review for "King Kong (1933)" with candidates A "tt0000001"/1 and B "tt0024216"/244
    And TMDB says id 244 was released in 1933
    When I resolve it with pick "B"
    Then "King Kong (1933)" holds imdb "tt0024216" and tmdb id "244"
    And the eval log has a verified human row for "King Kong (1933)" expecting "tt0024216"

  Scenario: --tt keys any tmdb no-match row, finding the tmdb id through TMDB
    Given an open tmdb "no-match" review for "King Kong (1933)"
    And TMDB finds "tt0024216" as id 244 released in 1933
    When I resolve it with tt "tt0024216"
    Then "King Kong (1933)" holds imdb "tt0024216" and tmdb id "244"
    And the eval log has a verified human row for "King Kong (1933)" expecting "tt0024216"

  Scenario: --tt without a TMDB client writes only the imdb id and warns
    Given an open tmdb "no-match" review for "King Kong (1933)"
    When I resolve it offline with tt "tt0024216"
    Then "King Kong (1933)" holds imdb "tt0024216" and no tmdb id
    And a warning mentions "tmdb id not resolved"

  Scenario: --none is a standing verified-unkeyed decision
    Given an open tmdb "no-match" review for "King Kong (1933)"
    When I resolve it with none
    Then the review is resolved
    And the eval log has a verified human row for "King Kong (1933)" expecting "NONE"
    And rebuilding the tmdb no-match queue queues nothing for "King Kong (1933)"

  Scenario: --pick on a row without candidates is refused
    Given an open tmdb "no-match" review for "King Kong (1933)"
    Then resolving it with pick "A" fails
