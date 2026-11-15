import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yt_dlp
from yt_dlp.postprocessor.embedthumbnail import EmbedThumbnailPP
from yt_dlp.postprocessor.ffmpeg import FFmpegMetadataPP
from yt_dlp.utils import PostProcessingError

MEDIA_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".opus",
    ".ogg", ".flac", ".mov", ".m4v", ".avi", ".ts", ".flv",
}
THUMBNAIL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
ID_PATTERN = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
FILENAME_TITLE_PATTERN = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}|undated) - (.+) \[([A-Za-z0-9_-]{11})\]$"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}


def iter_media_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() in MEDIA_EXTENSIONS:
                yield os.path.join(dirpath, name)


def _probe(path):
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", path,
            ],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    tags = {
        str(key).lower(): value
        for key, value in data.get("format", {}).get("tags", {}).items()
    }
    has_thumbnail = False
    for stream in data.get("streams", []):
        disposition = stream.get("disposition") or {}
        if disposition.get("attached_pic") == 1:
            has_thumbnail = True
        stream_tags = stream.get("tags") or {}
        if (
            stream.get("codec_type") == "attachment"
            and "image" in str(stream_tags.get("mimetype", ""))
        ):
            has_thumbnail = True
    return {
        "has_title": bool(str(tags.get("title", "")).strip()),
        "has_thumbnail": has_thumbnail,
    }


def _valid_id(value):
    return bool(value and re.fullmatch(r"[A-Za-z0-9_-]{11}", str(value)))


def _video_id(path, info=None):
    if info and _valid_id(info.get("id")):
        return info["id"]
    matches = ID_PATTERN.findall(os.path.basename(path))
    if matches:
        return matches[-1]
    stem = Path(path).stem
    return stem if _valid_id(stem) else None


def _read_info(base):
    path = base + ".info.json"
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _local_thumbnail(base):
    for ext in THUMBNAIL_EXTENSIONS:
        path = base + ext
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
    return None


def _write_sidecars(base, info, overwrite=False):
    info_path = base + ".info.json"
    if info and (overwrite or not os.path.exists(info_path)):
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
    description_path = base + ".description"
    description = (info or {}).get("description")
    if description and (overwrite or not os.path.exists(description_path)):
        with open(description_path, "w", encoding="utf-8") as f:
            f.write(description)


def _request(client, url):
    response = None
    for attempt in range(3):
        response = client.get(url)
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(2 * (attempt + 1))
            continue
        return response
    return response


def _write_thumbnail(base, content, content_type, url):
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    ext = mimetypes.guess_extension(content_type) or ""
    if not ext:
        ext = os.path.splitext(urlparse(url).path)[1]
    ext = ext.lower()
    if ext == ".jpe":
        ext = ".jpg"
    if ext not in THUMBNAIL_EXTENSIONS:
        ext = ".jpg"
    path = base + (".jpg" if ext == ".jpeg" else ext)
    with open(path, "wb") as f:
        f.write(content)
    return path


def _download_thumbnail(client, url, base):
    local = _local_thumbnail(base)
    if local:
        return local
    try:
        response = _request(client, url)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    content_type = response.headers.get("content-type", "")
    if not content_type.lower().startswith("image/"):
        return None
    if len(response.content) < 1024:
        return None
    return _write_thumbnail(base, response.content, content_type, url)


def _thumbnail_urls(info):
    urls = []
    for thumbnail in reversed((info or {}).get("thumbnails") or []):
        url = thumbnail.get("url")
        if url:
            urls.append(url)
    single = (info or {}).get("thumbnail")
    if single:
        urls.append(single)
    return list(dict.fromkeys(urls))


def _make_ydl():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "remote_components": {"ejs:github"},
    }
    runtime = next(
        (rt for rt in ("deno", "node", "bun") if shutil.which(rt)), None
    )
    if runtime:
        opts["js_runtimes"] = {runtime: {"path": None}}
    return yt_dlp.YoutubeDL(opts)


def _extract_info(urls):
    for url in urls:
        try:
            with _make_ydl() as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    return ydl.sanitize_info(info)
        except Exception:
            continue
    return None


def _archive_kinds(root, media_path, video_id):
    kinds = []
    root = os.path.abspath(root)
    current = os.path.dirname(os.path.abspath(media_path))
    while True:
        archive_path = os.path.join(current, "archive.txt")
        if os.path.exists(archive_path):
            try:
                with open(archive_path, encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 2 and parts[1] == video_id:
                            kinds.append(parts[0])
            except OSError:
                pass
        if current == root or os.path.dirname(current) == current:
            break
        current = os.path.dirname(current)
    return kinds


def _candidate_urls(root, media_path, video_id, info):
    urls = []
    webpage_url = (info or {}).get("webpage_url")
    if webpage_url:
        urls.append(webpage_url)
    live = f"https://www.youtube.com/watch?v={video_id}"
    wayback = (
        "https://web.archive.org/web/https://www.youtube.com/watch?v="
        f"{video_id}"
    )
    kinds = _archive_kinds(root, media_path, video_id)
    if "youtubewebarchive" in kinds:
        urls.extend([wayback, live])
    elif "youtube" in kinds:
        urls.extend([live, wayback])
    else:
        urls.extend([live, wayback])
    return list(dict.fromkeys(urls))


def _wayback_thumbnail(client, base, video_id):
    for name in (
        "maxresdefault.jpg", "sddefault.jpg", "hqdefault.jpg",
        "mqdefault.jpg", "default.jpg",
    ):
        path = _download_thumbnail(
            client, f"https://i.ytimg.com/vi/{video_id}/{name}", base
        )
        if path:
            return path

    params = {
        "url": f"i.ytimg.com/vi/{video_id}/*",
        "output": "json",
        "filter": "statuscode:200",
        "fl": "timestamp,original",
        "limit": "200",
    }
    try:
        response = _request(
            client, "https://web.archive.org/cdx/search/cdx?" + "&".join(
                f"{key}={value}" for key, value in params.items()
            )
        )
        rows = response.json()[1:]
    except (httpx.HTTPError, ValueError, IndexError):
        return None

    preferences = (
        "maxresdefault", "sddefault", "hqdefault", "mqdefault",
        "0.jpg", "1.jpg", "2.jpg", "3.jpg", "default",
    )
    best = {}
    for timestamp, original in rows:
        name = os.path.basename(urlparse(original).path)
        rank = next(
            (i for i, prefix in enumerate(preferences) if name.startswith(prefix)),
            None,
        )
        if rank is None:
            continue
        if rank not in best or timestamp > best[rank][0]:
            best[rank] = (timestamp, original)
    for rank in sorted(best):
        timestamp, original = best[rank]
        url = f"https://web.archive.org/web/{timestamp}if_/{original}"
        path = _download_thumbnail(client, url, base)
        if path:
            return path
    return None


def _ensure_thumbnail(client, base, info, video_id):
    local = _local_thumbnail(base)
    if local:
        return local
    for url in _thumbnail_urls(info):
        path = _download_thumbnail(client, url, base)
        if path:
            return path
    if video_id:
        return _wayback_thumbnail(client, base, video_id)
    return None


def _title_from_filename(path):
    stem = Path(path).stem
    match = FILENAME_TITLE_PATTERN.match(stem)
    if match:
        return match.group(1), match.group(2)
    return None


def _integrate_one(root, path, client, force=False):
    probe = _probe(path)
    if probe is None:
        return "skipped"
    if probe["has_title"] and probe["has_thumbnail"] and not force:
        return "ok"

    base = os.path.splitext(path)[0]
    info = _read_info(base)
    video_id = _video_id(path, info)
    extracted = None
    if info is None or not probe["has_title"]:
        if video_id:
            extracted = _extract_info(
                _candidate_urls(root, path, video_id, info)
            )
        if extracted:
            _write_sidecars(base, extracted)
            if info is None:
                info = extracted

    if info is None and extracted is not None:
        info = extracted
    if info is None:
        info = {}

    fallback = _title_from_filename(path)
    if fallback:
        if not info.get("title"):
            info["title"] = fallback[0]
        if not info.get("id"):
            info["id"] = fallback[1]
    if video_id and not info.get("id"):
        info["id"] = video_id

    thumbnail = _ensure_thumbnail(
        client, base, extracted or info, video_id
    )
    if not thumbnail:
        thumbnail = _local_thumbnail(base)

    info["filepath"] = path
    info["ext"] = os.path.splitext(path)[1].lstrip(".").lower()
    do_metadata = force or not probe["has_title"]
    do_thumbnail = bool(thumbnail) and (force or not probe["has_thumbnail"])
    if not do_metadata and not do_thumbnail:
        return "ok"

    if do_thumbnail:
        thumbnail_ext = os.path.splitext(thumbnail)[1].lstrip(".").lower()
        info["thumbnails"] = [{
            "filepath": thumbnail,
            "url": "",
            "ext": thumbnail_ext,
        }]
        info["__files_to_move"] = {thumbnail: thumbnail}

    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
    try:
        if do_metadata:
            FFmpegMetadataPP(
                ydl, add_metadata=True, add_chapters=False
            ).run(info)
        if do_thumbnail:
            EmbedThumbnailPP(
                ydl, already_have_thumbnail=True
            ).run(info)
    except (PostProcessingError, OSError) as error:
        print(f"  ⚠️ 統合失敗: {os.path.basename(path)}: {error}")
        return "failed"
    return "integrated"


def integrate_downloads(root, force=False):
    if not os.path.isdir(root):
        return {"integrated": 0, "ok": 0, "failed": 0, "skipped": 0}
    files = list(iter_media_files(root))
    if not files:
        return {"integrated": 0, "ok": 0, "failed": 0, "skipped": 0}

    print(f"=== サムネイル・メタデータ統合: {root} ({len(files)} 件) ===")
    counts = {"integrated": 0, "ok": 0, "failed": 0, "skipped": 0}
    with httpx.Client(
        http2=True, headers=HEADERS, timeout=60, follow_redirects=True
    ) as client:
        for index, path in enumerate(files, 1):
            result = _integrate_one(root, path, client, force)
            counts[result] = counts.get(result, 0) + 1
            if result != "ok":
                print(
                    f"[{index}/{len(files)}] {result}: "
                    f"{os.path.relpath(path, root)}"
                )
    print(
        "=== 統合完了: "
        f"更新 {counts['integrated']} / 正常 {counts['ok']} / "
        f"失敗 {counts['failed']} / スキップ {counts['skipped']} ==="
    )
    return counts
