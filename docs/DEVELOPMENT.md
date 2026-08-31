# Development Guide

Hướng dẫn chi tiết cho việc chạy dự án ở dev mode, mock API tồn kho, migration và logging. Xem [`README.md`](../README.md) để biết Quick Start bằng Docker Compose.

## Yêu cầu môi trường

- Python 3.11
- Node.js 20+ và npm
- Docker Desktop (nếu chạy bằng Docker Compose)

## Mock API tồn kho

Tồn kho căn được tra **real-time qua HTTP**, không ingest vào Qdrant — số lượng căn thay đổi liên tục nên vector hoá sẽ trả lời số cũ. Giai đoạn build dùng mock API dựng trên [mockapi.io](https://mockapi.io) theo đúng shape của API nội bộ sẽ dùng ở production, nên khi đổi sang API thật chỉ cần sửa biến môi trường, không phải sửa code.

**Bước 1 — Tạo resource trên mockapi.io**

Tạo project mới, thêm resource tên `units` với các field dưới đây (mockapi tự thêm `id`, `lookup_inventory` sẽ bỏ qua field lạ này). Ba field bắt buộc để một bản ghi hợp lệ là `unit_code`, `project_id`, `status`; các field còn lại càng đầy đủ thì kết quả tư vấn càng chính xác:

| Field | Kiểu | Ví dụ | Ghi chú |
| :--- | :--- | :--- | :--- |
| `unit_code` | string | `OP3-A-0203` | Mã căn |
| `project_id` | string | `ocean-park-3` | Khớp `project_id` truyền vào khi tra cứu |
| `subdivision` | string | `The Zenpark` | Phân khu của căn |
| `tower` | string | `R1.03` | Tòa/tháp |
| `floor` | string | `12` | Tầng; dùng string để giữ được giá trị như `12A` |
| `unit_type` | string | `2PN` | `1PN`…`10PN`, `Penthouse`, `Studio`, `Shophouse`, `Duplex` |
| `area_m2` | number | `68.2` | Diện tích m² |
| `direction` | string | `Đông Nam` | Hướng căn/hướng ban công theo quy ước của nguồn |
| `view_type` | string hoặc array | `["Hồ", "Cảnh quan nội khu"]` | Một hoặc nhiều loại view; chuỗi có thể phân tách bằng `,`, `|`, `/` |
| `price` | number | `3600000000` | VND. Nhận cả chuỗi `"3600000000"` |
| `status` | string | `available` | `available` / `reserved` / `sold` |

Endpoint trả về một JSON array:

```json
[
  { "unit_code": "R1.03-1205", "project_id": "ocean-park-1",
    "subdivision": "The Zenpark", "tower": "R1.03", "floor": "12",
    "unit_type": "2PN", "area_m2": 68.2, "direction": "Đông Nam",
    "view_type": ["Hồ", "Cảnh quan nội khu"],
    "price": 3600000000, "status": "available" }
]
```

**Bước 2 — Trỏ `.env` vào endpoint**

```bash
INVENTORY_API_URL=https://<project-id>.mockapi.io/units
INVENTORY_API_KEY=
```

> Tên biến phải đúng là `INVENTORY_API_URL`. `Settings` đặt `extra="ignore"` (`backend/core/config.py`), nên gõ sai tên (vd. `INVENTORY_MOCK_API`) sẽ **không báo lỗi** — biến bị bỏ qua im lặng và tra cứu luôn thất bại với thông báo "INVENTORY_API_URL chưa được cấu hình".

`INVENTORY_API_KEY` để trống với mockapi.io. Khi có giá trị, nó được gửi kèm dưới dạng header `Authorization: Bearer <key>` — dành cho API nội bộ ở production.

**Bước 3 — Kiểm tra**

```bash
python -c "from backend.services.inventory_service import lookup_inventory; print(lookup_inventory('ocean-park-3', 'Còn căn 2PN nào trống không?'))"

# hoặc unit test (không cần mạng, đã mock sẵn httpx)
pytest tests/test_services/test_inventory_service.py -v
```

**Cách hàm hoạt động** — `lookup_inventory(project_id, query)` trong `backend/services/inventory_service.py`:

- Gửi `project_id` làm query param, timeout 5 giây.
- Đọc loại căn ngay trong câu hỏi tự nhiên của Sale ("còn căn **2PN** không") và lọc theo đó; không nhắc loại căn nào thì trả cả bảng hàng.
- **Không còn căn khớp → trả về `[]`**, đây là câu trả lời hợp lệ ("hết căn 2PN").
- **Không gọi được API → raise `InventoryApiError`**, để pipeline hiển thị "Tạm thời không tra được tồn kho". Hai trường hợp này tách bạch: gộp lại sẽ báo lỗi hệ thống trong khi thực chất chỉ là hết hàng.
- Record thiếu field bắt buộc bị bỏ qua thay vì làm hỏng cả lần tra cứu.

## Chạy thủ công (dev mode, hot reload)

**Backend (FastAPI)**

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1

pip install -r requirements.txt
alembic upgrade head               # BẮT BUỘC trước lần chạy đầu

uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
# hoặc: make run
```

> Chạy bằng Docker Compose thì không cần `alembic upgrade head` thủ công — container tự chạy migration lúc khởi động (`docker-entrypoint.sh`).

**Ảnh dự án**

Ảnh mặt bằng/phối cảnh dùng trong trang "Chung cư" không nằm trong DB — code trỏ thẳng URL MinIO dạng `http://localhost:9000/project-images/<slug>/<file>`. Ảnh gốc (~58MB) không nằm trong git; backend tự tải về MinIO lúc khởi động (`backend/core/bootstrap_data.py`) theo `PROJECT_IMAGES_BASE_URL`/`PROJECT_IMAGES_ARCHIVE_URL` khai trong `.env`, dùng danh sách trong `seed-data/project_images_manifest.json`. Không cần chạy script thủ công hay có sẵn thư mục ảnh gốc nào ngoài repo — chỉ cần biến môi trường đúng và có mạng lúc khởi động lần đầu.

**Frontend (React + Vite)**

```bash
cd frontend
npm install
npm run dev          # dev server tại http://localhost:5173
npm run build         # build production vào frontend/dist
npm run preview        # xem thử bản build
npm run lint             # oxlint
```

## Migration cơ sở dữ liệu (Alembic)

Schema do Alembic quản lý, **không** dùng `Base.metadata.create_all`: `create_all` chỉ tạo bảng còn thiếu và không bao giờ `ALTER` bảng đã tồn tại, nên cột thêm sau sẽ âm thầm vắng mặt cho tới khi có query nổ lỗi lúc chạy.

```bash
alembic upgrade head                              # đưa DB lên bản mới nhất
alembic revision --autogenerate -m "mô tả"        # sinh migration sau khi sửa model
alembic downgrade -1                              # lùi 1 bước
alembic current                                   # DB đang ở revision nào
alembic check                                     # model có lệch migration không
```

Sau khi sửa bất kỳ file nào trong `backend/models/`, **phải** tạo revision mới — `tests/test_migrations.py` sẽ fail nếu quên.

DB đã có sẵn bảng từ trước (tạo bằng `create_all`) thì đánh dấu một lần thay vì chạy upgrade: `alembic stamp head`.

## Testing

Bộ test chia 3 tầng:

| Tầng | Đường dẫn | Cần gì | Kiểm cái gì |
| :--- | :--- | :--- | :--- |
| Unit / API | `tests/test_api/` | Không | Từng endpoint trên SQLite in-memory |
| Migration | `tests/test_migrations.py` | Không | Migration khớp model, không drift |
| E2E | `tests/test_e2e/` | `docker compose up -d` | Hành trình Sale/Admin trên MySQL thật |

```bash
pytest tests/test_api tests/test_migrations   # nhanh, không cần Docker
docker compose up -d && pytest tests/test_e2e # E2E trên stack thật
```

E2E tự **skip** nếu backend chưa chạy, nên `pytest tests/` luôn an toàn.

```bash
make test        # pytest tests/ -v
make lint        # ruff check backend/ tests/
make format      # ruff format backend/ tests/
make typecheck   # mypy backend/
make check       # lint + format + test
make clean       # xóa cache __pycache__, .pytest_cache, .ruff_cache
```

## Truy cập sau khi chạy

| Thành phần | URL | Thông tin đăng nhập |
| :--- | :--- | :--- |
| Frontend | `http://localhost:5173` | `sale_test` / `pass1234` — `admin_test` / `pass1234` |
| Backend API | `http://localhost:8000` | — |
| Swagger UI | `http://localhost:8000/docs` | — |
| Health check | `http://localhost:8000/health` | — |
| Qdrant Dashboard | `http://localhost:6333/dashboard` | — |
| MinIO Console | `http://localhost:9001` | `minioadmin` / `minioadmin` |
| MySQL | `localhost:3306` | `salesmate` / `salesmate` (db: `salesmate_db`) |
| Redis (long-term memory) | `localhost:6379` | — (`redis-cli KEYS "memory:*"`) |

Backend tự seed 2 tài khoản mỗi lần khởi động (`SEED_USERS` trong `backend/main.py`), nên máy nào clone repo về rồi `docker compose up` cũng đăng nhập được ngay. Seed là **idempotent**: tài khoản đã tồn tại thì được đặt lại mật khẩu/role/trạng thái active về đúng bảng trên. Muốn thêm tài khoản dùng chung thì bổ sung vào `SEED_USERS` — email phải là tên miền hợp lệ với `EmailStr` (tránh `.local`, `.test`), nếu không `/auth/login` sẽ lỗi 500 lúc serialize response.

## Logging & Observability

Backend ghi log **JSON có cấu trúc ra stdout** (một dòng = một record), nên `docker logs`, Loki hay CloudWatch đọc được ngay mà không cần parser riêng.

| Biến | Mặc định | Ý nghĩa |
| :--- | :--- | :--- |
| `LOG_LEVEL` | `INFO` | Ngưỡng log. `DEBUG` sẽ hiện thêm `/health` và các chi tiết phụ. |
| `LOG_JSON` | *(tự chọn)* | Bỏ trống: JSON ở production, text dễ đọc ở development. Đặt `true`/`false` để ép. |
| `LOG_QUERY_TEXT` | `true` | Ghi 200 ký tự đầu câu hỏi của Sale vào audit log. |

Mỗi request được gán `request_id` (hoặc dùng lại `X-Request-ID` client gửi lên) và trả về trong response header:

```bash
docker compose logs backend | grep <request_id> | jq .
docker compose logs backend | jq 'select(.event=="pipeline.crash")'
docker compose logs backend | jq 'select(.event=="sale.query" and .verifier_score < 0.7)'
```

Audit event (nghiệp vụ) ghi trên logger `salesmate.audit`, ghim cứng ở mức INFO — đặt `LOG_LEVEL=WARNING` để giảm nhiễu cũng không làm mất audit trail: `auth.login.success/.failure`, `auth.logout`, `document.upload`, `document.ingest.success/.blocked/.failure`, `sale.query`, `hitl.confirm`.

**Không bao giờ được log** (có test canh giữ trong `tests/test_api/test_audit_events.py` và `tests/test_services/test_silent_failures_logged.py`): mật khẩu/JWT/API key (`RedactingFilter` tự che), câu trả lời AI sinh ra (chỉ log điểm số), `confirmed_content` của HITL (chỉ log `content_len` + `edited`), giá trị input gây lỗi 422, nội dung file upload. Response 500 chỉ trả `{"detail": "Internal server error", "request_id": "..."}`.

## Nguồn tham khảo dữ liệu / API mock

| Hạng mục | Nguồn |
| :--- | :--- |
| File PDF Chính sách bán hàng | `market-files.vinhomes.vn` — tra cứu Google: `site:vinhomes.vn "chính sách bán hàng" filetype:pdf` |
| Hình ảnh Mặt bằng & Tiện ích | `rever.vn`, `batdongsan.com.vn` hoặc website chính thức của dự án |
| API tồn kho | Mock API — `mockapi.io` (xem mục "Mock API tồn kho" ở trên) |
