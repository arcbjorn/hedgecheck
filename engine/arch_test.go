package engine

import (
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
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

func TestNoThirdPartyModules(t *testing.T) {
	raw, err := os.ReadFile("go.mod")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), "require") {
		t.Error("go.mod declares a dependency; the evaluation path is standard library only")
	}
}
