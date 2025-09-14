// src/store/activityStore.js
let _subs = [];
let _rows = [];

// shape: { id, ts, kind, region, instance_id, instance_type, network, details }
export function addActivity(evt) {
  const row = {
    id: evt.id || cryptoRandom(),
    ts: evt.ts || Date.now(),
    ...evt,
  };
  _rows = [row, ..._rows].slice(0, 100); // keep latest 100
  _subs.forEach((fn) => fn(_rows));
}

export function getActivities() {
  return _rows;
}

export function subscribeActivities(fn) {
  _subs.push(fn);
  return () => {
    _subs = _subs.filter((x) => x !== fn);
  };
}

// simple random id
function cryptoRandom() {
  try {
    return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
      (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
    );
  } catch {
    return String(Math.random()).slice(2);
  }
}
