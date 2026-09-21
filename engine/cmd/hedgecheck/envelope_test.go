package main

import (
	"encoding/json"
	"strings"
	"testing"
)

const replay2026918 = "../../../fixtures/replay/2026-09-18"

// The order envelope reaches the CLI, and it carries the HAND-DERIVED numbers.
//
// These constants are not read out of this engine, the oracle or the TypeScript
// checker. From fixtures/replay/2026-09-18/book-3965-no.json, the ask ladder's
// cumulative sizes are 36, 151, 1151, 1192, 1232, 1253, 1293, 1333, 1383; 1383 < 1409,
// so the last 26 come from the 0.48404 level and that is the highest the walk touches.
// The cost in units of 1e-5 is 1623600 + 5203750 + 45600000 + 1875750 + 1840000 +
// 969150 + 1880000 + 1920000 + 2406150 + 1258504 = 64576904.
//
// And from book-bucket0-3971-yes.json, 924 <= 1200 fills entirely in the 0.17399
// level: 924 x 17399 = 15659100 + 417576 = 16076676.
func TestCheckIssuesTheEnvelopeOnlyWhenAsked(t *testing.T) {
	for _, row := range []struct {
		file, coin, size, limit, cost string
	}{
		{"binary.proposal.json", "#39651", "1409", "0.48404", "645.76904"},
		{"bucket0.proposal.json", "#39710", "924", "0.17399", "160.76676"},
	} {
		args := []string{"check", "--proposal", replay2026918 + "/" + row.file,
			"--registry", "../../../registry", "--snapshots", replay2026918, "--reviewed"}

		// Without the flag, nothing about execution is said at all.
		status, plain, stderr := invoke(t, args...)
		if status != exitPasses {
			t.Fatalf("%s exited %d: %s", row.file, status, stderr)
		}
		if strings.Contains(plain, "order_envelope") {
			t.Errorf("%s: an envelope was issued without --envelope", row.file)
		}
		var before map[string]any
		if err := json.Unmarshal([]byte(plain), &before); err != nil {
			t.Fatal(err)
		}
		if before["execution_readiness"] != "not_evaluated" {
			t.Errorf("%s: readiness is %v without --envelope", row.file, before["execution_readiness"])
		}

		// With it, the envelope is the hand-derived one.
		status, stdout, stderr := invoke(t, append(args, "--envelope")...)
		if status != exitPasses {
			t.Fatalf("%s --envelope exited %d: %s", row.file, status, stderr)
		}
		var after map[string]any
		if err := json.Unmarshal([]byte(stdout), &after); err != nil {
			t.Fatal(err)
		}
		if after["execution_readiness"] != "envelope_issued" {
			t.Fatalf("%s: readiness is %v", row.file, after["execution_readiness"])
		}
		envelope, ok := after["order_envelope"].(map[string]any)
		if !ok {
			t.Fatalf("%s: no envelope", row.file)
		}
		for key, want := range map[string]string{
			"coin": row.coin, "side": "buy", "size": row.size,
			"limit_price": row.limit, "time_in_force": "Ioc", "max_cost": row.cost,
		} {
			if envelope[key] != want {
				t.Errorf("%s: %s is %v, want %s", row.file, key, envelope[key], want)
			}
		}
		if envelope["input_digest"] != after["input_digest"] {
			t.Errorf("%s: the envelope names %v, the result is %v",
				row.file, envelope["input_digest"], after["input_digest"])
		}
		// The envelope's cost IS the premium the verdict was reached with.
		cost, ok := after["cost"].(map[string]any)
		if !ok {
			t.Fatal("no cost")
		}
		if cost["premium"] != row.cost {
			t.Errorf("%s: premium is %v, the envelope says %s", row.file, cost["premium"], row.cost)
		}
	}
}

// A verdict that is not `passes` gets no envelope, says why on stderr, and keeps its
// own exit status. "This cannot be executed" is not "this failed the objective".
func TestCheckBlocksTheEnvelopeOnAFailure(t *testing.T) {
	status, stdout, stderr := invoke(t, "check",
		"--proposal", replay2026918+"/bucket0-horizon.proposal.json",
		"--registry", "../../../registry", "--snapshots", replay2026918,
		"--reviewed", "--envelope")
	if status != exitFails {
		t.Fatalf("exited %d, want %d: %s", status, exitFails, stderr)
	}
	if strings.Contains(stdout, "order_envelope") {
		t.Error("an envelope was issued for a failing verdict")
	}
	if !strings.Contains(stderr, "no envelope: the verdict is fails") {
		t.Errorf("stderr does not say why: %q", stderr)
	}
	var result map[string]any
	if err := json.Unmarshal([]byte(stdout), &result); err != nil {
		t.Fatal(err)
	}
	if result["execution_readiness"] != "blocked" {
		t.Errorf("readiness is %v, want blocked", result["execution_readiness"])
	}
}
