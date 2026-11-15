# chukakuha-arciver

Wayback Machine のスナップショットや YouTube チャンネルから動画を収集し、[yt-dlp](https://github.com/yt-dlp/yt-dlp) で保存するためのツール集です。

## 特徴

- **Wayback Machine 経由の取得** — 過去の YouTube チャンネルページ（アーカイブ）から動画IDを抽出し、yt-dlp で取得
- **チャンネル一括取得** — `channels.toml` に登録したチャンネルの動画をまとめて取得
- **設定ファイルで管理** — チャンネルは TOML に追記するだけ。CLI からも追加可能
- **エラー耐性** — 取得できない動画があってもスキップして処理を継続
- **再実行に強い** — `archive.txt` により取得済みの動画をスキップ

## ディレクトリ構成

```text
.
├── Zenshin-ch.py          # Wayback Machine から動画IDを抽出して取得
├── download_channels.py   # channels.toml のチャンネルをライブYouTubeから取得
├── channels.toml          # 取得対象チャンネルの設定
├── pyproject.toml
├── uv.lock
├── src/
│   └── chukakuha_arciver/
│       └── __init__.py
└── downloads/             # 取得した動画（生成物・git管理外）
```

## 必要環境

- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/)
- `ffmpeg`（映像と音声の結合に使用）
- JavaScript ランタイム（`deno` / `node` / `bun` のいずれか。ライブYouTube取得時に推奨）

## セットアップ

```bash
uv sync
```

## 使い方

### 1. チャンネルを一括取得する

`channels.toml` に取得したいチャンネルを登録します。

```toml
[download]
dir = "downloads"

[[channels]]
name = "example"
url = "https://www.youtube.com/@example"
```

```bash
# 登録チャンネルを確認
uv run download_channels.py --list

# すべて取得
uv run download_channels.py

# 特定チャンネルだけ / 件数を制限
uv run download_channels.py --only example --limit 10

# 保存先を変更
uv run download_channels.py --download-dir /path/to/archive

# 設定ファイルにチャンネルを追記
uv run download_channels.py --add "https://www.youtube.com/@newchannel"
```

取得した動画は `downloads/<チャンネル名>/` に保存され、同ディレクトリの `archive.txt` で取得済みを管理します。

### 2. Wayback Machine から取得する

`Zenshin-ch.py` 内の `snapshots` に、取得したい Wayback のスナップショット（タイムスタンプと元URL）を記述します。

```bash
# 動画IDの抽出のみ
uv run Zenshin-ch.py

# 抽出した動画を Wayback Machine 経由で取得
uv run Zenshin-ch.py --download

# 件数を制限 / 保存先を変更
uv run Zenshin-ch.py --download --limit 5 --download-dir downloads_wayback
```

## 注意事項

- Wayback Machine は HTTP/1.1 のリクエストをボット判定して `429 Too Many Requests` を返すことがあります。本ツールは HTTP/2（`httpx[http2]`）と指数バックオフ付きリトライで対応しています。
- Wayback にアーカイブされていない動画は取得できません。その場合はスキップされます。
- 動画の取得・保存は各サービスの利用規約および著作権を尊重し、個人利用の範囲で行ってください。
- `downloads/` は `.gitignore` 対象です。大量のメディアをリポジトリに含めないよう注意してください。

## ライセンス

このリポジトリのライセンスは未設定です。
