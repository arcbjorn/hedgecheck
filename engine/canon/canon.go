// Package canon implements canonical JSON and digests: a strict profile of RFC 8785.
//
// Accepted documents are UTF-8 without a BOM and contain only objects, arrays, strings and
// booleans. Keys match [a-z][a-z0-9_]* and are unique. Strings are well-formed Unicode and
// do not contain U+FFFD, because encoding/json substitutes it silently for an escaped lone
// surrogate; admitting it would let two implementations digest different strings.
package canon

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"
)

// MaxDepth bounds nesting; every value counts, scalars included.
const MaxDepth = 32

var key = regexp.MustCompile(`\A[a-z][a-z0-9_]*\z`)

// ErrProfile reports a document outside the profile.
var ErrProfile = errors.New("outside the canonical JSON profile")

func reject(format string, args ...any) error {
	return fmt.Errorf("%w: %s", ErrProfile, fmt.Sprintf(format, args...))
}

// Parse decodes raw under the profile. Values are map[string]any, []any, string or bool.
func Parse(raw []byte) (any, error) {
	if bytes.HasPrefix(raw, []byte{0xEF, 0xBB, 0xBF}) {
		return nil, reject("byte order mark")
	}
	if !utf8.Valid(raw) {
		return nil, reject("invalid UTF-8")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	value, err := parseValue(decoder, 1)
	if err != nil {
		return nil, err
	}
	if _, err := decoder.Token(); err != io.EOF {
		return nil, reject("trailing text")
	}
	return value, nil
}

func parseValue(decoder *json.Decoder, depth int) (any, error) {
	token, err := decoder.Token()
	if err != nil {
		return nil, reject("%v", err)
	}
	return build(decoder, token, depth)
}

func build(decoder *json.Decoder, token json.Token, depth int) (any, error) {
	if depth > MaxDepth {
		return nil, reject("nested deeper than %d", MaxDepth)
	}
	switch typed := token.(type) {
	case bool:
		return typed, nil
	case string:
		if strings.ContainsRune(typed, utf8.RuneError) {
			return nil, reject("U+FFFD or a lone surrogate in a string")
		}
		return typed, nil
	case json.Number:
		return nil, reject("numbers are not allowed; write an exact string")
	case nil:
		return nil, reject("null")
	case json.Delim:
		if typed == '[' {
			list := []any{}
			for decoder.More() {
				item, err := parseValue(decoder, depth+1)
				if err != nil {
					return nil, err
				}
				list = append(list, item)
			}
			if _, err := decoder.Token(); err != nil {
				return nil, reject("%v", err)
			}
			return list, nil
		}
		object := map[string]any{}
		for decoder.More() {
			nameToken, err := decoder.Token()
			if err != nil {
				return nil, reject("%v", err)
			}
			name, ok := nameToken.(string)
			if !ok || !key.MatchString(name) {
				return nil, reject("key outside [a-z][a-z0-9_]*")
			}
			if _, seen := object[name]; seen {
				return nil, reject("duplicate key %q", name)
			}
			item, err := parseValue(decoder, depth+1)
			if err != nil {
				return nil, err
			}
			object[name] = item
		}
		if _, err := decoder.Token(); err != nil {
			return nil, reject("%v", err)
		}
		return object, nil
	}
	return nil, reject("unsupported token")
}

// Marshal returns the canonical bytes of a value produced by Parse or built to the profile.
func Marshal(value any) ([]byte, error) {
	var out bytes.Buffer
	if err := write(&out, value, 1); err != nil {
		return nil, err
	}
	return out.Bytes(), nil
}

// Digest returns the lowercase hex SHA-256 of the canonical bytes.
func Digest(value any) (string, error) {
	raw, err := Marshal(value)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), nil
}

func write(out *bytes.Buffer, value any, depth int) error {
	if depth > MaxDepth {
		return reject("nested deeper than %d", MaxDepth)
	}
	switch typed := value.(type) {
	case bool:
		if typed {
			out.WriteString("true")
		} else {
			out.WriteString("false")
		}
	case string:
		return writeString(out, typed)
	case []any:
		out.WriteByte('[')
		for index, item := range typed {
			if index > 0 {
				out.WriteByte(',')
			}
			if err := write(out, item, depth+1); err != nil {
				return err
			}
		}
		out.WriteByte(']')
	case map[string]any:
		names := make([]string, 0, len(typed))
		for name := range typed {
			if !key.MatchString(name) {
				return reject("key outside [a-z][a-z0-9_]*")
			}
			names = append(names, name)
		}
		// Keys are ASCII under the profile, so byte order equals RFC 8785's UTF-16 order.
		sort.Strings(names)
		out.WriteByte('{')
		for index, name := range names {
			if index > 0 {
				out.WriteByte(',')
			}
			if err := writeString(out, name); err != nil {
				return err
			}
			out.WriteByte(':')
			if err := write(out, typed[name], depth+1); err != nil {
				return err
			}
		}
		out.WriteByte('}')
	default:
		return reject("unsupported value %T", value)
	}
	return nil
}

func writeString(out *bytes.Buffer, text string) error {
	if !utf8.ValidString(text) || strings.ContainsRune(text, utf8.RuneError) {
		return reject("malformed string")
	}
	out.WriteByte('"')
	for _, char := range text {
		switch char {
		case '"':
			out.WriteString(`\"`)
		case '\\':
			out.WriteString(`\\`)
		case '\b':
			out.WriteString(`\b`)
		case '\f':
			out.WriteString(`\f`)
		case '\n':
			out.WriteString(`\n`)
		case '\r':
			out.WriteString(`\r`)
		case '\t':
			out.WriteString(`\t`)
		default:
			if char < 0x20 {
				fmt.Fprintf(out, `\u%04x`, char)
			} else {
				out.WriteRune(char)
			}
		}
	}
	out.WriteByte('"')
	return nil
}
