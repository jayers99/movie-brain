Feature: Tier ranker — place owned films into five tiers against anchors

  Background:
    Given owned films rated "Ten" 10, "Nine" 9, "Eight" 8, "Seven" 7, "Six" 6
    And owned unrated films "Uno", "Dos", "Tres"

  Scenario: The proposal names one seeded anchor per tier
    Then the proposal is Ten, Nine, Eight, Seven, Six

  Scenario: An emptied seed tier's fallback offers only the unrated films
    Given "Seven" is re-rated 8
    Then tier 4's choices are only the unrated films

  Scenario: A seeded film may only anchor its own tier
    When I start a session anchoring tier 4 with "Ten"
    Then starting is refused with 400

  Scenario: Two tiers cannot share the same anchor
    When I start a session anchoring tiers 4 and 5 both with "Uno"
    Then starting is refused with 400

  Scenario: Starting seeds the rated films and asks the first candidate against tier 3
    When I start a session with the proposed anchors
    Then the tally is 1, 1, 1, 1, 1
    And the pair asks the candidate against tier 3 "Eight"
    And 3 films remain

  Scenario Outline: Every verdict path lands in the tier the table says
    Given a started session
    When I answer <verdicts>
    Then the current candidate was placed in tier <tier>
    And the next candidate is asked against tier 3

    Examples:
      | verdicts              | tier |
      | better, better        | 1    |
      | better, worse         | 2    |
      | worse, better         | 3    |
      | worse, worse, better  | 4    |
      | worse, worse, worse   | 5    |

  Scenario: A stale verdict is refused
    Given a started session
    When I answer better
    Then answering "worse" against tier 3 is refused with 409

  Scenario: Pass with nothing marked defers the candidate to the back
    Given a started session
    When I pass with nothing marked
    Then the deferred film comes last in the queue
    And 3 films remain

  Scenario: Pass with the candidate marked sends it to the unseen bucket
    Given a started session
    When I pass with the candidate marked unseen
    Then that film is unseen
    And 2 films remain

  Scenario: Pass with the anchor marked empties the tier and asks for a new anchor
    Given a started session
    When I pass with the anchor marked unseen
    Then "Eight" is unseen
    And the session needs an anchor for tier 3
    And there is no pair
    When I swap tier 3's anchor to "Uno"
    Then the tally is 1, 1, 1, 1, 1
    And the pair asks the candidate against tier 3 "Uno"

  Scenario: A swap across tiers is refused
    Given a started session
    Then swapping tier 3's anchor to "Ten" is refused with 409

  Scenario: Undo reverts a placement, a deferral and a candidate-unseen, one level deep
    Given a started session
    When I answer better, better
    And I undo
    Then the current candidate has 1 verdict and is unplaced
    When I pass with nothing marked
    And I undo
    Then nothing is deferred
    When I pass with the candidate marked unseen
    And I undo
    Then nothing is unseen
    And undoing again is refused with 409

  Scenario: Saving writes a tied-rank list and re-saving replaces it
    Given a started session
    When I answer better, better
    And I save the list as "Mine"
    Then the list "my-owned-tiers" has 6 entries
    And its tier 1 entries carry label "=1"
    And its tier 5 entry carries no label
    When I answer worse, worse, worse
    And I save the list as "Mine"
    Then the list "my-owned-tiers" has 7 entries

  Scenario: A re-save with the name box left empty keeps the name I gave the list
    Given a started session
    When I answer better, better
    And I save the list as "Mine"
    And I save the list with no name
    Then the list "my-owned-tiers" is named "Mine"

  Scenario: A first save with no name takes the default name
    Given a started session
    When I answer better, better
    And I save the list with no name
    Then the list "my-owned-tiers" is named "My Ranking"

  Scenario: Saving refuses a slug a list file owns
    Given a started session
    And a list file "my-owned-tiers.tsv" exists
    Then saving is refused with 409

  Scenario: Reopening resumes the same pair
    Given a started session
    When I answer worse
    Then reopening the session shows the same candidate asked against tier 4

  Scenario: Marking a placed film unseen from the drawer drops its placement
    Given a started session
    When I answer better, better
    And that film is marked unseen from the drawer
    Then the tally is 1, 1, 1, 1, 1

  Scenario: A placement interrupted before it was written is completed on the next read
    Given a started session
    When the current candidate's verdicts are logged directly as "better, better"
    Then the tally is 2, 1, 1, 1, 1
    And the next candidate is asked against tier 3

  Scenario: An anchor marked unseen from the drawer stops serving pairs until swapped
    Given a started session
    When "Eight" is marked unseen from the drawer
    Then the session needs an anchor for tier 3
    And there is no pair

  Scenario: A corrupt verdict log is skipped, not fatal
    Given a started session
    When the current candidate's log is forced illegal with four "worse" verdicts
    Then the state lists that film as corrupt
    And the next candidate is asked against tier 3

  Scenario: Undo after a drawer unmark purged the comparison is a harmless no-op
    Given a started session
    When I answer better
    And that film is marked unseen from the drawer
    And I undo
    Then that film is unseen
    And undo is no longer available
