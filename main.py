import argparse
import sys

from verifier import config
from verifier.pipeline import analyze_file, analyze_url
from verifier.report.generator import write_reports


def percent(value):
    number = float(value)
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return number


def build_parser():
    parser = argparse.ArgumentParser(
        prog="deepfake-verifier",
        description="Check video, image, audio and web content for signs of manipulation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    file_cmd = sub.add_parser("file", help="analyze a local video, image or audio file")
    file_cmd.add_argument("path")
    file_cmd.add_argument("--no-deepware", action="store_true", help="skip the Deepware scan for videos")
    file_cmd.add_argument(
        "--deepware-score",
        type=percent,
        help="deepfake percentage read from scanner.deepware.ai, used instead of the API",
    )

    url_cmd = sub.add_parser("url", help="check a web page or link")
    url_cmd.add_argument("url")
    url_cmd.add_argument("--deepware", action="store_true", help="also scan a YouTube, Facebook or X video link with Deepware")
    url_cmd.add_argument("--no-fetch", action="store_true", help="analyze the link text only, without downloading the page")

    for command in (file_cmd, url_cmd):
        command.add_argument("--output-dir", default=config.OUTPUT_DIR)
        command.add_argument("--format", choices=("html", "json", "both"), default="both")
    return parser


def print_summary(report, written):
    overall = report["overall"]
    print(f"\nTarget:  {report['meta']['target']} ({report['meta']['media_type']})")
    print(f"Verdict: {overall['verdict']}  [risk {overall['risk_score']}/100]\n")
    for detector in report["detectors"]:
        print(f"{detector['name']}  ({detector['status']}, risk {detector['risk']})")
        if detector.get("note"):
            print(f"  note: {detector['note']}")
        for item in detector["findings"]:
            print(f"  [{item['severity']:<6}] {item['title']}")
    print("\nReports written:")
    for path in written:
        print(f"  {path}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "file":
            report, run_dir = analyze_file(
                args.path,
                args.output_dir,
                deepware_enabled=not args.no_deepware,
                manual_score=args.deepware_score,
            )
        else:
            report, run_dir = analyze_url(
                args.url,
                args.output_dir,
                scan_with_deepware=args.deepware,
                fetch=not args.no_fetch,
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    written = write_reports(report, run_dir, args.format)
    print_summary(report, written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
