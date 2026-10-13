# Small tasks — no functional change

Five independent commits. None of them touches the engine, the oracle, the checker,
the schemas, the registry or any fixture, so none can change a verdict.

**Before you start**

```sh
cd hedgecheck
make check          # must print "all checks passed" before you change anything
```

**After every single commit**

```sh
make check
```

If it fails, the commit broke something — fix it before moving on. Do not push a
commit that fails. `make check` is offline and takes about a minute.

**Commit style** (enforced by habit, not by a hook): conventional commits, lowercase,
50 characters max, one goal per commit.

---

## 1. Add the licence

The repository has no `LICENSE` file. `PLAN.md` section 11 commits to a permissive
licence, so this is an unmet promise rather than a new decision.

Create `LICENSE` in the repository root with the MIT licence text from
<https://opensource.org/license/mit>, used exactly — do not reword it.

The copyright line, exactly:

```
Copyright (c) 2026 HedgeCheck team
```

```
chore(repo): add the MIT licence
```

**Safe because** no code reads this file, and the layout guard in `tools/validate.py`
checks top-level *directories* only, not files.

---

## 2. Name the licence in the README

`README.md` does not mention a licence. Add one line at the very end of the file,
after the last paragraph:

```markdown
Licensed under the MIT Licence. See [LICENSE](./LICENSE).
```

```
docs(readme): name the licence
```

**Do this after task 1**, so the link is not dead at any commit.

---

## 3. Set the repository description and homepage

Not a code change — GitHub metadata. The repo currently has an empty description and
no homepage, so the site is not linked from the repo page.

```sh
gh repo edit arcbjorn/hedgecheck \
  --description "Pre-trade hedge verification for Hyperliquid HIP-4 outcome markets" \
  --homepage "https://arcbjorn.github.io/hedgecheck"
```

Then add topics:

```sh
gh repo edit arcbjorn/hedgecheck \
  --add-topic hyperliquid --add-topic defi --add-topic hedging \
  --add-topic formal-verification --add-topic outcome-markets
```

No commit — this changes nothing in the tree.

---

## 4. Add the site link to the README header

The README does not link the live site. Immediately under the first paragraph (the one
beginning "Pre-trade verification of whether a proposed hedge..."), add:

```markdown
**Live site:** <https://arcbjorn.github.io/hedgecheck> — including a verifier that
re-derives a retained result in the browser.
```

```
docs(readme): link the live site
```

---

## 5. Add alt text to the header logo

`site/index.html` has `<img src="mark.svg" alt="" ...>` in the `<h1>`. An empty `alt`
is correct for a purely decorative image, and this one sits beside the word
"HedgeCheck", so it IS decorative — **leave it alone**.

Instead, check `site/logo.svg` and `site/mark.svg` both still render after any edit:

```sh
open site/index.html
```

Confirm the mark appears beside the heading in both light and dark mode (toggle your
OS appearance). If it looks wrong in light mode, say so rather than guessing at a fix
— `mark.svg` uses `currentColor` deliberately.

No commit unless something is actually broken.

---

## What NOT to touch

Changing any of these can alter a verdict, and all three implementations must agree:

- `engine/`, `oracle/`, `checker/`, `consumer/`, `onchain/`
- `schema/` — a schema cannot change without a row in `schema/CHANGES.md`
- `registry/`, `references/` — contract semantics, reviewed by the owner only
- `fixtures/` — generated; regenerate with `make`, never hand-edit
- Any number published in `README.md` or `site/index.html` — `make check` holds those
  against the retained captures, and changing one will fail the build

If you think one of these needs changing, raise it rather than doing it.
