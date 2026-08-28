Feature: Thumbprint T4 — repair nomatch reruns open no-match films through the resolver

  Background:
    Given a no-match film "Bound" (1996) directed by "Lana Wachowski" with a criterion claim
    And a no-match film "Love" (2024) with a metacritic claim
    And the candidate pool has "Bound" → tt0115736/9081 1996 by "Lana Wachowski, Lilly Wachowski"
    And the candidate pool has "Love" → tt1/1 2024 and tt2/2 2024

  Scenario: dry run lists both verdicts and writes nothing
    When I run repair nomatch without --apply
    Then the nomatch report says match 1, review 1, applied 0
    And no film holds an imdb id
    And both no-match rows are still open as "no-match"

  Scenario: apply keys the match and promotes the review in place
    When I run repair nomatch --apply answering yes
    Then "Bound" holds imdb "tt0115736" and tmdb "9081" and is found
    And the only open tmdb row is for "Love" with reason "no-match-reviewed" and candidates A, B
    And the "Love" row keeps its original id

  Scenario: --none on the promoted row survives the next sync's rebuild
    Given I ran repair nomatch --apply answering yes
    When I resolve the "Love" row with --none
    And the tmdb no-match queue is rebuilt as sync would
    Then there are no open tmdb rows
    And the eval log has a verified human row for "Love" expecting "NONE"
