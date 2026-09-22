// Package doc decodes and encodes contract documents, strictly.
//
// Not encoding/json struct decoding. That matches keys case-insensitively, silently
// ignores fields it does not know, and accepts a number where a string is meant. A
// contract document that loses a field on the way in is worse than one that is
// rejected: the field it dropped might have been the objective.
//
// So every document is read from a `canon` value through an explicit reader that
// consumes each key it knows and refuses anything left over. What the schema states,
// this enforces; semantics the schema cannot state live here too, beside the types
// they belong to.
package doc

import (
	"fmt"
	"regexp"
	"strings"

	"hedgecheck/engine/canon"
	"hedgecheck/engine/exact"
)

// Error names the path at which a document failed, so a refusal says where.
type Error struct {
	Path string
	Why  string
}

func (e *Error) Error() string {
	if e.Path == "" {
		return e.Why
	}
	return e.Path + ": " + e.Why
}

func fail(path, why string, args ...any) error {
	return &Error{Path: path, Why: fmt.Sprintf(why, args...)}
}

var (
	timePattern   = regexp.MustCompile(`\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\z`)
	datePattern   = regexp.MustCompile(`\A[0-9]{4}-[0-9]{2}-[0-9]{2}\z`)
	digestPattern = regexp.MustCompile(`\A[0-9a-f]{64}\z`)
	slugPattern   = regexp.MustCompile(`\A[a-z][a-z0-9_]*\z`)
	legIDPattern  = regexp.MustCompile(`\A[a-z][a-z0-9-]*\z`)
	codePattern   = regexp.MustCompile(`\A[A-Z][A-Z0-9_]*\z`)
	intPattern    = regexp.MustCompile(`\A-?(?:0|[1-9][0-9]*)\z`)
	// defs.schema.json #/$defs/digits: a non-negative integer with no leading zero.
	digitsPattern = regexp.MustCompile(`\A(?:0|[1-9][0-9]*)\z`)
	coinPattern   = regexp.MustCompile(`\A#[0-9]{1,12}\z`)
	refPattern    = regexp.MustCompile(`\A(?:synthetic|[a-z0-9]+(?::[A-Za-z0-9/._-]+){2,4})\z`)
	// A reference TEMPLATE, as a registry entry carries: like a reference id, but a whole
	// segment may be a {placeholder} an instance resolves. PLAN section 6 says a reference
	// is "never free text"; the entry's was read with no pattern at all, so "free text
	// here" and "" were accepted.
	refTemplatePattern = regexp.MustCompile(`\A(?:synthetic|[a-z0-9]+(?::(?:\{[a-z_]+\}|[A-Za-z0-9/._-])+){2,4})\z`)
)

// reader consumes an object's keys one at a time and refuses whatever is left.
// Forgetting to read a key is therefore an error, not a silent drop.
type reader struct {
	path   string
	fields map[string]any
	err    error
}

func object(path string, value any) (*reader, error) {
	fields, ok := value.(map[string]any)
	if !ok {
		return nil, fail(path, "expected an object")
	}
	copied := make(map[string]any, len(fields))
	for key, item := range fields {
		copied[key] = item
	}
	return &reader{path: path, fields: copied}, nil
}

func (r *reader) at(key string) string {
	if r.path == "" {
		return key
	}
	return r.path + "." + key
}

func (r *reader) take(key string) (any, bool) {
	value, ok := r.fields[key]
	delete(r.fields, key)
	return value, ok
}

func (r *reader) note(err error) {
	if r.err == nil {
		r.err = err
	}
}

// done refuses any key the caller did not read. This is the rule that makes an
// unknown field an error rather than a shrug.
func (r *reader) done() error {
	if r.err != nil {
		return r.err
	}
	if len(r.fields) == 0 {
		return nil
	}
	leftover := make([]string, 0, len(r.fields))
	for key := range r.fields {
		leftover = append(leftover, key)
	}
	sortStrings(leftover)
	return fail(r.path, "unexpected key %q", leftover[0])
}

// ---------------------------------------------------------------- scalars

func (r *reader) str(key string, pattern *regexp.Regexp, what string) string {
	value, ok := r.take(key)
	if !ok {
		r.note(fail(r.at(key), "missing"))
		return ""
	}
	text, ok := value.(string)
	if !ok {
		r.note(fail(r.at(key), "expected a string"))
		return ""
	}
	if pattern != nil && !pattern.MatchString(text) {
		r.note(fail(r.at(key), "%q is not %s", text, what))
		return ""
	}
	return text
}

func (r *reader) optionalStr(key string, pattern *regexp.Regexp, what string) (string, bool) {
	if _, present := r.fields[key]; !present {
		return "", false
	}
	return r.str(key, pattern, what), true
}

// number reads an exact number through the one grammar. A rational library would
// accept "1e3" and "0x10"; the grammar is enforced before it ever sees the string.
func (r *reader) number(key string) exact.Q {
	value, ok := r.take(key)
	if !ok {
		r.note(fail(r.at(key), "missing"))
		return exact.Q{}
	}
	text, ok := value.(string)
	if !ok {
		r.note(fail(r.at(key), "a number travels as a string"))
		return exact.Q{}
	}
	number, err := exact.ParseQ(text)
	if err != nil {
		r.note(fail(r.at(key), "%q is not in the number grammar", text))
		return exact.Q{}
	}
	return number
}

func (r *reader) optionalNumber(key string) (exact.Q, bool) {
	if _, present := r.fields[key]; !present {
		return exact.Q{}, false
	}
	return r.number(key), true
}

func (r *reader) boolean(key string) bool {
	value, ok := r.take(key)
	if !ok {
		r.note(fail(r.at(key), "missing"))
		return false
	}
	flag, ok := value.(bool)
	if !ok {
		r.note(fail(r.at(key), "expected true or false"))
		return false
	}
	return flag
}

func (r *reader) optionalBool(key string) (bool, bool) {
	if _, present := r.fields[key]; !present {
		return false, false
	}
	return r.boolean(key), true
}

func (r *reader) enum(key string, allowed ...string) string {
	text := r.str(key, nil, "")
	if text == "" {
		return ""
	}
	for _, option := range allowed {
		if text == option {
			return text
		}
	}
	r.note(fail(r.at(key), "%q is not one of %s", text, strings.Join(allowed, ", ")))
	return ""
}

func (r *reader) list(key string, minimum int) []any {
	value, ok := r.take(key)
	if !ok {
		r.note(fail(r.at(key), "missing"))
		return nil
	}
	items, ok := value.([]any)
	if !ok {
		r.note(fail(r.at(key), "expected an array"))
		return nil
	}
	if len(items) < minimum {
		r.note(fail(r.at(key), "needs at least %d item(s), has %d", minimum, len(items)))
		return nil
	}
	return items
}

func (r *reader) optionalList(key string, minimum int) ([]any, bool) {
	if _, present := r.fields[key]; !present {
		return nil, false
	}
	return r.list(key, minimum), true
}

func (r *reader) sub(key string) (*reader, bool) {
	value, ok := r.take(key)
	if !ok {
		r.note(fail(r.at(key), "missing"))
		return nil, false
	}
	child, err := object(r.at(key), value)
	if err != nil {
		r.note(err)
		return nil, false
	}
	return child, true
}

func (r *reader) optionalSub(key string) (*reader, bool) {
	if _, present := r.fields[key]; !present {
		return nil, false
	}
	return r.sub(key)
}

func (r *reader) finish(child *reader) {
	if child == nil {
		return
	}
	if err := child.done(); err != nil {
		r.note(err)
	}
}

// at2 names an element inside a list, for an error that says exactly where.
func at2(path, key string, index int) string {
	return fmt.Sprintf("%s.%s[%d]", path, key, index)
}

func sortStrings(values []string) {
	for i := 1; i < len(values); i++ {
		for j := i; j > 0 && values[j] < values[j-1]; j-- {
			values[j], values[j-1] = values[j-1], values[j]
		}
	}
}

// parse reads raw bytes through the canonical profile before anything else looks at
// them, so a document outside the profile is refused for that reason.
func parse(raw []byte) (any, error) {
	value, err := canon.Parse(raw)
	if err != nil {
		return nil, &Error{Why: err.Error()}
	}
	return value, nil
}
