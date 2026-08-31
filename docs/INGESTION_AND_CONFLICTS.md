# Luồng ingestion và kiểm tra conflict

## Từ file đến RAG

Endpoint upload xử lý theo thứ tự:

1. Tạo row `documents` ở trạng thái `pending`, sau đó chuyển sang `processing`.
2. Kiểm tra magic bytes rồi parse PDF/DOCX thành các section có page; loại byte NUL, bỏ section rỗng và quét prompt injection.
3. Gửi filename và toàn bộ text đã parse sang Gemini bằng structured output schema. LLM chọn primary category và trả đầy đủ metadata hiện có (`subcategory`, scope, unit type, summary, version, dates, legal metadata, confidence, reason, `requires_admin_review`). Không còn keyword/regex classifier hoặc local fallback.
4. Pydantic kiểm tra enum, kiểu ngày, confidence 0-1, danh sách và thứ tự ngày. API lỗi, response rỗng hoặc sai schema làm ingestion `failed` trước khi tạo vector. Response hợp lệ hiện được ingestion tự approve; `requires_admin_review` được lưu làm tín hiệu nhưng chưa chặn publish.
5. Lưu metadata gợi ý vào MySQL và file gốc vào MinIO.
6. Chunk theo category: legal, table (`price_list`, `inventory_snapshot`, `payment_schedule`) hoặc general.
7. Embed theo batch và upsert Qdrant với `is_current=false`.
8. Giữ MySQL advisory lock theo `project_id + category`, kết thúc snapshot đọc cũ rồi scan conflict/duplicate với các document `completed` cùng scope.
9. Commit quyết định MySQL khi Qdrant vẫn bị quarantine. Chỉ document sạch, legal-active mới được publish `is_current=true`. Nếu publish mất ACK, MySQL vẫn giữ quyết định đã commit; audit sẽ phát hiện/retry drift thay vì đổi document thành `failed` và tạo trạng thái fail-open.

RAG lấy point đồng thời thỏa `is_current=true`, visibility và project filter. `review_status` hiện không nằm trong retrieval filter.

## Chỉnh metadata sau ingestion và visibility

- Trang metadata liệt kê các document `completed` để Admin sửa thông tin LLM sau ingestion; đây không phải hàng đợi approval.
- PATCH giữ nguyên các field không được gửi lên.
- Đổi `category` trả `409` vì cần quarantine, conflict rescan và controlled re-index. Đổi `subdivision_names`, `building_codes` hoặc `unit_types` cũng trả `409` vì cần conflict rescan. UI hiện khóa các field này thay vì cho phép một payload-only correction không an toàn.
- Metadata update chạy hai pha: pha 1 ghi metadata vào Qdrant với `is_current=false` trong khi giữ row lock, rồi commit MySQL; pha 2 lock/đọc lại row mới nhất và chỉ publish `is_current` thực tế. Lỗi pha 2 để document ở trạng thái quarantine an toàn.
- Legal status `not_yet_effective`, `expired`, `repealed` hoặc `replaced` luôn giữ `is_current=false`.
- Visibility chỉ được đổi khi ingestion đã `completed`. `internal → public` quarantine trước, commit MySQL rồi publish từ row mới đọc lại. `public → internal` ghi mức hạn chế hơn vào Qdrant trước MySQL commit.

## Điều kiện conflict

Hai document chỉ được so khi:

- cùng category;
- cùng project, hoặc cả hai không có project;
- metadata không chứng minh chúng thuộc scope tách biệt.

Scope được xét theo phân cấp:

- subdivision hoặc building có dữ liệu ở cả hai phía nhưng không giao nhau là bằng chứng tách scope;
- cùng subdivision/building vẫn phải được so dù danh sách unit type khác nhau, vì khác biệt đó có thể là một phiên bản thêm/bớt loại căn;
- khi không có location trùng, unit type có dữ liệu nhưng tách biệt mới được dùng để tách scope;
- metadata rỗng là “chưa biết”, không phải bằng chứng khác scope.

Sau bước scope:

- `price_list`: so giá theo mã đã normalize (`BE1-1201` và `BE1.1201` là một mã), hiểu bảng có đơn vị VNĐ ở header, số tiền ghép như `3 tỷ 500 triệu` và cách viết `3.500 triệu`; đồng thời so các footnote/điều kiện như “đã gồm VAT” và “chưa gồm VAT”;
- category khác: so cùng anchor điều khoản khi phần trăm, tiền, ngày, thời hạn hoặc vị trí giá trị thay đổi;
- comparator văn bản bắt thay đổi khẳng định/phủ định như “được” và “không được”;
- với category không phải `price_list`, cùng title sau khi bỏ extension, separator, version/phiên bản/tháng/đợt/quý là fallback conflict nếu meaningful content còn khác;
- legal document có cùng số hiệu được coi là cùng identity dù title upload khác;
- khác title phải có fact/polarity/legal identity anchor chung;
- không có project cần thêm title/legal identity, metadata overlap, mã giá chung hoặc fact anchor chung;
- khác version/period không tự loại conflict vì retrieval hiện chưa lọc theo thời điểm áp dụng.

Nội dung exact hoặc meaningful-normalized giống nhau là duplicate, không phải conflict. Bản upload mới bị `blocked`, `rejected`, `is_current=false` và lưu ID bản trùng trong classification reason để không chiếm top-k/citation. Thiếu source của một sibling làm scan fail closed; document mới không được kích hoạt.

## Resolve conflict

- Lock các conflict liên quan, inactive relation và document theo thứ tự cố định.
- Winner phải `completed`, không mang legal status chưa/không còn hiệu lực và không phải target của relation `REPLACES`, `SUPERSEDES` hoặc `REPEALS` đã duyệt.
- Pha 1 quarantine cả loser lẫn winner trong Qdrant, sau đó commit quyết định MySQL. Vì vậy timeout không thể công khai một quyết định Admin chưa commit.
- Pha 2 lock/đọc lại winner; chỉ bật nó nếu không còn OPEN conflict và không bị relation khác retire giữa hai pha.
- Các edge OPEN còn lại nhưng cả hai endpoint đã `blocked` được đóng tự động.
- Nếu commit outcome không xác định, không compensation theo hướng bật lại dữ liệu cũ; hai phía tiếp tục quarantine để audit/retry an toàn.

## Quan hệ thay thế/bãi bỏ

Khi duyệt `REPLACES`, `SUPERSEDES` hoặc `REPEALS`:

- source và target được lock theo thứ tự ID;
- source phải `completed`, `approved`, `is_current=true` và legal-active;
- target cũng phải là document `completed`, `approved`, current, nên không thể retire một upload còn `processing`;
- Qdrant target được tắt trước MySQL commit; target chuyển `blocked`, `is_current=false`;
- `REPEALS` đặt target legal thành `repealed`; target legal của `REPLACES/SUPERSEDES` thành `replaced`;
- nếu commit mất ACK, target vẫn bị quarantine thay vì bị compensation hồi sinh.

## Audit metadata

Xem [METADATA_AUDIT.md](./METADATA_AUDIT.md). Audit mặc định read-only, đọc đủ pagination Qdrant và kiểm tra MinIO/MySQL/Qdrant, duplicate, orphan, missing vector, lifecycle/current invariant, OPEN conflict, payload drift và classifier suggestion drift. Category drift chỉ được báo để re-chunk/re-embed, không được sửa bằng payload-only sync.
