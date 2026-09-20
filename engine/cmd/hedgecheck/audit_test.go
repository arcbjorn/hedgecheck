package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const auditFixtures = "../../../fixtures/replay/2026-09-18"
const auditRegistry = "../../../registry"

// Exit status is the contract a caller branches on without parsing output:
// 0 passes, 1 fails, 2 needs review, 3 refused, 4 usage or technical error.
//
// A refusal is NOT a verdict: status 3 must never mean "the objective was evaluated
// and found wanting". These are checked on the real commands, which had no direct
// coverage at all.
func TestAuditExitStatusIsTheContract(t *testing.T) {
	proposal := filepath.Join(auditFixtures, "bucket0.proposal.json")
	if _, err := os.Stat(proposal); err != nil {
		t.Skip(err)
	}
	cases := []struct {
		what string
		args []string
		want []int
	}{
		{"check on a draft registry", []string{"check", "--proposal", proposal,
			"--registry", auditRegistry, "--snapshots", auditFixtures}, []int{exitNeedsReview}},
		{"check with --reviewed", []string{"check", "--proposal", proposal,
			"--registry", auditRegistry, "--snapshots", auditFixtures, "--reviewed"},
			[]int{exitPasses, exitFails}},
		{"lower alone", []string{"lower", "--proposal", proposal,
			"--registry", auditRegistry, "--snapshots", auditFixtures}, []int{exitPasses}},
		{"a missing proposal file", []string{"check", "--proposal", "/nonexistent",
			"--registry", auditRegistry, "--snapshots", auditFixtures}, []int{exitUsage}},
		{"no arguments at all", []string{}, []int{exitUsage}},
		{"an unknown command", []string{"frobnicate"}, []int{exitUsage}},
		{"an unknown flag", []string{"check", "--wat", "x"}, []int{exitUsage}},
		{"a flag with no value", []string{"check", "--proposal"}, []int{exitUsage}},
		{"check without --registry", []string{"check", "--proposal", proposal}, []int{exitUsage}},
		{"help", []string{"--help"}, []int{exitPasses}},
	}
	for _, testCase := range cases {
		status, stdout, stderr := invoke(t, testCase.args...)
		ok := false
		for _, want := range testCase.want {
			if status == want {
				ok = true
			}
		}
		if !ok {
			t.Errorf("%s: exit %d, want one of %v\nstdout: %.200s\nstderr: %.200s",
				testCase.what, status, testCase.want, stdout, stderr)
		}
	}
}

// A technical error never prints a verdict. "Could not read the book" and "the hedge
// does not meet your objective" are different answers, and conflating them would let
// a broken pipe read as a failed hedge.
func TestAuditTechnicalErrorPrintsNoVerdict(t *testing.T) {
	verdicts := []string{"passes", "fails", "needs_review"}
	cases := [][]string{
		{"check", "--proposal", "/nonexistent", "--registry", auditRegistry, "--snapshots", auditFixtures},
		{"lower", "--proposal", "/nonexistent", "--registry", auditRegistry, "--snapshots", auditFixtures},
		{"evaluate", "--lowered", "/nonexistent"},
		{"check", "--proposal", filepath.Join(auditFixtures, "bucket0.proposal.json"),
			"--registry", "/nonexistent", "--snapshots", auditFixtures},
	}
	for _, args := range cases {
		status, stdout, _ := invoke(t, args...)
		if status != exitUsage {
			t.Errorf("%v: exit %d, want %d for a technical error", args[0], status, exitUsage)
		}
		for _, verdict := range verdicts {
			if strings.Contains(stdout, verdict) {
				t.Errorf("%v: a technical error printed the verdict %q on stdout", args[0], verdict)
			}
		}
	}
}

// A proposal citing evidence that was not supplied is REFUSED (3), with its class on
// stderr, and prints no verdict.
func TestAuditRefusalIsExitThreeWithItsClass(t *testing.T) {
	// A snapshots directory that has no books: every citation misses.
	empty := t.TempDir()
	if err := os.WriteFile(filepath.Join(empty, "nothing.json"), []byte(`{"a":"b"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	proposal := filepath.Join(auditFixtures, "bucket0.proposal.json")
	if _, err := os.Stat(proposal); err != nil {
		t.Skip(err)
	}
	status, stdout, stderr := invoke(t, "check", "--proposal", proposal,
		"--registry", auditRegistry, "--snapshots", empty)
	if status != exitRefused {
		t.Errorf("exit %d, want %d (refused)\nstderr: %s", status, exitRefused, stderr)
	}
	if !strings.Contains(stderr, "SNAPSHOT_NOT_SUPPLIED") {
		t.Errorf("the refusal does not name its class: %q", stderr)
	}
	for _, verdict := range []string{"passes", "fails", "needs_review"} {
		if strings.Contains(stdout, verdict) {
			t.Errorf("a refusal printed the verdict %q", verdict)
		}
	}
}

// Canonical output is canonical: what `lower` writes, `evaluate` reads, with no
// reformatting in between.
func TestAuditLowerAndEvaluateComposeThroughFiles(t *testing.T) {
	proposal := filepath.Join(auditFixtures, "bucket0.proposal.json")
	if _, err := os.Stat(proposal); err != nil {
		t.Skip(err)
	}
	outFile := filepath.Join(t.TempDir(), "ir.json")
	handle, err := os.Create(outFile)
	if err != nil {
		t.Fatal(err)
	}
	errHandle, err := os.Create(filepath.Join(t.TempDir(), "err"))
	if err != nil {
		t.Fatal(err)
	}
	status := run([]string{"lower", "--proposal", proposal,
		"--registry", auditRegistry, "--snapshots", auditFixtures}, handle, errHandle)
	handle.Close()
	errHandle.Close()
	if status != exitPasses {
		t.Fatalf("lower exited %d", status)
	}
	status, _, stderr := invoke(t, "evaluate", "--lowered", outFile)
	if status != exitNeedsReview {
		t.Errorf("evaluate on lower's own output exited %d, want %d: %s",
			status, exitNeedsReview, stderr)
	}
}

// --pretty changes only the whitespace, never the content: a caller that pipes
// pretty output back in must get the same answer.
func TestAuditPrettyIsOnlyWhitespace(t *testing.T) {
	proposal := filepath.Join(auditFixtures, "bucket0.proposal.json")
	if _, err := os.Stat(proposal); err != nil {
		t.Skip(err)
	}
	write := func(pretty bool) string {
		t.Helper()
		path := filepath.Join(t.TempDir(), "ir.json")
		handle, err := os.Create(path)
		if err != nil {
			t.Fatal(err)
		}
		errHandle, _ := os.Create(filepath.Join(t.TempDir(), "e"))
		args := []string{"lower", "--proposal", proposal,
			"--registry", auditRegistry, "--snapshots", auditFixtures}
		if pretty {
			args = append(args, "--pretty")
		}
		if status := run(args, handle, errHandle); status != exitPasses {
			t.Fatalf("lower exited %d", status)
		}
		handle.Close()
		errHandle.Close()
		return path
	}
	compact, pretty := write(false), write(true)
	for _, path := range []string{compact, pretty} {
		status, _, stderr := invoke(t, "evaluate", "--lowered", path)
		if status != exitNeedsReview {
			t.Errorf("%s: evaluate exited %d: %s", filepath.Base(path), status, stderr)
		}
	}
}
