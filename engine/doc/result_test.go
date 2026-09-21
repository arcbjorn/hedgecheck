package doc

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"hedgecheck/engine/canon"
)

func TestResultRoundTripIsByteExact(t *testing.T) {
	for _, path := range []string{
		"../../fixtures/golden/1000-contracts.result.json",
		"../../fixtures/bundles/good/result.json",
		"../../fixtures/bundles/good-horizon/result.json",
	} {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		result, err := ReadResult(raw)
		if err != nil {
			t.Fatalf("%s: refused a valid result: %v", path, err)
		}
		out, err := WriteResult(result)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		parsed, _ := canon.Parse(raw)
		want, _ := canon.Marshal(parsed)
		if string(out) != string(want) {
			t.Errorf("%s: round trip differs\n  got  %.200s\n  want %.200s", filepath.Base(path), out, want)
		}
	}
}

func TestRefusesEveryRejectedResult(t *testing.T) {
	matches, _ := filepath.Glob("../../fixtures/rejected/result/*.json")
	if len(matches) == 0 {
		t.Fatal("no rejected result fixtures")
	}
	for _, path := range matches {
		raw, _ := os.ReadFile(path)
		if _, err := ReadResult(raw); err == nil {
			why, _ := os.ReadFile(path[:len(path)-5] + ".why")
			t.Errorf("%s ACCEPTED, should refuse: %s", filepath.Base(path), why)
		}
	}
	t.Logf("checked %d rejected result documents", len(matches))
}

// THE READER CONSTRAINS WHAT THE SCHEMA CONSTRAINS.
//
// `model_result` was read with `enum`; `execution_readiness` and `evaluation_scope`, on
// the next two lines, were read with no pattern at all. The Go reader accepted
// `execution_readiness: "banana"`, `""`, `"ENVELOPE_ISSUED"` and `"blocked "` while the
// schema allows exactly three values -- and `execution_readiness` is the field that says
// whether an order envelope may exist, so an unconstrained reading of it is on the path
// that authorises an order.
func TestResultEnumsAreConstrained(t *testing.T) {
	raw, err := os.ReadFile("../../fixtures/bundles/good-envelope/result.json")
	if err != nil {
		t.Skip(err)
	}
	if _, err := ReadResult(raw); err != nil {
		t.Fatalf("the fixture does not read: %v", err)
	}

	cases := []struct {
		field string
		bad   []string
		good  string
	}{
		{
			field: "execution_readiness",
			bad:   []string{"banana", "ENVELOPE_ISSUED", "envelope issued", "blocked ", " blocked", "envelope_issued\n"},
			good:  "envelope_issued",
		},
		{
			field: "evaluation_scope",
			bad:   []string{"partial", "exhaustive", "EXHAUSTIVE_SUPPORTED_TERMINAL_MODEL", "exhaustive_supported_terminal_model "},
			good:  "exhaustive_supported_terminal_model",
		},
		{
			field: "model_result",
			bad:   []string{"pass", "PASSES", "passes ", "maybe"},
			good:  "passes",
		},
	}
	for _, testCase := range cases {
		for _, bad := range testCase.bad {
			var document map[string]any
			if err := json.Unmarshal(raw, &document); err != nil {
				t.Fatal(err)
			}
			document[testCase.field] = bad
			edited, err := json.Marshal(document)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := ReadResult(edited); err == nil {
				t.Errorf("%s=%q was accepted; the schema allows it no such value", testCase.field, bad)
			}
		}
		// And the real value still reads, so the check is not simply refusing everything.
		var document map[string]any
		if err := json.Unmarshal(raw, &document); err != nil {
			t.Fatal(err)
		}
		document[testCase.field] = testCase.good
		edited, _ := json.Marshal(document)
		if _, err := ReadResult(edited); err != nil {
			t.Errorf("%s=%q was refused: %v", testCase.field, testCase.good, err)
		}
	}
}
