// Package engine is the root of the HedgeCheck engine module.
//
// Pure packages (exact, canon, and later pwa, ir, lower, evaluate, result) compute and do
// nothing else: no network, no filesystem, no clock, no randomness, no floating point, no
// third-party code. Only adapter, store, service and cmd may touch the outside world.
// arch_test.go enforces this; see ARCHITECTURE.md section 4.
package engine
