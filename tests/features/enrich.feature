Feature: Enriching films with TMDB credits

  The search bar is only as good as the data under it. OMDb caps actors at four and
  holds no characters; TMDB's credits carry the full cast with the character each
  actor played, in one call per film. The verb walks every live movie holding a TMDB
  id and no `credits_fetched_on`, writes what it finds, and stamps the film so the
  next run resumes where this one stopped. It is dry-run by default and never
  runs inside sync.

  Background:
    Given a film "The Big Sleep" (1946) holding tmdb id 910
    And TMDB publishes credits for tmdb id 910 with cast "Humphrey Bogart" as "Philip Marlowe"

  Scenario: A dry run fetches, reports, and writes nothing
    When I enrich credits without applying
    Then the report counts 1 scanned and 1 enriched
    And the film "The Big Sleep" still has no credits

  Scenario: Applying writes the credits and stamps the film
    When I enrich credits with apply
    Then the film "The Big Sleep" credits "Humphrey Bogart" as "Philip Marlowe"
    And the film "The Big Sleep" is stamped as enriched

  Scenario: A stamped film is never asked about again
    Given the film "The Big Sleep" is already enriched
    When I enrich credits with apply
    Then the report counts 0 scanned and 0 enriched
    And TMDB was never asked for credits of tmdb id 910

  Scenario: A film without a tmdb id is not on the worklist
    Given a film "Orphan" (1950) holding no tmdb id
    When I enrich credits with apply
    Then the report counts 1 scanned and 1 enriched

  Scenario: Repeated TMDB failures stop the run so the next one can resume
    Given 6 more films holding tmdb ids that TMDB cannot serve
    When I enrich credits with apply
    Then the report is marked aborted
    And the report counts 6 scanned and 1 enriched
    And the film "The Big Sleep" credits "Humphrey Bogart" as "Philip Marlowe"

  Scenario: The pause between calls is skipped before the first one
    Given 2 more films holding tmdb ids with empty credits
    When I enrich credits with apply
    Then TMDB was paced with 2 pauses
