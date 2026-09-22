Feature: Films — add one film by its IMDb id, through the same gates every creating path runs

  Background:
    Given a film "Harbour Lights" (1972) holding imdb "tt9000002"
    And TMDB knows "tt9000009" as film 909 "The Glass Orchard" (1961)

  Scenario: A dry run mints nothing
    When I add "tt9000009"
    Then the add says "would-create"
    And no film was created

  Scenario: An add mints the film under TMDB's own title, born keyed
    When I add "tt9000009" with apply
    Then the add says "created"
    And the film "The Glass Orchard" holds imdb "tt9000009"
    And 1 film was created

  Scenario: An id the catalog already holds creates nothing and names the holder
    When I add "tt9000002" with apply
    Then the add says "held"
    And no film was created

  Scenario: A look-alike the ids cannot see vetoes the add
    Given a film "The Glass Orchard" (1961) holding no ids
    When I add "tt9000009" with apply
    Then the add says "blocked"
    And no film was created

  Scenario: An id TMDB does not know as a film is refused, not minted
    When I add "tt9000010" with apply
    Then the add says "blocked"
    And no film was created

  Scenario: A malformed id is refused before anything is asked
    Then adding "12300742" is refused
