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
    check(names == ["defs.schema.json", "ir.schema.json", "proposal.schema.json", "registry-entry.schema.json", "result.schema.json", "snapshot-record.schema.json"], "the six schema files")
    for name in names:
        lint(load(name), name)
        check(True, f"{name}: only enforced keywords")

    # ---- every contract document is inside the canonical JSON profile and valid against its schema
    documents = {}
    plan = [("fixtures/golden/*.ir.json", "ir.schema.json"), ("fixtures/golden/*.result.json", "result.schema.json"),
            ("fixtures/replay/*/*.proposal.json", "proposal.schema.json"), ("registry/*.json", "registry-entry.schema.json")]
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

    print(f"{CHECKS} checks passed; {len(documents)} contract documents valid, {len(refused)} mutations refused.")


if __name__ == "__main__":
    main()
