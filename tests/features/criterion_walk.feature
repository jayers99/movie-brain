Feature: The Criterion walk — a catalog item IS the film holding its mediaid (spec 2026-10-01 D2, D4–D7, D10)
  Only a mediaid no film holds is asked about: JW Player, the thumbprint resolver, then the
  gates `films add` runs. Everything is written in one transaction, or nothing is.

  Scenario: A film Criterion re-dated stays my film (Nadja #3057, story 3)
    # listed on the frontier and re-stamped: not an arrival, nothing departs
    Given the last walk listed "Nadja" (1994) as "7xCZH5br"
    And the film "Nadja" is rated 5
    And Criterion lists "Nadja" (1995) as "7xCZH5br"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 0
    And there is 1 film titled "Nadja"
    And the film "Nadja" has year 1994 and rating 5
    And the film "Nadja" is current on Criterion
    And the film "Nadja" has a criterion claim "7xCZH5br" titled "Nadja" for 1995
    And JW Player was asked 0 times in all

  Scenario: A film I hold that Criterion just added joins it (Barry Lyndon #3433, story 4)
    # no Criterion listing before → one arrival; gate 1 finds the holder, so TMDB is never asked
    Given a film "Barry Lyndon" (1975) holding imdb "tt9000433"
    And Criterion lists "Barry Lyndon" (1975) as "aAUEybAm"
    And JW knows "aAUEybAm" as "Barry Lyndon" directed by "Stanley Kubrick"
    And the resolver matches "Barry Lyndon" to "tt9000433" (tmdb 9433) directed by "Stanley Kubrick"
    When the walk runs
    Then the walk reports arrived 1, left 0, to review 0
    And no film was created
    And there is 1 film titled "Barry Lyndon"
    And the film "Barry Lyndon" holds criterion id "aAUEybAm"
    And the film "Barry Lyndon" arrived on Criterion today

  Scenario: A film new to Criterion and to me is born holding its mediaid, under TMDB's title
    Given Criterion lists "2 or 3 Things I Know About Her" (1967) as "L5Z3RaiC"
    And JW knows "L5Z3RaiC" as captured
    And the resolver matches "2 or 3 Things I Know About Her" to "tt9000304" (tmdb 8072) directed by "Jean-Luc Godard"
    And TMDB knows "tt9000304" as film 8072 "Two or Three Things I Know About Her" (1967)
    When the walk runs
    Then the walk reports arrived 1, left 0, to review 0
    And the walk created 1 film
    And the film "Two or Three Things I Know About Her" holds criterion id "L5Z3RaiC"
    And the film "Two or Three Things I Know About Her" has year 1967 and director "Jean-Luc Godard"
    And the film "Two or Three Things I Know About Her" holds imdb "tt9000304"
    And the film "Two or Three Things I Know About Her" has a criterion claim "L5Z3RaiC" titled "2 or 3 Things I Know About Her" for 1967
    And the film "Two or Three Things I Know About Her" is listed at "https://www.criterionchannel.com/films/L5Z3RaiC"

  Scenario: A film the resolver cannot place waits for me as one review row (story 7)
    Given Criterion lists "K-ON! The Movie" (2011) as "VBLiQBrA"
    And JW knows "VBLiQBrA" as "K-ON! The Movie" directed by "Naoko Yamada"
    And the resolver finds nothing for "K-ON! The Movie"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 1
    And no film was created
    And there is 1 open criterion "no-match" review for "VBLiQBrA"
    And that review shows Criterion's title "K-ON! The Movie", year 2011 and director "Naoko Yamada"

  Scenario: Two mediaids the resolver cannot tell apart are two rows; a rerun adds none and asks nothing
    Given Criterion lists "Dr. Dolittle" (1923) as "YM0kT8PG"
    And Criterion lists "Dr. Dolittle" (1923) as "BgC4kIqZ"
    And JW knows "YM0kT8PG" as "Dr. Dolittle" directed by "Lotte Reiniger"
    And JW knows "BgC4kIqZ" as "Dr. Dolittle" directed by "Lotte Reiniger"
    And the resolver finds two works named "Dr. Dolittle" (1923)
    When the walk runs
    And the walk runs again the next day
    Then there is 1 open criterion "no-match" review for "YM0kT8PG"
    And there is 1 open criterion "no-match" review for "BgC4kIqZ"
    And JW Player was asked 2 times in all

  Scenario: Two mediaids naming one work become ONE new film holding both (The Beast 2023)
    # the second item joins the film the first one reserved: one creation, one listing, one arrival
    Given Criterion lists "The Beast" (2023) as "1n2wLfer"
    And Criterion lists "The Beast" (2023) as "7G9Sr5tL"
    And JW knows "1n2wLfer" as "The Beast" directed by "Bertrand Bonello"
    And JW knows "7G9Sr5tL" as "The Beast" directed by "Bertrand Bonello"
    And the resolver matches "The Beast" to "tt9000301" (tmdb 9301) directed by "Bertrand Bonello"
    And TMDB knows "tt9000301" as film 9301 "The Beast" (2023)
    When the walk runs
    Then the walk reports arrived 1, left 0, to review 0
    And the walk created 1 film
    And the film "The Beast" holds criterion ids "1n2wLfer" and "7G9Sr5tL"
    And the film "The Beast" has 1 Criterion listing

  Scenario: Eve's Bayou — one film holding two listed mediaids is ONE listing, never a twin or a false arrival
    Given the last walk listed "Eve's Bayou" (1997) as "6tfyfj2f"
    And the film "Eve's Bayou" also holds criterion id "gOkSarah"
    And Criterion lists "Eve’s Bayou" (1997) as "6tfyfj2f"
    And Criterion lists "EVE’S BAYOU: Director’s Cut" (2022) as "gOkSarah"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 0
    And there is 1 film titled "Eve's Bayou"
    And the film "Eve's Bayou" has 1 Criterion listing
    And the film "Eve's Bayou" has 2 criterion claims
    And no film arrived on Criterion today

  Scenario: A second mediaid that resolves to a film already listed joins it without an arrival
    # the director's cut is unknown; the resolver names Eve's Bayou's own IMDb id (director corroborates
    # across the 1997/2022 years), gate 1 finds the holder, and the film keeps its one listing
    Given the last walk listed "Eve's Bayou" (1997) as "6tfyfj2f"
    And the film "Eve's Bayou" also holds imdb "tt9000150"
    And Criterion lists "Eve’s Bayou" (1997) as "6tfyfj2f"
    And Criterion lists "EVE’S BAYOU: Director’s Cut" (2022) as "gOkSarah"
    And JW knows "gOkSarah" as "EVE’S BAYOU: Director’s Cut" directed by "Kasi Lemmons"
    And the resolver matches "EVE’S BAYOU: Director’s Cut" to "tt9000150" (tmdb 9150) directed by "Kasi Lemmons"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 0
    And there is 1 film titled "Eve's Bayou"
    And the film "Eve's Bayou" holds criterion ids "6tfyfj2f" and "gOkSarah"
    And the film "Eve's Bayou" has 1 Criterion listing
    And no film arrived on Criterion today

  Scenario: A film that left is departed, kept, and loses its Leaving label (Some Came Running #33, stories 5 and 11)
    Given the last walk listed "Some Came Running" (1958) as "SmCmRn58"
    And the last walk listed "Nadja" (1994) as "7xCZH5br"
    And the film "Some Came Running" is on the watchlist
    And the film "Some Came Running" is leaving "September 30"
    And Criterion lists "Nadja" (1994) as "7xCZH5br"
    When the walk runs
    Then the walk reports arrived 0, left 1, to review 0
    And the film "Some Came Running" is not current on Criterion
    And the film "Some Came Running" is not leaving
    And the film "Some Came Running" is still on the watchlist

  Scenario: The dated leaving page relabels the films it names (story 6)
    Given the last walk listed "Zabriskie Point" (1970) as "Tg73fdO2"
    And the last walk listed "Nadja" (1994) as "7xCZH5br"
    And the film "Nadja" is leaving "September 30"
    And Criterion lists "Zabriskie Point" (1970) as "Tg73fdO2"
    And Criterion lists "Nadja" (1994) as "7xCZH5br"
    And the leaving page lists "Tg73fdO2" for "October 31"
    When the walk runs
    Then the film "Zabriskie Point" is leaving "October 31"
    And the film "Nadja" is not leaving

  Scenario: Leaving pages that cannot be read keep the labels of the films still listed
    Given the last walk listed "Zabriskie Point" (1970) as "Tg73fdO2"
    And the last walk listed "Some Came Running" (1958) as "SmCmRn58"
    And the film "Zabriskie Point" is leaving "October 31"
    And the film "Some Came Running" is leaving "September 30"
    And Criterion lists "Zabriskie Point" (1970) as "Tg73fdO2"
    And the leaving pages cannot be read
    When the walk runs
    Then the film "Zabriskie Point" is leaving "October 31"
    And the film "Some Came Running" is not leaving

  Scenario: A JW Player "no such id" is one review row and the walk carries on
    Given the last walk listed "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 1
    And there is 1 open criterion "no-record" review for "Gh0stEnt"
    And the film "Nadja" is current on Criterion

  Scenario: A JW Player failure fails the walk and writes nothing (story 8)
    Given the last walk listed "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "Nadja" (1995) as "7xCZH5br"
    And Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    And JW fails for "Gh0stEnt"
    When the walk runs and fails
    Then Criterion is exactly as it was before the walk

  Scenario: A failure late in the write leaves Criterion exactly as it was
    Given the last walk listed "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "Nadja" (1995) as "7xCZH5br"
    And Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    And the walk's write fails at its last step
    When the walk runs and fails
    Then Criterion is exactly as it was before the walk

  Scenario: A mediaid the owner dismissed is never asked about again
    Given Criterion lists "Ghost Entry" (2020) as "Gh0stEnt"
    When the walk runs
    And the owner dismisses the criterion review for "Gh0stEnt"
    And the walk runs again the next day
    Then JW Player was asked 1 time in all
    And there is no open criterion review for "Gh0stEnt"

  Scenario: A held mediaid is listed on its holder whatever review rows mention it
    Given the last walk listed "Test Pattern" (2019) as "gpRRkq27"
    And a film "Test Pattern Twin" (2019) holding no ids
    And an open criterion "id-conflict" review names "gpRRkq27" for "Test Pattern Twin"
    And Criterion lists "Test Pattern" (2021) as "gpRRkq27"
    When the walk runs
    Then the film "Test Pattern" is current on Criterion
    And JW Player was asked 0 times in all

  Scenario: A resolver lookup that fails is weather — no review row, and the next walk resolves it
    Given Criterion lists "2 or 3 Things I Know About Her" (1967) as "L5Z3RaiC"
    And JW knows "L5Z3RaiC" as captured
    And the resolver matches "2 or 3 Things I Know About Her" to "tt9000304" (tmdb 8072) directed by "Jean-Luc Godard"
    And TMDB knows "tt9000304" as film 8072 "Two or Three Things I Know About Her" (1967)
    And the resolver is offline for "2 or 3 Things I Know About Her"
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 0
    And the walk did not ask about 1 film tonight
    And no film was created
    When the resolver comes back
    And the walk runs again the next day
    Then the walk created 1 film

  Scenario: Without a resolver, new films wait unasked and known films still refresh
    Given the last walk listed "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "Nadja" (1994) as "7xCZH5br"
    And Criterion lists "2 or 3 Things I Know About Her" (1967) as "L5Z3RaiC"
    And JW knows "L5Z3RaiC" as captured
    When the walk runs without a TMDB token
    Then the walk reports arrived 0, left 0, to review 0
    And the walk did not ask about 1 film tonight
    And JW Player was asked 0 times in all
    And the film "Nadja" is current on Criterion

  Scenario: A film I hold under no ids is reachable only by a human (K-ON! #142)
    Given a film "K-ON! The Movie" (2011) holding no ids
    And Criterion lists "K-ON! The Movie" (2011) as "VBLiQBrA"
    And JW knows "VBLiQBrA" as "K-ON! The Movie" directed by "Naoko Yamada"
    And the resolver matches "K-ON! The Movie" to "tt9000142" (tmdb 9142) directed by "Naoko Yamada"
    And TMDB knows "tt9000142" as film 9142 "K-ON! The Movie" (2011)
    When the walk runs
    Then the walk reports arrived 0, left 0, to review 1
    And no film was created
    And there is 1 open criterion "corpus-veto" review for "VBLiQBrA"
    And the film "K-ON! The Movie" holds no criterion id

  Scenario: Two new works whose titles collide — the first is created, the second waits (ledger L5)
    Given Criterion lists "Le Trou" (1960) as "LeTrou60"
    And Criterion lists "The Hole" (1960) as "TheHole6"
    And JW knows "LeTrou60" as "Le Trou" directed by "Jacques Becker"
    And JW knows "TheHole6" as "The Hole" directed by "Jacques Becker"
    And the resolver matches "Le Trou" to "tt9000501" (tmdb 9501) directed by "Jacques Becker"
    And the resolver matches "The Hole" to "tt9000502" (tmdb 9502) directed by "Jacques Becker"
    And TMDB knows "tt9000501" as film 9501 "The Hole" (1960)
    And TMDB knows "tt9000502" as film 9502 "The Hole" (1960)
    When the walk runs
    Then the walk created 1 film
    And the walk reports arrived 1, left 0, to review 1
    And there is 1 open criterion "corpus-veto" review for "TheHole6"

  Scenario: A tombstoned holder is never relisted by a new mediaid
    Given a film "Trash Humpers" (2009) holding imdb "tt9000601"
    And the film "Trash Humpers" is tombstoned
    And Criterion lists "Trash Humpers" (2009) as "TrshHump"
    And JW knows "TrshHump" as "Trash Humpers" directed by "Harmony Korine"
    And the resolver matches "Trash Humpers" to "tt9000601" (tmdb 9601) directed by "Harmony Korine"
    When the walk runs
    Then there is 1 open criterion "tombstoned-holder" review for "TrshHump"
    And no film was created

  Scenario: A bridged film keeps its slugged link; an old-style link becomes the film's new page (story 10)
    Given the last walk listed "Test Pattern" (2019) as "gpRRkq27" at "https://www.criterionchannel.com/films/gpRRkq27/test-pattern"
    And the last walk listed "Nadja" (1994) as "7xCZH5br" at "https://www.criterionchannel.com/nadja"
    And Criterion lists "Test Pattern" (2021) as "gpRRkq27"
    And Criterion lists "Nadja" (1995) as "7xCZH5br"
    When the walk runs
    Then the film "Test Pattern" is listed at "https://www.criterionchannel.com/films/gpRRkq27/test-pattern"
    And the film "Nadja" is listed at "https://www.criterionchannel.com/films/7xCZH5br"

  Scenario: A walk before the bridge's apply refuses and writes nothing (Review Focus 1, ledger L7)
    Given the last walk listed "Nadja" (1994) under its old link only
    And Criterion lists "Nadja" (1995) as "7xCZH5br"
    When the walk runs and fails
    Then the walk failure names "criterion bridge --apply"
    And Criterion is exactly as it was before the walk
    And Criterion was never asked for its catalog

  Scenario: A JW record with no director gives the new film no director, never an empty one (Review Focus 5)
    Given Criterion lists "Untitled Short" (2020) as "UntShort"
    And JW knows "UntShort" as "Untitled Short" with no director
    And the resolver matches "Untitled Short" (2020) to "tt9000801" (tmdb 9801) with no director
    And TMDB knows "tt9000801" as film 9801 "Untitled Short" (2020)
    When the walk runs
    Then the walk created 1 film
    And the resolver was asked about "Untitled Short" with no director
    And the film "Untitled Short" has no director
