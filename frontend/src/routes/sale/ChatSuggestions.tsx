import { ArrowRightIcon } from "../../components/Icons";

const SUGGESTED_QUESTIONS = [
  "Bảng giá căn hộ The Zurich hiện tại thế nào?",
  "Mặt bằng tòa BE1 The Beverly có những loại căn nào?",
  "Chính sách bán hàng, tiến độ thanh toán ra sao?",
  "Còn căn 2 ngủ nào trống ở The Sapphire không?",
];

interface Props {
  onPick: (question: string) => void;
}

// MOSO-style "suggested questions" card — 4 preset questions for the Sale rep;
// clicking one fills the input (does not auto-send, so the Sale can edit before asking).
export function ChatSuggestions({ onPick }: Props) {
  return (
    <div className="chat-suggest-card">
      <span className="chat-suggest-label">Thử hỏi</span>
      {SUGGESTED_QUESTIONS.map((q) => (
        <button key={q} type="button" className="chat-suggest-item" onClick={() => onPick(q)}>
          <span>{q}</span>
          <ArrowRightIcon size={15} />
        </button>
      ))}
    </div>
  );
}
