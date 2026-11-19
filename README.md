# Deepfake Media Verifier

AI-assisted deepfake detection and digital media verification for fake news prevention. A cybersecurity mini project.

The tool combines the Deepware AI scanner for video with forensic checks for images, audio, and web links, then produces a single HTML or JSON report with a risk score, the evidence behind it, and next steps for verifying the content.

## Objectives and how the project covers them

| # | Objective | Where it is implemented |
| --- | --- | --- |
| 1 | Detect deepfake videos with the Deepware AI engine | `verifier/detectors/deepware.py` (API or manual score from the web scanner) |
| 2 | Analyze suspicious video, audio, and image files | `video.py`, `audio.py`, `image.py` in `verifier/detectors/` |
| 3 | Verify online content and spot altered elements | `url_check.py` plus image error level analysis |
| 4 | Understand how Deepware-style tools work in fake news prevention | [How it works](#how-it-works) and [Limitations](#limitations) |
| 5 | Improve digital literacy | [`docs/literacy-guide.md`](docs/literacy-guide.md) and the "what to do next" section of every report |
| 6 | Reduce misinformation with reliable results | Evidence-based risk score, honest limitations, fact-checker links |

## Features

- **Video:** Deepware scan, ffprobe metadata review, frame sampling, sharpness consistency, and audio-track analysis.
- **Image:** EXIF review, AI-generator metadata and C2PA markers, error level analysis with a saved heat map.
- **Audio:** digital-silence, loudness, bandwidth, and splice-point checks.
- **Links:** HTTPS, look-alike domains, shorteners, redirects, canonical link, author and date checks, embedded media. Optional Deepware scan of YouTube, Facebook, and X links.
- **Reports:** self-contained `report.html` and machine-readable `report.json`.

## Requirements

- Python 3.10 or newer
- [ffmpeg](https://ffmpeg.org/download.html) (includes `ffprobe`) for video and non-WAV audio
- Optional: a Deepware API key

## Setup

```bash
git clone https://github.com/<your-username>/deepfake-media-verifier.git
cd deepfake-media-verifier
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

On Windows, activate with `.venv\Scripts\activate` and copy the file with `copy .env.example .env`.

Install ffmpeg with `sudo apt install ffmpeg` (Debian, Ubuntu, Parrot, Kali), `brew install ffmpeg` (macOS), or `winget install ffmpeg` (Windows).

## Usage

Analyze a file:

```bash
python main.py file samples/suspect.mp4
python main.py file samples/photo.jpg
python main.py file samples/voice.mp3
```

Check a link:

```bash
python main.py url https://example.com/news/article
python main.py url https://www.youtube.com/watch?v=VIDEO_ID --deepware
```

Options:

| Option | Applies to | Purpose |
| --- | --- | --- |
| `--output-dir DIR` | both | Where reports are saved (default `reports_out`) |
| `--format html\|json\|both` | both | Report format (default `both`) |
| `--no-deepware` | file | Skip the Deepware scan |
| `--deepware-score N` | file | Use a percentage you read from scanner.deepware.ai |
| `--deepware` | url | Also run a Deepware URL scan |
| `--no-fetch` | url | Analyze the link text only, without downloading the page |

Each run creates `reports_out/<name>_<hash>/` containing `report.html`, `report.json`, and, depending on the media, `ela_map.png` and sampled `frames/`.

## Using Deepware

There are two ways to include the Deepware result.

**Without an API key (recommended for a student project).** Upload the video at <https://scanner.deepware.ai>, note the deepfake percentage, then run:

```bash
python main.py file samples/suspect.mp4 --deepware-score 87
```

**With an API key.** Request a key from Deepware, put it in `.env` as `DEEPWARE_API_KEY`, and run the normal command. The tool uploads the video, polls for the report, and summarizes how many detection models flagged it. Test keys allow only a few scans.

The API client follows Deepware's public API reference: a `POST /video/scan` request returns a report id, which is then sent to the report endpoint. If Deepware changes a path or the upload field name, adjust `DEEPWARE_BASE_URL` and `DEEPWARE_FILE_FIELD` in `.env`, and check the current swagger definition at <https://scanner.deepware.ai/developer>. Never commit your `.env` file.

## How it works

```
input file or URL
      |
      v
 media type detection
      |
      +--> video --> Video forensics + Deepware + Audio forensics
      +--> image --> Image forensics (EXIF, markers, ELA)
      +--> audio --> Audio forensics
      +--> url   --> Source and URL checks (+ optional Deepware)
      |
      v
 findings with severity -> per-detector risk -> combined score
      |
      v
 report.html / report.json
```

Each detector returns findings tagged `info`, `low`, `medium`, or `high`. Severities map to risk points, and the overall score is driven by the strongest detector, with a small bonus when several detectors agree. Scores of 50 and above are treated as high risk, 20 to 49 as suspicious, and anything lower as no strong indicators.

Deepware itself analyzes faces in video frames with several deep learning models and reports how many of them detect manipulation. This project wraps that result in a wider verification workflow, because a single score is rarely enough to decide whether to trust or share content.

## Project structure

```
deepfake-media-verifier/
├── main.py
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── verifier/
│   ├── config.py
│   ├── models.py
│   ├── utils.py
│   ├── pipeline.py
│   ├── detectors/
│   │   ├── deepware.py
│   │   ├── video.py
│   │   ├── image.py
│   │   ├── audio.py
│   │   └── url_check.py
│   └── report/
│       └── generator.py
├── tests/
├── docs/literacy-guide.md
├── samples/
└── .github/workflows/ci.yml
```

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

GitHub Actions runs the same tests on every push and pull request.

## Limitations

- Detection is probabilistic. A clean result does not prove authenticity, and a flag does not prove manipulation.
- Deepware targets face-swap manipulation in video. It does not analyze cloned voices or still images, which is why this project adds separate heuristic checks for them.
- Image, audio, and URL checks rely on metadata and signal statistics. They are not trained deepfake classifiers and can produce false positives and false negatives.
- Compression, re-uploads, and screenshots strip evidence. Always analyze the highest-quality original you can get.
- Deepware recommends videos of about 1920x1080 and up to roughly 10 minutes.

## Responsible use

Use this tool only on media you are allowed to analyze. Do not label a person's content as fake based on this report alone. Combine it with source checking and independent reporting.

## Roadmap ideas

- Add a trained audio anti-spoofing model
- Batch scanning of a folder
- Face-region frame analysis
- A small Flask or Streamlit interface

## License

Choose a license for your repository, for example MIT, and add it as `LICENSE`.
