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
    And the archive holds "Seven Samurai" (1955) scored 98 as "seven-samurai-1954"
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

  Scenario: A year-gap slug already claimed by its film does not requeue for review
    Given the film "Tokyo Story (1953)" already claims metacritic slug "tokyo-story"
    And the archive holds "Tokyo Story" (1972) scored 90 as "tokyo-story"
    When I match
    Then the review queue has 0 open entries
    And "Tokyo Story (1953)" has metacritic slug "tokyo-story"

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

  Scenario: Promotion creates real films for unmatched top-N titles
    Given the archive holds "Fresh Find" (2020) scored 95 as "fresh-find"
    When I promote the top 10
    Then the film "Fresh Find (2020)" exists with a guid
    And "Fresh Find (2020)" has metacritic slug "fresh-find"
    And the promote report says 1 promoted

  Scenario: Promotion records a metacritic claim for the film it creates
    Given the archive page 1 has "Fresh Find" slug "fresh-find" 2020 score 90
    When I promote the top 10
    Then "Fresh Find (2020)" has a "metacritic" claim titled "Fresh Find" for year 2020

  Scenario: Promotion never twins a film the matcher already linked
    Given the repository holds the film "Seven Samurai (1954)"
    And the archive holds "Seven Samurai" (1955) scored 98 as "seven-samurai-1954"
    When I promote the top 10
    Then "Seven Samurai (1954)" has metacritic slug "seven-samurai-1954"
    And the repository holds 1 films
    And the promote report says 0 promoted

  Scenario: A year-gap review-band title is skipped, not promoted as a twin
    Given the repository holds the film "Tokyo Story (1953)"
    And the archive holds "Tokyo Story" (1972) scored 90 as "tokyo-story"
    When I promote the top 10
    Then the review queue has a "year-gap" entry
    And the repository holds 1 films
    And the promote report says 0 promoted

  Scenario: The dial bounds promotion by rank
    Given the archive holds "First" (2020) scored 99 as "first"
    And the archive holds "Second" (2021) scored 98 as "second"
    When I promote the top 1
    Then the repository holds 1 films

  Scenario: Two staged titles colliding on one key promote once and queue a review
    Given the archive holds "Solaris" (2002) scored 90 as "solaris"
    And the archive holds "Solaris" (2002) scored 90 as "solaris-2002"
    When I promote the top 10
    Then the repository holds 1 films
    And the review queue has a "key-conflict" entry

  Scenario: An ambiguous staged title is skipped, not promoted
    Given the repository holds the film "Twin (1978)"
    And the repository holds the film "Twin (1980)"
    And the archive holds "Twin" (1979) scored 90 as "twin-1979"
    When I promote the top 10
    Then the repository holds 2 films
    And the review queue has an "ambiguous-title" entry

  Scenario: Re-running promotion is idempotent
    Given the archive holds "Fresh Find" (2020) scored 95 as "fresh-find"
    When I promote the top 10
    And I promote the top 10
    Then the repository holds 1 films
    And the promote report says 0 promoted
