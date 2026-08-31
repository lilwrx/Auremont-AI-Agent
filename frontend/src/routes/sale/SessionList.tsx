import { useMemo, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useMatch, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type { ChatSessionResponse } from "../../types";
import { ArrowLeftIcon, ChatIcon, PlusIcon, SearchIcon, TrashIcon } from "../../components/Icons";
import { parseServerDate } from "../../utils/datetime";

function formatDate(iso: string): string {
  const d = parseServerDate(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" });
}

interface Props {
  sessions: ChatSessionResponse[];
  loading: boolean;
  onChange: (next: ChatSessionResponse[]) => void;
}

// Sidebar: "new conversation" button + the list of past conversations.
export function SessionList({ sessions, loading, onChange }: Props) {
  // This component sits outside <Route path="sessions/:sessionId">, so useParams()
  // would always be undefined here — use useMatch to read sessionId directly from
  // the current URL instead.
  const match = useMatch("/chat/sessions/:sessionId");
  const sessionId = match?.params.sessionId;
  const navigate = useNavigate();

  const [naming, setNaming] = useState(false);
  const [customerName, setCustomerName] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const filteredSessions = useMemo(() => {
    const q = historyQuery.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) => (s.customer_name ?? s.title ?? `Cuộc trò chuyện #${s.id}`).toLowerCase().includes(q));
  }, [sessions, historyQuery]);

  const closeNaming = () => {
    setNaming(false);
    setCustomerName("");
  };

  // A name is the only thing a new conversation takes, and even that is optional —
  // Sale goes straight into the chat. No project is chosen here: the Agent resolves
  // which project a question is about from the question itself, and document
  // retrieval searches across every project either way.
  const submitNewSession = async (e: FormEvent) => {
    e.preventDefault();
    setActionError(null);
    const name = customerName.trim();
    let session: ChatSessionResponse;
    try {
      session = await api.post<ChatSessionResponse>("/sale/sessions", {
        customer_name: name || undefined,
      });
    } catch {
      // Same reasoning as removeSession below: without this the naming form just sat there
      // after a failed create, giving the Sale nothing to act on.
      setActionError("Không tạo được cuộc trò chuyện, vui lòng thử lại.");
      return;
    }
    onChange([session, ...sessions]);
    closeNaming();
    navigate(`/chat/sessions/${session.id}`);
  };

  const handleNameKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") closeNaming();
  };

  // The row is removed only after the server confirms the delete. Swallowing the error
  // here made a failed delete look successful: the conversation vanished from the list
  // and came back on the next reload.
  const removeSession = async (e: React.MouseEvent, id: number) => {
    e.preventDefault();
    e.stopPropagation();
    setActionError(null);
    try {
      await api.delete(`/sale/sessions/${id}`);
    } catch {
      setActionError("Không xoá được cuộc trò chuyện, vui lòng thử lại.");
      return;
    }
    onChange(sessions.filter((s) => s.id !== id));
    if (String(id) === sessionId) navigate("/chat");
  };

  return (
    <aside className="chat-sidebar">
      <div className="chat-sidebar-head">
        <Link to="/" className="chat-sidebar-home-link">
          <ArrowLeftIcon size={14} />
          Về trang chủ
        </Link>

        <div className="chat-sidebar-brand">
          <ChatIcon size={18} />
          Đoạn chat
        </div>

        {naming ? (
          <form className="chat-new-form" onSubmit={(e) => void submitNewSession(e)}>
            <input
              autoFocus
              className="chat-new-form-input"
              placeholder="Tên khách hàng (có thể bỏ trống)"
              value={customerName}
              onChange={(e) => setCustomerName(e.target.value)}
              onKeyDown={handleNameKeyDown}
            />
            <div className="chat-new-form-actions">
              <button type="submit" className="btn btn-primary chat-new-form-submit">
                Bắt đầu
              </button>
              <button type="button" className="chat-new-form-cancel" onClick={closeNaming}>
                Huỷ
              </button>
            </div>
          </form>
        ) : (
          <button onClick={() => setNaming(true)} className="chat-new-btn" type="button">
            <PlusIcon size={17} />
            Cuộc trò chuyện mới
          </button>
        )}

        <div className="chat-sidebar-search">
          <SearchIcon size={15} />
          <input
            value={historyQuery}
            onChange={(e) => setHistoryQuery(e.target.value)}
            placeholder="Tìm trong lịch sử"
          />
        </div>
      </div>

      {actionError && <p className="chat-conv-empty chat-conv-error">{actionError}</p>}

      <div className="chat-conv-list">
        {loading ? (
          <>
            <div className="skeleton chat-conv-skeleton" />
            <div className="skeleton chat-conv-skeleton" />
            <div className="skeleton chat-conv-skeleton" />
          </>
        ) : sessions.length === 0 ? (
          <p className="chat-conv-empty">
            Chưa có cuộc trò chuyện nào.
            <br />
            Bấm &ldquo;Cuộc trò chuyện mới&rdquo; để bắt đầu.
          </p>
        ) : filteredSessions.length === 0 ? (
          <p className="chat-conv-empty">Không tìm thấy cuộc trò chuyện nào khớp &ldquo;{historyQuery}&rdquo;.</p>
        ) : (
          filteredSessions.map((s) => (
            // The delete control is a sibling of the link, not a child: a <button> inside
            // an <a> is invalid HTML, and browsers/screen readers disagree on the resulting
            // focus order and on which handler a keyboard activation should fire.
            <div key={s.id} className="chat-conv-row">
              <Link
                to={`/chat/sessions/${s.id}`}
                className={`chat-conv-item ${String(s.id) === sessionId ? "chat-conv-item--active" : ""}`}
              >
                <span className="chat-conv-title">
                  {s.customer_name ?? s.title ?? `Cuộc trò chuyện #${s.id}`}
                </span>
                <span className="chat-conv-time">{formatDate(s.created_at)}</span>
              </Link>
              <button
                className="chat-conv-delete"
                onClick={(e) => removeSession(e, s.id)}
                aria-label="Xoá cuộc trò chuyện"
                type="button"
              >
                <TrashIcon size={14} />
              </button>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
