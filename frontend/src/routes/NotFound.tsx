import { Link } from "react-router-dom";
import { AlertIcon, ArrowLeftIcon } from "../components/Icons";

export function NotFound() {
  return (
    <div className="page">
      <div className="empty-state">
        <div className="empty-state-icon">
          <AlertIcon size={26} />
        </div>
        <h2 className="empty-state-title">Không tìm thấy trang</h2>
        <p className="empty-state-text">Đường dẫn bạn truy cập không tồn tại hoặc đã được di chuyển.</p>
        <Link to="/home" className="btn btn-primary" style={{ marginTop: 14 }}>
          <ArrowLeftIcon size={16} />
          Về trang chủ
        </Link>
      </div>
    </div>
  );
}
