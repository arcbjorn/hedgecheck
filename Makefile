# One command runs everything: `make check`. Every target is offline and needs no install step.
# Requires python3, go, node (>= 23.6, which runs TypeScript natively) and deno (type-check only).

.PHONY: check bundlecheck vectors bundles kernel rejected ircases generated refusals synthesis schema oracle engine checker consumer cross clean

check: vectors bundlecheck bundles kernel rejected ircases refusals synthesis schema oracle engine checker consumer cross clean
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
rejected: generated
	@python3 tools/make_rejected.py --check

# Whole results on generated proposals: the oracle's answers, which Go must reproduce.
ircases:
	@python3 tools/make_ir_cases.py --check

# The generated corpus is Python's OUTPUT and Go's INPUT: `engine/evaluate`, `engine/lower`
# and `engine/canon` read it to prove the two implementations agree byte for byte. It is
# gitignored -- 640 files of derived data -- so a fresh clone has to produce it before any
# Go test can compare against it. This target does that and nothing else; `ircases` above
# is the staleness GATE, which is a different question and belongs in `check`.
generated:
	@test -d fixtures/generated/ir || python3 tools/make_ir_cases.py >/dev/null
	@test -d fixtures/refusals || python3 tools/make_refusals.py >/dev/null
	@test -d fixtures/bundles || python3 tools/make_corruptions.py >/dev/null
	@test -d fixtures/rejected || python3 tools/make_rejected.py >/dev/null
	@test -d fixtures/synthesis || python3 tools/make_synthesis.py >/dev/null

# Synthesis answers and one corruption per refusal class, for the checker to judge.
synthesis:
	@python3 tools/make_synthesis.py --check

# One proposal per refusal code lowering can raise, so both sides refuse alike.
refusals:
	@python3 tools/make_refusals.py --check

# Whole-result agreement: Go writes a bundle, the Python refuser reads it.
cross:
	@python3 tools/cross_accept.py

schema: generated
	@python3 tools/validate.py

# Includes the guard on the example result printed in PLAN.md.
oracle: generated
	@python3 oracle/verify.py

engine: generated
	@cd engine && test -z "$$(gofmt -l .)" || { echo "gofmt: unformatted files"; exit 1; }
	@cd engine && go vet ./... && go test -race -count=1 ./...

# Fails if the committed checker build differs from its sources.
bundlecheck:
	@python3 tools/build_checker.py --check

checker: generated
	@cd checker && deno check --quiet src/*.ts
	@cd checker && deno check --quiet --node-modules-dir=none test/*.ts
	@cd checker && node --test "test/*.test.ts" > .test.log 2>&1; status=$$?; grep -E "^(ℹ (tests|pass|fail)|✖)" .test.log; \
		if [ $$status -eq 0 ]; then rm -f .test.log; else echo "checker: full output kept at checker/.test.log"; fi; exit $$status

# The approval gate. It runs its own copy of the checker, so it is checked after it.
#
# The tests are type-checked too: they are where the guarantees live, and a guard that
# stops asserting what it means to assert is the failure this project keeps meeting.
# `unrepresentable.ts` is excluded because it is DELIBERATELY uncompilable --
# typegate.test.ts runs deno over it and fails if it SUCCEEDS.
consumer: generated
	@cd consumer && deno check --quiet --node-modules-dir=none src/*.ts
	@cd consumer && deno check --quiet --node-modules-dir=none $$(ls test/*.ts | grep -v unrepresentable.ts)
	@cd consumer && node --test "test/*.test.ts" > .test.log 2>&1; status=$$?; grep -E "^(ℹ (tests|pass|fail)|✖)" .test.log; \
		if [ $$status -eq 0 ]; then rm -f .test.log; else echo "consumer: full output kept at consumer/.test.log"; fi; exit $$status

clean:
	@find . -name __pycache__ -type d -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null; true
