import os

FILENAME_TEMPLATE = (
    "%(upload_date>%Y-%m-%d|undated)s - %(title).160B [%(id)s].%(ext)s"
)

POSTPROCESSORS = (
    {"key": "FFmpegMetadata", "add_metadata": True},
    {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
    {"key": "EmbedThumbnail", "already_have_thumbnail": True},
)


def video_outtmpl(download_dir):
    return os.path.join(download_dir, FILENAME_TEMPLATE)


def apply_archive_options(opts):
    opts["allow_playlist_files"] = False
    opts["writethumbnail"] = True
    opts["writeinfojson"] = True
    opts["writedescription"] = True
    postprocessors = list(opts.get("postprocessors") or [])
    postprocessors.extend(dict(pp) for pp in POSTPROCESSORS)
    opts["postprocessors"] = postprocessors
    return opts
