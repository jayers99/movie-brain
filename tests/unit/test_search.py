from movie_brain.domain.search import trigram_query


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
