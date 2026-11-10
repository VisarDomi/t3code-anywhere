// Paired devices keep their sessions until revoked (owner request, 2026-11-10).
//
// The same edit as patch_sessions() in linux/power-recovery.py; the tests check that
// both produce identical output. A session from a pairing link (bearer, subject
// `one-time-token`) no longer expires, including sessions issued before the patch.
// CLI-issued tokens, browser cookies and DPoP tokens keep their lifetimes. Only exact,
// singly occurring anchors are accepted; anything else throws and the caller keeps the
// original code.

export const SESSION_MARKER = "// t3code-anywhere paired sessions v1";
export const SESSION_MODULE_ANCHOR = 'fn("SessionStore.verify")';
export const PAIRED_SESSION_HELPER =
  SESSION_MARKER + "\n" +
  "// A device paired with a pairing link keeps its session until it is revoked.\n" +
  "const T3_ANYWHERE_PAIRED_TTL = days(36500);\n" +
  'const t3AnywherePaired = (session) => session.method === "bearer-access-token" && ' +
  '(session.subject ?? session.sub) === "one-time-token";\n';

function replaceOne(source, oldText, newText) {
  const count = source.split(oldText).length - 1;
  if (count !== 1) {
    throw new Error(`unsupported bundle: expected one ${JSON.stringify(oldText.slice(0, 100))}, found ${count}`);
  }
  return source.replace(oldText, () => newText);
}

export function patchSessions(source) {
  if (source.includes(SESSION_MARKER)) return source;
  if (!/\bas days\b/.test(source)) throw new Error("unsupported bundle: missing Duration.days import");
  source = replaceOne(source, "const DEFAULT_SESSION_TTL = days(30);\n",
    "const DEFAULT_SESSION_TTL = days(30);\n" + PAIRED_SESSION_HELPER);
  // New pairings get a 100-year session instead of 30 days.
  const exchange = /(ttl: hours\(1\)\s*\} : )\{\}(,\s*replaceActiveForSubjectAndMethod: grant\.method === "desktop-bootstrap",)/g;
  const found = source.match(exchange) ?? [];
  if (found.length !== 1) throw new Error("unsupported bundle: expected one pairing-link session exchange");
  source = source.replace(exchange,
    (_, before, after) => before + 'grant.subject === "one-time-token" ? { ttl: T3_ANYWHERE_PAIRED_TTL } : {}' + after);
  // Sessions paired before the patch carry a signed and a stored 30-day expiry.
  source = replaceOne(source,
    "if (claims.exp <= observedAt.epochMilliseconds) return yield* new SessionTokenExpiredError({",
    "if (claims.exp <= observedAt.epochMilliseconds && !t3AnywherePaired(claims)) " +
    "return yield* new SessionTokenExpiredError({");
  source = replaceOne(source,
    "if (!connected && row.value.expiresAt.epochMilliseconds <=",
    "if (!connected && !t3AnywherePaired(row.value) && row.value.expiresAt.epochMilliseconds <=");
  source = replaceOne(source,
    "if (row.value.expiresAt.epochMilliseconds <= observedAt.epochMilliseconds) " +
    "return yield* new WebSocketSessionExpiredError({",
    "if (!t3AnywherePaired(row.value) && row.value.expiresAt.epochMilliseconds <= " +
    "observedAt.epochMilliseconds) return yield* new WebSocketSessionExpiredError({");
  // A live socket is closed at its session's expiry; a paired one only on revocation.
  source = replaceOne(source,
    "const remaining = current.expiresAt.epochMilliseconds - ",
    "const remaining = t3AnywherePaired(current) ? 2147483647 : current.expiresAt.epochMilliseconds - ");
  // `t3 auth session list` and the app's connected-clients list.
  source = replaceOne(source,
    'AND (expires_at > ${now} OR ${sql.in("session_id", connectedSessionIds)})',
    "AND (expires_at > ${now} OR (method = 'bearer-access-token' AND subject = 'one-time-token') " +
    'OR ${sql.in("session_id", connectedSessionIds)})');
  return source;
}
