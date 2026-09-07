Feature: Embedding films for semantic search

  A film is embedded from its prose — overview, plot, tagline — and never its title.
  The verb walks every live film holding prose and no vector for the current model,
  encodes in batches, and stamps each film so the next run resumes where this one
  stopped. Dry-run by default, it never touches the model; it never runs inside sync.

  Background:
    Given a prose film "Alpha" (1946) with overview "A private eye." and plot "Sternwood."
    And a prose film "Beta" (1950) with overview "A nurse in the alpha ward." and plot "Alpha shift."
    And a film "Gamma" (1960) enriched with no overview, plot or tagline

  Scenario: A dry run reports the worklist and touches neither the model nor the database
    When I embed without applying
    Then the embed report counts 2 scanned, 0 embedded, 1 skipped for no prose
    And the embedder was asked nothing
    And no film holds a vector

  Scenario: Applying embeds the prose alone and stamps each film
    When I embed with apply
    Then the embed report counts 2 scanned, 2 embedded, 1 skipped for no prose
    And the embedder was asked "A private eye. Sternwood." and "A nurse in the alpha ward. Alpha shift."
    And the films holding a vector are Alpha and Beta

  Scenario: A stamped film is never encoded again
    Given the corpus is already embedded
    When I embed with apply
    Then the embed report counts 0 scanned, 0 embedded, 1 skipped for no prose
    And the embedder was asked nothing

  Scenario: A film re-enriched after embedding is embedded again
    Given the corpus is already embedded
    And "Alpha" is re-enriched the next day with overview "A private detective."
    When I embed with apply
    Then the embed report counts 1 scanned, 1 embedded, 1 skipped for no prose
    And the embedder was asked "A private detective. Sternwood."

  Scenario: The batch size bounds one encode call
    When I embed with apply in batches of 1
    Then the embedder was called 2 times
