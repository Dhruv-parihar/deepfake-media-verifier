import base64
import html
import json
from pathlib import Path

STYLE = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1b1f24;--muted:#5b6570;--line:#dde1e6;--low:#2e7d32;--medium:#b26a00;--high:#c62828;--info:#1565c0}
@media (prefers-color-scheme:dark){:root{--bg:#14171a;--card:#1d2125;--text:#e8eaed;--muted:#9aa4af;--line:#2c3238;--low:#66bb6a;--medium:#ffb74d;--high:#ef5350;--info:#64b5f6}}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:920px;margin:0 auto}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:0 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin:16px 0}
.muted{color:var(--muted)}
.score{display:flex;align-items:center;gap:20px;flex-wrap:wrap}
.score .num{font-size:48px;font-weight:700;line-height:1}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid currentColor}
.level-low,.sev-low{color:var(--low)}
.level-medium,.sev-medium{color:var(--medium)}
.level-high,.sev-high{color:var(--high)}
.sev-info{color:var(--info)}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
pre{overflow-x:auto;background:var(--bg);padding:12px;border-radius:8px;font-size:12px}
details{margin-top:12px}
img.ela{max-width:100%;border-radius:8px;border:1px solid var(--line)}
a{color:var(--info)}
ul{padding-left:20px;margin:0}
li{margin:4px 0}
"""


def _esc(value):
    return html.escape(str(value))


def _embed_image(run_dir, filename):
    path = Path(run_dir) / filename
    if not path.is_file():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<h3>Error level analysis map</h3><img class="ela" alt="ELA map" src="data:image/png;base64,{encoded}">'


def _detector_block(detector, run_dir):
    parts = [
        '<section class="card">',
        f"<h2>{_esc(detector['name'])}</h2>",
        f'<p class="muted">Status: {_esc(detector["status"])} &middot; Risk contribution: {_esc(detector["risk"])}/100</p>',
    ]
    if detector.get("note"):
        parts.append(f"<p>{_esc(detector['note'])}</p>")
    findings = detector.get("findings") or []
    if findings:
        parts.append("<table><thead><tr><th>Severity</th><th>Finding</th><th>Details</th></tr></thead><tbody>")
        for item in findings:
            severity = _esc(item["severity"])
            parts.append(
                f'<tr><td><span class="pill sev-{severity}">{severity}</span></td>'
                f"<td>{_esc(item['title'])}</td><td>{_esc(item['detail'])}</td></tr>"
            )
        parts.append("</tbody></table>")
    elif detector["status"] == "ok":
        parts.append('<p class="muted">No findings.</p>')
    ela_file = (detector.get("data") or {}).get("ela_map_file")
    if ela_file:
        parts.append(_embed_image(run_dir, ela_file))
    if detector.get("data"):
        parts.append(f"<details><summary>Raw data</summary><pre>{_esc(json.dumps(detector['data'], indent=2, default=str))}</pre></details>")
    parts.append("</section>")
    return "".join(parts)


def render_html(report, run_dir):
    meta = report["meta"]
    overall = report["overall"]
    blocks = "".join(_detector_block(item, run_dir) for item in report["detectors"])
    steps = "".join(f"<li>{_esc(step)}</li>" for step in report["recommendations"])
    limits = "".join(f"<li>{_esc(item)}</li>" for item in report["limitations"])
    links = "".join(
        f'<li><a href="{_esc(item["url"])}" target="_blank" rel="noopener noreferrer">{_esc(item["name"])}</a></li>'
        for item in report["resources"]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Media verification report</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<h1>Media verification report</h1>
<p class="muted">{_esc(meta['target'])} &middot; {_esc(meta['media_type'])} &middot; generated {_esc(meta['generated_at'])}</p>
<section class="card score">
<div class="num level-{_esc(overall['level'])}">{_esc(overall['risk_score'])}</div>
<div>
<div><span class="pill level-{_esc(overall['level'])}">{_esc(overall['verdict'])}</span></div>
<div class="muted">Risk score out of 100. Indicators, not proof.</div>
<div class="muted">SHA-256: {_esc(meta['sha256'])} &middot; Size: {_esc(meta['size'])}</div>
</div>
</section>
{blocks}
<section class="card"><h2>What to do next</h2><ul>{steps}</ul></section>
<section class="card"><h2>Verification resources</h2><ul>{links}</ul></section>
<section class="card"><h2>Limitations</h2><ul>{limits}</ul></section>
</main>
</body>
</html>
"""


def write_reports(report, run_dir, formats):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    written = []
    if formats in ("json", "both"):
        target = run_dir / "report.json"
        target.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        written.append(target)
    if formats in ("html", "both"):
        target = run_dir / "report.html"
        target.write_text(render_html(report, run_dir), encoding="utf-8")
        written.append(target)
    return written
