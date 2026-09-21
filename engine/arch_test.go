package engine

import (
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// Packages allowed to touch the outside world. Everything else is pure.
var impure = map[string]bool{"adapter": true, "store": true, "service": true, "cmd": true}

// Imports a pure package may not use outside its tests.
var forbidden = []string{"net", "os", "time", "syscall", "unsafe", "math/rand", "crypto/rand", "database/sql", "io/ioutil", "log", "math"}

func TestPurePackagesStayPure(t *testing.T) {
	checked := 0
	err := filepath.WalkDir(".", func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return err
		}
		top := strings.Split(filepath.ToSlash(path), "/")[0]
		if impure[top] || !strings.Contains(filepath.ToSlash(path), "/") {
			return nil
		}
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			return err
		}
		checked++
		for _, spec := range file.Imports {
			name := strings.Trim(spec.Path.Value, `"`)
			first := strings.Split(name, "/")[0]
			if strings.Contains(first, ".") {
				t.Errorf("%s imports third-party %s", path, name)
			}
			for _, banned := range forbidden {
				if name == banned || (banned != "math" && strings.HasPrefix(name, banned+"/")) {
					t.Errorf("%s imports %s; pure packages compute and do nothing else", path, name)
				}
			}
			// AN IMPURE PROJECT PACKAGE IS AS IMPURE AS `os`.
			//
			// The stdlib list above missed the likelier route: `hedgecheck/engine/store`
			// carries no dot in its first segment and is in no banned list, so the pure
			// kernel could import it and this test stayed green -- proven by making
			// `pwa` import `store` and watching it pass. Purity is not "does not name
			// os", it is "cannot reach the outside world", and an import of something
			// that can reaches it too.
			if inner, ok := strings.CutPrefix(name, "hedgecheck/engine/"); ok {
				if impure[strings.Split(inner, "/")[0]] {
					t.Errorf("%s imports %s, which is impure; purity is not transitive through an import", path, name)
				}
			}
		}
		ast.Inspect(file, func(node ast.Node) bool {
			if ident, ok := node.(*ast.Ident); ok && (ident.Name == "float32" || ident.Name == "float64") {
				t.Errorf("%s uses %s; arithmetic is exact", path, ident.Name)
			}
			if literal, ok := node.(*ast.BasicLit); ok && literal.Kind == token.FLOAT {
				t.Errorf("%s contains the float literal %s", path, literal.Value)
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if checked == 0 {
		t.Fatal("no pure source files found; the test is not looking where it should")
	}
}

// math/big mutates its receivers. Exactly one package may hold that, and it wraps it
// in an immutable value type; everywhere else a shared number would be a silent wrong
// answer rather than a crash.
func TestOnlyExactImportsMathBig(t *testing.T) {
	checked := 0
	err := filepath.WalkDir(".", func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() || !strings.HasSuffix(path, ".go") {
			return err
		}
		slashed := filepath.ToSlash(path)
		if strings.HasPrefix(slashed, "exact/") {
			return nil
		}
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			return err
		}
		checked++
		for _, spec := range file.Imports {
			if strings.Trim(spec.Path.Value, `"`) == "math/big" {
				t.Errorf("%s imports math/big; only exact may, and it hands out immutable values", slashed)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if checked == 0 {
		t.Fatal("no files outside exact were checked; the test is not looking where it should")
	}
}

// An outcome id or a coin in non-test source is configuration, and configuration goes
// stale the moment the venue rolls the series over. Tests may name them: that is where
// the expectations live.
func TestNoLiteralInstrumentsOutsideTests(t *testing.T) {
	coin := regexp.MustCompile(`"#[0-9]+"`)
	ident := regexp.MustCompile(`(?:^|[^\w.#/-])([0-9]{4,5})(?:[^\w.]|$)`)
	// Four-digit numbers that are demonstrably not outcome ids: file modes, a
	// kilobyte, the request pace, a year, the reference year in Go's date layout,
	// the skew bound, the RFC number for canonical JSON, and the loopback port the
	// service binds. Each is here because it means something else, not because the
	// check was inconvenient.
	allowed := map[string]bool{
		"0644": true, "0755": true, "1000": true, "1024": true, "1500": true,
		"2006": true, "2026": true, "5000": true, "8785": true, "8787": true,
	}
	checked := 0
	err := filepath.WalkDir(".", func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return err
		}
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.ParseComments)
		if err != nil {
			return err
		}
		checked++
		// Comments may cite a historical id as evidence; code may not.
		var code strings.Builder
		ast.Inspect(file, func(node ast.Node) bool {
			if literal, ok := node.(*ast.BasicLit); ok {
				code.WriteString(literal.Value)
				code.WriteString("\n")
			}
			return true
		})
		text := code.String()
		if coin.MatchString(text) {
			t.Errorf("%s: contains a literal coin", path)
		}
		for _, match := range ident.FindAllStringSubmatch(text, -1) {
			if !allowed[match[1]] {
				t.Errorf("%s: contains the literal %s, which is the shape of an outcome id", path, match[1])
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if checked == 0 {
		t.Fatal("no non-test sources were scanned")
	}
}

// The adapter is the only package that speaks HTTP, and only the two packages that
// orchestrate may reach it. If a pure package could import it, "pure" would depend on
// what the adapter happened to do rather than on anything this test can see.
func TestOnlyCmdAndServiceImportTheAdapter(t *testing.T) {
	mayImport := map[string]bool{"cmd": true, "service": true, "adapter": true}
	checked, seen := 0, false
	err := filepath.WalkDir(".", func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() || !strings.HasSuffix(path, ".go") {
			return err
		}
		slashed := filepath.ToSlash(path)
		top := strings.Split(slashed, "/")[0]
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			return err
		}
		checked++
		for _, spec := range file.Imports {
			name := strings.Trim(spec.Path.Value, `"`)
			if !strings.Contains(name, "hedgecheck/engine/adapter") {
				continue
			}
			seen = true
			if !mayImport[top] {
				t.Errorf("%s imports the adapter; only cmd and service may", slashed)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if checked == 0 {
		t.Fatal("no sources were scanned")
	}
	// Guards against the test passing because nothing imports the adapter at all,
	// which would make it vacuous the day the import is added.
	if !seen {
		t.Skip("nothing imports the adapter yet")
	}
}

// Exactly one package makes outbound requests, and it is the adapter.
//
// TestPurePackagesStayPure keeps `net` out of the pure packages, but says nothing
// about the impure ones: without this, `store` or `cmd` could call the venue
// directly and slip the pace, the budget and the closed set of request types, which
// live in the adapter and nowhere else.
//
// A server is not a client. The service listens on loopback and must import net/http
// to do it, so it is allowed the package but not the outbound calls.
func TestOnlyTheAdapterMakesOutboundRequests(t *testing.T) {
	// Ways to start an outbound request with the standard library.
	callers := []string{
		"http.Get", "http.Post", "http.PostForm", "http.Head", "http.NewRequest",
		"http.NewRequestWithContext", "net.Dial", "net.DialTimeout", "url.Parse",
	}
	checked, seen := 0, 0
	err := filepath.WalkDir(".", func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return err
		}
		slashed := filepath.ToSlash(path)
		if strings.HasPrefix(slashed, "adapter/") {
			return nil
		}
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			return err
		}
		checked++
		ast.Inspect(file, func(node ast.Node) bool {
			call, ok := node.(*ast.CallExpr)
			if !ok {
				return true
			}
			selector, ok := call.Fun.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			receiver, ok := selector.X.(*ast.Ident)
			if !ok {
				return true
			}
			name := receiver.Name + "." + selector.Sel.Name
			for _, banned := range callers {
				if name == banned {
					t.Errorf("%s calls %s; only the adapter reaches the venue, and it is where the pace, the budget and the closed set of request types live", slashed, name)
				}
			}
			// A client's Do is the other way out.
			if selector.Sel.Name == "Do" && strings.Contains(receiver.Name, "lient") {
				t.Errorf("%s calls %s.Do; only the adapter reaches the venue", slashed, receiver.Name)
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if checked == 0 {
		t.Fatal("no sources were scanned")
	}
	// The adapter really does make the calls, so this is not vacuous.
	adapter, err := parser.ParseFile(token.NewFileSet(), "adapter/hyperliquid/adapter.go", nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	ast.Inspect(adapter, func(node ast.Node) bool {
		if call, ok := node.(*ast.CallExpr); ok {
			if selector, ok := call.Fun.(*ast.SelectorExpr); ok && selector.Sel.Name == "Do" {
				seen++
			}
		}
		return true
	})
	if seen == 0 {
		t.Error("the adapter makes no request; this test would pass on an engine that cannot fetch at all")
	}
}

func TestNoThirdPartyModules(t *testing.T) {
	raw, err := os.ReadFile("go.mod")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), "require") {
		t.Error("go.mod declares a dependency; the evaluation path is standard library only")
	}
}
