Feature: Data audit
  A read-only pass that scores every film against cross-source consistency checks and
  records the human's verdicts without ever fixing anything itself.

  Background:
    Given a fresh repository
    And a Criterion film "Alpha (1950)" directed by "Ann Author" linked to TMDB id 11
    And "Alpha (1950)" has an OMDb payload titled "Alpha" year 1950 imdb "tt1" director "Ann Author"

  Scenario: The verb caches TMDB facts once and writes flags
    Given TMDB facts for id 11 are title "Alpha" imdb "tt2" runtime 90
    When I run the audit
    Then the audit fetched 1 TMDB facts
    And "Alpha (1950)" is flagged with reasons "imdb-id"
    When I run the audit again
    Then the audit fetched 0 TMDB facts
    And "Alpha (1950)" is flagged with reasons "imdb-id"

  Scenario: --no-tmdb makes no TMDB calls and still runs the offline checks
    Given "Alpha (1950)" has an OMDb payload titled "Alpha Beta" year 1950 imdb "tt1" director "Ann Author"
    When I run the audit without TMDB
    Then no TMDB request was made
    And "Alpha (1950)" is flagged with reasons "omdb-title"

  Scenario: A TMDB failure on one film skips it and the audit still completes
    Given TMDB facts for id 11 fail with a server error
    When I run the audit
    Then the audit fetched 0 TMDB facts and 1 failed
    And "Alpha (1950)" is flagged with reasons ""
    And the audit exit code is 0

  Scenario: Flags are replaced, not accumulated
    Given "Alpha (1950)" has an OMDb payload titled "Alpha Beta" year 1950 imdb "tt1" director "Ann Author"
    When I run the audit without TMDB
    Then "Alpha (1950)" is flagged with reasons "omdb-title"
    Given "Alpha (1950)" has an OMDb payload titled "Alpha" year 1950 imdb "tt1" director "Ann Author"
    When I run the audit without TMDB
    Then "Alpha (1950)" is flagged with reasons ""

  Scenario: Verdict history lists in order and never changes the flags
    Given "Alpha (1950)" has an OMDb payload titled "Alpha Beta" year 1950 imdb "tt1" director "Ann Author"
    When I run the audit without TMDB
    And I mark "Alpha (1950)" as "omdb-wrong" with note "wrong record"
    And I mark "Alpha (1950)" as "fine" with note ""
    Then the verdict history is "omdb-wrong, fine"
    And "Alpha (1950)" is flagged with reasons "omdb-title"
