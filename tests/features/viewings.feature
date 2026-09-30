Feature: Viewings — one dictation becomes one deterministic write against the right film

  Background:
    Given today is 2026-09-27
    And the registry knows "Kino Film Collection" and "Criterion Channel"
    And a film "The Blue Angel" (1930)
    And a film "Solaris" (1972) directed by "Andrei Tarkovsky"
    And a film "Solaris" (2002) directed by "Steven Soderbergh"
    And a film "Pandora’s Box" (1929)
    And a film "Godzilla vs. Gigan" (1972)
    And a film "Godzilla" (1954)
    And a merged-away twin "Godzilla" (1954)
    And a film "M" (1931)

  Scenario: The open film wins when it carries the dictated title
    Given the drawer reported "Solaris" (1972) 30 seconds ago
    When I log "Solaris" on "criterion" saying "tonight"
    Then the outcome is "logged" for "Solaris" (1972) matched "matched the open film"
    And the film "Solaris" (1972) has 1 viewing on 2026-09-27 with service "criterion"

  Scenario: A stale drawer report is ignored and the same title asks
    Given the drawer reported "Solaris" (1972) 200 seconds ago
    When I log "Solaris" saying "tonight"
    Then the outcome is "ambiguous" with exit 3 listing "Solaris (1972)" and "Solaris (2002)"
    And nothing was written

  Scenario: The open film is skipped when the dictation names another year
    Given the drawer reported "Solaris" (1972) 30 seconds ago
    When I log "Solaris" year 2002 saying "the remake"
    Then the outcome is "logged" for "Solaris" (2002) matched "the one film with that title"

  Scenario: A fresh report on a differently titled film falls to rung 2
    Given the drawer reported "The Blue Angel" (1930) 30 seconds ago
    When I log "Solaris" year 1972 saying "the drawer shows another film"
    Then the outcome is "logged" for "Solaris" (1972) matched "the one film with that title"

  Scenario: A year inside the dictated title is not ignored
    When I log "Solaris (1972)" saying "year in the title"
    Then the outcome is "logged" for "Solaris" (1972) matched "the one film with that title"

  Scenario: Exactly one film with the title logs without a question
    When I log "The Blue Angel" on "kino-film-collection" rating 6 saying "about a six"
    Then the outcome is "logged" for "The Blue Angel" (1930) matched "the one film with that title"
    And the film "The Blue Angel" (1930) is rated 6

  Scenario: Apostrophes, case and accents do not matter
    When I log "pandora's box" saying "silent"
    Then the outcome is "logged" for "Pandora’s Box" (1929) matched "the one film with that title"

  Scenario: A bracketed edition in the dictated title is stripped before matching
    When I log "The Blue Angel (Restored)" saying "edition in the title"
    Then the outcome is "logged" for "The Blue Angel" (1930) matched "the one film with that title"

  Scenario: A merged-away twin is never a candidate
    When I log "Godzilla" saying "the original"
    Then the outcome is "logged" for "Godzilla" (1954) matched "the one film with that title"

  Scenario: A near-miss title lists the nearest films and writes nothing
    When I log "Blue Angel" saying "dropped the article"
    Then the outcome is "no-film" with exit 3 listing "The Blue Angel (1930)"
    And nothing was written

  Scenario: "versus" for "vs." still finds the film among the nearest
    When I log "Godzilla versus Gigan" saying "dictation writes versus"
    Then the outcome is "no-film" with exit 3 listing "Godzilla vs. Gigan (1972)"

  Scenario: A title of only stop words is no-film with no nearest list and no crash
    When I log "The" saying "nothing to go on"
    Then the outcome is "no-film" with exit 3 listing nothing

  Scenario: An unknown title with nothing close is no-film
    When I log "Mädchen in Uniform" saying "on a Blu-ray"
    Then the outcome is "no-film" with exit 3 listing nothing
    And nothing was written

  Scenario: A film id skips the ladder
    When I log film "Solaris" (2002) saying "by id"
    Then the outcome is "logged" for "Solaris" (2002) matched "by id"

  Scenario: A film id naming a merged-away or unknown film is refused
    When I log the merged twin of "Godzilla" (1954) saying "ghost"
    Then the outcome is "refused" with exit 2
    When I log film id 999999 saying "nobody"
    Then the outcome is "refused" with exit 2
    And nothing was written

  Scenario: --title and --film must agree
    When I log film "Solaris" (2002) titled "Godzilla vs. Hedorah" saying "mismatch"
    Then the outcome is "refused" with exit 2
    And nothing was written

  Scenario: The same film the same day appends a note and moves the rating
    When I log "The Blue Angel" on "kino-film-collection" rating 6 saying "first"
    And I log "The Blue Angel" on "criterion" rating 7 saying "second"
    Then the outcome is "added-to" with 2 notes
    And the film "The Blue Angel" (1930) has 1 viewing on 2026-09-27 with service "kino-film-collection"
    And the film "The Blue Angel" (1930) is rated 7

  Scenario: A dropped second service is named in the ADDED-TO line
    When I log "The Blue Angel" on "kino-film-collection" saying "first"
    And I log "The Blue Angel" on "criterion" saying "second"
    Then the outcome is "added-to" naming "service kept: kino-film-collection (criterion noted)"
    And the film "The Blue Angel" (1930) has 1 viewing on 2026-09-27 with service "kino-film-collection"

  Scenario: Another date is another viewing
    When I log "The Blue Angel" on 2026-09-21 saying "monday"
    And I log "The Blue Angel" saying "today"
    Then the film "The Blue Angel" (1930) has 2 viewings

  Scenario: Logging clears an Unseen mark and touches nothing else
    Given "Godzilla vs. Gigan" (1972) is marked unseen and on the watchlist
    When I log "Godzilla vs. Gigan" saying "watched it"
    Then "Godzilla vs. Gigan" (1972) is not unseen and is still on the watchlist

  Scenario Outline: Refusals write nothing
    When I log "The Blue Angel" <how>
    Then the outcome is "refused" with exit 2
    And nothing was written

    Examples:
      | how                                        |
      | on "not-a-real-service" saying "bad slug" |
      | on 2027-01-01 saying "future"              |
      | rating 11 saying "too high"                |
      | saying "   "                               |

  Scenario: Remove takes the whole viewing; remove a note takes one
    When I log "The Blue Angel" rating 6 saying "one"
    And I log "The Blue Angel" saying "two"
    And I log "The Blue Angel" saying "three"
    And I remove note 2 of the last viewing
    Then the outcome is "removed" with exit 0
    And the last viewing of "The Blue Angel" (1930) has notes "one" and "three"
    When I remove the last viewing
    Then the film "The Blue Angel" (1930) has 0 viewings
    And the film "The Blue Angel" (1930) is rated 6
    When I remove note 1 of viewing 999
    Then the outcome is "refused" with exit 2

  Scenario: A note number out of range says how many notes the line has
    When I log "The Blue Angel" saying "one"
    And I log "The Blue Angel" saying "two"
    And I remove note 9 of the last viewing
    Then the outcome is "refused" with exit 2 naming "has 2 notes, no note 9"

  Scenario: The listing and the open line
    Given the drawer reported "Solaris" (1972) 30 seconds ago
    When I log "The Blue Angel" on 2026-09-21 on "kino-film-collection" rating 6 saying "monday"
    Then the listing since 2026-09-01 reads "2026-09-21" then "The Blue Angel (1930)" then "kino-film-collection" then "1 note" then "rated 6"
    And the open line names "Solaris" (1972)
    Given the drawer reported nothing
    Then the open line says nothing is open

  Scenario: A listing filtered to one film numbers its notes
    When I log "The Blue Angel" saying "first remark"
    And I log "The Blue Angel" saying "second remark"
    Then the film listing for "The Blue Angel" (1930) shows note 1 "first remark" and note 2 "second remark"

  Scenario: A missing films.director falls back to the credits director in an AMBIGUOUS list
    Given a film "Nowhere" (1997) with credits director "Gregg Araki" but no stored director
    And a film "Nowhere" (2015) directed by "Someone Else"
    When I log "Nowhere" saying "which one"
    Then the outcome is "ambiguous" with exit 3 listing "Gregg Araki" and "Someone Else"

  Scenario: A viewing with no note is a date and nothing else
    Given a film "Seven Chances" (1925)
    When I mark "Seven Chances" watched on 2026-09-27 with no note
    Then the outcome is "logged" for "Seven Chances" (1925) matched "the one film with that title"
    And the last viewing of "Seven Chances" (1925) has no notes
    When I mark "Seven Chances" watched on 2026-09-27 with no note
    Then the outcome says the line already existed and nothing new was added

  # ---- the study mark (backlog 48): one mark on a viewing, set from the sentence or by number ----

  Scenario: Story 2 — a dictation that names a reason to go back marks the line it logs
    When I log "The Blue Angel" on "kino-film-collection" rating 7 for study saying "the tramline sequence — I need to watch that again"
    Then the outcome is "logged" naming "· rated 7 · study"
    And the last viewing is marked for study

  Scenario: Story 9 — the flag on a same-day or --on sentence marks the existing line and appends the note
    When I log "The Blue Angel" saying "first words"
    And I log "The Blue Angel" for study saying "mark it — the cuts land on the seams"
    Then the outcome is "added-to" naming "· note 2 · study"
    And the last viewing is marked for study

  Scenario: Story 7 — a past line is marked or cleared by its number
    When I log "The Blue Angel" on 2026-09-23 saying "the shot construction"
    And I mark the last viewing for study
    Then the outcome is "study" naming "· marked for study"
    And the last viewing is marked for study

  Scenario: Story 8 — marking a marked line, or clearing a clear one, changes nothing
    When I log "The Blue Angel" for study saying "marked"
    And I mark the last viewing for study
    Then the outcome is "study" naming "· already marked"
    And nothing was written
    When I clear the study mark on the last viewing
    Then the outcome is "study" naming "· mark cleared"
    And the last viewing is not marked for study
    When I clear the study mark on the last viewing
    Then the outcome is "study" naming "· already clear"

  Scenario: Story 8 — a number that is not a line is refused
    When I mark viewing 40 for study
    Then the outcome is "refused" with exit 2 naming "no viewing #40"
    And nothing was written

  Scenario: Story 4 — the listing shows the mark and can keep only marked rows
    When I log "The Blue Angel" on 2026-09-23 on "kino-film-collection" for study saying "general"
    And I log "Solaris (1972)" saying "plain"
    Then the listing shows "2026-09-23  #" with "kino-film-collection  study  1 note"
    And the study-only listing names "The Blue Angel" and not "Solaris"

  Scenario: Story 4 — the study-only listing says so when nothing is marked
    When I log "The Blue Angel" saying "plain"
    Then the study-only listing reads "no viewing marked for study"

  Scenario: Story 11 — removing a viewing takes its mark with it
    When I log "The Blue Angel" for study saying "marked"
    And I remove the last viewing
    Then the study-only listing reads "no viewing marked for study"

  Scenario: With --film every row names its viewing number, so a mark or a removal can read it
    When I log "The Blue Angel" on 2026-09-23 saying "general"
    And I log "The Blue Angel" saying "tonight"
    Then the film listing for "The Blue Angel" (1930) shows "viewing #1" and "viewing #2"
    And the plain listing shows no "viewing #"

  Scenario: A reason sentence landing on an already-marked line says so instead of claiming the mark
    When I log "The Blue Angel" for study saying "first reason"
    And I log "The Blue Angel" for study saying "second reason"
    Then the outcome is "added-to" naming "· note 2 · already marked"
    And the last viewing is marked for study

  Scenario: Story 11 — scratching the reason note leaves the mark; removing the line takes it
    When I log "The Blue Angel" on 2026-09-23 saying "the night"
    And I log "The Blue Angel" on 2026-09-23 for study saying "the reason"
    And I remove note 2 of the last viewing
    Then the last viewing is marked for study
    When I remove the last viewing
    Then the study-only listing reads "no viewing marked for study"
