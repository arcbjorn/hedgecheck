# One command runs everything: `make check`. Every target is offline and needs no install step.
# Requires python3, go, node (>= 23.6, which runs TypeScript natively) and deno (type-check only).

.PHONY: check bundlecheck vectors bundles kernel rejected ircases refusals schema oracle engine checker consumer cross clean

check: vectors bundlecheck bundles kernel rejected ircases refusals schema oracle engine checker consumer cross clean
	@echo "all checks passed"

# Vector files are generated from hand-written cases; a stale file is an error.
vectors:
	@python3 tools/make_vectors.py --check

# Certificate bundles are generated too: one good, one per documented corruption.
bundles:
	@python3 tools/make_corruptions.py --check

# Kernel agreement cases: the oracle's exact answers, which Go must reproduce.
kernel:
	@python3 tools/make_kernel_cases.py --check

# Documents every schema must refuse, as files so every language can use them.
rejected:
	@python3 tools/make_rejected.py --check

# Whole results on generated proposals: the oracle's answers, which Go must reproduce.
ircases:
	@python3 tools/make_ir_cases.py --check

# One proposal per refusal code lowering can raise, so both sides refuse alike.
refusals:
	@python3 tools/make_refusals.py --check

# Whole-result agreement: Go writes a bundle, the Python refuser reads it.
cross:
	@python3 tools/cross_accept.py

schema:
	@python3 tools/validate.py

# Includes the guard on the example result printed in PLAN.md.
oracle:
	@python3 oracle/verify.py

engine:
	@cd engine && test -z "$$(gofmt -l .)" || { echo "gofmt: unformatted files"; exit 1; }
	@cd engine && go vet ./... && go test -race -count=1 ./...

# The built checker module and its allowlist are BUILD OUTPUT, not committed. This
# builds them from checker/src, asserting on the way that the build is reproducible:
# twice in place, and once more from another directory, so a working directory baked
# into the output would be caught.
bundlecheck:
	@python3 tools/build_checker.py

checker:
	@cd checker && deno check --quiet src/*.ts
	@cd checker && node --test "test/*.test.ts" > .test.log 2>&1; status=$$?; grep -E "^(ℹ (tests|pass|fail)|✖)" .test.log; rm -f .test.log; exit $$status

# The approval gate. It runs its own copy of the checker, so it is checked after it.
consumer:
	@cd consumer && deno check --quiet src/*.ts
	@cd consumer && node --test "test/*.test.ts" > .test.log 2>&1; status=$$?; grep -E "^(ℹ (tests|pass|fail)|✖)" .test.log; rm -f .test.log; exit $$status

clean:
	@find . -name __pycache__ -type d -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null; true
