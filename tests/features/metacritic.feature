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
