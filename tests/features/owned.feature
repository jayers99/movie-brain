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
