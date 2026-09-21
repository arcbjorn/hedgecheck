package main

import (
	"fmt"
	"os"
	"path/filepath"

	runner "hedgecheck/engine/run"
	"hedgecheck/engine/screen"
	"hedgecheck/engine/service"
	"hedgecheck/engine/store"
)

// commandServe runs the local service.
//
// It binds loopback and says so on startup. This holds a person's position sizes and
// answers questions about their money; a tool that quietly listened on every
// interface would be a tool that leaked them.
func commandServe(flags options, out, errOut *os.File) int {
	if flags.registry == "" {
		fmt.Fprintln(errOut, "serve needs --registry")
		return exitUsage
	}
	if flags.store == "" {
		fmt.Fprintln(errOut, "serve needs --store")
		return exitUsage
	}
	registry, err := loadRegistry(flags.registry, flags.reviewed)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	keep := store.New(flags.store)
	checkerModule, checkerAllowlist := loadChecker(flags.checker)
	server := &service.Server{
		Store: keep, Registry: registry,
		Checker: checkerModule, Allowlist: checkerAllowlist,
		Page: func(inputDigest string) ([]byte, error) {
			return renderStored(keep, inputDigest)
		},
	}
	address := flags.address
	if address == "" {
		address = service.Address
	}
	httpServer := server.NewHTTPServer(address)

	fmt.Fprintf(out, "hedgecheck serving on http://%s\n", address)
	fmt.Fprintln(out, "  POST /v1/checks                        lower, evaluate and store a proposal")
	fmt.Fprintln(out, "  GET  /v1/checks/{input_digest}         the stored result")
	fmt.Fprintln(out, "  GET  /v1/snapshots/{sha256}            the exact retained bytes")
	fmt.Fprintln(out, "  GET  /v1/registry/{semantics_version}  the reading a result used")
	if flags.reviewed {
		fmt.Fprintln(out, "warning: --reviewed treats every registry entry as reviewed. Fixtures only.")
	}
	if err := httpServer.ListenAndServe(); err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	return exitPasses
}

// loadChecker reads the built module and its allowlist from --checker.
//
// Read at start-up rather than embedded: embedding would put a second copy of a
// GENERATED file inside this package, and two copies of a checker is one copy too
// many. The build guard already fails if what is committed is stale, so the file on
// disk is the one the sources produce.
func loadChecker(directory string) (module []byte, allowlist []byte) {
	if directory == "" {
		return nil, nil
	}
	module, _ = os.ReadFile(filepath.Join(directory, "checker.js"))
	allowlist, _ = os.ReadFile(filepath.Join(directory, "allowlist.json"))
	return module, allowlist
}

// renderStored renders a stored result as the screen shows it, with the checker
// mounted when the bundle parts are present.
func renderStored(keep *store.Store, inputDigest string) ([]byte, error) {
	raw, err := keep.Run(inputDigest)
	if err != nil {
		return nil, err
	}
	document, err := runner.Decode(raw)
	if err != nil {
		return nil, err
	}
	page, err := pageFor(document)
	if err != nil {
		return nil, err
	}
	// Verifiable only when the parts a checker needs are really stored: a page that
	// offered a check it could not run would be worse than one that offered none.
	if _, err := keep.BundlePart(inputDigest, "proposal"); err == nil {
		if _, err := keep.BundlePart(inputDigest, "lowered"); err == nil {
			page.Verifiable = true
			page.CheckDigest = inputDigest
		}
	}
	return screen.Render(page)
}
