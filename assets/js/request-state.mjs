// A resource has one current request. Old responses cannot change its state.
export function createRequestState(onChange = () => {}) {
  const resources = new Map();
  let sequence = 0;
  const get = (key) => resources.get(key) || { status: "idle", token: 0, label: key, error: null, updatedAt: null };
  const set = (key, value) => { resources.set(key, value); onChange(key, value); };
  return {
    get,
    entries: () => [...resources.entries()],
    start(key, label = key) {
      const token = ++sequence;
      set(key, { ...get(key), token, label, status: "loading", error: null });
      return token;
    },
    finish(key, token, status, error = null) {
      if (get(key).token !== token) return false;
      set(key, { ...get(key), status, error, updatedAt: status === "ready" ? new Date().toISOString() : get(key).updatedAt });
      return true;
    },
    invalidate(key) {
      set(key, { ...get(key), token: ++sequence, status: "idle", error: null });
    },
  };
}
