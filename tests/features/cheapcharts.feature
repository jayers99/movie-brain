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

  Scenario: A search answer CheapCharts files under another film's IMDb id is refused
    Given CheapCharts knows no imdb mapping for "tt0052357"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    And CheapCharts files product "999" under imdb id "tt7777777"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" still holds no itunes id
    And the report counts 1 unmatched

  Scenario: A search answer with no IMDb filing is believed when the director agrees
    Given the film "Vertigo" is directed by "Alfred Hitchcock"
    And CheapCharts knows no imdb mapping for "tt0052357"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    And CheapCharts files product "999" under no imdb id, directed by "Alfred Hitchcock"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "999"

  Scenario: A search answer with no IMDb filing and another director is refused
    Given the film "Vertigo" is directed by "Alfred Hitchcock"
    And CheapCharts knows no imdb mapping for "tt0052357"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    And CheapCharts files product "999" under no imdb id, directed by "Someone Else"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" still holds no itunes id

  Scenario: A search answer nothing can verify is refused, never guessed
    Given CheapCharts knows no imdb mapping for "tt0052357"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    And CheapCharts files product "999" under no imdb id, directed by "Alfred Hitchcock"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" still holds no itunes id

  Scenario: A recheck never replaces a removed id with another film's product
    Given the film "Vertigo" already holds itunes id "284815525"
    And CheapCharts maps "tt0052357" to a REMOVED itunes id "284815525"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    And CheapCharts files product "999" under imdb id "tt7777777"
    When I recheck cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "284815525"
    And the report counts 1 dead

  Scenario: A film CheapCharts had nothing for is remembered, and not asked about again
    Given CheapCharts knows no imdb mapping for "tt0052357"
    When I resolve cheapcharts ids with apply
    And I resolve cheapcharts ids with apply
    Then the second run scanned 0 films
    And CheapCharts was asked about "tt0052357" 1 time

  Scenario: A dry run remembers nothing
    Given CheapCharts knows no imdb mapping for "tt0052357"
    When I resolve cheapcharts ids without applying
    And I resolve cheapcharts ids with apply
    Then the second run scanned 1 films

  Scenario: Retrying the misses asks about a remembered film again, and finds what Apple now sells
    Given CheapCharts knows no imdb mapping for "tt0052357"
    When I resolve cheapcharts ids with apply
    And CheapCharts maps "tt0052357" to itunes id "284815525"
    And I resolve cheapcharts ids with apply, retrying the misses
    Then the film "Vertigo" holds itunes id "284815525"

  Scenario: A failed lookup is not a miss, and is asked again
    Given CheapCharts cannot be reached
    When I resolve cheapcharts ids with apply
    And CheapCharts can be reached again
    And I resolve cheapcharts ids with apply
    Then the second run scanned 1 films

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

  Scenario: An IMDb answer naming a product another film holds falls through to the title search
    Given CheapCharts maps "tt0052357" to itunes id "284815525"
    And a film "Vertigo (restored)" already holds itunes id "284815525"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "999"
    And the report counts 1 resolved by search
    And the report counts 0 held

  Scenario: When the title search only finds the held product too, it is still reported as held
    Given CheapCharts maps "tt0052357" to itunes id "284815525"
    And a film "Vertigo (restored)" already holds itunes id "284815525"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "284815525"
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

  Scenario: A product Apple removed is a miss by IMDb id and falls back to the search
    Given CheapCharts maps "tt0052357" to a REMOVED itunes id "284815525"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    When I resolve cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "999"
    And the report counts 1 resolved by search

  Scenario: A recheck replaces a removed id in place with its confirmed re-listing
    Given the film "Vertigo" already holds itunes id "284815525"
    And CheapCharts maps "tt0052357" to a REMOVED itunes id "284815525"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    When I recheck cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "999"
    And the film "Vertigo" holds exactly one itunes id
    And the report counts 1 replaced

  Scenario: A recheck leaves a removed id alone when nothing confirms a replacement
    Given the film "Vertigo" already holds itunes id "284815525"
    And CheapCharts maps "tt0052357" to a REMOVED itunes id "284815525"
    And a CheapCharts search for "Vertigo" returns "Vertigo Zone" (2011) as itunes id "999"
    When I recheck cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "284815525"
    And the report counts 1 dead

  Scenario: A recheck keeps a live id and asks nothing more
    Given the film "Vertigo" already holds itunes id "284815525"
    And CheapCharts maps "tt0052357" to itunes id "284815525"
    When I recheck cheapcharts ids with apply
    Then the report counts 1 live
    And the report counts 0 replaced
    And CheapCharts was never searched

  Scenario: A recheck resumes after a film id
    Given the film "Vertigo" already holds itunes id "284815525"
    And a film "Rear Window" (1954) holding imdb id "tt0047396"
    And the film "Rear Window" already holds itunes id "111"
    And CheapCharts maps "tt0052357" to itunes id "284815525"
    And CheapCharts maps "tt0047396" to itunes id "111"
    When I recheck cheapcharts ids with apply after "Vertigo"
    Then the report counts 1 scanned
    And CheapCharts was never asked about "tt0052357"

  Scenario: A recheck drops a removed id when the film already holds its confirmed re-listing
    Given the film "Vertigo" already holds itunes id "284815525"
    And the film "Vertigo" already holds itunes id "999"
    And CheapCharts maps "tt0052357" to a REMOVED itunes id "284815525"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    When I recheck cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "999"
    And the film "Vertigo" holds exactly one itunes id
    And the report counts 1 replaced

  Scenario: A film holding a removed product beside a live one loses the removed one, whatever the IMDb index says
    Given the film "Vertigo" already holds itunes id "284815525"
    And the film "Vertigo" already holds itunes id "999"
    And CheapCharts maps "tt0052357" to itunes id "999"
    And CheapCharts says product "284815525" is removed
    And CheapCharts says product "999" is live
    When I recheck cheapcharts ids with apply
    Then the film "Vertigo" holds itunes id "999"
    And the film "Vertigo" holds exactly one itunes id
    And the report counts 1 dropped
    And CheapCharts was never searched

  Scenario: Two live editions of one film are both kept
    Given the film "Vertigo" already holds itunes id "284815525"
    And the film "Vertigo" already holds itunes id "999"
    And CheapCharts maps "tt0052357" to itunes id "999"
    And CheapCharts says product "284815525" is live
    And CheapCharts says product "999" is live
    When I recheck cheapcharts ids with apply
    Then the film "Vertigo" holds every itunes id "284815525" and "999"
    And the report counts 0 dropped
    And the report counts 1 live

  Scenario: A recheck without apply leaves the removed id beside its re-listing
    Given the film "Vertigo" already holds itunes id "284815525"
    And the film "Vertigo" already holds itunes id "999"
    And CheapCharts maps "tt0052357" to a REMOVED itunes id "284815525"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    When I recheck cheapcharts ids without applying
    Then the film "Vertigo" holds every itunes id "284815525" and "999"
    And the report counts 1 replaced

  Scenario: A recheck without apply changes nothing
    Given the film "Vertigo" already holds itunes id "284815525"
    And CheapCharts maps "tt0052357" to a REMOVED itunes id "284815525"
    And a CheapCharts search for "Vertigo" returns "Vertigo" (1958) as itunes id "999"
    When I recheck cheapcharts ids without applying
    Then the film "Vertigo" holds itunes id "284815525"
    And the report counts 1 replaced
