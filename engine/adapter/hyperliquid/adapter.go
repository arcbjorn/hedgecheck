// Package hyperliquid is the only package in the engine that speaks HTTP as a client.
//
// Read-only POST to one endpoint, three request types, one request per 1.5 seconds,
// at most 40 per run. No other endpoint, no websocket, no key, no signing, no account
// data. Every response is stored as exact bytes under its SHA-256, beside a request
// record that says what was asked and when.
//
// T2's live path is this package and nothing else; the arch test holds that.
package hyperliquid

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"hedgecheck/engine/run"
)

// Endpoint is the only URL this package will call.
const Endpoint = "https://api.hyperliquid.xyz/info"

// Pace and Budget bound a run. The pace is a courtesy to a public endpoint; the
// budget is a guard against a loop that would otherwise hammer it.
const (
	Pace   = 1500 * time.Millisecond
	Budget = 40
)

// allowed is the closed set of request types. A type not named here is not sent, so a
// typo cannot reach an endpoint this package was not built to call.
var allowed = map[string]bool{"outcomeMeta": true, "metaAndAssetCtxs": true, "l2Book": true}

// BudgetSpent reports a run that has used its request allowance.
type BudgetSpent struct{ Budget int }

func (e *BudgetSpent) Error() string {
	return fmt.Sprintf("the %d-request budget for this run is spent", e.Budget)
}

// Client is a rate-limited, budgeted caller of one endpoint.
type Client struct {
	HTTP   *http.Client
	Pace   time.Duration
	Budget int

	// endpoint is unexported and empty by default, so a zero Client calls the real
	// venue and nothing outside this package can redirect it. Tests in this package
	// point it at a local server; no production path ever sets it.
	endpoint string
	spent    int
	last     time.Time
}

// url is the endpoint this client calls: the real one unless a test overrode it.
func (c *Client) url() string {
	if c.endpoint == "" {
		return Endpoint
	}
	return c.endpoint
}

// NewClient builds a client with the pace and budget this package requires.
func NewClient() *Client {
	return &Client{
		HTTP:   &http.Client{Timeout: 30 * time.Second},
		Pace:   Pace,
		Budget: Budget,
	}
}

// Spent reports how many requests this run has made.
func (c *Client) Spent() int { return c.spent }

// Response is retained bytes with the record of how they were obtained.
type Response struct {
	Digest string
	Raw    []byte
	Record []byte
}

// Fetch makes one request and returns the exact bytes with a request record.
func (c *Client) Fetch(body map[string]any) (Response, error) {
	kind, _ := body["type"].(string)
	if !allowed[kind] {
		return Response{}, fmt.Errorf("request type %q is not one of outcomeMeta, metaAndAssetCtxs, l2Book", kind)
	}
	if c.spent >= c.Budget {
		return Response{}, &BudgetSpent{Budget: c.Budget}
	}
	if !c.last.IsZero() {
		if wait := c.Pace - time.Since(c.last); wait > 0 {
			time.Sleep(wait)
		}
	}

	payload, err := json.Marshal(body)
	if err != nil {
		return Response{}, err
	}
	requestedAt := time.Now().UTC()
	request, err := http.NewRequest(http.MethodPost, c.url(), bytes.NewReader(payload))
	if err != nil {
		return Response{}, err
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := c.HTTP.Do(request)
	if err != nil {
		return Response{}, err
	}
	defer response.Body.Close()
	raw, err := io.ReadAll(response.Body)
	if err != nil {
		return Response{}, err
	}
	retrievedAt := time.Now().UTC()
	c.last = time.Now()
	c.spent++

	sum := sha256.Sum256(raw)
	digest := hex.EncodeToString(sum[:])
	record, err := json.MarshalIndent(map[string]any{
		"endpoint":        c.url(),
		"method":          http.MethodPost,
		"request_body":    body,
		"requested_at":    requestedAt.Format(time.RFC3339Nano),
		"retrieved_at":    retrievedAt.Format(time.RFC3339Nano),
		"http_status":     response.StatusCode,
		"response_file":   digest + ".json",
		"response_sha256": digest,
		"server_date":     response.Header.Get("Date"),
	}, "", "  ")
	if err != nil {
		return Response{}, err
	}
	return Response{Digest: digest, Raw: raw, Record: append(record, '\n')}, nil
}

// Catalogue, Contexts and Book are the three calls a capture makes. The coin is
// always discovered, never configured.
func (c *Client) Catalogue() (Response, error) {
	return c.Fetch(map[string]any{"type": "outcomeMeta"})
}

func (c *Client) Contexts() (Response, error) {
	return c.Fetch(map[string]any{"type": "metaAndAssetCtxs"})
}

func (c *Client) Book(coin string) (Response, error) {
	return c.Fetch(map[string]any{"type": "l2Book", "coin": coin})
}

// BookTime reads an l2Book's venue timestamp, in milliseconds. It delegates to the
// pure reader so the live path and a replay cannot drift apart: two copies of one
// parser is two chances to disagree about what a retained byte means.
//
// The contexts response carries no venue timestamp, which is why capture skew is
// measured against a book and asserted rather than derived (EVIDENCE section 4).
func BookTime(raw []byte) (int64, bool) { return run.BookTime(raw) }

// RetrievedAt reads a request record's local retrieval time, in milliseconds.
func RetrievedAt(record []byte) (int64, bool) {
	var value struct {
		RetrievedAt string `json:"retrieved_at"`
	}
	if err := json.Unmarshal(record, &value); err != nil {
		return 0, false
	}
	moment, err := time.Parse(time.RFC3339Nano, value.RetrievedAt)
	if err != nil {
		return 0, false
	}
	return moment.UnixMilli(), true
}
