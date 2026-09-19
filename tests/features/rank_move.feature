Feature: Move a film to another tier — a hand-set tier from the drawer, ordered afterwards by comparison

  Background:
    Given owned films rated "Alpha" 10, "Beta" 10, "Gamma" 10, "Delta" 10, "Nine" 9, "Eight" 8, "Seven" 7, "Six" 6
    And an owned unrated film "Uno"
    And a started tiering session

  Scenario: A moved film sets its tier by hand, leaves its old order and waits unordered in the new tier
    When I answer worse in order mode until the candidate is inserted
    Then 2 films are ordered and 2 remain to order
    When the film at position 2 is moved to tier 2 from the drawer
    Then the moved film is placed in tier 2 as "moved"
    And the move reported from tier 1 and awaiting order
    And 1 film is ordered and 2 remain to order
    And the tier 2 order has 1 film and 1 remaining
    And the moved film is the tier 2 order candidate
    And the next reads do not re-seed the moved film

  Scenario: Moving into tier 3 awaits its order like every other tier
    When "Nine" is joined in tier 2 by "Nine-b" rated 9, not owned
    And "Nine-b" is moved to tier 3 from the drawer
    Then the move reported from tier 2 and awaiting order
    And rank status for "Nine-b" is tier 3 "moved" and awaiting order
    When the tier 3 order is read
    And I answer worse in tier 3 order mode
    Then rank status for "Nine-b" is tier 3 "moved" and not awaiting order

  Scenario: A move invalidates the one-level undo
    When "Uno" is tiered into tier 1
    Then undo is available
    When "Uno" is moved to tier 2 from the drawer
    Then undo is not available
    And undoing is refused with 409
    And the next reads do not re-seed the moved film

  Scenario: A move refuses a bad tier, an unplaced film, an anchor and the same tier
    When "Nine" is joined in tier 2 by "Nine-b" rated 9, not owned
    Then moving "Nine-b" to tier 6 is refused with 400 "tier must be"
    And moving "Uno" to tier 2 is refused with 409 "not placed"
    And moving the tier 1 anchor to tier 2 is refused with 409 "swap the anchor first"
    And moving "Nine" to tier 3 is refused with 409 "swap the anchor first"
    And moving "Nine-b" to tier 2 is refused with 409 "already in tier 2"

  Scenario: The order pair whose candidate was moved is no longer current
    When the tier 1 order candidate is moved to tier 3 from the drawer
    Then answering the old order pair is refused with 409
    And the tier 1 order has 1 film and 2 remaining

  Scenario: Rank status reads the order's own state and never seeds or inserts
    Then rank status for "Uno" reports no tier
    And rank status for "Nine" is tier 2 "seed" and awaiting order
    When the tier 2 order is read
    Then rank status for "Nine" is tier 2 "seed" and not awaiting order

  Scenario: Re-ranking a placed film unplaces it, sets the mark, and the Tiers tab asks it again instead of re-seeding
    When I answer worse in order mode until the candidate is inserted
    And the film at position 2 is re-ranked from the drawer
    Then the re-ranked film is not placed and is marked
    And the re-rank reported from tier 1
    And undo is not available
    And the next reads do not re-seed the re-ranked film
    And the re-ranked film is in the tiering queue

  Scenario: The mark comes off once the re-ranked film is placed and ordered
    When "Nine" is joined in tier 2 by "Nine-b" rated 9, not owned
    And "Nine-b" is re-ranked from the drawer
    And "Nine-b" is answered worse than every anchor
    Then "Nine-b" is placed in tier 5 and still marked
    When the tier 5 order is read
    And I answer worse in tier 5 order mode
    Then "Nine-b" is placed in tier 5 and its mark is gone
    When "Uno" is tiered into tier 1
    And "Uno" is re-ranked from the drawer
    And "Uno" is tiered into tier 1
    Then "Uno" is placed in tier 1 and still marked
    When "Uno" is inserted into the tier 1 order
    Then "Uno" is placed in tier 1 and its mark is gone

  Scenario: A re-rank refuses an unplaced film and an anchor
    Then re-ranking "Uno" is refused with 409 "not placed"
    And re-ranking "Nine" is refused with 409 "swap the anchor first"
