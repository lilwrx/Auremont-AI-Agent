# Audit và sửa metadata tài liệu

Chạy từ thư mục gốc repository:

```powershell
python scripts/audit_document_metadata.py
```

Đây luôn là **dry-run** nếu không truyền cờ `--apply-*`. Lệnh mặc định đọc:

- MySQL để lấy metadata/lifecycle hiện tại;
- MinIO để băm file gốc, parse lại nội dung và chạy classifier hiện tại;
- Qdrant để kiểm tra point, payload và fingerprint chunk mà không tải vector.

## Những finding được phát hiện

- file gốc trùng byte, parsed content trùng và indexed chunk fingerprint trùng;
- vector có `document_id` không tồn tại trong MySQL, thiếu hoặc sai kiểu integer;
- document `completed` nhưng không có vector;
- payload Qdrant lệch project, visibility, title, review/legal status hoặc safe `is_current`;
- `QDRANT_CATEGORY_DRIFT_REQUIRES_REINDEX` khi category Qdrant khác MySQL;
- `CLASSIFIER_CATEGORY_SUGGESTION_DRIFT` khi classifier hiện tại gợi ý category khác MySQL; các metadata suggestion drift khác là `info`;
- `MYSQL_UNSAFE_CURRENT_STATE` khi MySQL đánh dấu current cho document non-terminal, rejected hoặc legal chưa/không còn hiệu lực;
- `OPEN_CONFLICT_BOTH_DOCUMENTS_RETRIEVABLE` khi cả hai endpoint của OPEN conflict đều completed, approved và current trong MySQL;
- `SOURCE_CONTENT_UNAVAILABLE` ở mức warning khi MinIO/source không đọc hoặc parse được, vì source duplicate/classifier audit chưa hoàn tất.

`is_current` được đối chiếu fail-closed: chỉ giữ `true` khi document `completed`, không bị rejected và legal status không thuộc `not_yet_effective`, `expired`, `repealed`, `replaced`. Với OPEN conflict mà MySQL đánh dấu cả hai phía current, công cụ không chọn một winner và không đưa hai endpoint vào payload-sync candidate.

Xuất JSON:

```powershell
python scripts/audit_document_metadata.py --json
```

Bỏ qua source hash, parsed duplicate và classifier checks:

```powershell
python scripts/audit_document_metadata.py --skip-source-check
```

`--strict` trả exit code `1` khi check đã chạy có warning/error. Lỗi kết nối hoặc audit không thể hoàn tất trả exit code `2`. Nếu chủ động dùng `--skip-source-check`, strict chỉ đánh giá các check MySQL–Qdrant còn lại.

Audit không tạo distributed snapshot giữa MySQL, Qdrant và MinIO. Qdrant scroll cũng không phải snapshot cô lập toàn collection. Nên chạy lúc ít ghi/maintenance window và lặp lại audit để xác nhận kết quả ổn định.

## Thao tác sửa an toàn

Đồng bộ các payload Qdrant không mang tính cấu trúc từ MySQL:

```powershell
python scripts/audit_document_metadata.py --apply-payload-sync
```

Lệnh chỉ đổi payload Qdrant; không đổi row MySQL, object MinIO, nội dung chunk hoặc vector. Category không bao giờ được sửa bằng lệnh này. Category drift cần review rồi re-chunk/re-embed/re-index.

Sau khi Admin/operator xem xét, quarantine từng orphan rõ ràng bằng:

```powershell
python scripts/audit_document_metadata.py --apply-orphan-quarantine --orphan-id 123 --orphan-id 456
```

Quarantine đặt `review_status=rejected`, `is_current=false` nhưng giữ nguyên point/vector để điều tra hoặc phục hồi. Không có chế độ quarantine tất cả. Orphan đã quarantine chỉ còn finding `info` và không apply lại.

Trước mỗi apply, CLI đọc lại MySQL/Qdrant. Payload sync lock các document row liên quan; orphan không có row nên được kiểm tra lại bằng state mới ngay trước khi quarantine. Nếu dùng cả hai cờ, state được refresh giữa hai thao tác. Sau apply, CLI scan lại; document biến mất hoặc còn drift được coi là lỗi xác minh.

Công cụ cố ý không tự động:

- xóa orphan hoặc tài liệu trùng;
- chọn version/winner;
- ghi classifier suggestion vào MySQL;
- sửa category/scope;
- re-chunk/re-embed/re-index.

Category và conflict-scope metadata (`subdivision_names`, `building_codes`, `unit_types`) hiện bị API/UI chặn khi thay đổi. Category cần controlled re-index cộng conflict rescan; scope cần conflict rescan. Workflow mutation này chưa được triển khai, nên audit chỉ báo để Admin xử lý có kiểm soát.
