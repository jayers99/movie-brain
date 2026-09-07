from movie_brain.domain.credits import build_credits, writer_label
from movie_brain.domain.models import CastEntry, WriterEntry


def test_screenplay_and_writer_print_bare():
    assert writer_label("Leigh Brackett", ["Screenplay"]) == "Leigh Brackett"
    assert writer_label("Ann", ["Writer"]) == "Ann"
    assert writer_label("William Faulkner", ["Story", "Screenplay"]) == "William Faulkner"


def test_other_jobs_are_tagged_lowercase_deduplicated_and_joined():
    assert writer_label("Raymond Chandler", ["Novel"]) == "Raymond Chandler (novel)"
    assert writer_label("X", ["Story", "Adaptation", "Story"]) == "X (story/adaptation)"
    assert writer_label("Y", [""]) == "Y"


ROWS = [
    ("cast", "Humphrey Bogart", "Philip Marlowe", "", ""),
    ("cast", "Lauren Bacall", "", "", ""),
    ("crew", "Howard Hawks", "", "Director", "Directing"),
    ("crew", "Leigh Brackett", "", "Screenplay", "Writing"),
    ("crew", "Raymond Chandler", "", "Novel", "Writing"),
    ("crew", "William Faulkner", "", "Story", "Writing"),
    ("crew", "William Faulkner", "", "Screenplay", "Writing"),
    ("crew", "Sid Hickox", "", "Director of Photography", "Camera"),
]


def test_build_credits_shapes_director_cast_and_writers_in_order():
    fc = build_credits(ROWS)
    assert fc is not None
    assert fc.director == "Howard Hawks"
    assert fc.cast == (CastEntry("Humphrey Bogart", "Philip Marlowe"), CastEntry("Lauren Bacall", ""))
    # one entry per person, first-seen order, Faulkner's Story folded into his bare Screenplay label
    assert fc.writers == (
        WriterEntry("Leigh Brackett", "Leigh Brackett"),
        WriterEntry("Raymond Chandler", "Raymond Chandler (novel)"),
        WriterEntry("William Faulkner", "William Faulkner"),
    )


def test_build_credits_is_none_without_rows():
    assert build_credits([]) is None


def test_to_dict_is_the_api_shape():
    fc = build_credits(ROWS[:1])
    assert fc is not None
    assert fc.to_dict() == {
        "director": None,
        "cast": [{"name": "Humphrey Bogart", "character": "Philip Marlowe"}],
        "writers": [],
    }
