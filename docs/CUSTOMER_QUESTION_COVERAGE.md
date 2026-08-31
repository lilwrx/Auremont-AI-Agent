# Phủ câu hỏi tư vấn khách hàng

Danh sách câu hỏi khách hàng không thể được giải quyết chỉ bằng cách thêm prompt. Mỗi câu trả lời phải đi qua đúng nguồn sự thật; nếu nguồn chưa có trường cần thiết, chatbot phải nói rõ phần thiếu và hỏi thêm dữ liệu hoặc chuyển chuyên viên.

## Ma trận nguồn dữ liệu

| Nhóm câu hỏi | Nguồn sự thật | Trạng thái |
|---|---|---|
| Vị trí, chủ đầu tư, quy mô, loại căn, diện tích, bàn giao, sở hữu tổng quan | `Project.details.project` | Đã đưa vào context có cấu trúc |
| Giá theo loại căn | `Project.details.pricing` | Đã hỗ trợ dưới dạng giá catalogue tham khảo |
| Tiện ích | `Project.details.amenities` | Đã đưa vào context có cấu trúc |
| Chính sách thanh toán, chiết khấu, vay | `Project.details.sales_policies` và tài liệu đã duyệt | Đã trả lời được phần có dữ liệu; chính sách thiếu ngày hiệu lực phải yêu cầu xác nhận |
| Căn còn trống, mã căn, diện tích và giá từng căn | Inventory API | Đã có route real-time; không được dùng PDF/catalogue để xác nhận còn căn |
| Mặt bằng căn/tòa | Gallery và metadata ảnh | Đã có ảnh nếu file được map đúng dự án, tòa và loại căn |
| Điều khoản pháp lý chi tiết, giấy phép, bảo lãnh, hợp đồng | Tài liệu pháp lý đã duyệt trong RAG | Chỉ trả lời khi tài liệu tương ứng đã được upload, phân loại và duyệt |
| Hướng, view, tầng, căn góc, gần thang/rác, độ ồn | Thuộc tính cấp mã căn trong inventory | Chưa đủ schema/dữ liệu cho mọi dự án |
| VAT, phí bảo trì, phí quản lý, gửi xe, điện nước | Bảng phí/chính sách có ngày hiệu lực | Chưa đủ dữ liệu chuẩn hóa |
| Số tiền từng đợt | Giá căn + lịch thanh toán có tỷ lệ và mốc ngày | Cần calculator và lịch thanh toán có cấu trúc |
| Khoản vay và tiền trả hàng tháng | Giá căn, vốn tự có, LTV, kỳ hạn, lãi suất theo giai đoạn, phương thức dư nợ | Cần calculator; không được tự chọn lãi suất/kỳ hạn |
| Thời gian di chuyển, ùn tắc, hạ tầng tương lai | Dữ liệu bản đồ/giao thông có thời điểm và tài liệu quy hoạch chính thức | Chưa có; không được ước lượng từ mô tả vị trí |
| Giá thuê, tỷ suất, thanh khoản, tăng giá | Dữ liệu giao dịch/cho thuê có ngày và mẫu so sánh | Chưa có; chỉ được tính kịch bản, không dự báo như sự thật |
| Giữ căn, đặt cọc, lịch xem, gặp tư vấn | CRM/booking/hold service | Lead được đánh dấu HOT; thao tác thật cần tích hợp dịch vụ tương ứng |

## Quy tắc trả lời

1. Tồn kho thắng catalogue và tài liệu tĩnh khi hỏi một mã căn hoặc trạng thái hiện tại.
2. Giá catalogue phải ghi rõ là khoảng tham khảo, không phải giá chốt của căn đang còn.
3. Chính sách, ưu đãi và lãi suất không có `effective_from`, `effective_to` hoặc `as_of` phải được xác nhận lại.
4. Không nội suy hướng/view/tầng/độ ồn/pháp lý/thời gian di chuyển từ tên dự án hay ảnh.
5. Phép tính tài chính chỉ chạy khi đủ đầu vào và phải hiển thị công thức, giả định, ngày áp dụng.
6. Câu hỏi gồm nhiều ý được trả lời theo từng ý: trả phần có bằng chứng, nêu chính xác phần đang thiếu, rồi đề nghị bước tiếp theo.

## Dữ liệu cần bổ sung

### Inventory cấp mã căn

Thêm các trường: `tower`, `floor`, `direction`, `view`, `is_corner`, `near_elevator`, `near_trash_room`, `noise_notes`, `gross_area_m2`, `net_area_m2`, `price_vnd`, `status`, `status_as_of`, `holdable_until` và nguồn cập nhật.

### Chính sách thương mại

Chuẩn hóa `deposit_amount`, danh sách đợt thanh toán (`percentage`, `due_date` hoặc điều kiện), VAT/phí bảo trì, chiết khấu, quà tặng, ngân hàng, LTV, thời gian hỗ trợ lãi, lãi suất sau ưu đãi, phí trả nợ sớm và `effective_from`/`effective_to`.

### Pháp lý và bàn giao

Mỗi khẳng định cần `document_id`, số văn bản, ngày ban hành, cơ quan phát hành, phạm vi áp dụng và trạng thái duyệt. Thông số bàn giao cần hãng/model hoặc mô tả chính xác, chiều cao trần, loại kính, PCCC, tiến độ và ngày cập nhật.

### Vận hành và đầu tư

Bảng phí cần ngày hiệu lực. Dữ liệu đầu tư cần giao dịch so sánh, hợp đồng thuê hoặc nguồn thị trường, phạm vi địa lý, khoảng thời gian và cỡ mẫu; kết quả hiển thị là kịch bản, không phải cam kết lợi nhuận.

## Lead Scoring HOT

Các ý định giao dịch rõ ràng được đánh dấu HOT ngay bằng rule: đặt cọc/chuyển tiền, xin bảng hàng mới nhất, xem căn thực tế hoặc căn mẫu, kiểm tra một căn còn không, giữ căn, xin chính sách/tiến độ cụ thể, tính từng đợt hoặc khoản vay, chuẩn bị/ký hồ sơ đặt cọc-hợp đồng, gặp nhân viên và sắp lịch tham quan. Tín hiệu được giữ qua các lượt sau để một câu “cảm ơn” không làm lead hạ nhiệt.

## Kiểm thử chấp nhận

Mỗi câu trong bộ câu hỏi nên có nhãn:

- `source`: `project_profile`, `inventory`, `document`, `calculator`, `crm` hoặc `unsupported`;
- `freshness`: có yêu cầu dữ liệu hiện tại hay không;
- `must_include`: dữ kiện hoặc cảnh báo bắt buộc;
- `must_not_claim`: điều chatbot không được suy diễn;
- `lead_tier`: riêng 12 câu giao dịch là `HOT`.

Bộ test phải kiểm tra cả câu có dấu/không dấu, câu nhiều ý, cách diễn đạt gần nghĩa và trường hợp nguồn phụ thuộc bị lỗi.
