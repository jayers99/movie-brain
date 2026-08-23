Feature: Metacritic archive
  One polite browse walk, archived raw with checkpoint/resume; matching enriches
  existing films and never deletes anything.

  Scenario: Crawl archives the requested pages
    Given Metacritic serves 3 browse pages
    When I crawl 3 pages
    Then the crawl exit code is 0
    And 3 pages are archived
    And the fetch log records 3 fetches

  Scenario: Crawl skips pages already archived
    Given Metacritic serves 3 browse pages
    And pages 1 and 2 are already archived
    When I crawl 3 pages
    Then only page 3 was fetched from the network
    And 3 pages are archived

  Scenario: Repeated failures stop the crawl but keep progress
    Given Metacritic serves page 1 then errors
    When I crawl 9 pages
    Then the crawl exit code is 1
    And 1 pages are archived

  Scenario: A bot wall page is a failure, not an archive entry
    Given Metacritic serves pages without title cards
    When I crawl 5 pages
    Then the crawl exit code is 1
    And 0 pages are archived

  Scenario: Match links an archived title to its film
    Given the repository holds the film "Seven Samurai (1954)"
    And the archive holds "Seven Samurai" (1956) scored 98 as "seven-samurai-1954"
    When I match
    Then "Seven Samurai (1954)" has metacritic slug "seven-samurai-1954"
    And the coverage report says 1 of 1 films matched

  Scenario: Matching strips annotations and punctuation
    Given the repository holds the film "Forbidden Lies (2007)"
    And the archive holds "Forbidden Lie$ (re-release)" (2009) scored 80 as "forbidden-lies"
    When I match
    Then "Forbidden Lies (2007)" has metacritic slug "forbidden-lies"

  Scenario: An ambiguous title goes to the review queue, not a guess
    Given the repository holds the film "Twin (1978)"
    And the repository holds the film "Twin (1980)"
    And the archive holds "Twin" (1979) scored 90 as "twin-1979"
    When I match
    Then the review queue has an "ambiguous-title" entry
    And the coverage report says 0 of 2 films matched

  Scenario: The same title archived on two pages does not un-link its film
    Given the repository holds the film "Seven Samurai (1954)"
    And the archive holds "Seven Samurai" (1954) scored 98 as "seven-samurai-1954" on page 1
    And the archive holds "Seven Samurai" (1954) scored 98 as "seven-samurai-1954" on page 2
    When I match
    Then "Seven Samurai (1954)" has metacritic slug "seven-samurai-1954"
    And the review queue has 0 open entries

  Scenario: A slug already claimed by another film is contained and queued
    Given the repository holds the film "Twin (1950)"
    And the film "Other (1960)" already claims metacritic slug "twin-1950"
    And the archive holds "Twin" (1950) scored 85 as "twin-1950"
    When I match
    Then the review queue has a "slug-conflict" entry
    And "Twin (1950)" has no metacritic slug

  Scenario: A film with an OMDb metascore above the floor that matched nothing is flagged
    Given the repository holds the film "Obscure (1950)" with OMDb metascore 85
    And the archive holds "Unrelated" (2000) scored 80 as "unrelated-2000"
    When I match
    Then the review queue has an "expected-miss" entry for "Obscure (1950)"

  Scenario: Re-running match is idempotent
    Given the repository holds the film "Twin (1978)"
    And the repository holds the film "Twin (1980)"
    And the archive holds "Twin" (1979) scored 90 as "twin-1979"
    When I match
    And I match
    Then the review queue has 1 open entries
    And no film was deleted

  Scenario: Match without an archive fails cleanly
    When I match
    Then the match exit code is 1
