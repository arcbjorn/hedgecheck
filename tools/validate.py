"""Validate every contract document in the tree against the draft schemas. Standard library only.

    python3 tools/validate.py

A deliberately small JSON Schema validator. It implements exactly the keywords in KEYWORDS
and treats any other keyword as an error, so a constraint can never be silently ignored.
Patterns must be fully anchored, `^(?:...)$`, and are matched as ECMA-262 would: `$` means
end of input, never "before a trailing newline" as Python's `$` does.
"""

import copy
import json
from pathlib import Path
import re
import subprocess
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "oracle"))
import canon  # noqa: E402

SCHEMAS = PROJECT / "schema"
EVIDENCE_COMMIT = "085ccfb"
ANNOTATIONS = {"$schema", "$id", "$comment", "$defs", "title", "description"}
KEYWORDS = {"$ref", "type", "enum", "const", "pattern", "minLength", "maxLength", "properties", "required", "additionalProperties",
            "minProperties", "dependentRequired", "items", "minItems", "maxItems", "oneOf"}
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int}
CHECKS = 0


class SchemaError(Exception):
    pass


def check(condition, description):
    global CHECKS
    if not condition:
        raise AssertionError(description)
    CHECKS += 1


_loaded = {}


def load(name):
    if name not in _loaded:
        _loaded[name] = json.loads((SCHEMAS / name).read_text())
    return _loaded[name]


def resolve(ref, base):
    name, _, pointer = ref.partition("#")
    node = load(name or base)
    for part in filter(None, pointer.split("/")):
        node = node[part]
    return node, (name or base)


def lint(schema, where):
    """Reject anything this validator would not enforce."""
    if not isinstance(schema, dict):
        raise SchemaError(f"{where}: a schema is an object")
    for key, value in schema.items():
        if key not in KEYWORDS | ANNOTATIONS:
            raise SchemaError(f"{where}: unsupported keyword '{key}'")
        if key == "pattern" and not (value.startswith("^(?:") and value.endswith(")$") and "$" not in value[:-1].replace("\\$", "")
                                     or re.fullmatch(r"\^[^$|]*\$", value)):
            raise SchemaError(f"{where}: pattern must be fully anchored: {value}")
        if key == "type" and value not in TYPES:
            raise SchemaError(f"{where}: unsupported type '{value}'")
        if key in ("properties", "$defs"):
            for name, sub in value.items():
                lint(sub, f"{where}/{key}/{name}")
        if key in ("items",) or (key == "additionalProperties" and isinstance(value, dict)):
            lint(value, f"{where}/{key}")
        if key == "oneOf":
            for index, sub in enumerate(value):
                lint(sub, f"{where}/oneOf/{index}")


def errors(instance, schema, base, where="$"):
    out = []
    if "$ref" in schema:
        target, target_base = resolve(schema["$ref"], base)
        out += errors(instance, target, target_base, where)
    if "type" in schema:
        kind = TYPES[schema["type"]]
        # One deliberate deviation from JSON Schema 2020-12, and the only one: the
        # specification counts 1.0 as an integer, this does not. `integer` appears in
        # exactly one place, snapshot-record's http_status, where the value is a status
        # code the venue returned. A float there means the record was rewritten by
        # something that round-tripped it through a float, which is precisely the
        # corruption a record is meant to expose. Being stricter than the spec cannot
        # accept a bad document; it could only reject a good one, and no good record
        # carries 200.0. Documented in ARCHITECTURE section 7.
        if not isinstance(instance, kind) or (kind is int and isinstance(instance, bool)) or (kind is not bool and isinstance(instance, bool)):
            return out + [f"{where}: expected {schema['type']}"]
    if "const" in schema and instance != schema["const"]:
        out.append(f"{where}: expected {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        out.append(f"{where}: not one of {schema['enum']}")
    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"][:-1] + r"\Z", instance):
            out.append(f"{where}: {instance!r} does not match {schema['pattern']}")
        if len(instance) < schema.get("minLength", 0) or len(instance) > schema.get("maxLength", len(instance)):
            out.append(f"{where}: length")
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        out += [f"{where}: missing '{name}'" for name in schema.get("required", []) if name not in instance]
        if len(instance) < schema.get("minProperties", 0):
            out.append(f"{where}: too few properties")
        for name, needs in schema.get("dependentRequired", {}).items():
            out += [f"{where}: '{name}' requires '{need}'" for need in needs if name in instance and need not in instance]
        for name, value in instance.items():
            if name in properties:
                out += errors(value, properties[name], base, f"{where}.{name}")
            elif schema.get("additionalProperties") is False:
                out.append(f"{where}: unexpected '{name}'")
            elif isinstance(schema.get("additionalProperties"), dict):
                out += errors(value, schema["additionalProperties"], base, f"{where}.{name}")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0) or len(instance) > schema.get("maxItems", len(instance)):
            out.append(f"{where}: item count")
        if "items" in schema:
            for index, value in enumerate(instance):
                out += errors(value, schema["items"], base, f"{where}[{index}]")
    if "oneOf" in schema:
        matches = [index for index, sub in enumerate(schema["oneOf"]) if not errors(instance, sub, base, where)]
        if len(matches) != 1:
            out.append(f"{where}: matches {len(matches)} of {len(schema['oneOf'])} alternatives, needs exactly one")
    return out


def valid(instance, name):
    return errors(instance, load(name), name)


DELETE = object()


def mutate(document, path, value=DELETE):
    """A deep copy with one change: set path to value, or delete it when value is omitted."""
    out = copy.deepcopy(document)
    node = out
    for step in path[:-1]:
        node = node[step]
    if value is DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return out


def main():
    # ---- the schemas stay inside the subset this validator enforces
    names = sorted(p.name for p in SCHEMAS.glob("*.schema.json"))
    check(names == ["bundle-manifest.schema.json", "comparison.schema.json", "defs.schema.json", "ir.schema.json", "proposal.schema.json", "refusal.schema.json", "registry-entry.schema.json", "result.schema.json", "snapshot-record.schema.json"], "the nine schema files")
    for name in names:
        lint(load(name), name)
        check(True, f"{name}: only enforced keywords")

    # ---- every contract document is inside the canonical JSON profile and valid against its schema
    documents = {}
    plan = [("fixtures/golden/*.ir.json", "ir.schema.json"), ("fixtures/golden/*.result.json", "result.schema.json"),
            ("fixtures/replay/*/*.proposal.json", "proposal.schema.json"), ("registry/*.json", "registry-entry.schema.json"),
            # Every bundle manifest, and the documents of the GOOD bundles. A corrupted
            # bundle is corrupt on purpose, and some corruptions are schema-invalid --
            # that is the refuser's business (oracle/verify.py), not the validator's.
            # Without these globs a good bundle could carry a schema-invalid result and
            # make check stayed green.
            ("fixtures/bundles/*/manifest.json", "bundle-manifest.schema.json"),
            ("fixtures/bundles/good*/proposal.json", "proposal.schema.json"),
            ("fixtures/bundles/good*/lowered.json", "ir.schema.json"),
            ("fixtures/bundles/good*/result.json", "result.schema.json")]
    for pattern, schema in plan:
        paths = sorted(PROJECT.glob(pattern))
        check(paths, f"{pattern}: at least one document")
        for path in paths:
            document = canon.loads(path.read_bytes())
            problems = valid(document, schema)
            check(not problems, f"{path.relative_to(PROJECT)}: {problems[:3]}")
            documents[str(path.relative_to(PROJECT))] = document

    # ---- documents agree with each other, not only with their schemas
    registry = {entry["family"]: (name, entry) for name, entry in documents.items() if name.startswith("registry/")}
    for name, (path, entry) in registry.items():
        check(path == f"registry/{name}.json", f"{path}: file is named after its family")
        selections = [canon.canonical(payoff["select"]) for payoff in entry["payoffs"]]
        check(len(selections) == len(set(selections)), f"{path}: each side is defined once")
        declared = {term["name"] for term in entry["terms"]}
        used = {bound["term"] for payoff in entry["payoffs"] for pays in payoff["pays"] for key, bound in pays["pays_on"].items() if isinstance(bound, dict)}
        check(used <= declared, f"{path}: payoffs use only declared terms")
        check(entry["review"]["state"] == "draft" or "reviewed_by" in entry["review"], f"{path}: a reviewed entry names its reviewer")
        # review.digest pins the semantics that were reviewed. A state of "reviewed" whose digest
        # does not match the entry's current semantics_version means the semantics changed after
        # review, so canon.reviewed() reports it unreviewed rather than trusting a stale approval.
        if entry["review"]["state"] == "reviewed":
            check("digest" in entry["review"], f"{path}: a reviewed entry records the digest it reviewed")
        check(canon.reviewed(entry) == (entry["review"]["state"] == "reviewed" and entry["review"].get("digest") == canon.semantics_version(entry)),
              f"{path}: review state and digest together decide whether it is reviewed")
    for name, document in documents.items():
        if name.endswith(".proposal.json"):
            for leg in document["legs"]:
                check(leg["family"] in registry, f"{name}: {leg['id']} names a family the registry has")
                check(leg["semantics_version"] == canon.semantics_version(registry[leg["family"]][1]), f"{name}: {leg['id']} pins the registry entry it was written against")
                check(10 * int(leg["instance"]["outcome"]) + (0 if leg["side"] == "yes" else 1) == int(leg["instance"]["coin"][1:]), f"{name}: {leg['id']} coin encodes outcome and side")

    # ---- "valid" means something: each mutation below must be refused
    lowered, result = documents["fixtures/golden/1000-contracts.ir.json"], documents["fixtures/golden/1000-contracts.result.json"]
    entry = registry["recurring.priceBinary"][1]
    # A minimal comparison, built here rather than read from disk: the mutations below only
    # need a valid shape to break, and the real one is exercised by oracle/verify.py.
    comparison = {
        "schema_version": "1",
        "shared": {"domain": lowered["domain"], "baseline": lowered["baseline"],
                   "objective": lowered["objective"], "objective_valuation_time": lowered["objective_valuation_time"]},
        "candidates": [{"label": "binary", "ir_digest": "a" * 64, "model_result": "passes", "cost": "645.76904"},
                       {"label": "bucket0", "ir_digest": "b" * 64, "model_result": "passes", "cost": "160.76676"}],
        "ranked_by": "cost_of_smallest_passing_size",
        "ranking": ["bucket0", "binary"],
        "engine_version": "reference-oracle-3",
    }
    check(not valid(comparison, "comparison.schema.json"), "a comparison of two results is valid")
    refused = [
        ("ir.schema.json", mutate(lowered, ["legs", 0, "size"], "1e3"), "an exponent"),
        ("ir.schema.json", mutate(lowered, ["legs", 0, "size"], "5\n"), "a trailing newline, which Python's own $ would let through"),
        ("ir.schema.json", mutate(lowered, ["legs", 0, "size"], "0x10"), "a hexadecimal number"),
        ("ir.schema.json", mutate(lowered, ["domain", "lower"], "05"), "a leading zero"),
        ("ir.schema.json", mutate(lowered, ["legs", 0, "pays_on", "upper_inclusive"]), "a bound that does not say who owns it"),
        ("ir.schema.json", mutate(lowered, ["legs", 0, "pays_on"], {}), "an indicator that pays nowhere in particular"),
        ("ir.schema.json", mutate(lowered, ["baseline"]), "a missing baseline"),
        ("ir.schema.json", mutate(lowered, ["baseline", "kind"], "strike_reference"), "an unknown baseline kind"),
        ("ir.schema.json", mutate(lowered, ["objective"], []), "an empty objective"),
        ("ir.schema.json", mutate(lowered, ["breakpoints"], ["90000"]), "breakpoints passed beside the function"),
        ("ir.schema.json", mutate(lowered, ["objective_valuation_time"], "2026-01-02T06:00:00+00:00"), "a time that is not UTC 'Z'"),
        ("ir.schema.json", mutate(lowered, ["legs", 0, "premium"], {"kind": "walked", "total": "645.76904", "path": "direct_book"}), "a walked cost that does not cite the book it walked"),
        ("ir.schema.json", mutate(lowered, ["legs", 0, "premium"], {"kind": "walked", "total": "645.76904", "path": "guessed", "snapshot": "d62ba1359f45abc313840ed63deef8d705fcc9bd988ca0f29e9412d8e2cd1ef1"}), "a walked cost on an unnamed acquisition path"),
        ("ir.schema.json", mutate(lowered, ["legs", 0, "premium"], {"kind": "walked", "price": "0.2", "path": "direct_book", "snapshot": "d62ba1359f45abc313840ed63deef8d705fcc9bd988ca0f29e9412d8e2cd1ef1"}), "a walked cost carrying a per-unit price instead of a total"),
        ("result.schema.json", mutate(result, ["model_result"], "unproven"), "an unknown verdict"),
        ("result.schema.json", mutate(result, ["reason_codes"], ["loss_bound_exceeded"]), "a lowercase reason code"),
        ("result.schema.json", mutate(result, ["failing_intervals", 0, "witness"]), "a failing interval without a witness"),
        ("result.schema.json", mutate(result, ["profile", 0, "lower_inclusive"]), "a piece without endpoint ownership"),
        ("result.schema.json", mutate(result, ["ir_digest"], "09B3"), "a malformed digest"),
        ("registry-entry.schema.json", mutate(entry, ["review", "state"], "approved"), "an unknown review state"),
        ("registry-entry.schema.json", mutate(entry, ["sources"], []), "an entry without a source"),
        ("registry-entry.schema.json", mutate(entry, ["evidence", 0, "label"], "verified"), "an evidence label outside V, T, U"),
        ("registry-entry.schema.json", mutate(entry, ["review", "digest"], canon.semantics_version(entry)), "a review digest without a reviewer and a date"),
        ("ir.schema.json", mutate(lowered, ["reductions"], [{"leg": "put", "rule": "horizon_mismatch", "reason_code": "LEG_WORST_CASED_HORIZON"}]), "a reduction that does not say whether it is tight"),
        ("ir.schema.json", mutate(lowered, ["reductions"], [{"leg": "put", "rule": "horizon_mismatch", "tight": "yes", "reason_code": "LEG_WORST_CASED_HORIZON"}]), "a tightness that is a string rather than a boolean"),
        ("result.schema.json", mutate(result, ["size_windows"], [{"leg": "put", "status": "nonempty", "binding": [], "smallest": "1409"}]), "a size window with a smallest size but no largest"),
        ("result.schema.json", mutate(result, ["size_windows"], [{"leg": "put", "status": "maybe", "binding": []}]), "a size window that is neither empty nor nonempty"),
        ("result.schema.json", mutate(result, ["size_windows"], [{"leg": "put", "status": "empty", "binding": [{"price": "60000", "side": "near"}]}]), "a binding site that is not at, above or below a price"),
        ("result.schema.json", mutate(result, ["size_windows"], [{"leg": "put", "status": "empty", "binding": [], "certificate": {"kind": "farkas", "weights": ["0.8"]}}]), "an infeasibility certificate with one weight instead of two"),
        ("result.schema.json", mutate(result, ["comparisons", "smallest_reduction", "keep_quantity"]), "an alternative that does not say how much to keep"),
        ("result.schema.json", mutate(result, ["comparisons", "smallest_reduction"]), "a result without the no-premium alternative"),
        ("result.schema.json", mutate(result, ["reductions"], [{"leg": "put", "rule": "horizon_mismatch", "tight": True}]), "a reduction in a result without its reason code"),
        ("comparison.schema.json", mutate(comparison, ["candidates"], comparison["candidates"][:1]), "a comparison of one candidate"),
        ("comparison.schema.json", mutate(comparison, ["candidates", 0, "ir_digest"], "not-a-digest"), "a candidate cited by something other than a digest"),
        ("comparison.schema.json", mutate(comparison, ["ranked_by"], "cheapest"), "an unknown ranking rule"),
        ("comparison.schema.json", mutate(comparison, ["shared"]), "a comparison that does not state the terms its candidates share"),
    ]
    for schema, document, what in refused:
        check(valid(document, schema), f"refuses {what}")

    # ---- "reviewed with a stale digest" is a cross-field rule no schema keyword can express
    genuine = mutate(entry, ["review"], {"state": "reviewed", "drafted_by": "model", "reviewed_by": "owner",
                                         "reviewed_on": "2026-09-19", "digest": canon.semantics_version(entry)})
    check(not valid(genuine, "registry-entry.schema.json"), "a correctly reviewed entry is still valid")
    check(canon.reviewed(genuine), "a review whose digest matches the semantics counts as reviewed")
    # The digest pins the semantics, so editing them after review must not leave the entry reviewed.
    edited = mutate(genuine, ["observation"], genuine["observation"] + " Edited after review.")
    check(canon.semantics_version(edited) != canon.semantics_version(genuine), "editing the semantics changes semantics_version")
    check(not canon.reviewed(edited), "refuses reviewed with a stale digest")
    # Review state alone is not enough, and neither is a digest of the wrong thing.
    check(not canon.reviewed(mutate(genuine, ["review", "digest"], canon.digest(genuine))), "refuses a digest taken over the whole entry")
    check(not canon.reviewed(mutate(genuine, ["review", "state"], "draft")), "a draft is not reviewed whatever its digest says")
    # The point of the split: marking an entry reviewed must not move the pin.
    check(canon.semantics_version(genuine) == canon.semantics_version(entry), "reviewing an entry does not change what proposals pin")
    # The one documented deviation from JSON Schema 2020-12, pinned so it stays a
    # decision rather than becoming an accident. `integer` is used only for a venue
    # status code, where a float means the record was rewritten.
    check(errors(1.0, {"type": "integer"}, "probe"), "stricter than 2020-12: 1.0 is not accepted as an integer")
    check(not errors(1, {"type": "integer"}, "probe"), "a whole number is an integer")
    check(errors(True, {"type": "integer"}, "probe"), "a boolean is never an integer")
    integer_uses = [name for name in names if '"integer"' in (SCHEMAS / name).read_text()]
    check(integer_uses == ["snapshot-record.schema.json"],
          f"'integer' is used only where that deviation is harmless, found in {integer_uses}")

    try:
        lint({"type": "string", "format": "date-time"}, "probe")
    except SchemaError:
        check(True, "refuses a schema keyword it does not enforce")
    else:
        check(False, "refuses a schema keyword it does not enforce")
    try:
        lint({"type": "string", "pattern": "[0-9]+"}, "probe")
    except SchemaError:
        check(True, "refuses an unanchored pattern")
    else:
        check(False, "refuses an unanchored pattern")

    # ---- the snapshot-record schema describes the records actually retained in history
    listing = subprocess.run(["git", "-C", str(PROJECT), "ls-tree", "-r", "--name-only", EVIDENCE_COMMIT, "research/"], capture_output=True, text=True)
    records = [p for p in listing.stdout.split() if p.endswith(".request.json") and "decisions" not in p]
    if listing.returncode != 0 or not records:
        print(f"note: evidence commit {EVIDENCE_COMMIT} is not available here; retained snapshot records were not checked")
    else:
        for path in records:
            raw = subprocess.run(["git", "-C", str(PROJECT), "show", f"{EVIDENCE_COMMIT}:{path}"], capture_output=True, check=True).stdout
            problems = valid(json.loads(raw), "snapshot-record.schema.json")
            check(not problems, f"{path} at {EVIDENCE_COMMIT}: {problems[:2]}")
        cited = {leg["acquisition"].get("snapshot") for doc in documents.values() for leg in doc.get("legs", []) if isinstance(leg.get("acquisition"), dict)} - {None}
        retained = {json.loads(subprocess.run(["git", "-C", str(PROJECT), "show", f"{EVIDENCE_COMMIT}:{p}"], capture_output=True, check=True).stdout)["response_sha256"] for p in records}
        check(cited <= retained, "every snapshot a draft proposal cites is a retained response")
        print(f"{len(records)} retained snapshot records at {EVIDENCE_COMMIT} match the schema")

    # ---- the freeze: a schema cannot change without schema/CHANGES.md changing
    #
    # The schemas are v1. A change needs a row in CHANGES.md naming the case that
    # forced it, so the two move together or not at all. Compared against HEAD rather
    # than a stored digest: a digest would itself need updating in the same commit,
    # which is the drift this prevents.
    changed = subprocess.run(["git", "-C", str(PROJECT), "diff", "--name-only", "HEAD", "--", "schema/"],
                             capture_output=True, text=True)
    untracked = subprocess.run(["git", "-C", str(PROJECT), "ls-files", "--others", "--exclude-standard", "schema/"],
                               capture_output=True, text=True)
    if changed.returncode != 0:
        print("note: not a git repository here; the schema freeze was not checked")
    else:
        touched = {line for line in (changed.stdout + untracked.stdout).split() if line.endswith(".json")}
        recorded = "schema/CHANGES.md" in (changed.stdout + untracked.stdout)
        check(not touched or recorded,
              f"schema files changed without schema/CHANGES.md: {sorted(touched)[:3]}")
        check((PROJECT / "schema" / "CHANGES.md").exists(), "schema/CHANGES.md exists")
        for name in names:
            comment = load(name).get("$comment", "")
            check("DRAFT" not in comment, f"{name}: no longer marked DRAFT")
            check("CHANGES.md" in comment, f"{name}: points at the change log")

    # ---- documented counts are printed by a command, never remembered
    #
    # Every count in the four documents drifted at least once before this existed:
    # README said six schemas when there were nine, ARCHITECTURE said seven. A count
    # in prose is a claim, and a claim needs a check.
    readme = (PROJECT / "README.md").read_text()
    architecture = (PROJECT / "ARCHITECTURE.md").read_text()
    words = {6: "Six", 7: "seven", 8: "Eight", 9: "Nine", 10: "Ten"}
    spelled = words.get(len(names), str(len(names)))
    check(f"{spelled} draft JSON Schemas" in readme,
          f"README names the schema count: expected '{spelled} draft JSON Schemas' for {len(names)} files")
    check(f"{spelled.lower()} draft schemas" in architecture,
          f"ARCHITECTURE names the schema count: expected '{spelled.lower()} draft schemas'")
    for directory in sorted(p.name for p in (PROJECT / "fixtures").iterdir() if p.is_dir()):
        check(f"`{directory}/`" in readme, f"README's fixtures row mentions {directory}/")
    for top in ("oracle", "engine", "checker", "tools", "schema", "spike", "research"):
        check(f"| `{top}/` |" in readme, f"README's layout table has a row for {top}/")

    print(f"{CHECKS} checks passed; {len(documents)} contract documents valid, {len(refused)} mutations refused.")


if __name__ == "__main__":
    main()
