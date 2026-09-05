Feature: Resolving the CheapCharts product page for a film

  The drawer's CheapCharts link was a title search, which lands on a list the
  owner then has to read. A direct link needs the iTunes track id, which the
  catalogue does not hold. CheapCharts' public API takes IMDb ids directly and
  answers with the product page, so the id is resolved once per film and stored
  under the `itunes` authority; the drawer builds the link from what is stored
  and never calls out at render time.

  Background:
    Given a film "Vertigo" (1958) holding imdb id "tt0052357"

  Scenario: A dry run reports the resolution and writes nothing
    Given CheapCharts maps "tt0052357" to itunes id "284815525"
    When I resolve cheapcharts ids without applying
    Then the report counts 1 scanned and 1 resolved
    And the film "Vertigo" still holds no itunes id

  Scenario: Applying stores the itunes id
    Given CheapCharts maps "tt0052357" to itunes id "284815525"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "284815525"

  Scenario: A film already holding an itunes id is never asked about again
    Given the film "Vertigo" already holds itunes id "284815525"
    When I resolve cheapcharts ids with apply
    Then the report counts 0 scanned and 0 resolved
    And CheapCharts was never asked about "tt0052357"

  Scenario: A gap in the IMDb index falls back to a title search
    Given CheapCharts knows no imdb mapping for "tt0052357"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "284815525"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "284815525"
    And the report counts 1 resolved by search

  Scenario: A search result for a different film is refused, never guessed
    Given CheapCharts knows no imdb mapping for "tt0052357"
    And a CheapCharts search for "Vertigo" returns "Vertigo Zone" (2011) as itunes id "999"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" still holds no itunes id
    And the report counts 1 unmatched

  Scenario: A store year far from the original is refused when nothing corroborates it
    Given CheapCharts knows no imdb mapping for "tt0052357"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (2013) as itunes id "284815525"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" still holds no itunes id

  Scenario: A matching director rescues a store year far from the original
    Given the film "Vertigo" is directed by "Alfred Hitchcock"
    And CheapCharts knows no imdb mapping for "tt0052357"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (2013) by "Alfred Hitchcock" as itunes id "284815525"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "284815525"

  Scenario: Two equally plausible search results are refused as ambiguous
    Given CheapCharts knows no imdb mapping for "tt0052357"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "284815525"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "111222333"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" still holds no itunes id
    And the report counts 1 ambiguous

  Scenario: An itunes id another film already holds is reported, never stolen
    Given CheapCharts maps "tt0052357" to itunes id "284815525"
    And a film "Vertigo (restored)" already holds itunes id "284815525"
    When I resolve cheapcharts ids with apply
    Then the report counts 1 held
    And the film "Vertigo" still holds no itunes id

  Scenario: Films are asked for in batches no larger than the API accepts
    Given 6 more films holding imdb ids that CheapCharts does not know
    When I resolve cheapcharts ids with apply
    Then CheapCharts was asked in 2 batches of at most 5 imdb ids

  Scenario: A rate-limited API stops the run instead of burning the rest of the worklist
    Given 9 more films holding imdb ids that CheapCharts does not know
    And CheapCharts starts refusing after 1 batch
    When I resolve cheapcharts ids with apply
    Then the report is marked rate limited
    And CheapCharts was asked in 1 batches of at most 5 imdb ids
