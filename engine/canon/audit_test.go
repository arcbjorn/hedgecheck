package canon

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"testing"
)

// Parse and Marshal must be inverses on everything the profile accepts.
//
// The shared vectors check fixed inputs against fixed outputs, which cannot catch the
// two halves disagreeing on a shape nobody wrote down. This drives generated
// structures through both, because a document's digest is its identity: if Marshal
// emits bytes that Parse will not read back to the same value, two engines can
// compute different digests for what is genuinely the same document.
func TestAuditParseAndMarshalAreInverses(t *testing.T) {
	// A deterministic LCG, written here rather than taken from math/rand, so the
	// cases do not change with the toolchain.
	seed := uint64(0x20260920_0001)
	next := func() uint64 {
		seed = seed*6364136223846793005 + 1442695040888963407
		return seed >> 33
	}
	pick := func(options []string) string { return options[next()%uint64(len(options))] }

	keys := []string{"a", "b", "zz", "k0", "schema_version", "lower", "upper_inclusive", "x9"}
	values := []string{
		"", "0", "-1/3", "60000", "BTC", "a b", "quoted \" inside",
		"back \\ slash", "tab \t here", "line \n break", strings.Repeat("x", 200),
		"", "é", "é", " ", "\U0001F600",
	}

	var build func(depth int) any
	build = func(depth int) any {
		if depth >= 3 || next()%5 == 0 {
			if next()%3 == 1 {
				return next()%2 == 0
			}
			return pick(values)
		}
		if next()%2 == 0 {
			object := map[string]any{}
			for count := int(next() % 5); count >= 0; count-- {
				object[pick(keys)] = build(depth + 1)
			}
			return object
		}
		list := []any{}
		for count := int(next() % 4); count >= 0; count-- {
			list = append(list, build(depth+1))
		}
		return list
	}

	for index := 0; index < 600; index++ {
		value := build(0)
		encoded, err := Marshal(value)
		if err != nil {
			// Marshal may refuse something outside the profile; that is its job.
			continue
		}
		// What Marshal produced, Parse must accept.
		parsed, err := Parse(encoded)
		if err != nil {
			t.Fatalf("case %d: Marshal wrote bytes Parse refuses: %v\n%s", index, err, encoded)
		}
		// And re-encoding must be a fixed point.
		again, err := Marshal(parsed)
		if err != nil {
			t.Fatalf("case %d: %v", index, err)
		}
		if string(again) != string(encoded) {
			t.Fatalf("case %d: not a fixed point\nfirst:  %s\nsecond: %s", index, encoded, again)
		}
		// The digest follows the bytes, so it must agree too.
		first, err := Digest(value)
		if err != nil {
			t.Fatal(err)
		}
		second, err := Digest(parsed)
		if err != nil {
			t.Fatal(err)
		}
		if first != second {
			t.Fatalf("case %d: the digest changed across a round trip", index)
		}
	}
}

// Digest is the identity of every document: the SHA-256 of the canonical bytes and
// nothing else. Checked against a hand-computed hash rather than against itself.
func TestAuditDigestIsTheHashOfTheCanonicalBytes(t *testing.T) {
	for _, value := range []any{
		map[string]any{},
		map[string]any{"a": "1"},
		map[string]any{"b": "2", "a": "1"},
		[]any{},
		[]any{"a", "b"},
		map[string]any{"nested": map[string]any{"deep": []any{"x"}}},
	} {
		encoded, err := Marshal(value)
		if err != nil {
			t.Fatal(err)
		}
		sum := sha256.Sum256(encoded)
		want := hex.EncodeToString(sum[:])
		got, err := Digest(value)
		if err != nil {
			t.Fatal(err)
		}
		if got != want {
			t.Errorf("Digest(%s) = %s, want the SHA-256 of its own bytes %s",
				encoded, got[:12], want[:12])
		}
	}
}

// Key order is the content's, never the map's. Two maps built in opposite orders are
// the same document and must encode identically.
func TestAuditKeyOrderDoesNotReachTheBytes(t *testing.T) {
	first := map[string]any{}
	second := map[string]any{}
	keys := []string{"zz", "a", "m0", "b1", "schema_version", "lower"}
	for _, key := range keys {
		first[key] = key
	}
	for index := len(keys) - 1; index >= 0; index-- {
		second[keys[index]] = keys[index]
	}
	a, err := Marshal(first)
	if err != nil {
		t.Fatal(err)
	}
	b, err := Marshal(second)
	if err != nil {
		t.Fatal(err)
	}
	if string(a) != string(b) {
		t.Errorf("insertion order reached the bytes:\n%s\n%s", a, b)
	}
	// And the keys really are sorted, not merely stable.
	if !strings.HasPrefix(string(a), `{"a":`) {
		t.Errorf("the encoding does not begin with the lowest key: %s", a)
	}
}

// The profile is a closed door: a number, a null, or a key outside the grammar is
// refused on the way OUT as well as on the way in. An encoder that emitted what its
// own parser refuses would hand another implementation bytes it cannot read.
func TestAuditMarshalRefusesWhatParseWould(t *testing.T) {
	refused := []struct {
		what  string
		value any
	}{
		{"an int", map[string]any{"a": 1}},
		{"a float", map[string]any{"a": 1.5}},
		{"a null", map[string]any{"a": nil}},
		{"an uppercase key", map[string]any{"A": "1"}},
		{"a key starting with a digit", map[string]any{"1a": "x"}},
		{"a key with a hyphen", map[string]any{"a-b": "x"}},
		{"an empty key", map[string]any{"": "x"}},
		{"a nested int", map[string]any{"a": []any{1}}},
		{"an unsupported type", map[string]any{"a": struct{}{}}},
	}
	for _, testCase := range refused {
		if _, err := Marshal(testCase.value); err == nil {
			t.Errorf("Marshal accepted %s, which Parse would refuse", testCase.what)
		}
	}
}
