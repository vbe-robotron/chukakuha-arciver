import argparse
import os
import shutil
import tomllib
import yt_dlp
from urllib.parse import unquote

from chukakuha_arciver.common import apply_archive_options, video_outtmpl

DEFAULT_CONFIG = "channels.toml"


def load_config(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def derive_name(url):
    """チャンネルURLから表示用の名前を推定する"""
    handle = unquote(url.rstrip("/").rsplit("/", 1)[-1]).lstrip("@")
    return handle or "channel"


def sanitize(name):
    """ディレクトリ名に使えない文字を置き換える"""
    return "".join("_" if c in '/\\:*?"<>|' else c for c in name).strip() or "channel"


def build_opts(channel_dir, limit=None):
    os.makedirs(channel_dir, exist_ok=True)
    opts = {
        "outtmpl": video_outtmpl(channel_dir),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "ignoreerrors": True,
        "retries": 5,
        "fragment_retries": 5,
        "download_archive": os.path.join(channel_dir, "archive.txt"),
        "quiet": False,
        "no_warnings": True,
        "noprogress": False,
        "remote_components": {"ejs:github"},
    }
    apply_archive_options(opts)
    js_runtime = next(
        (rt for rt in ("deno", "node", "bun") if shutil.which(rt)), None
    )
    if js_runtime:
        opts["js_runtimes"] = {js_runtime: {"path": None}}
    if limit is not None:
        opts["playlistend"] = limit
    return opts


def add_channel(path, url, name=None):
    config = load_config(path)
    existing = {c.get("url") for c in config.get("channels", [])}
    if url in existing:
        print(f"既に登録済みです: {url}")
        return
    name = name or derive_name(url)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f'\n[[channels]]\nname = "{name.replace(chr(34), chr(92) + chr(34))}"\n')
        f.write(f'url = "{url}"\n')
    print(f"追加しました: {name} <{url}>")


def download_channel(channel, download_dir, limit=None):
    name = sanitize(channel.get("name") or derive_name(channel["url"]))
    channel_dir = os.path.join(download_dir, name)
    opts = build_opts(channel_dir, limit)
    print(f"\n=== {name} ===")
    print(f"URL: {channel['url']}")
    print(f"保存先: {channel_dir}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([channel["url"]])


def parse_args():
    parser = argparse.ArgumentParser(
        description="channels.toml に登録した YouTube チャンネルを yt-dlp で一括取得する"
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG,
        help=f"設定ファイル (既定: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--download-dir", default=None,
        help="保存先ディレクトリ（設定ファイルの [download].dir を上書き）",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="各チャンネルで取得する動画数の上限",
    )
    parser.add_argument(
        "--only", default=None,
        help="指定した名前のチャンネルだけを対象にする",
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_only",
        help="登録チャンネルを一覧表示して終了する",
    )
    parser.add_argument(
        "--add", metavar="URL", default=None,
        help="指定したチャンネルURLを設定ファイルに追記する",
    )
    parser.add_argument(
        "--name", default=None,
        help="--add 時に使うチャンネル名",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.add:
        if not os.path.exists(args.config):
            with open(args.config, "w", encoding="utf-8") as f:
                f.write('[download]\ndir = "downloads"\n')
        add_channel(args.config, args.add, args.name)
        return

    config = load_config(args.config)
    channels = config.get("channels", [])
    download_dir = args.download_dir or config.get("download", {}).get(
        "dir", "downloads"
    )

    if args.only:
        channels = [
            c for c in channels
            if (c.get("name") or derive_name(c["url"])) == args.only
        ]

    if not channels:
        print("対象チャンネルがありません。")
        return

    if args.list_only:
        for c in channels:
            print(f"{c.get('name') or derive_name(c['url'])}\t{c['url']}")
        return

    print(f"=== {len(channels)} チャンネルを取得 ({download_dir}) ===")
    failures = []
    for channel in channels:
        try:
            download_channel(channel, download_dir, args.limit)
        except Exception as e:
            name = channel.get("name") or derive_name(channel["url"])
            print(f"  ⚠️ スキップ ({name}): {e}")
            failures.append(name)

    print("\n=== 完了 ===")
    if failures:
        print(f"失敗/スキップ: {', '.join(failures)}")


if __name__ == "__main__":
    main()
