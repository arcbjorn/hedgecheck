# One command runs everything: `make check`. Every target is offline and needs no install step.
# Requires python3, go, node (>= 23.6, which runs TypeScript natively) and deno (type-check only).

.PHONY: check vectors schema oracle spike engine checker clean

check: vectors schema oracle spike engine checker clean
	@echo "all checks passed"

# Vector files are generated from hand-written cases; a stale file is an error.
vectors:
	@python3 tools/make_vectors.py --check

schema:
	@python3 tools/validate.py

# Includes the guard on the example result printed in PLAN.md.
oracle:
	@python3 oracle/verify.py

# Offline only: discovery against a retained catalogue, and the guards on spike/.
spike:
	@python3 spike/verify.py

engine:
	@cd engine && test -z "$$(gofmt -l .)" || { echo "gofmt: unformatted files"; exit 1; }
	@cd engine && go vet ./... && go test -count=1 ./...

checker:
	@cd checker && deno check --quiet src/*.ts
	@cd checker && node --test "test/*.test.ts" > .test.log 2>&1; status=$$?; grep -E "^(ℹ (tests|pass|fail)|✖)" .test.log; rm -f .test.log; exit $$status

clean:
	@find . -name __pycache__ -type d -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null; true
