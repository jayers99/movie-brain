"""The trailer pick rule (brief docs/superpowers/briefs/2026-09-20-trailer-link/brief.md).

The video lists below are built from the SHAPE of real TMDB answers (2026-09-20) with invented
keys: TMDB files every video under a `type`, and CheapCharts' "bogus trailers" are what you get
when that label is ignored."""

from __future__ import annotations

from movie_brain.domain.trailers import MAX_YOUTUBE, Trailer, pick_youtube


def _video(key, name, type_="Trailer", *, official=True, size=1080, lang="en", site="YouTube"):
    return {"key": key, "name": name, "type": type_, "official": official, "size": size,
            "iso_639_1": lang, "site": site, "published_at": "2020-09-09T00:00:00.000Z"}


# Memories of Murder as TMDB files it: seven videos, two of them trailers.
MEMORIES = [
    _video("feat0000001", "This Scene in 'Memories of Murder' Was 100% Real—and Painful!", "Featurette"),
    _video("feat0000002", "Mark Kermode reviews Memories of Murder (2003) | BFI Player", "Featurette"),
    _video("clip0000001", "Clip", "Clip"),
    _video("trlr0000001", "MEMORIES OF MURDER Trailer"),
    _video("teas0000001", "Official UK Teaser Trailer", "Teaser"),
    _video("trlr0000002", "MEMORIES OF MURDER Official Int'l Main Trailer", size=360),
    _video("feat0000003", "Bong Joon Ho & Song Kang Ho Introduce Memories of Murder", "Featurette"),
]


def test_the_real_trailer_not_a_clip_not_a_review():
    picks = pick_youtube(MEMORIES, "ko")
    assert picks[0] == Trailer("youtube", "trlr0000001", "MEMORIES OF MURDER Trailer")
    assert [t.ref for t in picks] == ["trlr0000001", "trlr0000002", "teas0000001"]  # trailers, then the teaser


def test_a_film_with_only_clips_and_featurettes_has_no_trailer():
    assert pick_youtube([v for v in MEMORIES if v["type"] in ("Clip", "Featurette")], "ko") == []


def test_official_beats_sharper_and_sharper_breaks_the_tie():
    videos = [
        _video("fan00000001", "M (1931) Original Trailer [FHD]", official=False, size=1080),
        _video("off00000001", "Trailer", size=720),
        _video("off00000002", "Official 4K Restoration Trailer", size=2160),
    ]
    assert [t.ref for t in pick_youtube(videos, "de")] == ["off00000002", "off00000001", "fan00000001"]


def test_english_before_the_films_own_language_and_never_a_third():
    videos = [
        _video("fr000000001", "L'Armée des ombres : bande-annonce", lang="fr", size=2160),
        _video("de000000001", "L'armée des ombres (Army in the Shadows)", lang="de"),
        _video("en000000001", "Official 4K Restoration Trailer [Subtitled]", lang="en"),
    ]
    assert [t.ref for t in pick_youtube(videos, "fr")] == ["en000000001", "fr000000001"]


def test_a_dub_in_a_third_language_is_not_a_trailer_for_this_film():
    videos = [_video("it000000001", "Rosencrantz e Guildenstern sono morti TRAILER ITALIANO", lang="it")]
    assert pick_youtube(videos, "en") == []


def test_a_video_with_no_language_counts_as_english():
    videos = [_video("xx000000001", "Trailer", lang=None), _video("xx000000002", "Trailer 2", lang="xx", size=720)]
    assert [t.ref for t in pick_youtube(videos, "ja")] == ["xx000000001", "xx000000002"]


def test_only_youtube_is_played_and_at_most_three_are_kept():
    videos = [_video("vimeo000001", "Trailer", site="Vimeo")] + [
        _video(f"yt00000000{i}", f"Trailer {i}", size=1080 - i) for i in range(5)
    ]
    picks = pick_youtube(videos, "en")
    assert len(picks) == MAX_YOUTUBE == 3
    assert all(t.source == "youtube" and t.ref.startswith("yt") for t in picks)


def test_a_key_that_is_not_a_youtube_id_is_dropped():
    # The key ends up inside a player URL: anything but YouTube's own alphabet is refused at the door.
    videos = [_video('bad"key<x>', "Trailer"), _video("", "Trailer"), _video("good_KEY-01", "Trailer")]
    assert [t.ref for t in pick_youtube(videos, "en")] == ["good_KEY-01"]


def test_trailer_to_dict_is_the_stored_shape():
    assert Trailer("youtube", "abc", "Trailer").to_dict() == {"source": "youtube", "ref": "abc", "name": "Trailer"}
