import { useRef, type MouseEvent } from "react";

// Minimum gap between spawned particles — mousemove fires far more often than this on a
// real mouse, and one particle per event would flood the DOM with overlapping glows.
const PARTICLE_SPAWN_INTERVAL_MS = 45;
const PARTICLE_LIFETIME_MS = 700;

const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Spawns one glowing dot at (x, y) inside `layer` that pops, glows, and fades out via the
 * `.cursor-particle` CSS animation, then removes itself — plain DOM manipulation (not React
 * state) so a fast mouse doesn't trigger a re-render per particle. `lastSpawnAt` is a ref
 * shared across calls to throttle spawn rate. */
function spawnCursorParticle(layer: HTMLDivElement | null, x: number, y: number, lastSpawnAt: { current: number }) {
  if (!layer || prefersReducedMotion()) return;
  const now = performance.now();
  if (now - lastSpawnAt.current < PARTICLE_SPAWN_INTERVAL_MS) return;
  lastSpawnAt.current = now;

  const particle = document.createElement("span");
  particle.className = "cursor-particle";
  particle.style.left = `${x}px`;
  particle.style.top = `${y}px`;
  // Slight per-particle variation so a trail of them doesn't look like one repeating stamp.
  particle.style.setProperty("--drift-x", `${(Math.random() - 0.5) * 24}px`);
  particle.style.setProperty("--scale", `${0.7 + Math.random() * 0.6}`);
  layer.appendChild(particle);
  window.setTimeout(() => particle.remove(), PARTICLE_LIFETIME_MS);
}

/** Shared cursor-follow effect for `.chat-page` — a soft spotlight glow (--mx/--my custom
 * properties consumed by `.chat-page::before` in design-system.css) plus a trail of small
 * glowing particles (rendered into the returned `layerRef`'s div). Used by both
 * CustomerChatPage.tsx and ChatWindow.tsx so the two chat surfaces stay visually consistent
 * without duplicating this logic. */
export function useCursorTrail() {
  const layerRef = useRef<HTMLDivElement>(null);
  const lastParticleAt = useRef(0);

  const handleMouseMove = (e: MouseEvent<HTMLElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    e.currentTarget.style.setProperty("--mx", `${(x / rect.width) * 100}%`);
    e.currentTarget.style.setProperty("--my", `${(y / rect.height) * 100}%`);
    spawnCursorParticle(layerRef.current, x, y, lastParticleAt);
  };

  return { layerRef, handleMouseMove };
}
