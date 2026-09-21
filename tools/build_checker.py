"""Build the checker into one ES module the browser can load.

    python3 tools/build_checker.py          # rebuild, then check
    python3 tools/build_checker.py --check  # fail if the committed file is stale

WHY `deno bundle`. A browser cannot run TypeScript, so something must produce
JavaScript. Two tools are already installed and neither adds a dependency:

  - Node's built-in type stripping runs a `.ts` file directly, but strips types
    PER FILE at load time. It does not bundle. A browser would need every module
    served separately and would still meet TypeScript in the import specifiers.
  - `deno bundle` emits ONE ES module with the imports resolved, which is what a
    page can load. Deno is already required by `make check`, which type-checks the
    checker's sources.

The task asks for one module, so it is `deno bundle`. This script asserts
reproducibility rather than assuming it, and asserts the claim that matters for a
COMMITTED artefact: the same sources built FROM ANOTHER DIRECTORY give the same
bytes. Building twice in place would not catch a working directory baked into the
output, and two people on two machines must agree.

THE BUILT FILE IS GENERATED AND COMMITTED. It is committed because the Go service
embeds it and a browser must be served something; it is generated because a
hand-edited copy of a checker would check nothing. `make check` rebuilds it and
fails if what is committed differs.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "oracle"))

import canon  # noqa: E402

SOURCE = PROJECT / "checker" / "src" / "verify.ts"
BUNDLE = PROJECT / "checker" / "dist" / "checker.js"
ALLOWLIST = PROJECT / "checker" / "dist" / "allowlist.json"


def build_bundle(into):
    """One ES module, from the checker's sources."""
    result = subprocess.run(
        ["deno", "bundle", "--platform", "browser", str(SOURCE), "-o", str(into)],
        cwd=PROJECT / "checker", capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"deno bundle failed:\n{result.stderr}")
    return into.read_bytes()


def reviewed_digests():
    """The semantics_version of every registry entry that is genuinely reviewed.

    An entry counts only when its state is `reviewed` AND its review digest still
    matches its own semantics_version. Both entries are model drafts today, so this
    list is EMPTY, and that is the correct answer rather than a missing one: a
    checker that trusted a draft reading would be trusting a model's guess about
    what a contract pays.

    ROTATION. The list is derived, never hand-written. The owner reviews an entry,
    sets its state and its review digest, and the next build picks it up. Removing a
    review removes the digest. Nothing here is edited by hand, so the list cannot
    drift from the entries it claims to describe.
    """
    out = []
    for path in sorted((PROJECT / "registry").glob("*.json")):
        entry = json.loads(path.read_text())
        without_review = {k: v for k, v in entry.items() if k != "review"}
        version = canon.digest(without_review)
        review = entry.get("review") or {}
        if review.get("state") == "reviewed" and review.get("digest") == version:
            out.append(version)
    return sorted(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed files are stale")
    args = parser.parse_args()

    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    scratch = BUNDLE.parent / ".build.js"
    first = build_bundle(scratch)
    second = build_bundle(scratch)
    if first != second:
        raise SystemExit("deno bundle is not reproducible: two builds differ")
    scratch.unlink(missing_ok=True)

    # And reproducible from ANOTHER DIRECTORY, which is the claim that matters for a
    # committed artefact: two people on two machines must produce the same bytes.
    # Building twice in place would not catch an absolute path or a working
    # directory baked into the output.
    with tempfile.TemporaryDirectory() as elsewhere:
        shutil.copytree(SOURCE.parent, Path(elsewhere) / "src")
        away = Path(elsewhere) / "away.js"
        result = subprocess.run(
            ["deno", "bundle", "--platform", "browser",
             str(Path(elsewhere) / "src" / "verify.ts"), "-o", str(away)],
            cwd=elsewhere, capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(f"deno bundle failed elsewhere:\n{result.stderr}")
        if away.read_bytes() != first:
            raise SystemExit(
                "deno bundle is not reproducible: building from another directory "
                "gives different bytes, so the output depends on where it was built")

    allowlist = json.dumps({"reviewed": reviewed_digests()}, indent=2) + "\n"

    if args.check:
        stale = []
        if not BUNDLE.exists() or BUNDLE.read_bytes() != first:
            stale.append(str(BUNDLE.relative_to(PROJECT)))
        if not ALLOWLIST.exists() or ALLOWLIST.read_text() != allowlist:
            stale.append(str(ALLOWLIST.relative_to(PROJECT)))
        if stale:
            raise SystemExit(
                f"the committed build is stale: {', '.join(stale)}. "
                "Run python3 tools/build_checker.py")
        print(f"checker bundle current, {len(first)} bytes, "
              f"sha256 {hashlib.sha256(first).hexdigest()[:16]}; "
              f"{len(json.loads(allowlist)['reviewed'])} reviewed registry digests")
        return 0

    BUNDLE.write_bytes(first)
    ALLOWLIST.write_text(allowlist)
    print(f"wrote {BUNDLE.relative_to(PROJECT)} ({len(first)} bytes) and "
          f"{ALLOWLIST.relative_to(PROJECT)} "
          f"({len(json.loads(allowlist)['reviewed'])} reviewed digests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
