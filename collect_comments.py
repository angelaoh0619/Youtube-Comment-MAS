"""Fetch all public comments (and replies) of one YouTube video via the official Data API v3.

Usage:
    python3 collect_comments.py "https://www.youtube.com/watch?v=VIDEO_ID"
    python3 collect_comments.py VIDEO_ID --max 500 --no-replies

The API key is read from the YOUTUBE_API_KEY environment variable or from a .env file
next to this script. Results are written to data/<video_id>_<timestamp>.{csv,json}.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://www.googleapis.com/youtube/v3"
ROOT = Path(__file__).resolve().parent
FIELDS = ["comment_id", "parent_id", "is_reply", "author", "text", "like_count",
          "reply_count", "published_at", "updated_at"]


class YouTubeError(ValueError):
    def __init__(self, reason, message):
        self.reason = reason
        super().__init__(message)


def load_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    env_file = ROOT / ".env"
    if not key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip().upper() == "YOUTUBE_API_KEY":
                key = value.strip().strip('"').strip("'")
    if not key:
        raise ValueError("YOUTUBE_API_KEY not found. Put `YOUTUBE_API_KEY=...` in .env or the environment.")
    return key


def parse_video_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    if value.startswith(('youtube.com/', 'www.youtube.com/', 'm.youtube.com/', 'youtu.be/')):
        value = 'https://' + value
    url = urllib.parse.urlparse(value)
    if url.scheme not in ('http', 'https') or url.hostname not in ('youtu.be', 'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        raise ValueError('Enter a valid YouTube video link or video ID.')
    if url.hostname == "youtu.be":
        candidate = url.path.lstrip("/").split("/")[0]
    elif url.path.startswith(("/shorts/", "/embed/", "/live/")):
        candidate = url.path.split("/")[2]
    else:
        candidate = urllib.parse.parse_qs(url.query).get("v", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        raise ValueError('The link must point to a single YouTube video.')
    return candidate


class YouTubeAPI:
    def __init__(self, key: str):
        self.key = key
        self.requests = 0

    def get(self, endpoint: str, **params) -> dict:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        request = urllib.request.Request(f"{API_BASE}/{endpoint}?{query}",
                                         headers={"X-Goog-Api-Key": self.key})
        for attempt in range(3):
            self.requests += 1
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code >= 500 and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                try:
                    error = json.loads(body)["error"]
                    reason = error["errors"][0].get("reason", "")
                    message = error.get("message", "")
                except (ValueError, KeyError, IndexError):
                    reason, message = "", body[:200]
                raise YouTubeError(reason, f"YouTube API error {exc.code} {reason}: {message}") from None
            except urllib.error.URLError as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise YouTubeError('network', 'Could not connect to YouTube.') from None
        raise RuntimeError("unreachable")


def to_row(comment: dict, parent_id: str | None, reply_count: int | None) -> dict:
    s = comment["snippet"]
    return {
        "comment_id": comment["id"],
        "parent_id": parent_id or "",
        "is_reply": parent_id is not None,
        "author": s.get("authorDisplayName", ""),
        "text": s.get("textDisplay", ""),
        "like_count": s.get("likeCount", 0),
        "reply_count": "" if reply_count is None else reply_count,
        "published_at": s.get("publishedAt", ""),
        "updated_at": s.get("updatedAt", ""),
    }


def fetch_replies(api: YouTubeAPI, parent_id: str, limit: int | None = None) -> list[dict]:
    replies, token = [], None
    while True:
        data = api.get("comments", part="snippet", parentId=parent_id, maxResults=100,
                       textFormat="plainText", pageToken=token)
        replies.extend(to_row(item, parent_id, None) for item in data.get("items", []))
        if limit is not None and len(replies) >= limit:
            return replies[:limit]
        token = data.get("nextPageToken")
        if not token:
            return replies


def collect(api: YouTubeAPI, video_id: str, limit: int | None, with_replies: bool,
            *, max_total=None, progress=None, report=None) -> list[dict]:
    rows, token, threads = [], None, 0
    def notify():
        if progress:
            progress(len(rows))
    def truncated():
        if report is not None:
            report['limit_reached'] = True
        notify()
        return rows
    while True:
        data = api.get("commentThreads", part="snippet,replies" if with_replies else "snippet",
                       videoId=video_id, maxResults=100, textFormat="plainText",
                       order="time", pageToken=token)
        for item in data.get("items", []):
            top = item["snippet"]["topLevelComment"]
            reply_count = item["snippet"].get("totalReplyCount", 0)
            rows.append(to_row(top, None, reply_count))
            threads += 1
            if max_total is not None and len(rows) >= max_total:
                return truncated()
            if with_replies and reply_count:
                included = item.get("replies", {}).get("comments", [])
                remaining = None if max_total is None else max_total - len(rows)
                if len(included) >= reply_count:
                    replies = [to_row(r, top["id"], None) for r in included]
                else:
                    replies = fetch_replies(api, top["id"], remaining)
                rows.extend(sorted(replies, key=lambda r: r["published_at"])[:remaining])
                if max_total is not None and len(rows) >= max_total:
                    return truncated()
            if limit and threads >= limit:
                notify()
                return rows
        notify()
        print(f"  top-level {threads}, total {len(rows)} rows, requests {api.requests}", flush=True)
        token = data.get("nextPageToken")
        if not token:
            return rows


def collect_video(api, video_id, *, max_comments=500, with_replies=True, progress=None, video=None):
    """Collect a bounded snapshot; max_comments includes replies, not only threads."""
    if video is None:
        videos = api.get('videos', part='snippet,statistics', id=video_id).get('items', [])
        if not videos:
            raise YouTubeError('videoNotFound', 'This video is unavailable or private.')
        video = videos[0]
    snippet = video['snippet']
    thumbnails = snippet.get('thumbnails', {})
    thumbnail = next((thumbnails[k]['url'] for k in ('high', 'medium', 'default') if k in thumbnails), '')
    report = {'limit_reached': False}
    rows = collect(api, video_id, None, with_replies, max_total=max_comments, progress=progress, report=report)
    return {'meta': {'video_id': video_id, 'title': snippet['title'], 'channel_title': snippet.get('channelTitle', ''),
                     'thumbnail_url': thumbnail, 'reported_comment_count': video.get('statistics', {}).get('commentCount'),
                     'collected_at': datetime.now(timezone.utc).isoformat(), 'api_requests': api.requests,
                     'top_level': sum(not r['is_reply'] for r in rows), 'replies': sum(r['is_reply'] for r in rows),
                     'max_comments': max_comments, 'with_replies': with_replies, 'order': 'time', **report},
            'comments': rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", help="YouTube URL or 11-character video ID")
    parser.add_argument("--max", type=int, default=None, help="stop after this many top-level comments")
    parser.add_argument("--no-replies", action="store_true", help="skip replies")
    args = parser.parse_args()

    video_id = parse_video_id(args.video)
    api = YouTubeAPI(load_api_key())

    videos = api.get("videos", part="snippet,statistics", id=video_id).get("items", [])
    if not videos:
        sys.exit(f"Video not found or not accessible: {video_id}")
    title = videos[0]["snippet"]["title"]
    stated = videos[0]["statistics"].get("commentCount", "?")
    print(f"{title} ({video_id}) — commentCount reported by YouTube: {stated}")

    rows = collect(api, video_id, args.max, not args.no_replies)

    out_dir = ROOT / "data"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = out_dir / f"{video_id}_{stamp}"
    with open(base.with_suffix(".csv"), "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    meta = {"video_id": video_id, "title": title, "reported_comment_count": stated,
            "collected_at": datetime.now(timezone.utc).isoformat(), "api_requests": api.requests,
            "top_level": sum(not r["is_reply"] for r in rows),
            "replies": sum(r["is_reply"] for r in rows)}
    base.with_suffix(".json").write_text(json.dumps({"meta": meta, "comments": rows},
                                                    ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(rows)} comments ({meta['top_level']} top-level, {meta['replies']} replies) "
          f"with {api.requests} API requests -> {base}.csv / .json")


if __name__ == "__main__":
    main()
