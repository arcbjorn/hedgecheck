package main

import (
	"fmt"
	"os"

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
	server := &service.Server{Store: store.New(flags.store), Registry: registry}
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
