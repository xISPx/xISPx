#!/usr/bin/env python3
"""Generate GitHub profile stats SVGs (stats.svg + languages.svg).

Usage: generate_assets.py <username> <output_dir>
Data comes from the GitHub API; set GITHUB_TOKEN to raise the rate limit.
The SVGs adapt to GitHub's dark/light theme via a prefers-color-scheme
media query inside the SVG itself.
"""

import ipaddress
import json
import os
import re
import socket
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API_BASE = "https://api.github.com"
ALLOWED_HOST = "api.github.com"
USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")

LANG_COLORS = {
    "C": "#555555",
    "C++": "#f34b7d",
    "Python": "#3572a5",
    "Shell": "#89e051",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Batchfile": "#c2b280",
    "Other": "#8b949e",
}

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Noto Sans,Helvetica,Arial,sans-serif"

CSS = f"""
    .card {{ fill: #ffffff; stroke: #d0d7de; stroke-width: 1; }}
    .title {{ fill: #1f2328; font: 600 15px {FONT}; }}
    .accent {{ fill: #8b5cf6; }}
    .val {{ fill: #6d28d9; font: 700 26px {FONT}; }}
    .val-sm {{ fill: #6d28d9; font: 700 20px {FONT}; }}
    .lbl {{ fill: #59636e; font: 400 12px {FONT}; }}
    .name {{ fill: #1f2328; font: 500 13px {FONT}; }}
    .pct {{ fill: #59636e; font: 400 12px {FONT}; }}
    @media (prefers-color-scheme: dark) {{
      .card {{ fill: #0d1117; stroke: #30363d; }}
      .title, .name {{ fill: #e6edf3; }}
      .val, .val-sm {{ fill: #a78bfa; }}
      .lbl, .pct {{ fill: #9198a1; }}
    }}
"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_url(url):
    """HTTPS + exact host allowlist + all resolved IPs must be public."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError(f"blocked non-api url: {parsed.hostname!r}")
    for _, _, _, _, sockaddr in socket.getaddrinfo(parsed.hostname, 443):
        if not ipaddress.ip_address(sockaddr[0]).is_global:
            raise ValueError("blocked: api host resolved to a non-public address")
    return url


def fetch(path, token=None):
    if not path.startswith("/"):
        raise ValueError("api path must be absolute")
    req = urllib.request.Request(
        _validate_url(API_BASE + path),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "profile-assets"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(req, timeout=30) as resp:
        return json.load(resp)


def fetch_all_repos(user, token):
    repos, page = [], 1
    while True:
        chunk = fetch(f"/users/{user}/repos?per_page=100&page={page}", token)
        repos.extend(chunk)
        if len(chunk) < 100:
            return [r for r in repos if not r["fork"]]
        page += 1


def card(width, height, title):
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img">\n'
        f"<style>{CSS}</style>\n"
        f'<rect class="card" x="1" y="1" width="{width - 2}" height="{height - 2}" rx="14"/>\n'
        f'<text class="title" x="28" y="40">{title}</text>\n'
        f'<rect class="accent" x="28" y="49" width="42" height="3" rx="1.5"/>\n'
    )


def ranked_languages(langs):
    total = sum(langs.values()) or 1
    ranked = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)
    shown = [kv for kv in ranked if 100.0 * kv[1] / total >= 0.1][:8]
    return ranked, shown, total


def card_height(entries):
    legend_rows = max(1, (entries + 1) // 2)
    return max(192, 104 + 40 * (legend_rows - 1) + 30)


def stats_svg(repos, stars, followers, joined, height):
    tiles = [
        ("Public repos", str(len(repos)), "val"),
        ("Stars earned", str(stars), "val"),
        ("Followers", str(followers), "val"),
        ("Joined GitHub", joined.strftime("%b %Y"), "val-sm"),
    ]
    dy = (height - 192) // 2
    cols, rows = (36, 236), (92 + dy, 150 + dy)
    parts = [card(420, height, "GitHub Stats")]
    for i, (label, value, cls) in enumerate(tiles):
        x, y = cols[i % 2], rows[i // 2]
        parts.append(f'<text class="lbl" x="{x}" y="{y}">{label}</text>\n')
        parts.append(f'<text class="{cls}" x="{x}" y="{y + 30}">{value}</text>\n')
    parts.append("</svg>\n")
    return "".join(parts)


def languages_svg(langs, height):
    ranked, shown, total = ranked_languages(langs)

    bar_x, bar_w, bar_y, bar_h = 28, 364, 58, 14
    parts = [card(420, height, "Most Used Languages")]
    parts.append(f'<clipPath id="round"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" '
                 f'height="{bar_h}" rx="7"/></clipPath>\n')
    parts.append('<g clip-path="url(#round)">\n')
    cursor = bar_x
    for name, count in ranked:
        seg_w = bar_w * count / total
        color = LANG_COLORS.get(name, LANG_COLORS["Other"])
        parts.append(f'<rect x="{cursor:.1f}" y="{bar_y}" width="{seg_w:.1f}" '
                     f'height="{bar_h}" fill="{color}"/>\n')
        cursor += seg_w
    parts.append("</g>\n")

    cols = (36, 226)
    for i, (name, count) in enumerate(shown):
        x, y = cols[i % 2], 104 + 40 * (i // 2)
        color = LANG_COLORS.get(name, LANG_COLORS["Other"])
        pct = f"{100.0 * count / total:.1f}%"
        parts.append(f'<circle cx="{x + 4}" cy="{y - 4}" r="5" fill="{color}"/>\n')
        parts.append(f'<text class="name" x="{x + 16}" y="{y}">{name}</text>\n')
        parts.append(f'<text class="pct" x="{x + 170}" y="{y}" text-anchor="end">{pct}</text>\n')
    parts.append("</svg>\n")
    return "".join(parts)


def safe_outdir(outdir):
    """Resolve the output dir inside the current working tree, or exit."""
    candidate = Path(outdir)
    if candidate.is_absolute() or ".." in candidate.parts:
        sys.exit("output dir must be a relative path without '..'")
    base = (Path.cwd() / candidate).resolve()
    if not base.is_relative_to(Path.cwd().resolve()):
        sys.exit("output dir escapes the working directory")
    base.mkdir(parents=True, exist_ok=True)
    return base


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: generate_assets.py <username> <output_dir>")
    user = sys.argv[1]
    if not USERNAME_RE.match(user):
        sys.exit("invalid GitHub username")
    base = safe_outdir(sys.argv[2])
    token = os.environ.get("GITHUB_TOKEN")

    u = fetch(f"/users/{user}", token)
    repos = fetch_all_repos(user, token)
    stars = sum(r["stargazers_count"] for r in repos)
    langs = {}
    for r in repos:
        full_name = urllib.parse.quote(r["full_name"], safe="/")
        for name, count in fetch(f"/repos/{full_name}/languages", token).items():
            langs[name] = langs.get(name, 0) + count
    joined = datetime.fromisoformat(u["created_at"].replace("Z", "+00:00"))

    _, shown, _ = ranked_languages(langs)
    height = card_height(len(shown))

    (base / "stats.svg").write_text(
        stats_svg(repos, stars, u["followers"], joined, height), encoding="utf-8")
    (base / "languages.svg").write_text(languages_svg(langs, height), encoding="utf-8")
    print(f"written: {base}/stats.svg, {base}/languages.svg (height={height})")


if __name__ == "__main__":
    main()
