#!/usr/bin/env python3
"""Download high-resolution, SFW VTuber wallpapers from Danbooru into this folder."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import struct
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CREATORS = ROOT / "creators.txt"
DATABASE = ROOT / ".vtwall.sqlite3"
API = "https://danbooru.donmai.us/posts.json"
USER_AGENT = "vtuber-wallpaper-downloader/2.0 (personal collection)"

# Edit these simple defaults if you want to relax the wallpaper requirements.
MIN_WIDTH = 1920
MIN_HEIGHT = 1080
ASPECT = 16 / 9
ASPECT_TOLERANCE = 0.08
MIN_SCORE = 0
MAX_PAGES_PER_CREATOR = 10
REQUEST_DELAY = 1.0
RETRIES = 4
TIMEOUT = 45
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


class Danbooru:
    def __init__(self) -> None:
        self.last_request = 0.0
        self.login = os.getenv("DANBOORU_LOGIN")
        self.api_key = os.getenv("DANBOORU_API_KEY")

    def headers(self, accept: str) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT, "Accept": accept}
        if self.login and self.api_key:
            credential = base64.b64encode(f"{self.login}:{self.api_key}".encode()).decode()
            headers["Authorization"] = f"Basic {credential}"
        return headers

    def wait(self) -> None:
        remaining = REQUEST_DELAY - (time.monotonic() - self.last_request)
        if remaining > 0:
            time.sleep(remaining)
        self.last_request = time.monotonic()

    def posts(self, tags: str, before: int | None) -> list[dict[str, object]]:
        query = {"tags": tags, "limit": "200"}
        if before is not None:
            query["page"] = f"b{before}"
        for attempt in range(RETRIES + 1):
            self.wait()
            try:
                with urlopen(Request(f"{API}?{urlencode(query)}", headers=self.headers("application/json")), timeout=TIMEOUT) as response:
                    return json.loads(response.read())
            except HTTPError as error:
                if error.code != 429 and not 500 <= error.code < 600:
                    raise RuntimeError(f"Danbooru returned HTTP {error.code}: {error.reason}") from error
                retry_after = error.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt + random.random()
            except URLError as error:
                delay = 2**attempt + random.random()
                if attempt == RETRIES:
                    raise RuntimeError(f"network error: {error.reason}") from error
            if attempt == RETRIES:
                raise RuntimeError("Danbooru remained unavailable after retries")
            time.sleep(min(delay, 60))
        raise AssertionError("unreachable")

    def download(self, url: str, temporary: Path) -> None:
        for attempt in range(RETRIES + 1):
            try:
                with urlopen(Request(url, headers=self.headers("image/*")), timeout=TIMEOUT) as response, temporary.open("wb") as output:
                    while chunk := response.read(256 * 1024):
                        output.write(chunk)
                return
            except HTTPError as error:
                if error.code != 429 and not 500 <= error.code < 600:
                    raise RuntimeError(f"original download returned HTTP {error.code}") from error
                delay = 2**attempt + random.random()
            except (URLError, OSError) as error:
                if attempt == RETRIES:
                    raise RuntimeError(f"download failed: {error}") from error
                delay = 2**attempt + random.random()
            if attempt == RETRIES:
                raise RuntimeError("original remained unavailable after retries")
            time.sleep(min(delay, 60))


def image_dimensions(data: bytes) -> tuple[str, int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return "png", *struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            index += 2
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            size = int.from_bytes(data[index:index + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                height, width = struct.unpack(">HH", data[index + 3:index + 7])
                return "jpg", width, height
            index += size
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and data[12:16] == b"VP8X" and len(data) >= 30:
        return "webp", int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    raise ValueError("unsupported or corrupt image")


def acceptable(post: dict[str, object]) -> bool:
    extension = str(post.get("file_ext") or "").lower()
    width, height = int(post.get("image_width") or 0), int(post.get("image_height") or 0)
    media_asset = post.get("media_asset") or {}
    return bool(
        post.get("file_url")
        and post.get("rating") != "e"
        and not post.get("is_deleted")
        and not post.get("is_banned")
        and extension in ALLOWED_EXTENSIONS
        and not (isinstance(media_asset, dict) and media_asset.get("duration") is not None)
        and width >= MIN_WIDTH and height >= MIN_HEIGHT
        and int(post.get("score") or 0) >= MIN_SCORE
        and width >= height
        and abs(width / height - ASPECT) <= ASPECT_TOLERANCE
    )


def open_database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE)
    connection.execute("CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY, status TEXT NOT NULL, error TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    return connection


def known(connection: sqlite3.Connection, post_id: int) -> bool:
    return connection.execute("SELECT 1 FROM posts WHERE id=? AND status='downloaded'", (post_id,)).fetchone() is not None


def record(connection: sqlite3.Connection, post_id: int, status: str, error: str | None = None) -> None:
    connection.execute("INSERT INTO posts(id,status,error) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,error=excluded.error,updated_at=CURRENT_TIMESTAMP", (post_id, status, error))
    connection.commit()


def creator_names() -> list[str]:
    return [line.strip() for line in CREATORS.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]


def filename_part(value: str) -> str:
    """Keep creator names readable while making them safe as a single filename part."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "unknown"


def rotate_wallpapers(active_creators: list[str]) -> None:
    """Turn wallpapers outside the current roster into non-image archive files."""
    active = {filename_part(creator) for creator in active_creators}
    managed = re.compile(r"([A-Za-z0-9_.-]+)--danbooru-\d+\.(jpg|jpeg|png|webp)$", re.IGNORECASE)
    disabled = 0
    for file in ROOT.iterdir():
        match = managed.fullmatch(file.name)
        if match and match.group(1) not in active:
            file.rename(file.with_name(f"{file.name}.disabled"))
            disabled += 1
    if disabled:
        print(f"Rotation updated: {disabled} wallpaper(s) disabled.")


def has_active_wallpaper(creator: str) -> bool:
    return active_wallpaper(creator) is not None


def active_wallpaper(creator: str) -> tuple[int, Path] | None:
    """Return the newest currently active local wallpaper for a creator."""
    prefix = f"{filename_part(creator)}--danbooru-"
    matches: list[tuple[int, Path]] = []
    for file in ROOT.iterdir():
        if not file.name.startswith(prefix) or file.suffix.lower().lstrip(".") not in ALLOWED_EXTENSIONS:
            continue
        match = re.fullmatch(rf"{re.escape(filename_part(creator))}--danbooru-(\d+)\.[A-Za-z0-9]+", file.name)
        if match:
            matches.append((int(match.group(1)), file))
    return max(matches, default=None, key=lambda item: item[0])


def creator_for(post: dict[str, object], creators: list[str]) -> str | None:
    tags = set(str(post.get("tag_string") or "").split())
    for creator in creators:
        if creator in tags:
            return creator
    return None


def rename_existing(client: Danbooru, creators: list[str]) -> int:
    old_files = list(ROOT.glob("danbooru-*.*"))
    ids: dict[int, Path] = {}
    for file in old_files:
        match = re.fullmatch(r"danbooru-(\d+)\.[A-Za-z0-9]+", file.name)
        if match:
            ids[int(match.group(1))] = file
    if not ids:
        print("No old-style files to rename.")
        return 0

    # Danbooru supports a comma-separated id search. The API permits up to 200 posts per page.
    posts = client.posts("id:" + ",".join(map(str, ids)), None)
    metadata = {int(post["id"]): post for post in posts}
    renamed = unknown = 0
    for post_id, old in sorted(ids.items()):
        creator = metadata.get(post_id) and creator_for(metadata[post_id], creators)
        if not creator:
            print(f"Left {old.name}: no matching creator tag in creators.txt", file=sys.stderr)
            unknown += 1
            continue
        new = old.with_name(f"{filename_part(creator)}--danbooru-{post_id}{old.suffix}")
        if new.exists():
            print(f"Left {old.name}: {new.name} already exists", file=sys.stderr)
            continue
        old.rename(new)
        print(f"Renamed {old.name} -> {new.name}")
        renamed += 1
    print(f"Rename complete: {renamed} renamed, {unknown} without a creator match.")
    return 0


def sort_existing_by_creator() -> int:
    """One-time migration from danbooru-ID--creator.ext to creator--danbooru-ID.ext."""
    old_layout = re.compile(r"danbooru-(\d+)--([A-Za-z0-9_.-]+)\.(jpg|jpeg|png|webp)(\.disabled)?$", re.IGNORECASE)
    renamed = 0
    for file in ROOT.iterdir():
        match = old_layout.fullmatch(file.name)
        if not match:
            continue
        post_id, creator, extension, disabled = match.groups()
        new = file.with_name(f"{creator}--danbooru-{post_id}.{extension}{disabled or ''}")
        if new.exists():
            print(f"Left {file.name}: {new.name} already exists", file=sys.stderr)
            continue
        file.rename(new)
        renamed += 1
    print(f"Sort complete: {renamed} file(s) renamed.")
    return 0


def save_post(client: Danbooru, connection: sqlite3.Connection, creator: str, post: dict[str, object]) -> bool:
    post_id = int(post["id"])
    extension = str(post["file_ext"])
    destination = ROOT / f"{filename_part(creator)}--danbooru-{post_id}.{extension}"
    if destination.exists():
        return False
    temporary = ROOT / f".{destination.name}.part"
    try:
        client.download(str(post["file_url"]), temporary)
        data = temporary.read_bytes()
        kind, width, height = image_dimensions(data)
        expected = extension.replace("jpeg", "jpg")
        if kind != expected or (width, height) != (int(post["image_width"]), int(post["image_height"])):
            raise ValueError("downloaded file does not match Danbooru metadata")
        expected_md5 = post.get("md5")
        if expected_md5 and hashlib.md5(data).hexdigest() != expected_md5:
            raise ValueError("downloaded file checksum does not match Danbooru metadata")
        temporary.replace(destination)
        record(connection, post_id, "downloaded")
        print(f"Downloaded {destination.name} ({width}x{height})")
        return True
    except (OSError, RuntimeError, ValueError) as error:
        temporary.unlink(missing_ok=True)
        record(connection, post_id, "failed", str(error))
        print(f"Failed post {post_id}: {error}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Download VTuber wallpapers into this directory.")
    parser.add_argument("count", nargs="?", type=int, default=20, help="maximum images to download (default: 20)")
    parser.add_argument("--rename-existing", action="store_true", help="rename old danbooru-ID files once using creators.txt")
    parser.add_argument("--sort-existing", action="store_true", help="sort managed files by creator name once")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("count must be positive")
    if not CREATORS.exists():
        print(f"Missing {CREATORS}", file=sys.stderr)
        return 2

    creators = creator_names()
    connection, client = open_database(), Danbooru()
    downloaded = skipped = 0
    try:
        if args.rename_existing:
            return rename_existing(client, creators)
        if args.sort_existing:
            return sort_existing_by_creator()
        rotate_wallpapers(creators)
        random.shuffle(creators)
        for creator in creators:
            if downloaded >= args.count:
                break
            current = active_wallpaper(creator)
            current_id = current[0] if current else 0
            before = None
            for _ in range(MAX_PAGES_PER_CREATOR):
                posts = client.posts(f"{creator} highres", before)
                if not posts:
                    break
                for post in posts:
                    post_id = int(post["id"])
                    # Results are newest first. Once at the current file, no later
                    # result can replace it.
                    if current and post_id <= current_id:
                        break
                    if not acceptable(post):
                        continue
                    if save_post(client, connection, creator, post):
                        if current:
                            old = current[1]
                            old.rename(old.with_name(f"{old.name}.disabled"))
                            print(f"Disabled older wallpaper {old.name}")
                        downloaded += 1
                        break
                    skipped += 1
                else:
                    before = int(posts[-1]["id"])
                    continue
                break
    except KeyboardInterrupt:
        print("Interrupted; completed downloads are safe and the next run skips them.", file=sys.stderr)
        return 130
    finally:
        connection.close()
    print(f"Complete: {downloaded} downloaded, {skipped} already present or failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
