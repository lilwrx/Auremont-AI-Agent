import pytest

from backend.services.chunking_service import chunk_sections, chunk_sections_by_classification
from backend.services.parser_service import ParsedSection


def test_chunk_sections_preserves_page_and_global_index():
    sections = [
        ParsedSection(text="Noi dung trang mot.", page=1),
        ParsedSection(text="Noi dung trang hai.", page=2),
    ]

    chunks = chunk_sections(sections, chunk_chars=100, overlap_chars=10)

    assert len(chunks) == 2
    assert [chunk.index for chunk in chunks] == [0, 1]
    assert [chunk.page for chunk in chunks] == [1, 2]
    assert chunks[0].text == "Noi dung trang mot."
    assert chunks[1].text == "Noi dung trang hai."


def test_mixed_document_chunks_keep_one_approved_category_per_content_unit():
    sections = [
        ParsedSection(text="Chinh sach chiet khau 5% cho khach hang.", page=1),
        ParsedSection(text="| Ma can | Gia |\n| A-01 | 3.5 ty |", page=2, content_type="table"),
    ]

    chunks = chunk_sections_by_classification(
        sections,
        primary_category="sales_policy",
        section_classifications=[
            {"section_index": 0, "category": "sales_policy"},
            {"section_index": 1, "category": "price_list"},
        ],
    )

    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert [chunk.category for chunk in chunks] == ["sales_policy", "price_list"]
    assert [chunk.section_index for chunk in chunks] == [0, 1]
    assert [chunk.page for chunk in chunks] == [1, 2]


def test_chunk_sections_includes_roman_and_number_breadcrumb():
    sections = [
        ParsedSection(
            text=("I. CHINH SACH BAN HANG\n\n1. GIA BAN\n\nGia can ho 2PN tu 3.5 ty dong."),
            page=3,
        )
    ]

    chunks = chunk_sections(sections, chunk_chars=300, overlap_chars=30)

    assert len(chunks) == 1
    assert chunks[0].page == 3
    assert "I. CHINH SACH BAN HANG > 1. GIA BAN" in chunks[0].text
    assert "Gia can ho 2PN" in chunks[0].text


def test_chunk_sections_includes_alpha_heading_in_breadcrumb():
    sections = [
        ParsedSection(
            text=(
                "II. PHUONG THUC THANH TOAN\n\n"
                "2. DOT THANH TOAN\n\n"
                "a. THANH TOAN SOM\n\n"
                "Khach hang duoc chiet khau khi thanh toan som."
            ),
            page=5,
        )
    ]

    chunks = chunk_sections(sections, chunk_chars=500, overlap_chars=30)

    assert len(chunks) == 1
    assert "II. PHUONG THUC THANH TOAN" in chunks[0].text
    assert "2. DOT THANH TOAN" in chunks[0].text
    assert "a. THANH TOAN SOM" in chunks[0].text
    assert "Khach hang duoc chiet khau" in chunks[0].text


def test_chunk_sections_splits_long_text_with_overlap_and_size_limit():
    text = " ".join(f"tu{index}" for index in range(120))
    sections = [ParsedSection(text=text, page=7)]

    chunks = chunk_sections(sections, chunk_chars=80, overlap_chars=20)

    assert len(chunks) > 1
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.page == 7 for chunk in chunks)
    assert all(len(chunk.text) <= 80 for chunk in chunks)

    assert chunks[1].text.split()[0] in chunks[0].text


def test_chunk_sections_splits_large_table_without_exceeding_limit():
    table = "\n".join(
        [
            "| Ma can | Loai | Gia |",
            "| --- | --- | --- |",
            *[f"| A-{number:03d} | 2PN | {3 + number / 10:.1f} ty |" for number in range(20)],
        ]
    )
    sections = [ParsedSection(text=table, page=8)]

    chunks = chunk_sections(sections, chunk_chars=100, overlap_chars=20)

    assert len(chunks) > 1
    assert all(chunk.page == 8 for chunk in chunks)
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    assert "A-000" in chunks[0].text


def test_chunk_sections_handles_document_with_heading_only():
    sections = [
        ParsedSection(text="IV. CHINH SACH GIA BAN", page=9),
    ]

    chunks = chunk_sections(sections, chunk_chars=100, overlap_chars=10)

    assert len(chunks) == 1
    assert chunks[0].text == "IV. CHINH SACH GIA BAN"
    assert chunks[0].page == 9


def test_chunk_sections_handles_pdf_heading_without_blank_line():
    sections = [
        ParsedSection(
            text=(
                "I. CHINH SACH BAN HANG\n"
                "Ma van ban: VHOP3_CSBH-V64-260901\n"
                "1. UU DAI THANH TOAN SOM\n"
                "Khach hang thanh toan som duoc chiet khau 5%."
            ),
            page=1,
        )
    ]

    chunks = chunk_sections(sections, chunk_chars=300, overlap_chars=30)

    assert len(chunks) == 2
    assert "Ma van ban: VHOP3_CSBH-V64-260901" in chunks[0].text
    assert "I. CHINH SACH BAN HANG > 1. UU DAI THANH TOAN SOM" in chunks[1].text
    assert "chiet khau 5%" in chunks[1].text


def test_chunk_sections_keeps_bullet_terms_as_logical_units():
    sections = [
        ParsedSection(
            text=(
                "II. DIEU KHOAN\n"
                "- Ap dung cho can 2PN khi thanh toan som 95%.\n"
                "- Khong cong don voi uu dai khac.\n"
                "- Hieu luc den ngay 31/08/2026."
            ),
            page=4,
        )
    ]

    chunks = chunk_sections(sections, chunk_chars=100, overlap_chars=20)

    assert len(chunks) >= 2
    assert all(chunk.page == 4 for chunk in chunks)
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    assert any("Ap dung cho can 2PN" in chunk.text for chunk in chunks)
    assert any("Khong cong don" in chunk.text for chunk in chunks)


@pytest.mark.parametrize(
    ("chunk_chars", "overlap_chars"),
    [
        (0, 0),
        (-1, 0),
        (100, -1),
        (100, 100),
        (100, 101),
    ],
)
def test_chunk_sections_rejects_invalid_settings(
    chunk_chars: int,
    overlap_chars: int,
):
    sections = [ParsedSection(text="Du lieu", page=1)]

    with pytest.raises(ValueError):
        chunk_sections(
            sections,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
        )


def test_chunk_sections_ignores_empty_sections():
    sections = [
        ParsedSection(text="", page=1),
        ParsedSection(text="   ", page=2),
    ]

    assert chunk_sections(sections) == []


def test_chunk_sections_keeps_small_table_as_one_chunk():
    table = "|Ten du an|The Senique Hanoi|\n|Chu dau tu|CapitaLand|\n|Vi tri|Gia Lam|"
    sections = [ParsedSection(text=table, page=1, content_type="table")]

    chunks = chunk_sections(sections, chunk_chars=3200, overlap_chars=400)

    assert len(chunks) == 1
    assert chunks[0].content_type == "table"
    assert chunks[0].text == table
    assert chunks[0].page == 1


def test_chunk_sections_splits_large_table_without_dropping_rows():
    rows = [f"|A-{number:03d}|2PN|{3 + number / 10:.1f} ty|" for number in range(20)]
    table = "\n".join(rows)
    sections = [ParsedSection(text=table, page=8, content_type="table")]

    chunks = chunk_sections(sections, chunk_chars=100, overlap_chars=20)

    assert len(chunks) > 1
    assert all(chunk.content_type == "table" for chunk in chunks)
    assert all(chunk.page == 8 for chunk in chunks)

    seen_rows = "\n".join(chunk.text for chunk in chunks).splitlines()
    assert sorted(seen_rows) == sorted(rows)


def test_chunk_sections_table_chunks_do_not_exceed_chunk_chars():
    rows = [f"|A-{number:03d}|2PN|{3 + number / 10:.1f} ty|" for number in range(20)]
    table = "\n".join(rows)
    sections = [ParsedSection(text=table, page=8, content_type="table")]

    chunks = chunk_sections(sections, chunk_chars=100, overlap_chars=20)

    assert all(len(chunk.text) <= 100 for chunk in chunks)


def test_legal_chunking_preserves_article_clause_and_point_breadcrumbs():
    sections = [
        ParsedSection(
            text=(
                "CHƯƠNG II QUYỀN VÀ NGHĨA VỤ\n"
                "Điều 12. Nghĩa vụ cung cấp thông tin\n"
                "1. Chủ đầu tư phải công khai thông tin dự án.\n"
                "a) Thông tin về giá bán và tiến độ thanh toán.\n"
                "b) Thông tin về tình trạng pháp lý của dự án.\n"
                "2. Thông tin phải chính xác và đầy đủ.\n"
                "Điều 13. Hiệu lực áp dụng\n"
                "1. Điều này có hiệu lực từ ngày 01/08/2026."
            ),
            page=4,
        )
    ]

    chunks = chunk_sections(
        sections,
        chunk_chars=260,
        overlap_chars=30,
        document_category="legal_document",
    )

    assert all(chunk.page == 4 for chunk in chunks)
    assert any("Điều 12" in chunk.text and "Khoản 1" in chunk.text and "Điểm a" in chunk.text for chunk in chunks)
    assert any("Điều 12" in chunk.text and "Khoản 2" in chunk.text for chunk in chunks)
    assert any("Điều 13" in chunk.text and "Khoản 1" in chunk.text for chunk in chunks)
    assert not any("Điều 12" in chunk.text and "Điều 13" in chunk.text for chunk in chunks)


def test_price_table_repeats_header_and_never_splits_a_row():
    header = "| Mã căn | Loại căn | Diện tích | Giá bán |"
    separator = "| --- | --- | --- | --- |"
    rows = [f"| BE1-{number:02d} | 2PN | 68 m2 | {3.2 + number / 10:.1f} tỷ |" for number in range(8)]
    sections = [
        ParsedSection(
            text="\n".join([header, separator, *rows]),
            page=7,
        )
    ]

    chunks = chunk_sections(
        sections,
        chunk_chars=150,
        overlap_chars=20,
        document_category="price_list",
    )

    assert len(chunks) > 1
    assert all(header in chunk.text for chunk in chunks)
    assert all(separator in chunk.text for chunk in chunks)
    for row in rows:
        assert sum(row in chunk.text for chunk in chunks) == 1


def test_price_table_recognises_pdf_rows_separated_by_multiple_spaces():
    sections = [
        ParsedSection(
            text=(
                "Mã căn    Loại căn    Diện tích    Giá bán\n"
                "A-101     2PN          68 m2         3.5 tỷ\n"
                "A-102     3PN          92 m2         4.8 tỷ"
            ),
            page=9,
        )
    ]

    chunks = chunk_sections(
        sections,
        chunk_chars=100,
        overlap_chars=10,
        document_category="price_list",
    )

    assert len(chunks) == 2
    assert all("Mã căn" in chunk.text for chunk in chunks)
    assert any("A-101" in chunk.text and "3.5 tỷ" in chunk.text for chunk in chunks)
    assert any("A-102" in chunk.text and "4.8 tỷ" in chunk.text for chunk in chunks)
