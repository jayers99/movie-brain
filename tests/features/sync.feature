Feature: Daily sync
  Keep the catalog and OMDb ratings in SQLite up to date, cheaply when nothing changed.

  Background:
    Given a fresh repository
    And the Criterion browse page exposes a token

  Scenario: First run does a full walk and fills ratings
    Given the Criterion catalog has films "Trio (1950)" and "Quartet (1948)"
    And OMDb knows every film
    When I sync
    Then the exit code is 0
    And the catalog walk was full
    And 2 films are current
    And 2 films have OMDb ratings
    And films_fetched_at is today

  Scenario: Unchanged page 1 within 7 days reuses the stored catalog
    Given the repository already holds "Trio (1950)" walked 2 days ago
    And the Criterion catalog has films "Trio (1950)"
    And OMDb knows every film
    When I sync
    Then the catalog walk was cheap
    And only page 1 of the movie catalog was requested
    And films_fetched_at is 2 days ago

  Scenario: A changed page 1 forces a full walk
    Given the repository already holds "Trio (1950)" walked 2 days ago
    And the Criterion catalog has films "Trio (1950)" and "New (2020)"
    And OMDb knows every film
    When I sync
    Then the catalog walk was full
    And 2 films are current

  Scenario: --full always walks
    Given the repository already holds "Trio (1950)" walked 2 days ago
    And the Criterion catalog has films "Trio (1950)"
    And OMDb knows every film
    When I sync with --full
    Then the catalog walk was full

  Scenario: --ratings-only skips Criterion
    Given the repository already holds "Trio (1950)" walked 2 days ago
    And OMDb knows every film
    When I sync with --ratings-only
    Then the exit code is 0
    And Criterion was never contacted
    And 1 films have OMDb ratings

  Scenario: --ratings-only without a stored catalog fails
    When I sync with --ratings-only
    Then the exit code is 1

  Scenario: Catalog failure leaves the database untouched
    Given the repository already holds "Trio (1950)" walked 2 days ago
    And the Criterion API returns 500
    When I sync
    Then the exit code is 1
    And 1 films are current
    And 0 films have OMDb ratings

  Scenario: Leaving-soon failure keeps last-known departures
    Given the repository already holds "Trio (1950)" walked 2 days ago leaving "August 31"
    And the Criterion catalog has films "Trio (1950)"
    And the leaving-soon categories endpoint returns 500
    And OMDb knows every film
    When I sync
    Then the exit code is 0
    And "Trio (1950)" is leaving "August 31"

  Scenario: OMDb quota stops lookups but keeps what was fetched
    Given the Criterion catalog has films "Trio (1950)" and "Quartet (1948)"
    And OMDb answers once then reports the request limit
    When I sync
    Then the exit code is 0
    And the quota flag is set
    And 1 films have OMDb ratings

  Scenario: OMDb rejects the key
    Given the Criterion catalog has films "Trio (1950)"
    And OMDb rejects the API key
    When I sync
    Then the exit code is 2

  Scenario: Repeated OMDb failures stop lookups but keep what was fetched
    Given the Criterion catalog has films "Trio (1950)" and "Quartet (1948)" and "Third (1960)" and "Fourth (1970)" and "Fifth (1980)" and "Sixth (1990)" and "Seventh (2000)"
    And OMDb answers once then errors repeatedly
    When I sync
    Then the exit code is 0
    And the failing flag is set
    And 1 films have OMDb ratings
