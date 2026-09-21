// A fake exchange, on nothing. It records every request and answers a script.
//
// Nothing here opens a socket: `send` is a function, so a test drives the order path
// without a server, a port or any chance of reaching a real venue.

export type Scenario =
  | "full-fill"
  | "partial-fill"
  | "no-fill"
  | "rejected"
  | "timeout"
  | "duplicate"
  | "server-error"
  | "rate-limited"
  | "redirected";

/** Every scenario, so a test can sweep them all rather than naming a few. */
export const SCENARIOS: readonly Scenario[] = [
  "full-fill",
  "partial-fill",
  "no-fill",
  "rejected",
  "timeout",
  "duplicate",
  "server-error",
  "rate-limited",
  "redirected",
];

export interface Request {
  readonly url: string;
  readonly body: string;
}

export class FakeExchange {
  readonly requests: Request[] = [];
  private scenario: Scenario = "full-fill";
  private filled = "0";

  script(scenario: Scenario, filled = "0"): void {
    this.scenario = scenario;
    this.filled = filled;
  }

  /** The injected sender. Records first, so a timeout still leaves a record. */
  readonly send = async (url: string, body: string): Promise<{ status: number; body: string }> => {
    this.requests.push({ url, body });
    switch (this.scenario) {
      case "full-fill":
        return { status: 200, body: this.resting(this.sizeOf(body)) };
      case "partial-fill":
        return { status: 200, body: this.resting(this.filled) };
      case "no-fill":
        return { status: 200, body: this.resting("0") };
      case "rejected":
        return {
          status: 200,
          body: JSON.stringify({
            status: "err",
            response: "Order could not immediately match against any resting orders.",
          }),
        };
      case "timeout":
        throw new Error("socket hang up");
      // NON-200 ANSWERS. Without these every scenario returned 200, so a retry
      // conditioned on the status -- the way anyone would actually write one -- was
      // never exercised, and a duplicate live order would have gone unnoticed.
      case "server-error":
        return { status: 503, body: "upstream unavailable" };
      case "rate-limited":
        return { status: 429, body: "slow down" };
      case "redirected":
        return { status: 307, body: "" };
      case "duplicate":
        // The venue answered twice for one request. A caller that sent once must
        // not conclude it sent twice.
        return { status: 200, body: this.resting(this.sizeOf(body)) };
    }
  };

  private sizeOf(body: string): string {
    const order = JSON.parse(body).action.orders[0];
    return order.s as string;
  }

  private resting(filled: string): string {
    return JSON.stringify({
      status: "ok",
      response: {
        type: "order",
        data: { statuses: [{ filled: { totalSz: filled, avgPx: "0.17399", oid: 1 } }] },
      },
    });
  }
}

/** What actually filled, read from the venue's answer. */
export function filledSize(body: string): string {
  const parsed = JSON.parse(body);
  if (parsed.status !== "ok") return "0";
  const status = parsed.response?.data?.statuses?.[0];
  if (status?.filled?.totalSz !== undefined) return String(status.filled.totalSz);
  return "0";
}
