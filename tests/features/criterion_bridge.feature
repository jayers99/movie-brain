Feature: Criterion bridge — give every stored film its new Criterion id before the first new sync

  Background:
    Given a Criterion film "Test Pattern" (2019) at old link "test-pattern"
    And the old link "test-pattern" forwards to "/films/gpRRkq27/test-pattern"
    And the catalog lists "gpRRkq27" as "Test Pattern" (2021)

  Scenario: A dry run asks every link, keeps the answers, and writes nothing
    When I run the bridge
    Then the bridge counted 1 "film"
    And the drift shows "Test Pattern" 2019 → 2021 as "year"
    And the film "Test Pattern" holds no criterion id
    And the observation file has 1 line

  Scenario: Apply records the id and the new link, and never changes the title or year
    When I run the bridge with apply
    Then the film "Test Pattern" holds criterion id "gpRRkq27"
    And the film "Test Pattern" is listed at "https://www.criterionchannel.com/films/gpRRkq27/test-pattern"
    And the film "Test Pattern" is still 2019

  Scenario: Apply within a day replays the dry run's answers without asking again
    When I run the bridge
    And I run the bridge with apply
    Then the site was asked 1 time

  Scenario: An interrupted run resumes where it stopped
    Given a Criterion film "Bigger Than Life" (1956) at old link "bigger-than-life"
    And the old link "bigger-than-life" forwards to "/films/Ab12Cd34/bigger-than-life"
    And the first run is interrupted after 1 answer
    When I run the bridge
    Then the site was asked 2 times

  Scenario: A link that now leads nowhere, and one that became an extra, write nothing
    Given a Criterion film "Yam daabo" (1987) at old link "yam-daabo"
    And the old link "yam-daabo" answers 404
    And a Criterion film "Contras' City" (1969) at old link "contras-city"
    And the old link "contras-city" forwards to "/supplements/3ekwz1ry/contras-city"
    When I run the bridge with apply
    Then the bridge counted 1 "gone"
    And the bridge counted 1 "supplement"
    And the film "Yam daabo" holds no criterion id

  Scenario: An id another film already holds is a clash for review, never a merge
    Given a Criterion film "Lone Wolf and Cub: Sword of Vengeance" (1972) at old link "sword-of-vengeance"
    And the old link "sword-of-vengeance" forwards to "/films/rLiSVzkD/lone-wolf-and-cub"
    And a Criterion film "Lone Wolf and Cub: Baby Cart at the River Styx" (1972) at old link "river-styx"
    And the old link "river-styx" forwards to "/films/rLiSVzkD/lone-wolf-and-cub"
    When I run the bridge with apply
    Then the bridge counted 1 "held"
    And there is 1 open criterion "id-conflict" review
    When I run the bridge with apply
    Then there is 1 open criterion "id-conflict" review

  Scenario: Two old links on one film that reach the same id are one row and no clash
    Given the film "Test Pattern" also holds old link "test-pattern-1"
    And the old link "test-pattern-1" forwards to "https://www.criterionchannel.com/films/gpRRkq27/test-pattern"
    When I run the bridge with apply
    Then the bridge counted 1 "same-film"
    And there are 0 open criterion "id-conflict" reviews

  Scenario: A link that failed is asked again only with --retry
    Given a Criterion film "Penkelemes" (2025) at old link "penkelemes"
    And the old link "penkelemes" fails
    When I run the bridge
    And the old link "penkelemes" forwards to "/films/Pk00Pk00/penkelmes"
    And I run the bridge
    Then the bridge counted 1 "retry"
    When I run the bridge with retry
    Then the bridge counted 0 "retry"

  Scenario: A restored backup re-opens lines the database no longer holds
    When I run the bridge with apply
    And the database loses the criterion id "gpRRkq27"
    And I run the bridge
    Then the bridge reopened 1 line

  Scenario: A settled link is not asked again a day later
    When I run the bridge with apply
    And I run the bridge with apply a day later
    Then the site was asked 1 time
    And the film "Test Pattern" holds criterion id "gpRRkq27"
    And the bridge counted 1 "same-film"

  Scenario: An unsettled answer older than a day is asked again on apply
    When I run the bridge
    And I run the bridge with apply a day later
    Then the site was asked 2 times

  Scenario: A crash after the database write and before the answers are marked is healed on the next run
    Given a Criterion film "Lone Wolf and Cub: Sword of Vengeance" (1972) at old link "sword-of-vengeance"
    And the old link "sword-of-vengeance" forwards to "/films/rLiSVzkD/lone-wolf-and-cub"
    And a Criterion film "Lone Wolf and Cub: Baby Cart at the River Styx" (1972) at old link "river-styx"
    And the old link "river-styx" forwards to "/films/rLiSVzkD/lone-wolf-and-cub"
    When I run the bridge with apply but the answers cannot be marked
    Then the film "Test Pattern" holds criterion id "gpRRkq27"
    And the observation for "test-pattern" is not applied
    When I run the bridge with apply
    Then the film "Test Pattern" holds criterion id "gpRRkq27"
    And the bridge counted 2 "same-film"
    And the bridge counted 1 "held"
    And the observation for "test-pattern" is applied
    And there is 1 open criterion "id-conflict" review

  Scenario: The lower film id wins a shared id, whatever the link order
    Given a Criterion film "Zeta Film" (1960) at old link "zzz-last"
    And the old link "zzz-last" forwards to "/films/Sh4reD01/shared"
    And a Criterion film "Alpha Film" (1960) at old link "aaa-first"
    And the old link "aaa-first" forwards to "/films/Sh4reD01/shared"
    When I run the bridge with apply
    Then the film "Zeta Film" holds criterion id "Sh4reD01"
    And the film "Alpha Film" holds no criterion id
    And the film "Alpha Film" is the claimant of the open criterion "id-conflict" review

  Scenario: A film whose old links forward to two different ids gets both and is counted
    Given the film "Test Pattern" also holds old link "test-pattern-2"
    And the old link "test-pattern-2" forwards to "/films/Zz99Zz99/test-pattern-cut"
    When I run the bridge with apply
    Then the bridge bound 2 ids on 1 film
    And the film "Test Pattern" holds criterion id "gpRRkq27"
    And the film "Test Pattern" holds criterion id "Zz99Zz99"
