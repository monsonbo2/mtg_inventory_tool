export const DEFAULT_SIGN_IN_URL = "/oauth2/start?rd={returnTo}";
export const DEFAULT_SIGN_OUT_URL = "/oauth2/sign_out?rd={returnTo}";

const configuredSignInUrl =
  import.meta.env.VITE_AUTH_SIGN_IN_URL?.trim() || DEFAULT_SIGN_IN_URL;
const configuredSignOutUrl =
  import.meta.env.VITE_AUTH_SIGN_OUT_URL?.trim() || DEFAULT_SIGN_OUT_URL;

function buildAuthUrl(template: string, returnTo: string) {
  const nextReturnTo = returnTo || "/";
  return template.split("{returnTo}").join(encodeURIComponent(nextReturnTo));
}

export function getCurrentReturnToPath() {
  if (typeof window === "undefined") {
    return "/";
  }
  return `${window.location.pathname}${window.location.search}${window.location.hash}` || "/";
}

export function getSignInUrl(returnTo = getCurrentReturnToPath()) {
  return buildAuthUrl(configuredSignInUrl, returnTo);
}

export function getSignOutUrl(returnTo = "/") {
  return buildAuthUrl(configuredSignOutUrl, returnTo);
}
