export type AvatarEmotion = "idle" | "greeting" | "thinking" | "happy" | "regretful" | "respectful";

interface Props {
  size?: number;
  /** Default "idle" — a gentle breathing/blink loop when nothing else is happening. */
  emotion?: AvatarEmotion;
  /** "full" (default) — the whole character, for roomy spots (chat landing hero). "face" —
   * just the head, cropped to a near-square. Small icon slots (the launcher button, a topbar
   * icon, a 20px per-message avatar) don't have room for legs/arms and the full body reads as
   * clutter at that size — this crops down to the one part built to read at a glance. */
  variant?: "full" | "face";
  className?: string;
}

// Aspect ratio of the composed character (torso + head + both arms + legs, see avatar.css for
// the per-part crop/position math) — height/width of the shared bounding box the five PNGs
// were extracted into. Keeps `size` driving both dimensions like the old square-ish SVG
// viewBox did.
const ASPECT_RATIO = 1082.27 / 670.8;

// head.png's own native aspect ratio (415/617) — used to size the "face" variant, which
// shows that image alone rather than the full composed-character bbox above.
const FACE_ASPECT_RATIO = 415 / 617;

// Custom character (head/torso/left arm/right arm/legs as separate transparent PNGs, see
// public/avatar/) composited here as absolutely-positioned <img> layers instead of one flat
// image, specifically so each part can rotate INDEPENDENTLY per emotion around its own pivot
// (shoulder for an arm, neck for the head) — a single flat PNG could only ever animate as one
// rigid unit. Position/size/pivot percentages and the animations driving them live in
// styles/avatar.css; this component only lays out the layers and toggles the emotion class.
export function AuremontAvatar({ size = 64, emotion = "idle", variant = "full", className }: Props) {
  if (variant === "face") {
    return (
      <div
        className={`aura-avatar aura-avatar--face aura-avatar--${emotion} ${className ?? ""}`}
        style={{ width: size, height: Math.round(size * FACE_ASPECT_RATIO) }}
        role="img"
        aria-label="Auremont AI"
      >
        <img className="aura-part aura-head" src="/avatar/head.png" alt="" aria-hidden="true" draggable={false} />
      </div>
    );
  }

  return (
    <div
      className={`aura-avatar aura-avatar--${emotion} ${className ?? ""}`}
      style={{ width: size, height: Math.round(size * ASPECT_RATIO) }}
      role="img"
      aria-label="Auremont AI"
    >
      <img className="aura-part aura-legs" src="/avatar/legs.png" alt="" aria-hidden="true" draggable={false} />
      <img className="aura-part aura-torso" src="/avatar/torso.png" alt="" aria-hidden="true" draggable={false} />
      <img className="aura-part aura-arm-left" src="/avatar/arm_left.png" alt="" aria-hidden="true" draggable={false} />
      <img className="aura-part aura-arm-right" src="/avatar/arm_right.png" alt="" aria-hidden="true" draggable={false} />
      {/* Dedicated open-palm wave pose (own source render — the resting arm's hand is
          curled/pointing, not shaped for a wave) — hidden except during "greeting", where it
          crossfades in over aura-arm-left. See avatar.css. */}
      <img className="aura-part aura-arm-wave" src="/avatar/arm_wave.png" alt="" aria-hidden="true" draggable={false} />
      <img className="aura-part aura-head" src="/avatar/head.png" alt="" aria-hidden="true" draggable={false} />
    </div>
  );
}
