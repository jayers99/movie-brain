"""The iTunes lookup adapter: Apple's own store preview for a store id (trailer-link brief).

Answer shape from a real lookup (2026-09-20), invented ids: `results` holds one object per product
Apple still answers for — a product it has removed is simply absent — `trackId` is an INTEGER, and
`previewUrl` may be missing."""

from __future__ import annotations

import pytest
import requests
import responses

from movie_brain.infrastructure.itunes import BATCH, LOOKUP_URL, ItunesLookup


def _answer(*items):
    return {"resultCount": len(items), "results": list(items)}


@responses.activate
def test_previews_are_keyed_by_the_store_id_as_a_string():
    responses.get(LOOKUP_URL, json=_answer(
        {"wrapperType": "track", "kind": "feature-movie", "trackId": 900000001, "trackName": "To Die For",
         "previewUrl": "https://video-ssl.itunes.apple.com/itunes-assets/Video1/v4/aa/mzvf_1.640x354.h264lc.U.p.m4v"},
        {"wrapperType": "track", "kind": "feature-movie", "trackId": 900000002, "trackName": "No Preview"},
    ))
    got = ItunesLookup(sleep=lambda s: None).previews(["900000001", "900000002", "900000003"])
    assert got == {"900000001": "https://video-ssl.itunes.apple.com/itunes-assets/Video1/v4/aa/mzvf_1.640x354.h264lc.U.p.m4v"}
    params = responses.calls[0].request.params
    assert params["id"] == "900000001,900000002,900000003" and params["country"] == "us"


@responses.activate
def test_a_preview_that_is_not_an_https_file_on_apples_own_hosts_is_dropped():
    # The URL ends up as a <video src> in the drawer: only Apple's own https hosts are believed.
    responses.get(LOOKUP_URL, json=_answer(
        {"trackId": 1, "previewUrl": "javascript:alert(1)"},
        {"trackId": 2, "previewUrl": "http://video-ssl.itunes.apple.com/x.m4v"},
        {"trackId": 3, "previewUrl": "https://evil.example/apple.com/x.m4v"},
        {"trackId": 4, "previewUrl": "https://notapple.com/x.m4v"},
        {"trackId": 5, "previewUrl": "https://video-ssl.itunes.apple.com/x.m4v"},
    ))
    assert ItunesLookup(sleep=lambda s: None).previews(["1", "2", "3", "4", "5"]) == {
        "5": "https://video-ssl.itunes.apple.com/x.m4v"
    }


@responses.activate
def test_many_ids_go_out_in_paced_batches():
    responses.get(LOOKUP_URL, json=_answer())
    slept: list[float] = []
    ItunesLookup(sleep=slept.append, clock=lambda: 0.0).previews([str(i) for i in range(BATCH + 1)])
    assert len(responses.calls) == 2 and len(slept) == 1
    assert len(responses.calls[0].request.params["id"].split(",")) == BATCH


def test_no_ids_no_call():
    assert ItunesLookup(sleep=lambda s: None).previews([]) == {}


@responses.activate
def test_a_failed_lookup_raises():
    responses.get(LOOKUP_URL, status=503)
    with pytest.raises(requests.RequestException):
        ItunesLookup(sleep=lambda s: None).previews(["1"])
