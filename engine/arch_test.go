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
	allowed := map[string]bool{"0644": true, "0755": true, "1000": true, "1024": true, "1500": true, "2026": true, "5000": true, "8785": true}
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

func TestNoThirdPartyModules(t *testing.T) {
	raw, err := os.ReadFile("go.mod")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), "require") {
		t.Error("go.mod declares a dependency; the evaluation path is standard library only")
	}
}
