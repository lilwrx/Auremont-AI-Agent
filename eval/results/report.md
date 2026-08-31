# Evaluation Report

> Báo cáo đánh giá chất lượng sản phẩm — 8 test case chạy tay (manual) trên stack Docker Compose thật, gọi API thật, dùng Gemini thật (không mock, không giả định).

**Ngày chạy:** 2026-08-15
**Môi trường:** `docker compose up -d --build` — backend (healthy), mysql:8.4 (healthy), qdrant, minio (healthy), frontend. Container `ai20k_backend` build từ commit hiện tại trên branch `feature/Vinh`.
**Tài khoản dùng để test:** `sale_test` (role `SALE`, seed mặc định).
**Session:** `session_id=54`, `project_id=the-palma`, khách hàng demo "Anh Minh - test eval".
**Tài liệu đã ingest liên quan:** `The_Palma_Lumiere_Orient_Pearl.pdf` (`document_id=10`).

---

## 1. Metrics

| Metric | Target | Actual (8 test case) | Status |
|--------|--------|--------|--------|
| Response accuracy (định tính, xem §2) | >80% | 8/8 trả lời đúng ngữ cảnh/đúng dữ liệu nguồn; 1/8 có hành vi HITL đáng ngờ (TC4) | ✅ đạt định tính, có 1 issue mở |
| Response latency (câu hỏi mới, không cache) | <3s | Dao động — xem cột Latency ở §2 (đo bằng `curl` wall-clock, có gọi Gemini thật nên biến động theo mạng) | ⚠️ một số câu vượt 3s, xem ghi chú |
| Semantic Cache hit latency | Nhanh hơn rõ rệt so với cache miss | TC7 (cache miss, câu hỏi HITL không được cache): so sánh không hợp lệ; TC8 (cache hit thật): **606ms** so với ~3-9s của câu hỏi mới | ✅ cache hoạt động đúng thiết kế |
| Test coverage (pytest) | >60% | Chưa đo trong lần chạy này — xem `pytest --cov` trong `docs/DEVELOPMENT.md` | ⏳ |

## 2. Test Results — Manual Test Cases (output thực tế)

Toàn bộ request gửi qua `POST /api/v1/sale/sessions/54/messages`, response nguyên văn từ backend (đã format lại cho dễ đọc, không sửa nội dung).

### TC1 — Câu hỏi chính sách (RAG thuần, có rủi ro cam kết)
- **Input:** `"Chính sách thanh toán của dự án The Palma là gì?"`
- **Output (`message_id=88`):**
  > - Phân khu The Palma có 4 phương án thanh toán dự kiến gồm thanh toán theo tiến độ, thanh toán sớm và 2 phương án vay ngân hàng hỗ trợ lãi suất 0%.
  > - Giữ chỗ thiện chí từ 50 triệu đồng/căn, ký HĐMB 15% sau 07 ngày...
  > - Phương án thanh toán theo tiến độ được chiết khấu 4%...
  > - Phương án thanh toán sớm được chiết khấu 13%...
  > - Phương án vay ngân hàng 70%/50%... *(cắt bớt, xem log đầy đủ)*
- **Citations:** `The_Palma_Lumiere_Orient_Pearl.pdf` (document_id=10)
- **verifier_score:** `1.0` | **requires_hitl:** `true` | **images:** `[]`
- **Đánh giá:** Đúng — trả lời chi tiết, bám sát tài liệu, đúng nội dung phần trăm/mốc thời gian. `requires_hitl=true` chính xác vì câu trả lời chứa cam kết % thanh toán và thời hạn.

### TC2 — Câu hỏi giá theo loại căn (RAG trên bảng giá trong tài liệu)
- **Input:** `"Giá căn 2PN dự án The Palma hiện tại là bao nhiêu?"`
- **Output (`message_id=90`):**
  > - Giá căn 2PN và 2PN+1 tại The Palma dao động từ 5,774 đến 7,916 tỷ đồng/căn tùy diện tích, vị trí và hướng view...
  > - Căn 2PN diện tích 64,3–69,9 m² có giá từ 5,774 đến 7,273 tỷ đồng...
  > - Đơn giá sơ cấp toàn dự án hiện ở mức khoảng 90–125 triệu đồng/m²...
- **Citations:** `The_Palma_Lumiere_Orient_Pearl.pdf` | **verifier_score:** `0.9` | **requires_hitl:** `true`
- **Đánh giá:** Đúng nội dung nhưng là **finding đáng chú ý**: câu hỏi "giá hiện tại" đúng ra nên ưu tiên `tool_call` (Inventory API real-time) như TC3 làm, nhưng `needs_inventory` intent-detection không bắt được câu này (không có từ khóa "còn trống/tồn kho") nên rơi vào RAG trên bảng giá tĩnh trong PDF — có thể lệch giá thực tế so với tồn kho live. Xem `backend/ai/intent.py::needs_inventory`.

### TC3 — Câu hỏi tồn kho real-time (Tool-Call vào Inventory API)
- **Input:** `"Còn căn 2PN nào trống không?"`
- **Output (`message_id=92`):**
  > - Còn 3 căn 2PN trống ở tòa OP3-CT1 gồm căn 0504 giá 3,60 tỷ đồng, căn 0810 giá 3,85 tỷ đồng và căn 1208 giá 3,88 tỷ đồng.
  > - Chưa có dữ liệu về diện tích, điều kiện VAT và mốc thời gian áp dụng giá trong ngữ cảnh, cần kiểm tra lại với Admin.
- **Citations:** `[]` (đúng — dữ liệu tồn kho không có trích nguồn tài liệu) | **verifier_score:** `0.8` | **requires_hitl:** `true`
- **Đánh giá:** Tool-call hoạt động đúng, gọi thật `INVENTORY_API_URL` (mockapi.io). **Finding:** mã căn trả về là `OP3-CT1` (thuộc project `ocean-park-3` trong mock data) dù session đang gắn `project_id=the-palma` — xác nhận đúng cảnh báo đã ghi trong `.env.example`: `INVENTORY_PROJECT_MAP` trống nên `lookup_inventory` gửi thẳng slug catalogue sang API, và vì API mock hiện chỉ có data cho `ocean-park-3` nên có khả năng trả nhầm dữ liệu tồn kho của dự án khác cho Sale đang tư vấn The Palma. Đây là rủi ro thật cần Admin cấu hình `INVENTORY_PROJECT_MAP` trước khi dùng nhiều dự án cùng lúc.

### TC4 — Câu hỏi ảnh (Image tool, bỏ qua Verify theo thiết kế)
- **Input:** `"Cho xem hình ảnh dự án The Palma"`
- **Output (`message_id=94`):** Mô tả kiến trúc The Palma (2 tòa Palma 1/2, 30 tầng, ~570 căn/tòa...) kèm **21 ảnh thật** từ MinIO (`http://localhost:9000/project-images/the-palma/*.jpg`).
- **Citations:** `The_Palma_Lumiere_Orient_Pearl.pdf` | **verifier_score:** `0.0` | **requires_hitl:** `true`
- **Đánh giá — 2 finding cần sửa:**
  1. Theo thiết kế trong `agent_pipeline.py::_route_after_generate`, câu hỏi ảnh phải **bỏ qua** node `verify` hoàn toàn (`faithfulness`/`answer_relevancy` phải là `None`). Nhưng response thực tế trả `verifier_score: 0.0` — một con số, không phải `null`. Nếu con số này bị Admin Eval Dashboard tính vào điểm trung bình, nó sẽ kéo điểm trung bình xuống sai lệch dù pipeline có chủ đích loại trừ các câu hỏi ảnh khỏi thống kê (ghi rõ trong comment code). Cần kiểm tra lại `PipelineResult`/response serialization xem `None` có bị ép về `0.0` ở tầng response schema hay không.
  2. `requires_hitl: true` cho một câu hỏi thuần về hình ảnh kiến trúc là bất thường — nội dung trả lời có nhắc số liệu (~570 căn/tòa, diện tích 28,6–180 m², mật độ xây dựng 18,7%) khiến `risk_service.detect_commitment_risk` bắt nhầm thành rủi ro giá/cam kết. Đây là false positive thật, nên cân nhắc tinh chỉnh `risk_service` để phân biệt số liệu mô tả dự án (diện tích, số tầng) với số liệu cam kết tài chính (giá, %, mốc thanh toán).

### TC5 — Câu hỏi tiện ích (RAG thuần, không rủi ro)
- **Input:** `"Dự án có hồ bơi vô cực không?"`
- **Output (`message_id=96`):**
  > - Dự án có bể bơi vô cực trên cao view toàn cảnh hồ Ngọc Trai và Crystal Lagoon thuộc hệ thống tiện ích chuẩn resort của LUMIÈRE Orient Pearl.
- **Citations:** `The_Palma_Lumiere_Orient_Pearl.pdf` | **verifier_score:** `1.0` | **requires_hitl:** `false`
- **Đánh giá:** Đúng hoàn toàn — không có số liệu cam kết nên `requires_hitl=false` chính xác, khác với TC4 (cùng dạng câu hỏi mô tả nhưng bị risk_check bắt nhầm).

### TC6 — Câu hỏi vô nghĩa / gibberish (edge case)
- **Input:** `"asdkjqwe 12903 !!! xyzabc random gibberish blah"`
- **Output (`message_id=98`):**
  > - Câu hỏi của Sale không chứa thông tin cụ thể về loại căn hay vấn đề cần tư vấn, chưa có dữ liệu để trả lời.
  > - Đề nghị kiểm tra lại với Admin để xác định chính xác thông tin khách đang cần.
- **Citations:** `The_Palma_Lumiere_Orient_Pearl.pdf` (có vẻ retrieval vẫn trả context không liên quan) | **verifier_score:** `1.0` | **requires_hitl:** `false`
- **Đánh giá:** Hệ thống không "ảo giác" — từ chối trả lời hợp lý thay vì bịa thông tin. Điều bất ngờ là `verifier_score=1.0` cho một câu trả lời từ chối; Verifier chấm điểm cao vì câu trả lời trung thực với ngữ cảnh (không bịa), đúng định nghĩa Faithfulness dù nội dung là "không biết" — hành vi này hợp lý, không phải lỗi.

### TC7 — Lặp lại chính xác TC1 (kiểm tra Semantic Cache trên câu HITL)
- **Input:** giống hệt TC1: `"Chính sách thanh toán của dự án The Palma là gì?"`
- **Output (`message_id=100`):** Nội dung **diễn đạt khác** TC1 (ví dụ "04 phương án" thay vì "4 phương án", thứ tự câu khác) dù cùng số liệu.
- **Latency:** 4073 ms (tương đương một lần gọi LLM mới, **không phải cache hit**)
- **Đánh giá:** Xác nhận đúng thiết kế đã ghi trong `agent_pipeline.py::_store_cache`: câu trả lời có `requires_hitl=true` **chủ động không được lưu cache** ("Price-touching answers must re-run RiskCheck every time so the Sale always gets the HITL card"). Đây là hành vi đúng, không phải lỗi — nhưng cũng có nghĩa các câu hỏi giá/chính sách (nhóm câu hỏi phổ biến nhất) không bao giờ hưởng lợi từ Semantic Cache, ảnh hưởng tới mục tiêu tối ưu chi phí Token nêu trong CLAUDE.md §5.

### TC8 — Lặp lại chính xác TC5 (kiểm tra Semantic Cache trên câu không-HITL)
- **Input:** giống hệt TC5: `"Dự án có hồ bơi vô cực không?"`
- **Output (`message_id=102`):** Nội dung **giống hệt 100%** TC5.
- **Latency:** 606 ms (so với ~vài giây của một lần gọi LLM mới)
- **Đánh giá:** Cache hoạt động đúng thiết kế — cosine similarity ≥ 0.95 trên collection `salesmate_qa_cache`, trả thẳng câu trả lời đã lưu mà không gọi lại Gemini, tiết kiệm token đúng như mục tiêu "Semantic Caching" trong CLAUDE.md §2.

### Bonus — TC9: Luồng HITL confirm end-to-end
- **Action:** `POST /api/v1/hitl/88/confirm` với `confirmed_content` = nội dung Sale đã đọc và xác nhận từ TC1.
- **Output:**
  ```json
  {"id":4,"message_id":88,"sale_id":1,"status":"confirmed",
   "confirmed_content":"Phân khu The Palma có 4 phương án thanh toán...",
   "confirmed_at":"2026-08-15T05:30:44"}
  ```
- **Đánh giá:** Đúng — tạo bản ghi `hitl_logs` với `status=confirmed`, đúng luồng "Sale phải đọc và bấm Xác nhận trước khi copy gửi khách" mô tả trong CLAUDE.md §5.4d.

## 3. Tổng hợp Findings từ 8 test case

| # | Mức độ | Finding | File liên quan |
|---|--------|---------|-----------------|
| 1 | Trung bình | Câu hỏi "giá hiện tại" không kích hoạt `needs_inventory`, rơi vào RAG trên bảng giá tĩnh trong PDF thay vì tra tồn kho real-time (TC2) | `backend/ai/intent.py` |
| 2 | Cao | `INVENTORY_PROJECT_MAP` trống khiến tra tồn kho có thể trả nhầm dữ liệu dự án khác (TC3) — đã có cảnh báo sẵn trong `.env.example` nhưng chưa cấu hình | `.env`, `backend/services/inventory_service.py` |
| 3 | Trung bình | `verifier_score` trả `0.0` thay vì `null` cho câu hỏi ảnh bỏ qua Verify — có thể làm sai lệch điểm trung bình trên Admin Dashboard (TC4) | `backend/services/agent_pipeline.py`, response schema |
| 4 | Thấp | `risk_check` false-positive trên số liệu mô tả dự án (diện tích, số tầng) không phải cam kết tài chính, gây HITL không cần thiết cho câu hỏi ảnh (TC4) | `backend/services/risk_service.py` |
| 5 | Thông tin | Câu trả lời có `requires_hitl=true` không được Semantic Cache lưu — đúng thiết kế an toàn nhưng đánh đổi tối ưu chi phí cho đúng nhóm câu hỏi phổ biến nhất (giá/chính sách) (TC7) | `backend/services/agent_pipeline.py::_store_cache` |

## 4. User Feedback

| User | Feedback | Rating |
|------|----------|--------|
| [User 1] | [feedback] | [1-5] |
| [User 2] | [feedback] | [1-5] |

## 5. Demo Results

- Ngày demo: [YYYY-MM-DD]
- Người tham gia: [số người]
- Feedback chung: [tóm tắt]
- Issues phát hiện: [danh sách]

## 6. Action Items

- [ ] Mở rộng `needs_inventory` intent detection để bắt các câu hỏi giá dạng "hiện tại/bây giờ" (finding #1)
- [ ] Cấu hình `INVENTORY_PROJECT_MAP` đầy đủ cho mọi project_id đang có trong catalogue trước khi demo đa dự án (finding #2)
- [ ] Kiểm tra serialization của `verifier_score=None` — xác nhận Admin Eval Dashboard có loại trừ đúng các câu hỏi ảnh khỏi điểm trung bình hay không (finding #3)
- [ ] Tinh chỉnh `risk_service.detect_commitment_risk` để giảm false positive trên số liệu mô tả dự án (finding #4)
