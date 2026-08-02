/** Eased mouse-wheel scrolling for the main content column.
 *
 * CSS `scroll-behavior: smooth` only eases *programmatic* scrolls (anchors,
 * scrollTo) — the wheel stays native. To make the wheel itself glide we take
 * the event over and interpolate scrollTop ourselves each frame.
 *
 * Deliberately conservative about what it hijacks:
 * - trackpads are left alone (they already emit smooth sub-pixel deltas;
 *   easing them again feels laggy and drifty),
 * - Ctrl+wheel (zoom) and horizontal scrolls pass through,
 * - a wheel over a nested scrollable box (the raw-log panel, the bridging
 *   timeline) scrolls that box natively instead,
 * - `prefers-reduced-motion` disables the whole thing.
 */
import { useEffect, type RefObject } from "react";

/** Fraction of the remaining distance covered per frame. Higher = snappier;
 * this lands at roughly a 200 ms glide at 60 fps without feeling floaty. */
const EASE = 0.18;
/** Below this the animation has visually arrived — snap and stop. */
const SETTLE_PX = 0.5;
/** Wheel notches are large integers (100/120); trackpads emit small and
 * often fractional deltas. Anything under this that isn't a whole number is
 * treated as a trackpad and left native. */
const TRACKPAD_DELTA_MAX = 30;

function isTrackpad(e: WheelEvent): boolean {
  return (
    e.deltaMode === 0 &&
    Math.abs(e.deltaY) < TRACKPAD_DELTA_MAX &&
    !Number.isInteger(e.deltaY)
  );
}

/** True when some element between `target` and `container` can absorb the
 * scroll itself — then the wheel belongs to that box, not to the page. */
function nestedScrollerAbsorbs(
  target: EventTarget | null,
  container: HTMLElement,
  deltaY: number,
): boolean {
  let node = target instanceof Node ? target : null;
  while (node && node !== container) {
    if (node instanceof HTMLElement) {
      const style = getComputedStyle(node);
      const scrollable =
        (style.overflowY === "auto" || style.overflowY === "scroll") &&
        node.scrollHeight > node.clientHeight;
      if (scrollable) {
        const atTop = node.scrollTop <= 0;
        const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 1;
        // only absorb if it can actually move the way the user is scrolling,
        // otherwise the page should keep scrolling past a maxed-out box
        if ((deltaY < 0 && !atTop) || (deltaY > 0 && !atBottom)) return true;
      }
    }
    node = node.parentNode;
  }
  return false;
}

export function useSmoothScroll(ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let target = el.scrollTop;
    let frame = 0;
    let animating = false;

    const maxScroll = () => Math.max(0, el.scrollHeight - el.clientHeight);

    const step = () => {
      const diff = target - el.scrollTop;
      if (Math.abs(diff) < SETTLE_PX) {
        el.scrollTop = target;
        animating = false;
        frame = 0;
        return;
      }
      el.scrollTop += diff * EASE;
      frame = requestAnimationFrame(step);
    };

    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.defaultPrevented) return;
      // Browsers freeze requestAnimationFrame in a hidden/occluded window. If
      // we swallowed the wheel there, the animation would never run and the
      // view would simply refuse to scroll — so hand it back to the browser.
      if (document.hidden) return;
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
      if (isTrackpad(e)) return;
      if (nestedScrollerAbsorbs(e.target, el, e.deltaY)) return;

      const delta = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      const next = Math.min(maxScroll(), Math.max(0, target + delta));
      // already pinned at the edge: let the browser do its normal thing
      if (next === target) return;

      e.preventDefault();
      target = next;
      if (!animating) {
        animating = true;
        frame = requestAnimationFrame(step);
      }
    };

    // Anything that moves the scroller by other means — page changes, the
    // scrollbar, keyboard — must retarget, or the next wheel tick would
    // animate back from a stale position.
    const onScroll = () => {
      if (!animating) target = el.scrollTop;
    };

    // Going hidden mid-glide would strand the scroll partway (no frames run
    // until the window is visible again) — land it immediately instead.
    const onVisibility = () => {
      if (!document.hidden || !animating) return;
      if (frame) cancelAnimationFrame(frame);
      el.scrollTop = target;
      animating = false;
      frame = 0;
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("scroll", onScroll, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("scroll", onScroll);
      document.removeEventListener("visibilitychange", onVisibility);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ref]);
}
