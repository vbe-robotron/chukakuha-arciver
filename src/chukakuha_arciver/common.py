import os
import re
import unicodedata

DEFAULT_KEYWORDS = (
    "動労千葉",
    "久留里線",
    "JR民営化",
    "JRの民営化",
    "国鉄民営化",
    "中核派",
    "革命的共産主義者同盟全国委員会",
    "革共同",
    "Doro-Chiba",
    "DoroChiba",
    "三里塚闘争",
    "三里塚",
)

FILTER_FIELDS = (
    "title",
    "fulltitle",
    "uploader",
    "channel",
    "creator",
)

FILENAME_TEMPLATE = (
    "%(upload_date>%Y-%m-%d|undated)s - %(title).160B [%(id)s].%(ext)s"
)

REJECT_REASON = "対象キーワードを含まないためスキップ"

POSTPROCESSORS = (
    {"key": "FFmpegMetadata", "add_metadata": True},
    {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
    {"key": "EmbedThumbnail", "already_have_thumbnail": True},
)


def video_outtmpl(download_dir):
    return os.path.join(download_dir, FILENAME_TEMPLATE)


def _normalize(text):
    return re.sub(
        r"\s+", "", unicodedata.normalize("NFKC", str(text)).casefold()
    )


def _flatten(value):
    if value is None:
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _flatten(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _flatten(item)
    else:
        text = str(value).strip()
        if text:
            yield text


def _searchable_text(info):
    parts = []
    for field in FILTER_FIELDS:
        parts.extend(_normalize(value) for value in _flatten(info.get(field)))
    return "\x00".join(part for part in parts if part)


def normalize_keywords(keywords):
    if isinstance(keywords, str):
        keywords = re.split(r"[,、\n]", keywords)
    return tuple(
        str(keyword).strip() for keyword in keywords or () if str(keyword).strip()
    )


def keyword_match_filter(keywords):
    normalized = tuple(
        keyword
        for keyword in (_normalize(value) for value in normalize_keywords(keywords))
        if keyword
    )
    if not normalized:
        return None

    def _match(info, *, incomplete=False):
        if incomplete:
            return None
        text = _searchable_text(info)
        if any(keyword in text for keyword in normalized):
            return None
        title = info.get("title") or info.get("id") or "entry"
        return f"{title}: {REJECT_REASON}"

    return _match


def apply_archive_options(opts, keywords=None):
    opts["allow_playlist_files"] = False
    opts["writethumbnail"] = True
    opts["writeinfojson"] = True
    opts["writedescription"] = True
    postprocessors = list(opts.get("postprocessors") or [])
    postprocessors.extend(dict(pp) for pp in POSTPROCESSORS)
    opts["postprocessors"] = postprocessors
    match_filter = keyword_match_filter(keywords)
    if match_filter is not None:
        opts["match_filter"] = match_filter
    return opts
