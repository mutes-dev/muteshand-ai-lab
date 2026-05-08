export function log(tag, payload) {
  try {
    console.log(`[GUI:${tag}]`, payload);
  } catch {}
}
