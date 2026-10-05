# /// script
# dependencies = ["ytmusicapi"]
# ///
"""Finds the official YouTube Music audio (and its play count) for each song in songs_master.json.

Run: uv run match_youtube.py   (then: uv run build_songs.py to merge the matches in)
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
    """A YouTube Music song by the same artist whose length is within 2s of Apple's: the same recording."""
    for r in yt.search(f"{song['t']} {song['a']}", filter="songs", limit=5):
        if (r.get("videoId") and abs((r.get("duration_seconds") or 0) - song["d"]) <= 2
                and any(same_artist(a["name"], song) for a in r.get("artists") or [])):
            return {"v": r["videoId"], "n": plays(r.get("views"))}
    return None


def main():
    assert same_artist("Om Kolthoum", {"a": "Oum Kalthoum", "ar": "أم كلثوم"})
    assert not same_artist("Collage Radiu", {"a": "Abdel Halim Hafez", "ar": "عبد الحليم حافظ"})
    assert plays("1.2M") == 1_200_000 and plays("950") == 950 and plays(None) == 0
    songs = json.loads(pathlib.Path("songs_master.json").read_text(encoding="utf-8"))
    found = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [s for s in songs if str(s["id"]) not in found]
    yt = YTMusic()

    def one(song):
        try:
            return song["id"], match(yt, song)
        except Exception as e:  # network hiccup: leave it for the next run
            return song["id"], e

    with ThreadPoolExecutor(4) as pool:
        for i, (sid, vid) in enumerate(pool.map(one, todo), 1):
            if not isinstance(vid, Exception):
                found[str(sid)] = vid
            if i % 100 == 0 or i == len(todo):
                OUT.write_text(json.dumps(found))
                print(f"{i}/{len(todo)} looked up, {sum(bool(v) for v in found.values())} matched so far", file=sys.stderr, flush=True)
    print(f"{sum(bool(v) for v in found.values())} of {len(songs)} songs have official YouTube audio", file=sys.stderr)


if __name__ == "__main__":
    main()
