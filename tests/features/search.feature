Feature: Resolving a search into an exact film-id set

  A fuzzy field is corrected to an exact value BEFORE the query runs, and the
  correction is always shown (spec D7). A quoted value is exact and never
  corrected. Freeform text ranks; fields narrow. An unknown field is a hint,
  not an error.

  Background:
    Given the search corpus of Alpha, Beta and Gamma

  Scenario: An exact field query returns the set, unranked
    When I search for "character: philip marlowe"
    Then the result ids are Alpha
    And the result is not ranked
    And there are no corrections

  Scenario: A misspelled actor is corrected visibly
    When I search for "actor: bogrt"
    Then the result ids are Alpha
    And the correction for "actor" reads bogrt → Humphrey Bogart

  Scenario: A quoted value is exact and is never corrected
    When I search for "actor: \"bogrt\""
    Then the result is empty
    And there are no corrections
    And there are no suggestions

  Scenario: A name too far from any person is refused with suggestions
    When I search for "actor: bogxrtq"
    Then the result is empty
    And the suggestions for "actor" include Humphrey Bogart

  Scenario: A director field never matches an actor of the same name
    When I search for "director: humphrey bogart"
    Then the result is empty

  Scenario: Fields AND and freeform ranks within them
    When I search for "alpha director: hawks"
    Then the result ids are Alpha then Beta
    And the result is ranked

  Scenario: An unknown field is searched as text, with a hint saying so
    When I search for "foo: gamma"
    Then the result is empty
    And the hints include "unknown field 'foo'"
    And the result is not ranked

  Scenario: Genre matches the OMDb spelling however it is typed
    When I search for "genre: film noir"
    Then the result ids are Alpha

  Scenario: A keyword typo is corrected against the keyword vocabulary
    When I search for "keyword: hospitl"
    Then the result ids are Beta
    And the correction for "keyword" reads hospitl → hospital

  Scenario: A year range narrows
    When I search for "year: 1940-1949"
    Then the result ids are Alpha

  Scenario: A people field on a catalogue with no credits explains itself
    Given a catalogue with no credits at all
    When I search for "actor: anyone"
    Then the result is empty
    And the hints include "no credits loaded — run `movie-brain enrich credits --apply`"

  Scenario: The same field twice is ORed, even for a year range
    When I search for "year: 1946 year: 1950"
    Then the result ids are Alpha then Beta

  Scenario: One unresolvable value does not empty an OR group
    When I search for "actor: humphrey bogart actor: bacalllzz"
    Then the result ids are Alpha
    And there are no corrections

  Scenario: A too-short fuzzy value explains itself instead of failing silently
    When I search for "character: xy"
    Then the result is empty
    And the hints include "'xy' is too short to correct — try three characters or more"

  Scenario: An unmatched multi-word freeform query explains itself instead of failing silently
    When I search for "purple elephant parade"
    Then the result is empty
    And the hints include "no film matches all 3 words — try fewer, or quote a phrase"

  Scenario: A field that emptied the result is not blamed on the freeform words
    When I search for "private eye actor: bacalllzz"
    Then the result is empty
    And the hints do not include "no film matches all 2 words — try fewer, or quote a phrase"
