Feature: Settling a criterion review row (spec 2026-10-01 D9, story 7)
  `--film`, `--create` and `--tt` give a film the mediaid, so the next walk lists it there;
  `--dismiss` is a standing decision. A gate that finds a holder refuses, naming the film.
  On these human paths a mere resemblance (gate 3) warns and never refuses (ledger L1).

  Scenario: --film gives that film the mediaid, and the next walk lists it there
    Given a film "Ghost Entry" (2020) holding no ids
    And Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    When the walk runs
    And the owner resolves the review for "Gh0stEnt" with --film "Ghost Entry"
    And the walk runs again the next day
    Then the film "Ghost Entry" holds criterion id "Gh0stEnt"
    And the film "Ghost Entry" has a criterion claim "Gh0stEnt" titled "Ghost Entry" for 2020
    And the film "Ghost Entry" is current on Criterion
    And the film "Ghost Entry" arrived on Criterion today
    And there is no open criterion review for "Gh0stEnt"

  Scenario: --film on the bridge's id-conflict row is refused, naming the film that holds the id
    Given the last walk listed "Test Pattern" (2019) as "gpRRkq27"
    And a film "Test Pattern Twin" (2019) holding no ids
    And an open criterion "id-conflict" review names "gpRRkq27" for "Test Pattern Twin"
    When the owner resolves the review for "gpRRkq27" with --film "Test Pattern Twin"
    Then the resolution is refused naming the film "Test Pattern"
    And there is 1 open criterion "id-conflict" review for "gpRRkq27"

  Scenario: --create mints the film under Criterion's title, year and director; the next walk lists it
    Given Criterion lists "K-ON! The Movie" (2011) as "VBLiQBrA"
    And JW knows "VBLiQBrA" as "K-ON! The Movie" directed by "Naoko Yamada"
    And the resolver finds nothing for "K-ON! The Movie"
    When the walk runs
    And the owner resolves the review for "VBLiQBrA" with --create
    And the walk runs again the next day
    Then there is 1 film titled "K-ON! The Movie"
    And the film "K-ON! The Movie" has year 2011 and director "Naoko Yamada"
    And the film "K-ON! The Movie" holds criterion id "VBLiQBrA"
    And the film "K-ON! The Movie" arrived on Criterion today

  Scenario: --create is refused naming the film that already holds the key; the row stays open
    Given a film "K-ON! The Movie" (2011) holding no ids
    And Criterion lists "K-ON! The Movie" (2011) as "VBLiQBrA"
    And JW knows "VBLiQBrA" as "K-ON! The Movie" directed by "Naoko Yamada"
    And the resolver finds nothing for "K-ON! The Movie"
    When the walk runs
    And the owner resolves the review for "VBLiQBrA" with --create
    Then the resolution is refused naming the film "K-ON! The Movie"
    And there is 1 open criterion "no-match" review for "VBLiQBrA"
    And there is 1 film titled "K-ON! The Movie"

  Scenario: --tt naming a film I hold binds the mediaid to it
    Given a film "Barry Lyndon" (1975) holding imdb "tt9000433"
    And Criterion lists "Barry Lyndon" (1975) as "aAUEybAm"
    And JW knows "aAUEybAm" as "Barry Lyndon" directed by "Stanley Kubrick"
    And the resolver finds nothing for "Barry Lyndon"
    When the walk runs
    And the owner resolves the review for "aAUEybAm" with --tt "tt9000433"
    Then there is 1 film titled "Barry Lyndon"
    And the film "Barry Lyndon" holds criterion id "aAUEybAm"
    And there is no open criterion review for "aAUEybAm"

  Scenario: --tt naming a work I lack creates it under TMDB's title, born keyed
    Given Criterion lists "Le Trou" (1960) as "LeTrou60"
    And JW knows "LeTrou60" as "Le Trou" directed by "Jacques Becker"
    And the resolver finds nothing for "Le Trou"
    And TMDB knows "tt9000501" as film 9501 "The Hole" (1960)
    When the walk runs
    And the owner resolves the review for "LeTrou60" with --tt "tt9000501"
    Then the film "The Hole" holds criterion id "LeTrou60"
    And the film "The Hole" holds imdb "tt9000501"
    And the film "The Hole" has year 1960 and director "Jacques Becker"
    And the film "The Hole" has a criterion claim "LeTrou60" titled "Le Trou" for 1960

  Scenario: A resemblance does not stop the owner — gate 3 warns on a human path (ledger L1, The Beast 2023)
    Given a film "The Beast" (1975) holding no ids
    And Criterion lists "The Beast" (2023) as "1n2wLfer"
    And JW knows "1n2wLfer" as "The Beast" directed by "Bertrand Bonello"
    And the resolver matches "The Beast" to "tt9000301" (tmdb 9301) directed by "Bertrand Bonello"
    And TMDB knows "tt9000301" as film 9301 "The Beast" (2023)
    When the walk runs
    Then there is 1 open criterion "corpus-veto" review for "1n2wLfer"
    When the owner resolves the review for "1n2wLfer" with --create
    Then there are 2 films titled "The Beast"
    And the resolution warned that it resembles "'The Beast' (1975)"
    And the 2023 film "The Beast" holds criterion id "1n2wLfer"
    And the 2023 film "The Beast" holds imdb "tt9000301"

  Scenario: --none is refused on a criterion row
    Given Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    When the walk runs
    And the owner resolves the review for "Gh0stEnt" with --none
    Then the resolution is refused
    And there is 1 open criterion "no-record" review for "Gh0stEnt"
