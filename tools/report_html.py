"""Offline report rendering; escape evidence and keep unavailable values explicit.

These helpers never modify trial artifacts, perform inference or load remote
assets. Only their caller's derived report directory is written.
"""

import json
from html import escape


def display(value):
    if value is None:
        return "—"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def table(headers, rows, *, table_id=""):
    identifier = f' id="{escape(table_id, quote=True)}"' if table_id else ""
    head = "".join(f"<th scope='col'>{escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(display(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<div class='table'><table{identifier}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def details(title, value):
    return (
        f"<details><summary>{escape(title)}</summary><pre>{escape(display(value))}</pre></details>"
    )


def figure(folder, name, title):
    """Link only generated files that exist, including empty-report cases."""
    if not (folder / (name + ".svg")).is_file():
        return ""
    links = " · ".join(
        f'<a href="{escape(name)}.{ext}">{ext.upper()}</a>'
        for ext in ("svg", "png", "pdf")
        if (folder / (name + "." + ext)).is_file()
    )
    return f'<h3>{escape(title)}</h3><img src="{escape(name)}.svg" alt="{escape(title)}"><p>{links}</p>'


def findings(cases):
    body = ""
    for case in cases:
        label = f"Trial {case.get('trial', '—')} · {case.get('blind_id', '—')} · {case.get('audit_kind', 'translation_fidelity')}"
        body += f"<details><summary>{escape(label)}</summary>"
        body += details(
            "Verdict and provenance", {k: v for k, v in case.items() if k != "findings"}
        )
        for finding in case.get("findings", []):
            body += details("Cited finding — unapproved", finding)
        body += "</details>"
    return body or "<p>No quality assessment is available.</p>"


def document(title, body):
    css = "body{font:16px/1.6 system-ui;color:#24364b;background:#f6f8fb;max-width:1250px;margin:32px auto;padding:0 24px}h2{margin-top:36px}img{width:100%;height:auto}a{color:#145e9a}.table{overflow:auto}table{border-collapse:collapse;width:100%;background:white;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid #dce5ef;white-space:pre-wrap}th{background:#eaf0f7}details{padding:12px;background:white;border:1px solid #dce5ef;margin:12px 0}summary{cursor:pointer;font-weight:600}pre,.prose{white-space:pre-wrap;overflow-wrap:anywhere}input{padding:8px}.cards{display:flex;gap:24px;flex-wrap:wrap}.cards div{background:white;border:1px solid #dce5ef;padding:20px}.cards strong{font-size:22px}"
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{escape(title)}</title><style>{css}</style></head><body>{body}</body></html>'
