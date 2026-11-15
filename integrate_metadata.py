import argparse

from chukakuha_arciver.metadata import integrate_downloads


def parse_args():
    parser = argparse.ArgumentParser(
        description="既存のダウンロード動画にサムネイル・タイトル・メタデータを統合する"
    )
    parser.add_argument(
        "--download-dir", default="downloads",
        help="対象ディレクトリ (既定: downloads)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="統合済みの動画にも再適用する",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    integrate_downloads(args.download_dir, args.force)


if __name__ == "__main__":
    main()
