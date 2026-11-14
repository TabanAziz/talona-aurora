interface MotionClock {
  now: () => number;
  request: (callback: FrameRequestCallback) => number;
  cancel: (id: number) => void;
}
const browserClock: MotionClock = {
  now: () => performance.now(),
  request: (callback) => requestAnimationFrame(callback),
  cancel: (id) => cancelAnimationFrame(id),
};

/** A bounded camera command. Cancelling leaves the camera exactly where the user interrupted it. */
export function cameraTransition(update: (progress: number) => void, reducedMotion: boolean, clock = browserClock): () => void {
  if (reducedMotion) { update(1); return () => {}; }
  const started = clock.now();
  let cancelled = false;
  let frame = 0;
  const tick = () => {
    if (cancelled) return;
    const progress = Math.min(1, Math.max(0, (clock.now() - started) / 220));
    update(1 - Math.pow(1 - progress, 3));
    if (progress < 1) frame = clock.request(tick);
  };
  update(0);
  frame = clock.request(tick);
  return () => { cancelled = true; clock.cancel(frame); };
}
