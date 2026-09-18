"""Retain the official documentation pages and the name-availability sweep behind the 18 September decisions.

GitBook serves each page as Markdown when `.md` is appended, so the retained bytes are the
official text itself, not a rendering or a summary. Namespace lookups are point-in-time:
retaining them records what the registries answered, not what they answer now.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
DOCS = "https://hyperliquid.gitbook.io/hyperliquid-docs/"
PAGES = {
    "contract-specifications": "trading/contract-specifications.md",
    "hip-4-outcome-markets": "hyperliquid-improvement-proposals-hips/hip-4-outcome-markets.md",
    "hip-4-deployer-actions": "for-developers/api/hip-4-deployer-actions.md",
    "interacting-with-hypercore": "for-developers/hyperevm/interacting-with-hypercore.md",
    "builder-codes": "trading/builder-codes.md",
    "asset-ids": "for-developers/api/asset-ids.md",
}
NAMES = ["payoffbounds", "payoffbound", "payoffproof", "lossbounds", "pnlbounds", "payoffverdict", "hedgeassert",
         "payoffcheck", "settlecheck", "payoff", "worstcase", "countersign"]
AGENT = {"User-Agent": "evidence-capture (research; github.com/arcbjorn)"}
RDAP = {
    "com": "https://rdap.verisign.com/com/v1/domain/{}.com",
    "xyz": "https://rdap.centralnic.com/xyz/domain/{}.xyz",
    "ai": "https://rdap.identitydigital.services/rdap/domain/{}.ai",
    "dev": "https://pubapi.registry.google/rdap/domain/{}.dev",
    "app": "https://pubapi.registry.google/rdap/domain/{}.app",
}
REGISTRIES = {
    "npm": "https://registry.npmjs.org/{}",
    "crates": "https://crates.io/api/v1/crates/{}",
    "pypi": "https://pypi.org/pypi/{}/json",
}


def status(url, accept=None):
    headers = dict(AGENT, **({"Accept": accept} if accept else {}))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25) as resp:
            return resp.status
    except urllib.error.HTTPError as error:
        return error.code


def capture_page(stem, path):
    url = DOCS + path
    requested_at = datetime.now(timezone.utc)
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=30) as resp:
        raw, code, server_date = resp.read(), resp.status, resp.headers.get("Date")
    (ROOT / f"{stem}.md").write_bytes(raw)
    record = {"url": url, "method": "GET", "requested_at": requested_at.isoformat(),
              "retrieved_at": datetime.now(timezone.utc).isoformat(), "http_status": code,
              "response_file": f"{stem}.md", "response_sha256": sha256(raw).hexdigest(), "server_date": server_date}
    (ROOT / f"{stem}.request.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"{stem}: {code} {len(raw)} bytes sha256={record['response_sha256'][:16]}")
    time.sleep(1)


def github(path):
    done = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if done.returncode == 0:
        return json.loads(done.stdout)
    return {"missing": "404" in done.stderr}


def whois_io(name):
    out = subprocess.run(["whois", "-h", "whois.nic.io", f"{name}.io"], capture_output=True, text=True, timeout=30).stdout
    if "Creation Date" in out:
        return "taken"
    return "free" if "not found" in out.lower() else "unknown"


def word(code):
    return {404: "free", 200: "taken"}.get(code, f"http-{code}")


def sweep():
    rows = {}
    for name in NAMES:
        user = github(f"users/{name}")
        repos = github(f"search/repositories?q={name}+in:name&per_page=1")
        row = {"github_user": "taken" if "login" in user else ("free" if user.get("missing") else "unknown"),
               "github_repos_named": repos.get("total_count")}
        row.update({key: word(status(url.format(name))) for key, url in REGISTRIES.items()})
        row.update({key: word(status(url.format(name), "application/rdap+json")) for key, url in RDAP.items()})
        row["io"] = whois_io(name)
        rows[name] = row
        print(name, row)
        time.sleep(2.2)
    record = {"retrieved_at": datetime.now(timezone.utc).isoformat(),
              "method": {"github": "gh api users/<name>, search/repositories?q=<name>+in:name", "registries": REGISTRIES,
                         "rdap": RDAP, "io": "whois -h whois.nic.io <name>.io"},
              "rule": "HTTP 404 is recorded as free and 200 as taken; anything else is recorded verbatim",
              "names": rows}
    (ROOT / "name-availability.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    for stem, path in PAGES.items():
        capture_page(stem, path)
    sweep()
