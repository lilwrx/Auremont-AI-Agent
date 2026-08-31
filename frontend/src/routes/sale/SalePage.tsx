import { useCallback, useEffect, useState } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type { ChatSessionResponse } from "../../types";
import { ChatWindow } from "./ChatWindow";
import { SessionList } from "./SessionList";
import { ChatSuggestions } from "./ChatSuggestions";
import { AuremontAvatar } from "../../components/AuremontAvatar";
import { useAuth } from "../../hooks/useAuth";
import { useCursorTrail } from "../../hooks/useCursorTrail";

// ChatGPT-style shell: Session sidebar on the left, main chat panel, and a
// context panel on the right.
export function SalePage() {
  const { username } = useAuth();
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<ChatSessionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const { layerRef: particleLayerRef, handleMouseMove: handleChatMouseMove } = useCursorTrail();

  const reload = useCallback(() => {
    api
      .get<ChatSessionResponse[]>("/sale/sessions")
      .then(setSessions)
      .catch(() => setSessions([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(reload, [reload]);

  // Before a session is selected: create a new session as soon as the user types
  // or picks a suggestion, matching the "type to start" flow of the MOSO design.
  const startSession = useCallback(
    async (prefill?: string) => {
      const session = await api.post<ChatSessionResponse>("/sale/sessions", {});
      setSessions((prev) => [session, ...prev]);
      navigate(`/chat/sessions/${session.id}`, prefill ? { state: { prefill } } : undefined);
    },
    [navigate],
  );

  return (
    <div className="chat-shell">
      <SessionList sessions={sessions} loading={loading} onChange={setSessions} />
      <Routes>
        <Route path="sessions/:sessionId" element={<ChatWindow onSessionsChange={reload} />} />
        <Route
          path="*"
          element={
            <div className="chat-page" onMouseMove={handleChatMouseMove}>
              <div className="cursor-particle-layer" ref={particleLayerRef} aria-hidden="true" />
              <div className="chat-messages">
                <div className="chat-messages-inner">
                  <div className="chat-landing">
                    <AuremontAvatar size={64} emotion="greeting" className="chat-landing-mascot" />
                    <h2 className="chat-empty-title">Hỏi Auremont bằng câu nói của bạn</h2>
                    <p className="chat-empty-text">
                      Chào {username ?? "bạn"}, mô tả điều cần tra cứu — bảng giá, mặt bằng, chính sách bán hàng —
                      Auremont sẽ tự mở cuộc trò chuyện mới và trả lời kèm trích nguồn.
                    </p>
                    <ChatSuggestions onPick={startSession} />
                  </div>
                </div>
              </div>
            </div>
          }
        />
      </Routes>
    </div>
  );
}
