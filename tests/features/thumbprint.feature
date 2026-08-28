Feature: Thumbprint T1 — claims backfill and Title (YYYY) twins

  Background:
    Given a film "Blade Runner" (1982) with a criterion listing and metacritic slug "blade-runner"
    And an owned film "Blade Runner (The Final Cut)" from archive line "Blade Runner (The Final Cut)	2007	7020"

  Scenario: backfill dry run writes nothing and reports counts
    When I run the claims backfill without --apply
    Then the dry run added no claim rows
    And the backfill report says criterion 1, metacritic 1, apple 1, editions 1

  Scenario: backfill apply is idempotent and fills title_norm
    When I run the claims backfill with --apply twice
    Then there are exactly 3 claim rows
    And the apple claim has edition_label "the final cut", year_claimed 2007 and runtime_min 117
    And every film has a title_norm

  Scenario: an owned film with no archive line still gets a claim
    Given an owned film "Orphan" (2001) with no archive line
    When I run the claims backfill with --apply
    Then the apple claim for "Orphan" has value "Orphan" and the report says apple_unrecovered 1

  Scenario: a raw Title (YYYY) film with one same-year twin whose keys agree is merged
    Given a raw film "Rear Window (1954)" year 2013 with OMDb imdbID "tt0047396" and an owned row
    And a clean film "Rear Window" (1954) with TMDB imdb "tt0047396"
    And the contract expects the raw film's twin to be the clean film
    When I run repair twins --apply answering yes
    Then the raw film is merged into the clean film, which is owned, and the raw film's year is 1954
    And the applied hook saw the raw film once

  Scenario: keys disagree → conflict, nothing written
    Given a raw film "Vertigo (1958)" year 1958 with OMDb imdbID "tt0052357" and an owned row
    And a clean film "Vertigo" (1958) with TMDB imdb "tt0000001"
    When I run repair twins --apply answering yes
    Then the raw film's verdict is "conflict" and it has no disposition

  Scenario: contract disagrees with the computed twin → csv-mismatch, skipped loudly
    Given a raw film "Hamlet (1996)" year 1996 with OMDb imdbID "tt0116477" and an owned row
    And a clean film "Hamlet" (1996) with TMDB imdb "tt0116477"
    And the contract expects the raw film's twin to be film 999
    When I run repair twins --apply answering yes
    Then the raw film's verdict is "csv-mismatch" and it has no disposition

  Scenario: no twin → keyed directly
    Given a raw film "Doctor Strange (2016)" year 2016 with OMDb imdbID "tt1211837" and an owned row
    When I run repair twins --apply answering yes
    Then the raw film is titled "Doctor Strange" with imdb "tt1211837" and has no disposition

  Scenario: a twin one year off is accepted only when the IMDb keys agree
    Given a raw film "The Pink Panther (1964)" year 1964 with OMDb imdbID "tt0057413" and an owned row
    And a clean film "The Pink Panther" (1963) with TMDB imdb "tt0057413"
    When I run repair twins --apply answering yes
    Then the raw film is merged into the clean film

  Scenario: a twin one year off without key agreement is no-twin, not guessed
    Given a raw film "The Pink Panther (1964)" year 1964 with OMDb imdbID "tt0057413" and an owned row
    And a clean film "The Pink Panther" (1963) with TMDB imdb "tt0000002"
    When I run repair twins --apply answering yes
    Then the raw film is titled "The Pink Panther" with imdb "tt0057413" and has no disposition

  Scenario: backfill recovers a raw Title (YYYY) owned film under its own raw title
    Given an owned film "Vertigo (1958)" (1958) with no archive line
    And an owned film "Vertigo" (1958) with no archive line
    And an archive line "Vertigo (1958)	1958	7680"
    When I run the claims backfill with --apply
    Then the apple claim "Vertigo (1958)" belongs to the film titled "Vertigo (1958)" with runtime_min 128
