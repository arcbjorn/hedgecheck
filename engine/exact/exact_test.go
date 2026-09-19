package exact

import (
	"encoding/json"
	"os"
	"testing"
)

func TestVectors(t *testing.T) {
	raw, err := os.ReadFile("../../fixtures/vectors/numbers.json")
	if err != nil {
		t.Fatal(err)
	}
	var file struct {
		Vectors []struct {
			Input     string `json:"input"`
			Accepted  bool   `json:"accepted"`
			Canonical string `json:"canonical"`
		} `json:"vectors"`
	}
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatal(err)
	}
	if len(file.Vectors) == 0 {
		t.Fatal("no vectors")
	}
	for _, vector := range file.Vectors {
		value, err := Parse(vector.Input)
		if (err == nil) != vector.Accepted {
			t.Errorf("%q: accepted=%v, want %v", vector.Input, err == nil, vector.Accepted)
			continue
		}
		if err == nil && Format(value) != vector.Canonical {
			t.Errorf("%q: canonical %q, want %q", vector.Input, Format(value), vector.Canonical)
		}
	}
}
