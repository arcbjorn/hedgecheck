package discover

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func loadCatalogue(t *testing.T, path string) any {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		t.Fatal(err)
	}
	return value
}

// Discovery finds the live instruments in a retained catalogue, unaided. The ids it
// must find are written here, in the test, and never in the package under test.
func TestFindsTheLiveInstrumentsUnaided(t *testing.T) {
	catalogue := loadCatalogue(t, "../../fixtures/replay/2026-09-18/outcome-meta.json")
	expiry, candidates, err := Candidates(catalogue, "BTC", "")
	if err != nil {
		t.Fatal(err)
	}
	if expiry != "20260919-0600" {
		t.Fatalf("expiry %s", expiry)
	}
	found := map[string]Candidate{}
	for _, candidate := range candidates {
		found[candidate.ID] = candidate
	}
	if found["binary-no"].Outcome != "3965" || found["binary-no"].Coin != "#39651" {
		t.Errorf("binary: outcome %s coin %s", found["binary-no"].Outcome, found["binary-no"].Coin)
	}
	if found["bucket0-yes"].Outcome != "3971" || found["bucket0-yes"].Coin != "#39710" {
		t.Errorf("bucket: outcome %s coin %s", found["bucket0-yes"].Outcome, found["bucket0-yes"].Coin)
	}
	if found["binary-no"].Terms["target_price"] != "77457" {
		t.Errorf("target %v", found["binary-no"].Terms["target_price"])
	}
	if found["binary-no"].Terms["expiry"] != "2026-09-19T06:00:00Z" {
		t.Errorf("expiry %v", found["binary-no"].Terms["expiry"])
	}
	if _, _, err := Candidates(catalogue, "DOGE", ""); err == nil {
		t.Error("an underlying with no live series was not refused")
	}
}

// The 19 September capture rolled over: different ids, same code, no configuration.
func TestFindsTheNextDaysInstruments(t *testing.T) {
	catalogue := loadCatalogue(t, "../../fixtures/replay/2026-09-19/catalogue.json")
	expiry, candidates, err := Candidates(catalogue, "BTC", "")
	if err != nil {
		t.Fatal(err)
	}
	found := map[string]Candidate{}
	for _, candidate := range candidates {
		found[candidate.ID] = candidate
	}
	t.Logf("expiry %s: binary %s %s, bucket %s %s", expiry,
		found["binary-no"].Outcome, found["binary-no"].Coin,
		found["bucket0-yes"].Outcome, found["bucket0-yes"].Coin)
	if found["binary-no"].Outcome == "3965" {
		t.Error("the 19 September catalogue returned the 18 September instance")
	}
}
