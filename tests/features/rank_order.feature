Feature: Order a tier — strict order inside any of the five tiers by binary insertion

  Background:
    Given owned films rated "Alpha" 10, "Beta" 10, "Gamma" 10, "Delta" 10, "Nine" 9, "Eight" 8, "Seven" 7, "Six" 6
    And an owned unrated film "Uno"
    And a started tiering session

  Scenario: The first tier 1 film is ordered without a click and the second is asked against it
    Then 1 film is ordered and 3 remain to order
    And the order pair shows position 1 of 1

  Scenario: Answering better every time puts each film at the top
    When I answer better in order mode until the candidate is inserted
    Then the last inserted film is at position 1
    When I answer better in order mode until the candidate is inserted
    Then the last inserted film is at position 1
    And 3 films are ordered

  Scenario: Answering worse every time appends each film
    When I answer worse in order mode until the candidate is inserted
    Then the last inserted film is at position 2
    When I answer worse in order mode until the candidate is inserted
    Then the last inserted film is at position 3

  Scenario: Every film ordered means done, and a later tier 1 placement reopens the queue
    When I answer better in order mode until the candidate is inserted
    And I answer better in order mode until the candidate is inserted
    And I answer better in order mode until the candidate is inserted
    Then the order is done with 4 films ordered
    When "Uno" is tiered into tier 1
    Then 4 films are ordered and 1 remains to order

  Scenario: A stale order verdict is refused
    Then answering better against a film that is not the shown one is refused with 409

  Scenario: Pass in order mode defers the candidate to the back
    When I pass in order mode
    Then the deferred film comes last in the order queue

  Scenario: Undo reverts an order verdict, an insertion and a deferral, one level deep
    When I answer worse in order mode
    Then 2 films are ordered
    When I undo
    Then 1 film is ordered and the same candidate is asked with 0 verdicts
    And the undo returned the order state
    When I pass in order mode
    And I undo
    Then nothing is deferred in order mode
    And undoing again is refused with 409

  Scenario: One undo slot serves both modes
    When I answer worse in order mode
    And I answer better, better in tiering mode
    And I undo
    Then the tiering candidate is unplaced again
    And 2 films are ordered
    And the undo returned the tiering state
    And undoing again is refused with 409

  Scenario: Undoing a tier 1 placement also drops the film from the order
    Then the order is empty
    When "Uno" is tiered into tier 1
    Then 1 film is ordered
    When I undo
    Then 1 film is ordered
    And "Uno" is not in the order

  Scenario: A corrupt order log is skipped, not fatal
    Then 1 film is ordered and 3 remain to order
    When the current candidate's order log is made corrupt
    Then the corrupt film is skipped and the pair asks a different candidate
    And 1 film is corrupt and 2 remain to order
    And the order is not done
    When every remaining candidate's order log is made corrupt
    Then 3 films are corrupt and 0 remain to order
    And the order is not done

  Scenario: Marking an ordered film unseen from the drawer removes it and every verdict naming it
    When I answer worse in order mode
    And I answer worse in order mode until the candidate is inserted
    Then 3 films are ordered
    When I answer better in order mode
    And the film at position 2 is marked unseen from the drawer
    Then 2 films are ordered
    And the current candidate has 0 verdicts

  Scenario: Saving writes tier 1's order bare, the rest of tier 1 tied, and the other tiers as before
    When I answer worse in order mode
    And I save the list as "Mine"
    Then the list "my-owned-tiers" has 8 entries
    And entries 1 and 2 carry no label
    And entry 2 is the last inserted film
    And entries 3 and 4 carry label "=3"
    And entry 5 is "Nine" with no label

  Scenario: Tier 2 has its own order, queue, deferral and undo
    Then the tier 2 order has 1 film and 0 remaining
    When "Nine" is joined in tier 2 by "Nine-b" rated 9, not owned
    Then the tier 2 order has 1 film and 1 remaining
    When I answer worse in tier 2 order mode
    Then the tier 2 order has 2 films and 0 remaining
    And the tier 1 order still has 1 film and 3 remaining
    When I undo
    Then the undo returned the tier 2 order state
    And the tier 2 order has 1 film and 1 remaining
    When I pass in tier 2 order mode
    Then "Nine-b" is deferred in tier 2

  Scenario: Undo of an order click logged before tiers existed lands on tier 1
    When I answer worse in order mode
    And the stored undo action loses its tier, as an old row has
    And I undo
    Then the undo returned the tier 1 order state
    And 1 film is ordered and the same candidate is asked with 0 verdicts

  Scenario: An order tier outside 1 to 5 is refused
    Then reading the tier 6 order is refused with 400
    And reading the tier 0 order is refused with 400

  Scenario: Tier 5 has its own order, independent of tiers 1 and 2
    Then the tier 5 order has 1 film and 0 remaining
    When "Six" is joined in tier 5 by "Six-b" rated 6, not owned
    Then the tier 5 order has 1 film and 1 remaining
    When I answer worse in tier 5 order mode
    Then the tier 5 order has 2 films and 0 remaining
    And the tier 1 order still has 1 film and 3 remaining
    And the tier 2 order still has 1 film and 0 remaining

  Scenario: Saving writes both ordered tiers bare
    When I answer worse in order mode
    And "Nine" is joined in tier 2 by "Nine-b" rated 9, not owned
    And I answer worse in tier 2 order mode
    And I save the list as "Mine"
    Then entries 1 and 2 carry no label
    And entries 5 and 6 carry no label

  Scenario: Order state needs an open session
    Given the session is finished
    Then reading the order state is refused with 404
