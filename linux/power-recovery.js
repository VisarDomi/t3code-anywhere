// Shared by the installed bundle repair and its network-failure tests.
const T3_RECOVERY_OFFLINE = "T3_POWER_RECOVERY_WAITING_FOR_INTERNET";
let t3RecoveryProbe = null;

async function t3RecoveryWaitForInternet() {
  if (t3RecoveryProbe === null) {
    t3RecoveryProbe = Promise.all([
      "https://www.gstatic.com/generate_204",
      "https://cp.cloudflare.com/generate_204",
    ].map(async (url) => {
      try {
        const response = await fetch(url, {
          redirect: "error",
          credentials: "omit",
          cache: "no-store",
          signal: AbortSignal.timeout(5000),
        });
        await response.body?.cancel();
        return response.status === 204;
      } catch {
        return false;
      }
    })).then((results) => {
      if (!results.some(Boolean)) throw new Error(T3_RECOVERY_OFFLINE);
    }).finally(() => { t3RecoveryProbe = null; });
  }
  await t3RecoveryProbe;
}

function t3RecoveryWaiting(effectType, error) {
  return effectType === "provider-runtime.continue" &&
    String(error).includes(T3_RECOVERY_OFFLINE);
}
