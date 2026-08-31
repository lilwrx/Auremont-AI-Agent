# Engineering Weekly Journal — Team P-110 (Auremont AI Agent)

> **Dự án:** Auremont AI Agent — Trợ lý AI Đa tác tử (Multi-Agent RAG) cho Chuyên viên Tư vấn & Khách hàng Bất động sản.  
> **Chương trình:** AI20K Build Phase (Cohort 3)  
> **Repository:** `AI20K-Build-Phase-Cohort-3/P-110`

---

## 📅 Week 1: Problem Definition & Knowledge Base Grounding (RAG Baseline)
**Trạng thái:** ✅ Đã hoàn thành

### 🎯 Mục tiêu tuần
- [x] Khảo sát nghiệp vụ bán hàng bất động sản (Sales Consultation) và các điểm nghẽn về tra cứu bảng giá, chính sách bán hàng.
- [x] Thiết lập kiến trúc hệ thống cơ bản: FastAPI Backend + Qdrant Vector Store + React 19 Frontend.
- [x] Xây dựng luồng Document Ingestion cơ bản cho các tài liệu PDF dự án (*LUMIÈRE Orient Pearl / The Palma, Vinhomes Ocean Park*).
- [x] Tích hợp Google Gemini Embeddings (`gemini-embedding-001`) và LLM Generation (`gemini-2.0-flash`).

### 🚀 Đã hoàn thành
- Khởi tạo cấu trúc dự án chuẩn enterprise với cấu hình Docker Compose ban đầu (FastAPI, Qdrant, MySQL, MinIO).
- Xây dựng module `rag_service.py` hỗ trợ trích xuất văn bản từ PDF, chia chunk có ngữ cảnh tiêu đề và đánh chỉ mục vào Qdrant.
- Hoàn thành giao diện chat cơ bản hỗ trợ hiển thị trích dẫn nguồn tài liệu (`citations`).

### 💡 Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
| :--- | :--- | :--- |
| Chunking văn bản thuần túy làm đứt gãy bảng giá và điều kiện thanh toán nhiều tầng trong PDF. | Xây dựng chiến lược Semantic Chunking bám theo cấu trúc đề mục và bảng biểu của tài liệu bất động sản. | Tỷ lệ trích xuất đúng bảng giá và tiến độ thanh toán tăng rõ rệt, không bị mất dòng. |
| Tiếng Việt có dấu/không dấu dễ gây lệch ngữ nghĩa khi tìm kiếm vector. | Chuẩn hóa toàn bộ text qua bộ xử lý diacritic stripping và lowercase trước khi xử lý intent. | Xử lý mượt mà cả khi Sale gõ vội không dấu trên điện thoại. |

### 🧠 Bài học kinh nghiệm
- Tài liệu bất động sản có đặc thù nhiều con số và bảng biểu phức tạp; việc chunking ẩu sẽ phá hủy hoàn toàn độ chính xác của RAG.
- Phải thiết kế hệ thống có khả năng trích xuất chính xác số trang và tên file để tạo niềm tin cho người dùng.

---

## 📅 Week 2: Advanced Retrieval & Ingestion Pipeline Hardening
**Trạng thái:** ✅ Đã hoàn thành

### 🎯 Mục tiêu tuần
- [x] Nâng cấp chất lượng tìm kiếm với mô hình Hybrid Search (Dense Vector + Sparse BM25 via FastEmbed).
- [x] Thiết lập hệ thống phân quyền tài liệu RBAC (`PUBLIC` vs `INTERNAL`).
- [x] Bổ sung tầng quét mã độc / Prompt Injection Scanner khi Admin tải lên tài liệu mới.
- [x] Xây dựng cơ chế phát hiện xung đột thông tin (Conflict Detection) giữa tài liệu mới và tài liệu cũ.

### 🚀 Đã hoàn thành
- Tích hợp BM25 qua thư viện FastEmbed, kết hợp với Qdrant RRF (Reciprocal Rank Fusion) để khắc phục nhược điểm của vector search thuần túy.
- Xây dựng module Ingestion Pipeline với 4 bước: `Sanitize -> Auto-Classify -> Chunk -> Embed`.
- Hoàn thành cơ chế Document Quarantine: Tài liệu có dấu hiệu xung đột chính sách sẽ được cách ly và cảnh báo cho Admin.

### 💡 Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
| :--- | :--- | :--- |
| Vector search thuần túy dễ nhầm lẫn giữa các mã căn hộ tương tự nhau (`2PN` vs `3PN`, `BE1` vs `BE2`). | Kết hợp Sparse BM25 keyword search cùng Dense Vector search thông qua RRF. | Bắt chính xác 100% mã căn hộ và loại phòng ngủ mà Sale yêu cầu. |
| Nguy cơ rò rỉ tài liệu nội bộ (chính sách hoa hồng, giá mật) ra luồng chat của khách hàng vãng lai. | Phân định rạch ròi 2 cấp độ `clearance` (`PUBLIC` và `INTERNAL`) từ tầng Filter của Qdrant. | Khách hàng vãng lai tuyệt đối không thể truy xuất tài liệu nội bộ của Sale. |

### 🧠 Bài học kinh nghiệm
- Hybrid Search là bắt buộc đối với dữ liệu bất động sản vì chứa rất nhiều mã định danh và thuật ngữ viết tắt.
- Bảo mật thông tin phải được thực thi ở tầng truy vấn dữ liệu (Query Filter) chứ không thể chỉ dựa vào prompt instruction của LLM.

---

## 📅 Week 3: Multi-Agent Orchestration, Live Inventory & Safety Verification Gate
**Trạng thái:** ✅ Đã hoàn thành (Tuần hiện tại)

### 🎯 Mục tiêu tuần
- [x] Chuyển đổi toàn bộ pipeline xử lý sang **LangGraph Multi-Agent StateGraph**.
- [x] Tích hợp Tool tra cứu tồn kho căn hộ thời gian thực (**Real-time Inventory Function Calling**) & Slug Mapping.
- [x] Xây dựng **Verifier Agent** độc lập (Faithfulness, Relevancy, Completeness) cùng vòng lặp tự sửa lỗi (**Reflexion Loop**).
- [x] Triển khai **Deterministic RiskCheck Gate & HITL Confirmation Card** cho các cam kết tài chính/giá cả.
- [x] Tích hợp **Semantic QA Cache** trên Qdrant và **Reflection Memory** trên Redis (Fail-Open).
- [x] Tối ưu hóa độ trễ phản hồi với cơ chế **Fast-Path Skip Verifier** cho câu hỏi thông tin đơn giản.
- [x] Hoàn thiện bộ Unit & Regression Tests (46+ tests passed 100%).

### 🚀 Đã hoàn thành
- Thiết kế StateGraph hoàn chỉnh: `CacheCheck -> Retrieve -> Inventory Tool -> Image Tool -> Generate -> Verify/Reflexion -> RiskCheck`.
- Function Calling vào MockAPI tồn kho: Tự động trích xuất bộ lọc loại căn, diện tích, phân khu và mức giá từ câu hỏi tự nhiên.
- Bộ phân loại rủi ro bằng Regex (`risk_service.py`) khóa câu trả lời báo giá sau thẻ HITL, yêu cầu Sale xác nhận trước khi gửi khách.
- Hoàn thiện Semantic Cache Qdrant (ngưỡng Cosine $\ge 0.95$, phản hồi $<200\text{ms}$) và Reflection Memory Redis lưu trữ bài học sửa sai giữa các phiên.
- Hoàn tất 46/46 unit tests cho toàn bộ Inventory, Pipeline Routing và Reflexion logic.

### 💡 Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
| :--- | :--- | :--- |
| Tồn kho căn thay đổi liên tục; slug catalog (`the-palma`) lệch mã API (`ocean-park-3`). | Xây dựng `resolve_api_project_id()` với `INVENTORY_PROJECT_MAP`, cảnh báo rõ ràng khi unmapped và có startup validation. | Tra cứu tồn kho chính xác theo thời gian thực, không bị lỗi 404 ngầm. |
| LLM có nguy cơ hallucinate con số hoặc báo giá lỗi thời khi tư vấn. | Kết hợp 2 lớp bảo vệ: Verifier Agent chấm điểm Faithfulness + RiskCheck Regex kích hoạt thẻ xác nhận HITL. | 100% câu trả lời có số tiền/cam kết đều phải qua kiểm duyệt của Sale trước khi đến tay khách hàng. |
| Gọi Verifier cho mọi câu hỏi làm tăng độ trễ lên 4-6s. | Triển khai Fast-Path: Bỏ qua Verifier nếu câu hỏi và câu trả lời hoàn toàn không chứa rủi ro tài chính/cam kết. | Giảm 50% độ trễ cho câu hỏi thông tin chung (còn 1.5-2.5s) mà vẫn an toàn tuyệt đối. |

### 🧠 Bài học kinh nghiệm
- Sự kết hợp giữa **Deterministic Risk Gate** (Regex không độ trễ) và **LLM Verifier** (chấm ngữ nghĩa) mang lại độ tin cậy cao nhất cho hệ thống AI Doanh nghiệp.
- Mọi dịch vụ phụ trợ (Redis, Cohere, Cache) phải tuân thủ nguyên tắc **Fail-Open** để đảm bảo hệ thống cốt lõi không bao giờ sập vì lỗi bên ngoài.

---

## 📅 Week 4: Evaluation Flywheel & Production Hardening
**Trạng thái:** ⏳ Kế hoạch tuần tới

### 🎯 Mục tiêu dự kiến
- [ ] Mở rộng bộ dữ liệu đánh giá chuẩn (**Golden Benchmark Dataset**) với hơn 50+ kịch bản tư vấn thực tế.
- [ ] Tích hợp công cụ chạy tự động hóa đánh giá toàn diện (**Evaluation Flywheel Runner** `scripts/run_eval.py`).
- [ ] Tối ưu hóa giao diện người dùng (UX) trên mobile cho chuyên viên tư vấn khi thao tác ngoài dự án.
- [ ] Hoàn thiện đóng gói môi trường staging và tài liệu bàn giao sản phẩm.

---

## 📅 Week 5: End-to-End Integration, Stress Testing & Security Audit
**Trạng thái:** ⏳ Dự kiến

### 🎯 Mục tiêu dự kiến
- [ ] Kiểm thử tải (Load Testing) và đo lường độ ổn định của hệ thống với nhiều phiên tư vấn đồng thời.
- [ ] Rà soát bảo mật toàn diện: Rate limiting, JWT Token rotation, SQL injection, XSS và RBAC boundaries.
- [ ] Thu thập phản hồi từ người dùng thử nghiệm (UAT) để tinh chỉnh prompt tone & suggestions.

---

## 📅 Week 6: Final Demo, Optimization & Project Release
**Trạng thái:** ⏳ Dự kiến

### 🎯 Mục tiêu dự kiến
- [ ] Hoàn thiện slide thuyết trình và kịch bản Demo trực tiếp đầy đủ các tính năng nổi bật.
- [ ] Tổng hợp báo cáo kỹ thuật tổng kết toàn bộ quá trình xây dựng sản phẩm (Build Phase Cohort 3).
- [ ] Đóng băng phiên bản phát hành chính thức (Release v1.0.0).
