import argparse
import os
import re
import time
import httpx
import yt_dlp
from urllib.parse import urljoin

from chukakuha_arciver.common import apply_archive_options, video_outtmpl

# ===== 設定 =====
# 抽出対象のCDXデータ（ファイルから読み込むか、直接記述）
# ここでは、提供されたデータから「200 OK」かつ「text/html」のものだけを手動で抜粋した例
snapshots = [
    {"timestamp": "20171009152843", "original": "https://www.youtube.com/channel/UCy4QO9DkKIximR3EmIMy0gg"},
    {"timestamp": "20181107021026", "original": "https://www.youtube.com/channel/UCy4QO9DkKIximR3EmIMy0gg"},
    {"timestamp": "20190325161000", "original": "https://www.youtube.com/channel/UCy4QO9DkKIximR3EmIMy0gg"},
    # ... 他のスナップショットも同様に追加 ...
    {"timestamp": "20250615084139", "original": "https://www.youtube.com/channel/UCy4QO9DkKIximR3EmIMy0gg"},
]

# 動画IDを抽出するための正規表現パターン
# YouTubeの動画IDは11文字で、URLは /watch?v=ID や /shorts/ID などの形式
VIDEO_ID_PATTERNS = [
    re.compile(r'/watch\?v=([a-zA-Z0-9_-]{11})'),
    re.compile(r'/shorts/([a-zA-Z0-9_-]{11})'),
    re.compile(r'youtu\.be/([a-zA-Z0-9_-]{11})'),
]

def extract_video_ids(html_content):
    """HTMLから動画IDを抽出する"""
    video_ids = set()
    for pattern in VIDEO_ID_PATTERNS:
        matches = pattern.findall(html_content)
        video_ids.update(matches)
    return video_ids

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

def get_snapshot_url(timestamp, original_url):
    """Wayback MachineのスナップショットURLを構築する"""
    # タイムスタンプ形式: YYYYMMDDhhmmss
    # 例: https://web.archive.org/web/20171009152843/https://www.youtube.com/channel/...
    return f"https://web.archive.org/web/{timestamp}/{original_url}"

def fetch_with_retry(client, url, max_retries=5, base_wait=10):
    """429/5xx を指数バックオフでリトライする"""
    for attempt in range(max_retries):
        response = client.get(url)
        if response.status_code == 429 or response.status_code >= 500:
            wait = base_wait * (2 ** attempt)
            print(f"  … HTTP {response.status_code}、{wait}秒待機して再試行 "
                  f"({attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response
    response.raise_for_status()
    return response

def download_videos(video_ids, download_dir="downloads"):
    """抽出した動画IDを Wayback Machine 経由で yt-dlp に渡してダウンロードする"""
    os.makedirs(download_dir, exist_ok=True)
    ydl_opts = {
        "outtmpl": video_outtmpl(download_dir),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "ignoreerrors": True,
        "retries": 3,
        "fragment_retries": 3,
        "download_archive": os.path.join(download_dir, "archive.txt"),
        "quiet": False,
        "no_warnings": True,
        "noprogress": True,
    }
    apply_archive_options(ydl_opts)

    urls = [
        f"https://web.archive.org/web/https://www.youtube.com/watch?v={vid}"
        for vid in sorted(video_ids)
    ]
    print(f"\n=== Wayback Machine から {len(urls)} 件を yt-dlp で取得 ({download_dir}) ===")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}")
            try:
                ydl.download([url])
            except Exception as e:
                print(f"  ⚠️ スキップ: {e}")
                continue


def parse_args():
    parser = argparse.ArgumentParser(
        description="Wayback Machine から YouTube 動画IDを抽出し、yt-dlp でダウンロードする"
    )
    parser.add_argument(
        "--download", action="store_true",
        help="抽出した動画を Wayback Machine 経由で yt-dlp により取得する",
    )
    parser.add_argument(
        "--download-dir", default="downloads",
        help="ダウンロード先ディレクトリ (既定: downloads)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="ダウンロードする動画数の上限",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    all_video_ids = set()

    with httpx.Client(http2=True, headers=HEADERS, timeout=60,
                      follow_redirects=True) as client:
        for snap in snapshots:
            timestamp = snap["timestamp"]
            original_url = snap["original"]
            snapshot_url = get_snapshot_url(timestamp, original_url)

            print(f"取得中: {snapshot_url}")
            try:
                response = fetch_with_retry(client, snapshot_url)
                # 文字コードを明示的に指定（必要に応じて）
                response.encoding = response.charset_encoding or "utf-8"

                # HTMLから動画IDを抽出
                video_ids = extract_video_ids(response.text)
                all_video_ids.update(video_ids)
                print(f"  -> {len(video_ids)} 件の動画IDを検出")

            except Exception as e:
                print(f"  ⚠️ 取得失敗: {e}")

            # サーバー負荷を避けるため、スナップショット間に待機を入れる
            time.sleep(5)

    print(f"\n=== 抽出されたユニークな動画ID: {len(all_video_ids)} 件 ===")
    for vid in sorted(all_video_ids):
        print(f"https://www.youtube.com/watch?v={vid}")

    if args.download and all_video_ids:
        targets = all_video_ids
        if args.limit is not None:
            targets = set(sorted(all_video_ids)[:args.limit])
        download_videos(targets, args.download_dir)


if __name__ == "__main__":
    main()
