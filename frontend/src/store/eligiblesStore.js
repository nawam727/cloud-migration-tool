// frontend/src/store/eligiblesStore.js
const KEY = "cmtool.lastEligibles";

let _eligibles = (() => {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || [];
  } catch {
    return [];
  }
})();

const subscribers = new Set();

export function getEligibles() {
  return _eligibles;
}

export function setEligibles(rows) {
  _eligibles = Array.isArray(rows) ? rows : [];
  try {
    localStorage.setItem(KEY, JSON.stringify(_eligibles));
  } catch {}
  subscribers.forEach((fn) => {
    try {
      fn(_eligibles);
    } catch {}
  });
}

// subscribe to changes; returns an unsubscribe function
export function subscribeEligibles(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}