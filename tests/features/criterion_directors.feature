Feature: Criterion's directors fill the blanks no one else fills

  The dashboard shows our director, else OMDb's. A film that holds a Criterion id
  and shows neither takes the director Criterion's own record (JW Player) names —
  only there, and never over a director anyone can already see (spec 2026-10-01 D8,
  story 9). It runs last in the catch-up chain and by hand as
  `enrich criterion-directors`. No stamp: a film JW names nobody for is asked again.

  Scenario: A film OMDb found nothing for takes Criterion's directors (Keeping Secrets Will Destroy You #735)
    Given the film "Keeping Secrets Will Destroy You" (2023) holds Criterion id "3ehCWylD"
    And OMDb found nothing for "Keeping Secrets Will Destroy You"
    And JW answers for "3ehCWylD" as captured on 2026-10-02
    When I fill Criterion directors with apply
    Then the director of "Keeping Secrets Will Destroy You" is "Ryan Daly, Will Oldham"
    And the report reads 1 scanned, 1 filled, 0 without a director, 0 not on JW, 0 failed

  Scenario: OMDb's "N/A" is no director (The Horse in Focus #1766)
    Given the film "The Horse in Focus" (1956) holds Criterion id "5pVD2vhU"
    And OMDb's record for "The Horse in Focus" is the captured "the-horse-in-focus.json"
    And JW answers for "5pVD2vhU" as captured on 2026-10-02
    When I fill Criterion directors with apply
    Then the director of "The Horse in Focus" is "Various"

  Scenario: The IX Olympiad in Amsterdam takes "Various" as printed (#1777)
    Given the film "The IX Olympiad in Amsterdam" (1928) holds Criterion id "dYbj5nMq"
    And OMDb's record for "The IX Olympiad in Amsterdam" is the captured "the-horse-in-focus.json"
    And JW answers for "dYbj5nMq" as captured on 2026-10-02
    When I fill Criterion directors with apply
    Then the director of "The IX Olympiad in Amsterdam" is "Various"

  Scenario: A director OMDb shows is never replaced, and JW is not asked (story 9's 103)
    Given the film "Mistress Dispeller" (2025) holds Criterion id "vuGxAj8b"
    And OMDb's record for "Mistress Dispeller" is the captured "mistress-dispeller.json"
    And JW lists "vuGxAj8b" with director "Someone Else"
    When I fill Criterion directors with apply
    Then "Mistress Dispeller" has no director of its own
    And JW was asked about nothing
    And the report reads 0 scanned, 0 filled, 0 without a director, 0 not on JW, 0 failed

  Scenario: A director we hold is never overwritten
    Given the film "Nadja" (1994) directed by "Michael Almereyda" holds Criterion id "nadjaXX1"
    And JW lists "nadjaXX1" with director "Someone Else"
    When I fill Criterion directors with apply
    Then the director of "Nadja" is "Michael Almereyda"
    And JW was asked about nothing

  Scenario: A filled film is never asked again
    Given the film "Keeping Secrets Will Destroy You" (2023) holds Criterion id "3ehCWylD"
    And JW answers for "3ehCWylD" as captured on 2026-10-02
    When I fill Criterion directors with apply
    And I fill Criterion directors with apply
    Then JW was asked about "3ehCWylD" once
    And the report reads 0 scanned, 0 filled, 0 without a director, 0 not on JW, 0 failed

  Scenario: A record naming no director leaves the blank, and the next run asks again
    Given the film "The IX Olympiad in Amsterdam" (1928) holds Criterion id "dYbj5nMq"
    And JW lists "dYbj5nMq" with no director
    When I fill Criterion directors with apply
    And I fill Criterion directors with apply
    Then "The IX Olympiad in Amsterdam" has no director of its own
    And JW was asked about "dYbj5nMq" twice
    And the report reads 1 scanned, 0 filled, 1 without a director, 0 not on JW, 0 failed

  Scenario: A JW 404 for one film and a JW failure for another never stop the third
    Given the film "Gone Film" (1960) holds Criterion id "goneXXX1"
    And the film "Flaky Film" (1961) holds Criterion id "flakyXX1"
    And the film "Keeping Secrets Will Destroy You" (2023) holds Criterion id "3ehCWylD"
    And JW has no record of "goneXXX1"
    And JW fails for "flakyXX1"
    And JW answers for "3ehCWylD" as captured on 2026-10-02
    When I fill Criterion directors with apply
    Then the director of "Keeping Secrets Will Destroy You" is "Ryan Daly, Will Oldham"
    And JW was asked about "goneXXX1", "flakyXX1", "3ehCWylD" in that order
    And the report reads 3 scanned, 1 filled, 0 without a director, 1 not on JW, 1 failed
    And the log names "goneXXX1" and "flakyXX1"

  Scenario: A dry run asks and reports, and writes nothing
    Given the film "Keeping Secrets Will Destroy You" (2023) holds Criterion id "3ehCWylD"
    And JW answers for "3ehCWylD" as captured on 2026-10-02
    When I fill Criterion directors without applying
    Then "Keeping Secrets Will Destroy You" has no director of its own
    And the report reads 1 scanned, 1 filled, 0 without a director, 0 not on JW, 0 failed
