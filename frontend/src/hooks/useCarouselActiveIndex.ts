import { useEffect, useRef, useState } from "react";

/** Shared scroll-snap tracking for the chat's horizontal "peek" carousels (property
 * listings, answer photos): which of a track's direct-child slides is currently snapped
 * into view, plus a `scrollToIndex` for the arrow/dot controls to drive it.
 *
 * Keeps a running visibility ratio per slide rather than trusting a single
 * IntersectionObserver callback's own `entries` — each callback only contains the
 * slides whose ratio crossed a threshold *since the last callback*, not every slide
 * currently observed, so picking "most visible" from just that one callback let a
 * barely-peeking slide "win" over an already-dominant one simply because it fired most
 * recently. Comparing across the full running map is what makes this correct regardless
 * of which slide's threshold happened to fire last. */
export function useCarouselActiveIndex<T extends HTMLElement>(count: number) {
  const trackRef = useRef<T>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    const slides = Array.from(track.children) as HTMLElement[];
    if (slides.length === 0) return;

    const ratios = new Map<Element, number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          ratios.set(entry.target, entry.isIntersecting ? entry.intersectionRatio : 0);
        }
        let bestIdx = -1;
        let bestRatio = -1;
        slides.forEach((slide, i) => {
          const ratio = ratios.get(slide) ?? 0;
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestIdx = i;
          }
        });
        if (bestIdx !== -1) setActiveIndex(bestIdx);
      },
      { root: track, threshold: [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1] },
    );
    slides.forEach((s) => observer.observe(s));
    return () => observer.disconnect();
  }, [count]);

  const scrollToIndex = (i: number) => {
    const track = trackRef.current;
    if (!track) return;
    const clamped = Math.max(0, Math.min(i, count - 1));
    const slide = track.children[clamped] as HTMLElement | undefined;
    slide?.scrollIntoView({ behavior: "smooth", inline: "start", block: "nearest" });
  };

  return { trackRef, activeIndex, scrollToIndex };
}
