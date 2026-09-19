package canon

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"
)

func TestVectors(t *testing.T) {
	raw, err := os.ReadFile("../../fixtures/vectors/canonical-json.json")
	if err != nil {
		t.Fatal(err)
	}
	var file struct {
		Vectors []struct {
			Name      string `json:"name"`
			InputHex  string `json:"input_hex"`
			Accepted  bool   `json:"accepted"`
			Canonical string `json:"canonical"`
			SHA256    string `json:"sha256"`
		} `json:"vectors"`
	}
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatal(err)
	}
	if len(file.Vectors) == 0 {
		t.Fatal("no vectors")
	}
	for _, vector := range file.Vectors {
		input, err := hex.DecodeString(vector.InputHex)
		if err != nil {
			t.Fatal(err)
		}
		value, err := Parse(input)
		if (err == nil) != vector.Accepted {
			t.Errorf("%s: accepted=%v (%v), want %v", vector.Name, err == nil, err, vector.Accepted)
			continue
		}
		if err != nil {
			continue
		}
		out, err := Marshal(value)
		if err != nil {
			t.Errorf("%s: %v", vector.Name, err)
			continue
		}
		if string(out) != vector.Canonical {
			t.Errorf("%s: canonical %q, want %q", vector.Name, out, vector.Canonical)
		}
		sum := sha256.Sum256(out)
		if hex.EncodeToString(sum[:]) != vector.SHA256 {
			t.Errorf("%s: digest mismatch", vector.Name)
		}
	}
}
