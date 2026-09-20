Feature: Looking up each film's trailer ahead of time

  The drawer's "▶ Trailer" link plays what this verb stored; nothing is fetched when the
  drawer opens. TMDB files every video under a type, and only the ones it calls a trailer
  (or a teaser) are kept — a clip, a featurette or a critic's review is never a trailer.
  Apple's own store preview stands in behind them for a film that holds a store id. The
  verb is dry-run by default, stamps every film it looks up (even when it finds nothing),
  and never runs inside sync.

  Background:
    Given a film "Memories of Murder" (2003) holding tmdb id 11423 and store id "900000001"
    And TMDB files for tmdb id 11423 a "Featurette" "Mark Kermode reviews Memories of Murder" and a "Trailer" "MEMORIES OF MURDER Trailer"
    And Apple publishes a preview for store id "900000001"

  Scenario: A dry run looks everything up and writes nothing
    When I look up trailers without applying
    Then the trailer report counts 1 scanned and 1 with a YouTube trailer
    And the film "Memories of Murder" has no stored trailers

  Scenario: Applying stores the trailer first and Apple's preview behind it
    When I look up trailers with apply
    Then the film "Memories of Murder" plays "MEMORIES OF MURDER Trailer" from "youtube" first
    And the film "Memories of Murder" plays "Apple's store preview" from "apple" last
    And the film "Memories of Murder" never plays "Mark Kermode reviews Memories of Murder"

  Scenario: A film that was looked up is never asked about again
    Given trailers were already looked up
    When I look up trailers with apply
    Then the trailer report counts 0 scanned and 0 with a YouTube trailer
    And TMDB was asked for videos 1 time

  Scenario: Refreshing asks about every film again
    Given trailers were already looked up
    When I refresh trailers with apply
    Then the trailer report counts 1 scanned and 1 with a YouTube trailer

  Scenario: No trailer on TMDB, so Apple's preview is all the film has
    Given a film "To Die For" (1995) holding tmdb id 577 and store id "900000002"
    And TMDB files no videos for tmdb id 577
    And Apple publishes a preview for store id "900000002"
    When I look up trailers with apply
    Then the film "To Die For" plays "Apple's store preview" from "apple" first
    And the trailer report counts 1 Apple-only and 0 with nothing

  Scenario: No trailer anywhere is still a finished lookup
    Given a film "The Hitch-Hiker" (1953) holding tmdb id 41462 and no store id
    And TMDB files no videos for tmdb id 41462
    When I look up trailers with apply
    Then the film "The Hitch-Hiker" has no stored trailers
    And the trailer report counts 0 Apple-only and 1 with nothing
    And looking up trailers again scans 0 films

  Scenario: A foreign film with no English trailer is asked again in its own language
    Given a film "The Fire Within" (1963) holding tmdb id 1111 and no store id
    And TMDB files no English videos for the "fr" film with tmdb id 1111 but a "fr" "Trailer" "Le feu follet"
    When I look up trailers with apply
    Then the film "The Fire Within" plays "Le feu follet" from "youtube" first

  Scenario: An English teaser does not stand in the way of the film's own trailer
    Given a film "Kings of the Road" (1976) holding tmdb id 2222 and no store id
    And TMDB files for the "de" film with tmdb id 2222 an English "Teaser" "Teaser" and a "de" "Trailer" "Im Lauf der Zeit Trailer"
    When I look up trailers with apply
    Then the film "Kings of the Road" plays "Im Lauf der Zeit Trailer" from "youtube" first
    And the film "Kings of the Road" plays "Teaser" from "youtube" last

  Scenario: A TMDB id that no longer exists is a finished lookup, and Apple's preview still counts
    Given a film "Gone From TMDB" (1980) holding tmdb id 404404 and store id "900000004"
    And TMDB answers 404 for tmdb id 404404
    And Apple publishes a preview for store id "900000004"
    When I look up trailers with apply
    Then the film "Gone From TMDB" plays "Apple's store preview" from "apple" first
    And the trailer report counts 0 failed
    And looking up trailers again scans 0 films

  Scenario: A film with two store products takes the preview of the one Apple still sells
    Given a film "Two Products" (1990) holding tmdb id 3333 and store id "900000010"
    And the film "Two Products" also holds store id "900000020"
    And TMDB files no videos for tmdb id 3333
    And Apple publishes a preview for store id "900000020"
    When I look up trailers with apply
    Then the film "Two Products" plays "Apple's store preview" from "apple" first

  Scenario: A film TMDB cannot serve is left for the next run
    Given a film "Broken" (1990) holding tmdb id 666 and no store id
    And TMDB cannot serve tmdb id 666
    When I look up trailers with apply
    Then the trailer report counts 1 failed
    And looking up trailers again scans 1 films

  Scenario: Apple being down stops the run before anything is stamped
    Given Apple's lookup is down
    When I look up trailers with apply
    Then the trailer report is marked aborted
    And the film "Memories of Murder" has no stored trailers
    And looking up trailers again scans 1 films

  Scenario: Repeated TMDB failures stop the run so the next one can resume
    Given 9 more films holding tmdb ids that TMDB cannot serve
    When I look up trailers with apply
    Then the trailer report is marked aborted
    And the film "Memories of Murder" plays "MEMORIES OF MURDER Trailer" from "youtube" first
    And looking up trailers again scans 9 films
