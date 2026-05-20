export function debugLog(...args) {
  // No-op in production, console.log in dev
  if (import.meta.env?.DEV) {
    console.log(...args);
  }
}
