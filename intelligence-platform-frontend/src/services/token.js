const TOKEN_KEY = 'mi_access_token';
const REFRESH_KEY = 'mi_refresh_token';
const USER_KEY = 'mi_user';
export const SESSION_EVENT = 'mi:session';
let generation = 0;
export const getSessionGeneration = () => generation;
export const getStoredToken = () => localStorage.getItem(TOKEN_KEY);
export const getStoredRefreshToken = () => localStorage.getItem(REFRESH_KEY);
function changed() {
  generation += 1;
  window.dispatchEvent(new Event(SESSION_EVENT));
}
export function storeTokens(accessToken, refreshToken) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken);
  else localStorage.removeItem(REFRESH_KEY);
  changed();
}
export function clearTokens() {
  for (const key of [TOKEN_KEY, REFRESH_KEY, USER_KEY]) localStorage.removeItem(key);
  changed();
}
export function getStoredUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); }
  catch { return null; }
}
export function storeUser(user) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  window.dispatchEvent(new Event(SESSION_EVENT));
}
