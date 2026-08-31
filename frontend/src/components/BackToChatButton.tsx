import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeftIcon, ChatIcon } from "./Icons";

const CAME_FROM_CHAT_KEY = "auremont_came_from_chat";

/** Set right before a chat listing card's link opens a catalogue page in a new tab (see
 * PropertyListingCarousel.tsx) — a `target="_blank"` navigation clones the opener's
 * sessionStorage into the new tab, so this flag survives there even though it never
 * touches the original chat tab. */
export function markCameFromChat(): void {
  try {
    sessionStorage.setItem(CAME_FROM_CHAT_KEY, "1");
  } catch {
    // Private-browsing or storage-blocked: the back button just won't show. Not fatal.
  }
}

/** Floating "back to chat" affordance for a tab that was opened from a listing card link.
 *
 * The customer's actual conversation lives on a separate `/chat` tab, untouched — this
 * button exists only because the alternative, the floating ChatWidget bubble in the
 * corner, starts a *different* mini conversation rather than returning to the one they
 * were already having. `/chat` resumes the real session on load (it reads the same
 * localStorage-backed session id/token this tab already has, being same-origin), so a
 * plain link back there is enough — no state to hand off manually.
 */
export function BackToChatButton() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      setVisible(sessionStorage.getItem(CAME_FROM_CHAT_KEY) === "1");
    } catch {
      setVisible(false);
    }
  }, []);

  if (!visible) return null;

  return (
    <Link to="/chat" className="back-to-chat-btn">
      <ArrowLeftIcon size={15} />
      <ChatIcon size={15} />
      Quay lại đoạn chat
    </Link>
  );
}
