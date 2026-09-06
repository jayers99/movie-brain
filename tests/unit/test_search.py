from movie_brain.domain.search import (
    ALIASES,
    FIELDS,
    ParsedQuery,
    Term,
    fts_words,
    norm_genre,
    parse_query,
    parse_year_range,
    trigram_query,
)


def test_trigram_query_ors_every_window_of_three_lowercased():
    assert trigram_query("Bogrt") == '"bog" OR "ogr" OR "grt"'


def test_trigram_query_is_empty_below_three_characters():
    """FTS5's trigram tokenizer cannot match a term shorter than three characters,
    so a caller must treat '' as 'nothing to look up', never send it as MATCH."""
    assert trigram_query("bo") == ""
    assert trigram_query("") == ""


def test_trigram_query_escapes_embedded_double_quotes():
    """Each window is a double-quoted FTS5 string, and FTS5 escapes a quote by doubling it.
    'a"bc' has two windows: a"b and "bc."""
    expected = '"a""b" OR """bc"'
    assert trigram_query('a"bc') == expected


def test_freeform_only():
    assert parse_query("film noir") == ParsedQuery(terms=(), free="film noir", hints=())


def test_field_value_runs_to_end_of_input():
    assert parse_query("genre: film noir").terms == (Term("genre", "film noir", False),)


def test_field_value_runs_to_the_next_field_token():
    q = parse_query("actor: bogart genre: film noir")
    assert q.terms == (Term("actor", "bogart", False), Term("genre", "film noir", False))
    assert q.free == ""


def test_freeform_before_the_first_field_is_kept():
    q = parse_query("hard boiled private eye genre: film noir")
    assert q.free == "hard boiled private eye" and q.terms == (Term("genre", "film noir", False),)


def test_quotes_group_a_value_and_mark_it_exact():
    q = parse_query('actor: "Bogart" title: brazil')
    assert q.terms == (Term("actor", "Bogart", True), Term("title", "brazil", False))


def test_quoted_text_containing_a_field_token_is_freeform_not_a_field():
    q = parse_query('"crew: catering" title: brazil')
    assert q.free == "crew: catering" and q.terms == (Term("title", "brazil", False),)


def test_aliases_resolve_to_the_canonical_field():
    q = parse_query("cast: bacall role: vivian dp: hickox kw: whodunit")
    assert [t.field for t in q.terms] == ["actor", "character", "cinematographer", "keyword"]


def test_field_names_are_case_insensitive_and_colon_may_hug_the_value():
    assert parse_query("Director:hawks").terms == (Term("director", "hawks", False),)


def test_unknown_field_becomes_freeform_with_a_hint():
    q = parse_query("foo: bar actor: bogart")
    assert q.free == "foo: bar" and q.terms == (Term("actor", "bogart", False),)
    assert q.hints == ("unknown field 'foo'",)


def test_empty_value_becomes_freeform_with_a_hint():
    q = parse_query("actor:")
    assert q.terms == () and q.free == "actor:" and q.hints == ("field 'actor' has no value",)


def test_repeated_field_yields_two_terms():
    q = parse_query("actor: bogart actor: bacall")
    assert q.terms == (Term("actor", "bogart", False), Term("actor", "bacall", False))


def test_a_url_in_freeform_is_not_a_field():
    """'https:' would otherwise parse as a field named https."""
    q = parse_query("see https://example.com")
    assert q.terms == () and q.free == "see https://example.com" and q.hints == ("unknown field 'https'",)


def test_year_ranges():
    assert parse_year_range("1946") == (1946, 1946)
    assert parse_year_range("1940-1949") == (1940, 1949)
    assert parse_year_range("1940-") == (1940, None)
    assert parse_year_range("-1949") == (None, 1949)
    assert parse_year_range("nineteen") is None
    assert parse_year_range("1950-1940") is None  # inverted


def test_norm_genre_makes_omdb_tmdb_and_typed_forms_equal():
    assert norm_genre("Film-Noir") == norm_genre("film noir") == norm_genre("FILM NOIR") == "filmnoir"
    assert norm_genre("Sci-Fi") == "scifi" and norm_genre("Science Fiction") == "sciencefiction"


def test_fts_words_quotes_each_word_and_drops_short_ones_when_asked():
    assert fts_words('hard "boiled" eye') == '"hard" "boiled" "eye"'
    assert fts_words("a to bogart", min_len=3) == '"bogart"'
    assert fts_words("", min_len=3) == ""


def test_every_field_has_a_kind_and_every_alias_points_at_a_field():
    assert set(ALIASES.values()) <= set(FIELDS)
    assert {f.kind for f in FIELDS.values()} <= {"person", "character", "title", "genre", "keyword", "year", "text"}
    assert FIELDS["writer"].jobs == (
        "Screenplay", "Writer", "Story", "Novel", "Original Story", "Dialogue", "Adaptation", "Author", "Book",
        "Short Story", "Theatre Play", "Scenario Writer", "Co-Writer", "Screenstory", "Original Film Writer",
    )
    assert FIELDS["actor"].credit_kind == "cast" and FIELDS["crew"].credit_kind == "crew" and FIELDS["crew"].jobs == ()


def test_abutting_tokens_are_kept_verbatim_in_freeform():
    for s in ("a:b:c", "foo:bar", "mailto:x@y.z", "see https://example.com"):
        q = parse_query(s)
        assert q.free == s and q.terms == (), s


def test_abutting_tokens_are_kept_verbatim_inside_a_field_value():
    q = parse_query("title: 2001:a space odyssey")
    assert q.terms == (Term("title", "2001:a space odyssey", False),)


def test_unknown_field_inside_a_value_is_absorbed_and_hinted():
    q = parse_query("actor: bogart foo: bar")
    assert q.terms == (Term("actor", "bogart foo: bar", False),) and q.hints == ("unknown field 'foo'",)


def test_internal_whitespace_of_a_value_is_preserved_as_typed():
    assert parse_query("title:  the   big sleep ").terms == (Term("title", "the   big sleep", False),)
