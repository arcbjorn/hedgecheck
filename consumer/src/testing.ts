// The injectable gate, for tests only.
//
// `gate()` in `gate.ts` is bound to the real checker and takes no verifier: a caller
// on the production path cannot substitute one that always accepts. That seam used to
// sit in `Policy.verifier`, in the signature `run.ts` itself calls.
//
// A test still needs it. Driving a checker that THROWS is not reachable any other way
// -- `verify` catches its own faults and returns `ENGINE_DISAGREES`, so nothing inside
// a bundle makes it throw -- and the gate must answer "nothing was checked" for a
// wiring fault rather than "the bundle was refused".
//
// So the seam lives here, in a module `run.ts` does not import. A guard in
// `consumer/test/gate.test.ts` fails if it ever does.

export { gateWith } from "./gate.ts";
export type { Verifier } from "./gate.ts";
