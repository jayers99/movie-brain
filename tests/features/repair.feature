Feature: Dispositioned films stay out of every collector's way

  Background:
    Given a repository with films "Alpha (1950)" on Criterion and "Alpha (1951)" from commerce

  Scenario: A merged film disappears from the dashboard view but its title still resolves to the survivor
    When I merge "Alpha (1951)" into "Alpha (1950)"
    Then the dashboard lists 1 film titled "Alpha"
    And matching the Metacritic title "Alpha" year 1951 resolves to "Alpha (1950)"

  Scenario: A Criterion re-walk of a merged film's key writes to the survivor
    When I merge "Alpha (1951)" into "Alpha (1950)"
    And Criterion lists "Alpha (1951)" again
    Then "Alpha (1950)" has a criterion listing and "Alpha (1951)" has none

  Scenario: Promotion never resurrects a tombstoned film
    Given a tombstoned film "Bravo (1975)"
    When the Metacritic archive stages "Bravo" (1975) as slug "bravo-1975"
    And the top 10 staged titles are promoted
    Then no film was promoted and slug "bravo-1975" is unclaimed

  Scenario: Owned import marks the survivor, never a tombstone or a merged loser
    When I merge "Alpha (1951)" into "Alpha (1950)"
    And the Apple library contains "Alpha" from 1951
    Then "Alpha (1950)" is owned and "Alpha (1951)" is not

  Scenario: Discovery lookups skip dispositioned films
    Given "Alpha (1951)" is tombstoned
    Then no discovery film needs an OMDb lookup
    And no film needs a TMDB match except "Alpha (1950)"

  Scenario: A multi-hop merge chain resolves matching and owned-import to the ultimate survivor
    Given the repository also has film "Alpha (1952)"
    When I merge "Alpha (1951)" into "Alpha (1950)"
    And I merge "Alpha (1950)" into "Alpha (1952)"
    And the Apple library contains "Alpha" from 1951
    Then matching the Metacritic title "Alpha" year 1951 resolves to "Alpha (1952)"
    And "Alpha (1952)" is owned and "Alpha (1950)" is not

  Scenario: Same-TMDB-id norm-title twins merge into the Criterion survivor
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1951)" has an open id-conflict review claiming tmdb id "5"
    When I audit dupes
    Then the group "alpha" is a twin with survivor "Alpha (1950)" from source "id-conflict"
    When I apply dupes confirming every group
    Then "Alpha (1951)" is merged into "Alpha (1950)"
    And the id-conflict review is resolved

  Scenario: An id-conflict pair with mismatched titles is undecided, not a tautological twin
    Given "Alpha (1950)" holds tmdb id "5"
    And the repository also has film "Factory (1970)"
    And "Factory (1970)" has an open id-conflict review claiming tmdb id "5"
    When I audit dupes
    Then the group "alpha" is undecided from source "id-conflict"
    When I apply dupes confirming every group
    Then nothing was merged

  Scenario: An id-conflict row claiming an imdb id is no longer invisible to the audit
    Given "Alpha (1950)" holds imdb id "tt0024216"
    And the repository also has film "Factory (1970)"
    And "Factory (1970)" has an open id-conflict review claiming imdb id "tt0024216"
    When I audit dupes
    Then exactly 1 group is keyed "alpha"
    And the group "alpha" is undecided from source "id-conflict"

  Scenario: An imdb-id conflict between same-titled films is undecided, never a false "distinct"
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1950)" holds imdb id "tt0024216"
    And "Alpha (1951)" has an open id-conflict review claiming imdb id "tt0024216"
    When I audit dupes
    Then the group "alpha" is undecided from source "id-conflict"

  Scenario: Distinct TMDB ids are kept both
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1951)" holds tmdb id "6"
    When I audit dupes
    Then the group "alpha" is distinct

  Scenario: A group missing TMDB evidence is undecided and never merged in batch
    When I audit dupes
    Then the group "alpha" is undecided
    When I apply dupes confirming every group
    Then nothing was merged

  Scenario: Declining the confirmation merges nothing
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1951)" has an open id-conflict review claiming tmdb id "5"
    When I apply dupes declining every group
    Then nothing was merged

  Scenario: An id-conflict pair inside a larger norm-title bucket doesn't spawn a spurious second group
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1951)" has an open id-conflict review claiming tmdb id "5"
    And the repository also has film "Alpha (1990)"
    When I audit dupes
    Then exactly 1 group is keyed "alpha"
    And the group "alpha" is a twin with survivor "Alpha (1950)" from source "id-conflict"

  Scenario: A TMDB link whose titles disagree with the film is a suspect and can be cleared
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1951)" holds tmdb id "62518"
    And TMDB describes id 5 as "Alpha" / "Alpha" from 1950
    And TMDB describes id 62518 as "Wild Blood" / "Vahşi Kan" from 1983
    When I audit links
    Then the only link suspect is "Alpha (1951)"
    When I apply links
    Then "Alpha (1951)" has no tmdb id and is a TMDB miss
    And "Alpha (1950)" still holds tmdb id "5"

  Scenario: A film matching TMDB's original title is not a suspect
    Given "Alpha (1950)" holds tmdb id "5"
    And TMDB describes id 5 as "The Alpha Movie" / "Alpha" from 1950
    When I audit links
    Then there are no link suspects

  Scenario: A film matching one of TMDB's alternative titles is not a suspect
    Given "Alpha (1950)" holds tmdb id "5"
    And TMDB describes id 5 as "Alfa" / "Alfa" from 1950 with alternative titles "Alpha; Der Alpha"
    When I audit links
    Then there are no link suspects

  Scenario: Repairing one film by id clears its link even when the titles agree
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1951)" holds tmdb id "62518"
    And TMDB describes id 5 as "Alpha" / "Alpha" from 1950
    And TMDB describes id 62518 as "Wild Blood" / "Vahşi Kan" from 1983
    When I audit links for film "Alpha (1950)"
    Then the only link suspect is "Alpha (1950)"
    When I apply links for film "Alpha (1950)"
    Then "Alpha (1950)" has no tmdb id and is a TMDB miss
    And "Alpha (1951)" still holds tmdb id "62518"

  Scenario: Repairing a film that holds no TMDB link is an error
    When I apply links for film "Alpha (1950)"
    Then the links repair fails with "no TMDB link"

  Scenario: Re-keying a confidently-wrong film swaps both ids and queues an OMDb refetch
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1950)" holds imdb id "tt0075335"
    And "Alpha (1950)" has an OMDb payload for imdb "tt0075335"
    And TMDB finds movie 162505 for imdb "tt0075915"
    And TMDB describes id 162505 as "One Way or Another" / "De cierta manera" from 1977
    When I re-key film "Alpha (1950)" to imdb "tt0075915"
    Then "Alpha (1950)" holds imdb id "tt0075915" and tmdb id "162505"
    And "Alpha (1950)" needs an OMDb refresh
    And the re-key repair re-keyed 1 films and exits 0

  Scenario: A re-key of a film that holds no TMDB link keys it instead of erroring
    Given TMDB finds movie 162505 for imdb "tt0075915"
    And TMDB describes id 162505 as "One Way or Another" / "De cierta manera" from 1977
    When I re-key film "Alpha (1950)" to imdb "tt0075915"
    Then "Alpha (1950)" holds imdb id "tt0075915" and tmdb id "162505"

  Scenario: A re-key dry run writes nothing
    Given "Alpha (1950)" holds tmdb id "5"
    And "Alpha (1950)" holds imdb id "tt0075335"
    And "Alpha (1950)" has an OMDb payload for imdb "tt0075335"
    And TMDB finds movie 162505 for imdb "tt0075915"
    When I dry-run a re-key of film "Alpha (1950)" to imdb "tt0075915"
    Then "Alpha (1950)" holds imdb id "tt0075335" and tmdb id "5"
    And "Alpha (1950)" does not need an OMDb refresh
    And the re-key repair re-keyed 0 films and exits 0

  Scenario: A re-key never steals an IMDb id another film holds
    Given "Alpha (1951)" holds imdb id "tt0075915"
    And "Alpha (1950)" holds imdb id "tt0075335"
    When I re-key film "Alpha (1950)" to imdb "tt0075915"
    Then "Alpha (1950)" holds imdb id "tt0075335" and no tmdb id
    And the re-key repair re-keyed 0 films and exits 1
    # Without this the scenario cannot tell `held` from `error`: a regression that made
    # key_film fetch before its holder check would raise, and every assertion above would
    # still pass. Pin the REASON, and that the id stayed with its rightful owner.
    And the re-key log says "already held"
    And "Alpha (1951)" holds imdb id "tt0075915"

  Scenario: A re-key leaves the film untouched when TMDB fails
    Given "Alpha (1950)" holds imdb id "tt0075335"
    And TMDB is down for imdb "tt0075915"
    When I re-key film "Alpha (1950)" to imdb "tt0075915"
    Then "Alpha (1950)" holds imdb id "tt0075335" and no tmdb id
    And the re-key repair re-keyed 0 films and exits 1

  Scenario: A malformed IMDb id is refused before anything is read
    When I re-key film "Alpha (1950)" to imdb "0075915"
    Then the links repair fails with "malformed"

  Scenario: A re-key without a film is refused
    When I re-key every film to imdb "tt0075915"
    Then the links repair fails with "requires --film"

  Scenario: A re-key of an unknown film is refused
    When I re-key film 9999 to imdb "tt0075915"
    Then the links repair fails with "not found"

  Scenario: A re-key of a tombstoned film is refused
    Given "Alpha (1951)" is tombstoned
    When I re-key film "Alpha (1951)" to imdb "tt0075915"
    Then the links repair fails with "tombstoned"

  Scenario: A re-key of a merged-away film names its survivor instead
    When I merge "Alpha (1951)" into "Alpha (1950)"
    And I re-key film "Alpha (1951)" to imdb "tt0075915"
    Then the links repair fails with "merged into"

  Scenario: The years worklist lists stale OMDb payloads and applying marks them for refetch
    Given "Alpha (1951)" has an OMDb payload fetched for year 1953
    When I audit years
    Then the stale OMDb list is exactly "Alpha (1951)"
    When I apply years
    Then "Alpha (1951)" needs an OMDb refresh

  Scenario: A manual year correction is dry-run first, then applied with a refetch mark
    Given "Alpha (1951)" has an OMDb payload fetched for year 1951
    When I dry-run setting "Alpha (1951)" to 1949
    Then "Alpha (1951)" still has year 1951
    When I apply setting "Alpha (1951)" to 1949
    Then a film "Alpha (1949)" exists and its OMDb row is marked for refresh

  Scenario: A manual year correction that collides queues a merge candidate instead
    When I apply setting "Alpha (1951)" to 1950
    Then "Alpha (1951)" still has year 1951
    And an open tmdb year-collision review names "Alpha (1950)"
