Feature: Old ratings — my 2004-08 stars linked to films as a watching signal, never as ratings

  Background:
    Given a film "The Lantern Keeper" (1956) holding imdb "tt9000001"
    And a film "Harbour Lights" (1972) holding imdb "tt9000002"
    And the resolver knows "The Lantren Keeper" as "tt9000001" "The Lantern Keeper" (1956)
    And the resolver knows "Harbour Lights" as "tt9000003" "Harbour Lights" (1957)
    And the resolver knows "Nine Bridges" as "tt9000004" "Nine Bridges" (1975)
    And the resolver knows "Mister Finch" as "tt9000005" "Mister Finch" (1950)

  Scenario: A typo'd title is linked through the resolver, and the link is a real foreign key
    Given the old ratings
      | stars | title            | year | rented     |
      | 3     | The Lantren Keeper | 1956 | 2005-03-02 |
    When I import the old ratings with apply
    Then row 1 is linked to "The Lantern Keeper" by "resolver"
    And no film was created

  Scenario: A dry run writes nothing at all
    Given the old ratings
      | stars | title            | year | rented     |
      | 3     | The Lantren Keeper | 1956 | 2005-03-02 |
    When I import the old ratings
    Then the scorecard says row 1 is "LINKED"
    And no old rating is stored

  Scenario: A same-titled film from another year is not linked
    Given the old ratings
      | stars | title                 | year | rented     |
      | 2     | Harbour Lights | 1957 | 2006-01-10 |
    When I import the old ratings with apply
    Then row 1 is stored unlinked
    And the scorecard says row 1 is "ABSENT"

  Scenario: The import never creates, even a five-star row with apply
    Given the old ratings
      | stars | title          | year | rented     |
      | 5     | Nine Bridges | 1975 | 2004-06-01 |
    When I import the old ratings with apply
    Then the scorecard says row 1 is "WOULD-CREATE"
    And row 1 is stored unlinked
    And no film was created

  Scenario: A row the resolver cannot place stays unlinked and queues no review
    Given the old ratings
      | stars | title             | year | rented     |
      | 4     | Not A Film At All | 2003 | 2004-06-01 |
    When I import the old ratings with apply
    Then the scorecard says row 1 is "UNRESOLVED"
    And row 1 is stored unlinked
    And no review row was queued

  Scenario: A re-run links a row whose film arrived since, and never moves an existing link
    Given the old ratings
      | stars | title            | year | rented     |
      | 1     | Mister Finch           | 1950 | 2004-05-05 |
      | 3     | The Lantren Keeper | 1956 | 2005-03-02 |
    When I import the old ratings with apply
    Then row 1 is stored unlinked
    When a film "Mister Finch" (1950) holding imdb "tt9000005" arrives
    And I import the old ratings with apply
    Then row 1 is linked to "Mister Finch" by "resolver"
    And row 2 is linked to "The Lantern Keeper" by "resolver"
    And the resolver was not asked about "The Lantren Keeper" on the second run

  Scenario: Create mints a five-star film born keyed and refuses a one-star one
    Given the old ratings
      | stars | title          | year | rented     |
      | 5     | Nine Bridges | 1975 | 2004-06-01 |
      | 1     | Mister Finch         | 1950 | 2004-05-05 |
    When I import the old ratings with apply
    And I create the missing films with apply
    Then row 1 is linked to "Nine Bridges" by "created"
    And the film "Nine Bridges" holds imdb "tt9000004"
    And row 2 is stored unlinked
    And 1 film was created

  Scenario: A create dry run mints nothing
    Given the old ratings
      | stars | title          | year | rented     |
      | 5     | Nine Bridges | 1975 | 2004-06-01 |
    When I import the old ratings with apply
    And I create the missing films
    Then the scorecard says row 1 is "WOULD-CREATE"
    And no film was created

  Scenario: Two rows naming one work mint it once
    Given the resolver knows "Nine Bridgez" as "tt9000004" "Nine Bridges" (1975)
    And the old ratings
      | stars | title          | year | rented     |
      | 5     | Nine Bridges | 1975 | 2004-06-01 |
      | 5     | Nine Bridgez  | 1975 | 2006-02-01 |
    When I import the old ratings with apply
    And I create the missing films with apply
    Then row 1 is linked to "Nine Bridges" by "created"
    And row 2 is linked to "Nine Bridges" by "resolver"
    And 1 film was created

  Scenario: Create links instead of twinning when the film arrived since the import
    Given the old ratings
      | stars | title          | year | rented     |
      | 5     | Nine Bridges | 1975 | 2004-06-01 |
    When I import the old ratings with apply
    And a film "Nove Ponti" (1975) holding imdb "tt9000004" arrives
    And I create the missing films with apply
    Then row 1 is linked to "Nove Ponti" by "resolver"
    And no film was created

  Scenario: Create is vetoed by a look-alike the ids cannot see
    Given the old ratings
      | stars | title          | year | rented     |
      | 5     | Nine Bridges | 1975 | 2004-06-01 |
    When I import the old ratings with apply
    And a film "Nine Bridges" (1976) holding no ids arrives
    And I create the missing films with apply
    Then the scorecard says row 1 is "BLOCKED"
    And row 1 is stored unlinked

  Scenario: A hand create mints a row the resolver cannot read, under TMDB's own title
    Given the old ratings
      | stars | title             | year | rented     |
      | 4     | Teh Glas Orchrad  | 1962 | 2004-06-01 |
    And TMDB knows "tt9000009" as film 909 "The Glass Orchard" (1961)
    When I import the old ratings with apply
    And I hand-create row 1 as "tt9000009" with apply
    Then row 1 is linked to "The Glass Orchard" by "created"
    And the film "The Glass Orchard" holds imdb "tt9000009"
    And 1 film was created

  Scenario: A hand create dry run mints nothing
    Given the old ratings
      | stars | title             | year | rented     |
      | 4     | Teh Glas Orchrad  | 1962 | 2004-06-01 |
    And TMDB knows "tt9000009" as film 909 "The Glass Orchard" (1961)
    When I import the old ratings with apply
    And I hand-create row 1 as "tt9000009"
    Then the hand create says "would-create"
    And no film was created
    And row 1 is stored unlinked

  Scenario: A hand create links instead of twinning when a film already holds the id
    Given the old ratings
      | stars | title             | year | rented     |
      | 4     | Habor Lihgts      | 1972 | 2004-06-01 |
    When I import the old ratings with apply
    And I hand-create row 1 as "tt9000002" with apply
    Then row 1 is linked to "Harbour Lights" by "hand"
    And no film was created

  Scenario: A hand create is vetoed by a look-alike the ids cannot see
    Given the old ratings
      | stars | title             | year | rented     |
      | 4     | Teh Glas Orchrad  | 1962 | 2004-06-01 |
    And TMDB knows "tt9000009" as film 909 "The Glass Orchard" (1961)
    When I import the old ratings with apply
    And a film "The Glass Orchard" (1961) holding no ids arrives
    And I hand-create row 1 as "tt9000009" with apply
    Then the hand create says "blocked"
    And row 1 is stored unlinked
    And no film was created

  Scenario: A hand create never mints a film I rated three stars or fewer
    Given the old ratings
      | stars | title             | year | rented     |
      | 3     | Teh Glas Orchrad  | 1962 | 2004-06-01 |
    And TMDB knows "tt9000009" as film 909 "The Glass Orchard" (1961)
    When I import the old ratings with apply
    Then hand-creating row 1 as "tt9000009" is refused

  Scenario: A hand link, a cleared link, and a merge that re-points the row
    Given the old ratings
      | stars | title             | year | rented     |
      | 4     | Not A Film At All | 2003 | 2004-06-01 |
    When I import the old ratings with apply
    And I hand-link row 1 to "Harbour Lights"
    Then row 1 is linked to "Harbour Lights" by "hand"
    When "Harbour Lights" is merged into "The Lantern Keeper"
    Then row 1 is linked to "The Lantern Keeper" by "hand"
    And the view of "The Lantern Keeper" carries an old rating of 4 stars
    When I clear the link of row 1
    Then row 1 is stored unlinked
    And hand-linking row 1 to film 99999 is refused
    And hand-linking row 7 to "The Lantern Keeper" is refused

  Scenario: My ratings are never written
    Given the old ratings
      | stars | title            | year | rented     |
      | 5     | The Lantren Keeper | 1956 | 2005-03-02 |
    When I import the old ratings with apply
    Then "The Lantern Keeper" has no rating of mine
    And the view of "The Lantern Keeper" carries an old rating of 5 stars
