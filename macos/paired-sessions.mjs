// Pairing mode: a device paired through a pairing link gets a 100-year session instead of
// 30 days (owner request, 2026-11-12).
//
// The same edit as patch_sessions() in linux/power-recovery.py; the tests check that both
// produce identical output. Only issuing changes: every expiry check stays upstream's, so
// a device paired in pairing mode stays signed in on every later, unmodified T3. Only
// exact, singly occurring anchors are accepted; anything else throws and the caller keeps
// the original code.

export const SESSION_MARKER = "// t3code-anywhere paired sessions v1";
export const SESSION_MODULE_ANCHOR = 'fn("SessionStore.verify")';
export const PAIRED_SESSION_HELPER =
  SESSION_MARKER + "\n" +
  "// Pairing mode: a device paired now keeps its session until it is revoked.\n" +
  "const T3_ANYWHERE_PAIRED_TTL = days(36500);\n";

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
  const exchange = /(ttl: hours\(1\)\s*\} : )\{\}(,\s*replaceActiveForSubjectAndMethod: grant\.method === "desktop-bootstrap",)/g;
  const found = source.match(exchange) ?? [];
  if (found.length !== 1) throw new Error("unsupported bundle: expected one pairing-link session exchange");
  return source.replace(exchange,
    (_, before, after) => before + 'grant.subject === "one-time-token" ? { ttl: T3_ANYWHERE_PAIRED_TTL } : {}' + after);
}
