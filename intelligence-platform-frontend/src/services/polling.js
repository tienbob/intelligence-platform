// One request at a time; hidden tabs resume immediately when visible.
export function startPolling(load, interval, visibility = document) {
  let stopped = false;
  let running = false;
  let terminal = false;
  let timer;
  const active = () => !stopped;
  async function run() {
    clearTimeout(timer);
    if (stopped || running || terminal || visibility.hidden) return;
    running = true;
    try {
      terminal = (await load(active)) === false;
    } finally {
      running = false;
      if (!stopped && !terminal && !visibility.hidden && interval > 0) {
        timer = setTimeout(run, interval);
      }
    }
  }
  function onVisibility() {
    clearTimeout(timer);
    if (!visibility.hidden) run();
  }
  visibility.addEventListener('visibilitychange', onVisibility);
  run();
  return () => {
    stopped = true;
    clearTimeout(timer);
    visibility.removeEventListener('visibilitychange', onVisibility);
  };
}
