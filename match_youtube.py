# /// script
# dependencies = ["ytmusicapi"]
# ///
"""Finds the official YouTube Music audio (and its play count) for each song in songs_master.json.

Run: uv run match_youtube.py          look up songs that have no answer yet
     uv run match_youtube.py verify   fetch the YouTube title of each published match, so the build can
                                      throw out matches whose title is a different song
(then: uv run build_songs.py to merge the results in)
Results are kept in youtube_matches.json, so re-runs only look up new songs.
"""
import json
import pathlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

from ytmusicapi import YTMusic

OUT = pathlib.Path("youtube_matches.json")


def norm(s):
    return re.sub(r"\W+", "", re.sub(r"\(.*?\)|\[.*?\]", "", (s or "").lower()))


def same_artist(name, song):
    ours = re.split(r"&|,| feat", song["a"]) + [song["ar"]]
    return any(o.strip() and SequenceMatcher(None, norm(name), norm(o)).ratio() >= 0.5 for o in ours)


def plays(text):
    """'1.2M' -> 1200000. YouTube Music reports plays as short text."""
    m = re.match(r"([\d.]+)\s*([KMB]?)", (text or "").upper())
    return int(float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)]) if m else 0


def match(yt, song):
    """A YouTube Music song by the same artist with the same length as Apple's: the same recording.

    Within 2s is enough by itself. Apple and YouTube often differ by 3-4s, so that is accepted too, but only
    when the titles also agree (which needs them to be in the same script).
    """
    for r in yt.search(f"{song['t']} {song['a']}", filter="songs", limit=5):
        off = abs((r.get("duration_seconds") or 0) - song["d"])
        same_title = SequenceMatcher(None, norm(r.get("title")), norm(song["t"])).ratio() >= 0.6
        # same alphabet but a clearly different title: another song by this artist that happens to be the same length
        other_song = norm(r.get("title")).isascii() == norm(song["t"]).isascii() and SequenceMatcher(None, norm(r.get("title")), norm(song["t"])).ratio() < 0.4
        if (r.get("videoId") and not other_song and (off <= 2 or (off <= 4 and same_title))
                and any(same_artist(a["name"], song) for a in r.get("artists") or [])):
            return {"v": r["videoId"], "n": plays(r.get("views")), "t": r.get("title") or ""}
    return None


def run(todo, work, found, label):
    """Run `work(key)` over `todo` four at a time, saving as it goes. `work` returns the value to store, or raises."""
    def one(key):
        try:
            return key, work(key)
        except Exception as e:  # throttled or a network hiccup: leave it for the next run
            return key, e

    with ThreadPoolExecutor(4) as pool:
        for i, (key, value) in enumerate(pool.map(one, todo), 1):
            if not isinstance(value, Exception):
                found[key] = value
            if i % 100 == 0 or i == len(todo):
                OUT.write_text(json.dumps(found, ensure_ascii=False))
                print(f"{i}/{len(todo)} {label}", file=sys.stderr, flush=True)


def verify(yt, found):
    """Store the YouTube title for every published match that lacks one."""
    songs = json.loads(pathlib.Path("songs.json").read_text(encoding="utf-8"))
    todo = [str(s["id"]) for s in songs if s.get("yt") and "t" not in (found.get(str(s["id"])) or {})]
    run(todo, lambda k: {**found[k], "t": yt.get_song(found[k]["v"])["videoDetails"]["title"]}, found, "titles fetched")


def main():
    assert same_artist("Om Kolthoum", {"a": "Oum Kalthoum", "ar": "أم كلثوم"})
    assert not same_artist("Collage Radiu", {"a": "Abdel Halim Hafez", "ar": "عبد الحليم حافظ"})
    assert plays("1.2M") == 1_200_000 and plays("950") == 950 and plays(None) == 0
    songs = json.loads(pathlib.Path("songs_master.json").read_text(encoding="utf-8"))
    found = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [s for s in songs if found.get(str(s["id"])) is None]  # missing, throttled, or "no match" under the older, stricter rule
    yt = YTMusic()

    if sys.argv[1:] == ["verify"]:
        return verify(yt, found)
    by_id = {str(s["id"]): s for s in todo}
    run(list(by_id), lambda k: match(yt, by_id[k]) or False, found, "looked up")
    print(f"{sum(bool(v) for v in found.values())} of {len(songs)} songs have official YouTube audio", file=sys.stderr)


if __name__ == "__main__":
    main()
