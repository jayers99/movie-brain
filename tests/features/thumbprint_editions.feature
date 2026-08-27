Feature: Thumbprint T2 — edition-year films fold into their work

  # No Background on purpose: these scenarios build their own films, and the T1 feature's
  # Background ("Blade Runner" (1982) + an owned "Blade Runner (The Final Cut)") would hold
  # the very keys the no-twin scenarios key with.

  Scenario: an edition-year film with a clean twin merges into the work and keeps its edition year on the claim
    Given an edition film "Eyes Without a Face [re-release]" year 2003 from "metacritic" slug "eyes-without-a-face-re-release"
    And a work film "Eyes Without a Face" (1960) with tmdb id "31417"
    And the edition contract says the work is "Eyes Without a Face" 1960 tt "tt0053459" tmdb "31417"
    When I run repair editions --apply answering yes
    Then the edition film is merged into the work film
    And the work film holds imdb "tt0053459" and its metacritic claim has edition_year 2003
    And the editions report says twin 1, no-twin 0, conflict 0, csv-mismatch 0, applied 1

  Scenario: a same-title film with the wrong tmdb id is not a twin (Overlord 2018)
    Given an edition film "Overlord [re-release]" year 2006 from "metacritic" slug "overlord-re-release"
    And a work film "Overlord" (2018) with tmdb id "438799"
    And a work film "Overlord" (1975) with tmdb id "55343"
    And the edition contract says the work is "Overlord" 1975 tt "tt0073502" tmdb "55343"
    When I run repair editions --apply answering yes
    Then the edition film is merged into the work film "Overlord" (1975)

  Scenario: an edition-year film without a twin becomes the work
    Given an edition film "Blade Runner (The Final Cut)" year 2007 from "apple-tv" slug "Blade Runner (The Final Cut)"
    And the edition contract says the work is "Blade Runner" 1982 tt "tt0083658" tmdb "78"
    And the edition film has an open tmdb no-match review
    When I run repair editions --apply answering yes
    Then the edition film is titled "Blade Runner" year 1982 with imdb "tt0083658" and tmdb "78" and no disposition
    And its apple-tv claim has edition_year 2007
    And its tmdb no-match review is resolved

  Scenario: two editions of one work — the loser merges and the survivor is keyed as the work
    Given an edition film "Donnie Darko: The Director's Cut" year 2004 from "metacritic" slug "donnie-darko-the-directors-cut"
    And an edition film "Donnie Darko: Anniversary Special Edition" year 2001 from "apple-tv" slug "Donnie Darko: Anniversary Special Edition"
    And the edition contract says the work is "Donnie Darko" 2001 tt "tt0246578" tmdb "141" for both
    When I run repair editions --apply answering yes
    Then the film "Donnie Darko: The Director's Cut" is merged into the film now titled "Donnie Darko" (2001) holding tmdb "141"
    And the editions report says twin 1, no-twin 0, conflict 0, csv-mismatch 0, applied 1

  Scenario: an old year before the work year is not an edition year (Scenes from a Marriage)
    Given an edition film "SCENES FROM A MARRIAGE: Theatrical Version" year 1973 from "criterion" slug "https://c/sfam-theatrical"
    And the edition contract says the work is "Scenes from a Marriage" 1974 tt "tt6725014" tmdb "133919"
    When I run repair editions --apply answering yes
    Then the edition film is titled "Scenes from a Marriage" year 1974 with imdb "tt6725014" and tmdb "133919" and no disposition
    And its criterion claim has no edition_year

  Scenario: the target key is held by another live film → conflict, nothing written
    Given an edition film "Phantasm: Remastered" year 2016 from "apple-tv" slug "Phantasm: Remastered"
    And a work film "Phantasm" (1979) with tmdb id "1"
    And the edition contract says the work is "Phantasm" 1979 tt "tt0079714" tmdb "9638"
    When I run repair editions --apply answering yes
    Then the edition film's verdict is "conflict" and it has no disposition and year 2016

  Scenario: a film Criterion still lists is never re-keyed → conflict, nothing written
    Given an edition film "SCENES FROM A MARRIAGE: Theatrical Version" year 1973 from "criterion" slug "https://c/sfam-theatrical"
    And the edition film has a criterion listing
    And the edition contract says the work is "Scenes from a Marriage" 1974 tt "tt6725014" tmdb "133919"
    When I run repair editions --apply answering yes
    Then the edition film's verdict is "conflict" and it has no disposition and year 1973
    And the edition film is still titled "SCENES FROM A MARRIAGE: Theatrical Version" and holds no imdb id
    And the editions report says twin 0, no-twin 0, conflict 1, csv-mismatch 0, applied 0

  Scenario: a second apply is a no-op
    Given an edition film "Blade Runner (The Final Cut)" year 2007 from "apple-tv" slug "Blade Runner (The Final Cut)"
    And the edition contract says the work is "Blade Runner" 1982 tt "tt0083658" tmdb "78"
    When I run repair editions --apply answering yes
    And I run repair editions --apply answering yes
    Then the editions report says twin 0, no-twin 0, conflict 0, csv-mismatch 0, applied 0

  Scenario: a same-year edition with a clean twin merges and records no edition year
    Given an edition film "Apocalypse Now (Final Cut)" year 1979 from "apple-tv" slug "Apocalypse Now (Final Cut)"
    And a work film "Apocalypse Now" (1979) with tmdb id "28"
    And the edition contract says the work is "Apocalypse Now" 1979 tt "tt0078788" tmdb "28"
    When I run repair editions --apply answering yes
    Then the edition film is merged into the work film
    And the work film's apple-tv claim has edition_label "final cut" and no edition_year
    And the editions report says twin 1, no-twin 0, conflict 0, csv-mismatch 0, applied 1

  Scenario: a same-year edition without a twin becomes the work
    Given an edition film "Paul (Unrated) [2011]" year 2011 from "apple-tv" slug "Paul (Unrated) [2011]"
    And the edition contract says the work is "Paul" 2011 tt "tt1092026" tmdb "39513"
    When I run repair editions --apply answering yes
    Then the edition film is titled "Paul" year 2011 with imdb "tt1092026" and tmdb "39513" and no disposition
    And its apple-tv claim has no edition_year
    And the editions report says twin 0, no-twin 1, conflict 0, csv-mismatch 0, applied 1

  Scenario: a second apply over a same-year edition is a no-op
    Given an edition film "Paul (Unrated) [2011]" year 2011 from "apple-tv" slug "Paul (Unrated) [2011]"
    And the edition contract says the work is "Paul" 2011 tt "tt1092026" tmdb "39513"
    When I run repair editions --apply answering yes
    And I run repair editions --apply answering yes
    Then the editions report says twin 0, no-twin 0, conflict 0, csv-mismatch 0, applied 0

  Scenario: two editions and the real work — one apply folds both, the unkeyed fellow is not a rival
    Given an edition film "Apocalypse Now Redux" year 2001 from "apple-tv" slug "Apocalypse Now Redux"
    And a work film "Apocalypse Now" (1979) with tmdb id "28"
    And an edition film "Apocalypse Now (Final Cut)" year 1979 from "apple-tv" slug "Apocalypse Now (Final Cut)"
    And the edition contract says the work is "Apocalypse Now" 1979 tt "tt0078788" tmdb "28" for both
    When I run repair editions --apply answering yes
    Then both edition films are merged into the work film
    And the editions report says twin 2, no-twin 0, conflict 0, csv-mismatch 0, applied 2

  Scenario: a same-year row whose title carries no edition marker already IS the work and is not listed
    Given an edition film "Donnie Darko" year 2001 from "apple-tv" slug "Donnie Darko"
    And the edition contract says the work is "Donnie Darko" 2001 tt "tt0246578" tmdb "141"
    When I run repair editions --apply answering yes
    Then the editions report says twin 0, no-twin 0, conflict 0, csv-mismatch 0, applied 0

  Scenario: a same-year edition Criterion still lists is never re-keyed → conflict, nothing written
    Given an edition film "FANNY AND ALEXANDER: Theatrical Version" year 1982 from "criterion" slug "https://c/fanny-theatrical"
    And the edition film has a criterion listing
    And the edition contract says the work is "Fanny and Alexander" 1982 tt "tt0083922" tmdb "5961"
    When I run repair editions --apply answering yes
    Then the edition film's verdict is "conflict" and it has no disposition and year 1982
    And the edition film is still titled "FANNY AND ALEXANDER: Theatrical Version" and holds no imdb id
    And the editions report says twin 0, no-twin 0, conflict 1, csv-mismatch 0, applied 0

  Scenario: a same-title same-year film with the wrong tmdb id blocks rather than merges
    Given an edition film "Overlord [re-release]" year 2006 from "metacritic" slug "overlord-re-release"
    And a work film "Overlord" (1975) with tmdb id "438799"
    And the edition contract says the work is "Overlord" 1975 tt "tt0073502" tmdb "55343"
    When I run repair editions --apply answering yes
    Then the edition film's verdict is "conflict" and it has no disposition and year 2006
    And the editions report says twin 0, no-twin 0, conflict 1, csv-mismatch 0, applied 0
