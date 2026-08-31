import pytest

from backend.utils.text import strip_markdown


def test_strips_bold_and_normalises_bullets():
    """Đúng dạng câu trả lời hỏng đã gặp: '*   **Nhãn:**' hiện nguyên dấu sao trên chat."""
    raw = "*   **Tiện ích trong nhà (12 tiện ích):** Tập trung vào thư giãn."

    assert strip_markdown(raw) == "- Tiện ích trong nhà (12 tiện ích): Tập trung vào thư giãn."


def test_removes_every_markdown_marker():
    raw = (
        "### Tổng quan\n"
        "*   **Giá:** từ 3 tỷ đồng\n"
        "*   *Diện tích* 54m²\n"
        "Xem [bảng giá gốc](https://example.com/gia.pdf) và ***lưu ý***."
    )

    cleaned = strip_markdown(raw)

    assert "*" not in cleaned
    assert "#" not in cleaned
    assert "](" not in cleaned
    assert "bảng giá gốc" in cleaned
    assert "https://" not in cleaned


def test_keeps_plain_prose_untouched():
    """Câu trả lời văn xuôi sạch không được bị hàm này can thiệp."""
    raw = "Căn 2PN tại The Zenpark có diện tích 64-70m², giá từ 3 tỷ đến 3,5 tỷ đồng."

    assert strip_markdown(raw) == raw


def test_preserves_multiplication_and_standalone_symbols():
    """Dấu sao không bao quanh nội dung (ví dụ ghi chú) không phải cú pháp nhấn mạnh."""
    raw = "Diện tích 8 * 12 mét."

    assert strip_markdown(raw) == raw


def test_collapses_excess_blank_lines():
    raw = "Đoạn một.\n\n\n\nĐoạn hai."

    assert strip_markdown(raw) == "Đoạn một.\n\nĐoạn hai."


@pytest.mark.parametrize("value", ["", "   ", "\n\n"])
def test_blank_input_collapses_to_empty(value):
    """_generate dựa vào kết quả rỗng để rơi vào nhánh lỗi thay vì gửi bong bóng trắng."""
    assert strip_markdown(value) == ""


def test_repairs_a_bullet_joined_to_the_previous_sentence():
    assert strip_markdown("Tòa P4 có 30 tầng.- Kề đường nội khu 17 m.") == (
        "Tòa P4 có 30 tầng.\n- Kề đường nội khu 17 m."
    )
