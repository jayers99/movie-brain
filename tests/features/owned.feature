Feature: Apple TV owned films
  One AppleScript export, matched into the database; owned movies missing from
  the catalog become real films. Nothing is deleted, nothing is guessed.

  Scenario: An owned title marks its matching film
    Given the repository holds the film "Seven Samurai (1954)"
    And my Apple TV library has "Seven Samurai (Unrated)" (1954)
    When I import owned films
    Then "Seven Samurai (1954)" is owned
    And the repository holds 1 films
    And the owned report says 1 matched and 0 created

  Scenario: An owned title missing from the catalog becomes a real film
    Given my Apple TV library has "Step Brothers" (2008)
    When I import owned films
    Then the film "Step Brothers (2008)" exists with a guid
    And "Step Brothers (2008)" is owned
    And the owned report says 0 matched and 1 created

  Scenario: One year of drift still matches
    Given the repository holds the film "Alpha (1950)"
    And my Apple TV library has "Alpha" (1951)
    When I import owned films
    Then "Alpha (1950)" is owned
    And the repository holds 1 films

  Scenario: An ambiguous title goes to review, not a guess
    Given the repository holds the film "Twin (1978)"
    And the repository holds the film "Twin (1980)"
    And my Apple TV library has "Twin" (1979)
    When I import owned films
    Then the owned review queue has an "ambiguous-owned" entry
    And no film is owned

  Scenario: Re-running the import is idempotent
    Given my Apple TV library has "Step Brothers" (2008)
    When I import owned films
    And I import owned films
    Then the repository holds 1 films
    And the owned report says 1 already owned

  Scenario: Two editions of one movie own a single film
    Given my Apple TV library has "Blade Runner" (1982)
    And my Apple TV library has "Blade Runner (Director's Cut)" (1982)
    When I import owned films
    Then the repository holds 1 films
    And "Blade Runner (1982)" is owned

  Scenario: An export failure changes nothing
    Given my Apple TV library export fails
    When I import owned films
    Then the owned import exit code is 1
    And the repository holds 0 films

  Scenario: A year embedded in the title beats a re-release year field
    Given the repository holds the film "Rear Window (1954)"
    And my Apple TV library has "Rear Window (1954)" (2013)
    When I import owned films
    Then "Rear Window (1954)" is owned
    And the repository holds 1 films

  Scenario: A big year disagreement goes to review, never a twin
    Given the repository holds the film "Solaris (1972)"
    And my Apple TV library has "Solaris" (2002)
    When I import owned films
    Then the owned review queue has a "year-drift" entry
    And the repository holds 1 films
    And no film is owned

  Scenario: A rerelease annotation corroborates a commerce-year gap
    Given the repository holds the film "The Leopard (1963)"
    And my Apple TV library has "The Leopard (Restored Version)" (2004)
    When I import owned films
    Then "The Leopard (1963)" is owned
    And the repository holds 1 films

  Scenario: The Apple import records a claim carrying the raw title and runtime
    Given the repository holds the film "Seven Samurai (1954)"
    And my Apple TV library has "Seven Samurai (Unrated)" (1954) running 207 minutes
    When I import owned films
    Then "Seven Samurai (1954)" has an "apple-tv" claim titled "Seven Samurai (Unrated)" for year 1954
    And that claim has runtime 207 and edition label "unrated"

  Scenario: An owned edition lands on the keyed work instead of twinning it
    Given the repository holds the film "Blade Runner (1982)" keyed imdb "tt0083658" tmdb "78"
    And my Apple TV library has "Blade Runner (The Final Cut)" (2007)
    And the resolver pool has "Blade Runner (The Final Cut)" → tt0083658/78 1982
    When I import owned films
    Then "Blade Runner (1982)" is owned
    And the repository holds 1 films
    And the owned report says 0 created and 1 resolved to existing

  Scenario: An owned film nobody holds is created and keyed in one pass
    Given my Apple TV library has "Step Brothers" (2008)
    And the resolver pool has "Step Brothers" → tt1023111/12133 2008
    When I import owned films
    Then the film "Step Brothers (2008)" exists with a guid
    And "Step Brothers (2008)" holds imdb "tt1023111" and tmdb id "12133"
    And the owned report says 1 created and 1 keyed

  Scenario: An ambiguous owned title falls back to the corpus path, never a guess
    Given the repository holds the film "Nosferatu (1922)"
    And my Apple TV library has "Nosferatu" (2024)
    And the resolver pool has "Nosferatu" ambiguous
    When I import owned films
    Then the review queue has a "year-drift" entry
    And the repository holds 1 films

  Scenario: With no resolver the import behaves exactly as before
    Given my Apple TV library has "Step Brothers" (2008)
    When I import owned films without a resolver
    Then the film "Step Brothers (2008)" exists with a guid
    And the owned report says 1 created and 0 keyed

  Scenario: Re-running an import that lands on an existing holder is idempotent
    Given the repository holds the film "Blade Runner (1982)" keyed imdb "tt0083658" tmdb "78"
    And my Apple TV library has "Blade Runner (Director's Cut)" (2007)
    And the resolver pool has "Blade Runner (Director's Cut)" → tt0083658/78 1982
    When I import owned films
    And I import owned films
    Then the owned report says 1 already owned
    And the repository holds 1 films

  Scenario: An owned edition never binds to a tombstoned holder
    Given the repository holds the film "Blade Runner (1982)" keyed imdb "tt0083658" tmdb "78"
    And "Blade Runner (1982)" is tombstoned
    And my Apple TV library has "Blade Runner (Director's Cut)" (2007)
    And the resolver pool has "Blade Runner (Director's Cut)" → tt0083658/78 1982
    When I import owned films
    Then "Blade Runner (1982)" is not owned
    And the film "Blade Runner (2007)" exists with a guid
    And "Blade Runner (2007)" is owned
    And the owned report says 1 created and 0 keyed
