"""Generate Vinhomes Ocean Park sub-zone JSON files into data/seed/:
The Beverly, The London, The Paris, The Zenpark, The Pavilion, The Senique Hanoi.

Data was manually extracted from vinhomeoceanpark.com.vn (see each build_* function's
docstring) and hardcoded into this script — no network calls. Safe to re-run (idempotent),
overwrites existing files.

Usage:
    python scripts/seed/generate_sub_zone_json.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "seed"


def _pricing_row(
    category: str,
    apartment_type: str,
    size_min: float | None,
    size_max: float | None,
    price_min: int | None,
    price_max: int | None,
    description: str,
    price_note: str | None = None,
) -> dict[str, Any]:
    """price_min/price_max = None when the source page says 'sold out' or 'pending update' —
    price_note keeps the original reason verbatim, so the AI doesn't infer a price that doesn't exist."""
    row = {
        "category": category,
        "apartment_type": apartment_type,
        "size_min_sqm": size_min,
        "size_max_sqm": size_max,
        "price_min": price_min,
        "price_max": price_max,
        "currency": "VND",
        "description": description,
    }
    if price_note:
        row["price_note"] = price_note
    return row


def _floor_plan_slots(project_id: str, towers: list[str]) -> list[dict[str, Any]]:
    """One empty slot (url=None) per tower — waiting for the admin to upload the actual floor plan image."""
    return [
        {"tower": tower, "floor_label": f"Mặt bằng tòa {tower}", "display_order": i + 1, "url": None}
        for i, tower in enumerate(towers)
    ]


def build_the_beverly() -> dict[str, Any]:
    """Source: https://vinhomeoceanpark.com.vn/the-beverly (retrieved 2026-08-08)."""
    return {
        "project": {
            "id": "the-beverly",
            "name": "The Beverly",
            "full_name": "The Beverly - Vinhomes Ocean Park",
            "parent_project_id": "vinhomes-ocean-park",
            "sub_zone": "The Metropolitan",
            "developer": "Mitsubishi Corporation và Vingroup",
            "location": {
                "district": "Quận Gia Lâm",
                "city": "Hà Nội",
                "within": "Vinhomes Ocean Park",
            },
            "description": "The Beverly là phân khu căn hộ thuộc The Metropolitan, Vinhomes Ocean Park.",
            "overview": {
                "towers": ["BE1", "BE2", "BE3", "BE4"],
                "towers_on_sale": ["BE1", "BE2", "BE3", "BE4"],
                "total_units": 1825,
                "unit_types": "Studio, 1 ngủ, 2 ngủ, 2 ngủ + 1, 3 ngủ",
                "area_range": "28 – 108,2m²",
                "floors": "24 – 26 tầng",
                "handover": "Quý 3/2026",
                "ownership": "Sở hữu không thời hạn",
            },
            "location_highlights": [
                "Kế cận Quảng trường ga Metro tuyến 8",
                "Kế cận đường Lý Thánh Tông",
                "Giáp các tuyến Vinbus",
                "Giáp đường Hải Đăng 3/5/8",
            ],
        },
        "pricing": [
            _pricing_row("Chung cư", "Studio", 28, 36, 1800000000, 2100000000, "Căn hộ studio"),
            _pricing_row("Chung cư", "1 ngủ", 43.2, 48.6, 2500000000, 3200000000, "Căn hộ 1 phòng ngủ"),
            _pricing_row("Chung cư", "2 ngủ", 54.4, 75.3, 3100000000, 4200000000, "Căn hộ 2 phòng ngủ"),
            _pricing_row("Chung cư", "2 ngủ + 1", 76.2, 79, 4200000000, 4500000000, "Căn hộ 2 phòng ngủ cộng"),
            _pricing_row("Chung cư", "3 ngủ", 81.5, 109.2, 5300000000, 6500000000, "Căn hộ 3 phòng ngủ"),
        ],
        "sales_policies": [
            {"no": 1, "type": "Chiết khấu", "content": "Chiết khấu 1% khi không nhận bảo lãnh ngân hàng"},
            {"no": 2, "type": "Chiết khấu", "content": "Early Bird chiết khấu 4% cho 150 căn đầu tiên"},
            {"no": 3, "type": "Thanh toán", "content": "Thanh toán 14 đợt, mỗi đợt 3–5%"},
            {"no": 4, "type": "Vay vốn", "content": "Hỗ trợ vay 70% giá trị căn hộ, lãi suất 0%, ân hạn nợ gốc đến 20/12/2026"},
        ],
        "amenities": [
            {"name": "Bể bơi Santa Monica", "category": "Tiện ích ngoài trời"},
            {"name": "Quảng trường Beverly", "category": "Tiện ích ngoài trời"},
            {"name": "Đài phun nước", "category": "Tiện ích ngoài trời"},
            {"name": "Vườn đọc sách", "category": "Tiện ích ngoài trời"},
            {"name": "Sân chơi sắc màu", "category": "Tiện ích ngoài trời"},
            {"name": "Gym & Sauna", "category": "Tiện ích trong nhà"},
            {"name": "Kids Corner", "category": "Tiện ích trong nhà"},
            {"name": "Game room", "category": "Tiện ích trong nhà"},
        ],
        "images": {
            "gallery": [],
            "location_maps": [],
            "master_plan": [],
            "floor_plans": _floor_plan_slots("the-beverly", ["BE1", "BE2", "BE3", "BE4"]),
            "interior": [],
        },
        "contact": {"hotline": "+84915976556", "phone": "091 597 6556", "business_hours": "24/7"},
    }


def build_the_london() -> dict[str, Any]:
    """Source: https://vinhomeoceanpark.com.vn/the-london (retrieved 2026-08-08)."""
    return {
        "project": {
            "id": "the-london",
            "name": "The London",
            "full_name": "The London - Vinhomes Ocean Park",
            "parent_project_id": "vinhomes-ocean-park",
            "sub_zone": "The Metropolitan",
            "developer": "Mitsubishi Corporation và Vingroup",
            "location": {
                "district": "Quận Gia Lâm",
                "city": "Hà Nội",
                "within": "Vinhomes Ocean Park",
            },
            "description": "The London là một trong những phân khu căn hộ cuối cùng được triển khai xây dựng và mở bán tại Vinhomes Ocean Park, thiết kế theo kiến trúc London.",
            "overview": {
                "towers": ["LD1", "LD2", "LD3"],
                "towers_on_sale": ["LD1", "LD2", "LD3"],
                "total_units": "hơn 1.750 căn",
                "unit_types": "Studio, 1 ngủ, 1 ngủ +1, 2 ngủ, 3 ngủ",
                "area_range": "26,6 – 99,5m²",
                "floors": "26 – 29 tầng",
                "handover": "Quý 3/2026",
                "ownership": "Sở hữu không thời hạn",
            },
            "location_highlights": [
                "Đông Bắc: đường Hải Đăng 8, Quảng trường Ga Metro",
                "Đông Nam: đường nội khu, giáp phân khu The Beverly",
                "Tây Nam: đường Hải Đăng 5",
                "Tây Bắc: đường Lý Thánh Tông (tuyến Metro số 08)",
            ],
        },
        "pricing": [
            _pricing_row("Chung cư", "Studio", 26.6, 38, 1700000000, 2200000000, "Căn hộ studio"),
            _pricing_row("Chung cư", "1 ngủ", 37.2, 43.9, 2300000000, 2700000000, "Căn hộ 1 phòng ngủ"),
            _pricing_row("Chung cư", "1 ngủ + 1", 47.6, 48.4, 2800000000, 3200000000, "Căn hộ 1 phòng ngủ cộng"),
            _pricing_row("Chung cư", "2 ngủ", 56.8, 64.2, 3700000000, 4100000000, "Căn hộ 2 phòng ngủ"),
            _pricing_row("Chung cư", "2 ngủ + 1", 76.7, 76.7, 4400000000, 4700000000, "Căn hộ 2 phòng ngủ cộng"),
            _pricing_row("Chung cư", "3 ngủ", 81.6, 99.5, 5000000000, 6500000000, "Căn hộ 3 phòng ngủ"),
        ],
        "sales_policies": [
            {"no": 1, "type": "Chiết khấu", "content": "Chiết khấu 1% khi không nhận bảo lãnh ngân hàng"},
            {"no": 2, "type": "Chiết khấu", "content": "Chiết khấu 3% cho khách hàng tiên phong"},
            {"no": 3, "type": "Quà tặng", "content": "Quà tặng nội thất tương đương chiết khấu 3%"},
            {"no": 4, "type": "Thanh toán", "content": "Thanh toán theo 14 đợt, mỗi đợt 3–5%"},
            {"no": 5, "type": "Vay vốn", "content": "Hỗ trợ vay 70% giá trị căn hộ, lãi suất 0%, ân hạn nợ gốc 24–27 tháng"},
        ],
        "amenities": [
            {"name": "Bể bơi Santa Monica", "category": "Tiện ích ngoài trời"},
            {"name": "Sân thể thao", "category": "Tiện ích ngoài trời"},
            {"name": "Sân chơi trẻ em", "category": "Tiện ích ngoài trời"},
            {"name": "Gym ngoài trời", "category": "Tiện ích ngoài trời"},
            {"name": "Công viên", "category": "Tiện ích ngoài trời"},
            {"name": "Phòng tập Gym", "category": "Tiện ích trong nhà"},
            {"name": "Phòng vui chơi trẻ em", "category": "Tiện ích trong nhà"},
            {"name": "Phòng giải trí", "category": "Tiện ích trong nhà"},
            {"name": "Phòng karaoke", "category": "Tiện ích trong nhà"},
            {"name": "Phòng dance", "category": "Tiện ích trong nhà"},
        ],
        "images": {
            "gallery": [],
            "location_maps": [],
            "master_plan": [],
            "floor_plans": _floor_plan_slots("the-london", ["LD1", "LD2", "LD3"]),
            "interior": [],
        },
        "contact": {"hotline": "+84915976556", "phone": "091 597 6556", "business_hours": "24/7"},
    }


def build_the_paris() -> dict[str, Any]:
    """Source: https://vinhomeoceanpark.com.vn/the-paris (retrieved 2026-08-08)."""
    return {
        "project": {
            "id": "the-paris",
            "name": "The Paris",
            "full_name": "The Paris - Vinhomes Ocean Park",
            "parent_project_id": "vinhomes-ocean-park",
            "sub_zone": "The Metropolitan",
            "developer": "Mitsubishi Corporation và Vingroup",
            "location": {
                "district": "Quận Gia Lâm",
                "city": "Hà Nội",
                "within": "Vinhomes Ocean Park",
            },
            "description": "The Paris là khu căn hộ cuối cùng thuộc phân khu The Metropolitan được mở bán tại Vinhomes Ocean Park.",
            "overview": {
                "towers": ["PR1", "PR2", "PR3", "PR5", "PR6"],
                "towers_on_sale": ["PR1", "PR2", "PR3", "PR5", "PR6"],
                "total_units": 3144,
                "unit_types": "Studio, 1PN, 1PN+1, 2PN, 2PN+1, 3PN, 4PN",
                "area_range": "27,1 – 113,1m²",
                "floors": "30 – 38 tầng",
                "handover": "Tháng 12/2026",
                "ownership": "Sở hữu không thời hạn",
            },
            "location_highlights": [
                "Đông Bắc: tiếp giáp đường Hải Đăng và khu đất quân sự",
                "Đông Nam: tiếp giáp đường nội khu và phân khu The Zurich",
                "Tây Nam: tiếp giáp đường Đại Dương, công viên cây xanh, hồ San Hô",
                "Tây Bắc: tiếp giáp đường Lý Thánh Tông (Metro số 08 tương lai)",
            ],
        },
        "pricing": [
            _pricing_row("Chung cư", "Studio", 27.1, 30.9, 1800000000, 2200000000, "Căn hộ studio"),
            _pricing_row("Chung cư", "1PN", 42.7, 43.5, 2700000000, 2800000000, "Căn hộ 1 phòng ngủ"),
            _pricing_row("Chung cư", "1PN+1", 46.5, 54.8, 2900000000, 3300000000, "Căn hộ 1 phòng ngủ cộng"),
            _pricing_row("Chung cư", "2PN", 61.1, 74.2, 3800000000, 4200000000, "Căn hộ 2 phòng ngủ"),
            _pricing_row("Chung cư", "2PN+1", 73.7, 76.8, 4600000000, 4900000000, "Căn hộ 2 phòng ngủ cộng"),
            _pricing_row("Chung cư", "3PN", 83.8, 97.4, 5100000000, 6200000000, "Căn hộ 3 phòng ngủ"),
            _pricing_row("Chung cư", "4PN", 113.1, 113.1, 6700000000, 7300000000, "Căn hộ 4 phòng ngủ"),
        ],
        "sales_policies": [
            {"no": 1, "type": "Chiết khấu", "content": "Chiết khấu 1% khi không nhận bảo lãnh ngân hàng"},
            {"no": 2, "type": "Quà tặng", "content": "Chiết khấu 2% gói quà tặng ban công sân vườn"},
            {"no": 3, "type": "Quà tặng", "content": "Chiết khấu 3% gói quà tặng nội thất"},
            {"no": 4, "type": "Chiết khấu", "content": "Chiết khấu 3–6% dành cho 100 khách hàng tiên phong"},
            {"no": 5, "type": "Thanh toán", "content": "Không vay: thanh toán 14 đợt (2–3% mỗi đợt)"},
            {"no": 6, "type": "Thanh toán", "content": "Tối đa thanh toán 50% trước khi nhận bàn giao"},
            {"no": 7, "type": "Vay vốn", "content": "Hỗ trợ vay 70% giá trị căn hộ, lãi suất 0%, ân hạn nợ gốc 24 tháng"},
        ],
        "amenities": [
            {"name": "Sảnh lễ tân", "category": "Tiện ích nội tòa"},
            {"name": "Cigar Lounge", "category": "Tiện ích nội tòa"},
            {"name": "Phòng tập Gym", "category": "Tiện ích nội tòa"},
            {"name": "Phòng Yoga", "category": "Tiện ích nội tòa"},
            {"name": "Phòng tập Pilates", "category": "Tiện ích nội tòa"},
            {"name": "Phòng vui chơi trẻ em", "category": "Tiện ích nội tòa"},
            {"name": "Phòng Trà/Lounge/Âm nhạc", "category": "Tiện ích nội tòa"},
            {"name": "Phòng làm việc", "category": "Tiện ích nội tòa"},
            {"name": "Phòng Bida/Game", "category": "Tiện ích nội tòa"},
        ],
        "images": {
            "gallery": [],
            "location_maps": [],
            "master_plan": [],
            "floor_plans": _floor_plan_slots("the-paris", ["PR1", "PR2", "PR3", "PR5", "PR6"]),
            "interior": [],
        },
        "contact": {"hotline": "+84915976556", "phone": "091 597 6556", "business_hours": "24/7"},
    }


def build_the_zenpark() -> dict[str, Any]:
    """Source: https://vinhomeoceanpark.com.vn/the-zenpark (retrieved 2026-08-08).

    Sold directly by Vinhomes (not via Mitsubishi/Masterise like other sub-zones).
    The 3BR+1 unit type is sold out — price_min/max=None, price_note keeps the status.
    """
    return {
        "project": {
            "id": "the-zenpark",
            "name": "The Zenpark",
            "full_name": "The Zenpark - Vinhomes Ocean Park",
            "parent_project_id": "vinhomes-ocean-park",
            "developer": "Vinhomes",
            "location": {
                "district": "Quận Gia Lâm",
                "city": "Hà Nội",
                "within": "Vinhomes Ocean Park",
            },
            "description": "The Zenpark là khu căn hộ cao cấp bậc nhất tại Quận Ocean, Vinhomes Ocean Park, đã bàn giao và nhận nhà ngay.",
            "overview": {
                "towers": ["R1.01", "R1.02", "R1.03", "R1.05"],
                "towers_on_sale": ["R1.01", "R1.02", "R1.03", "R1.05"],
                "total_units": "hơn 2.500 căn hộ cao cấp",
                "unit_types": "Studio, 1 ngủ, 1 ngủ+1, 2 ngủ, 2 ngủ+1, 3 ngủ, 3 ngủ+1",
                "area_range": "27 – 100,6m²",
                "handover": "Nhận nhà ngay",
                "ownership": "Sở hữu không thời hạn",
            },
            "location_highlights": [
                "Kế cận đường Lý Thánh Tông",
                "Gần cao tốc Hà Nội – Hải Phòng",
                "Liền kề biệt thự khu Ngọc Trai",
            ],
        },
        "pricing": [
            _pricing_row("Chung cư", "Studio", 27, 30, 1200000000, 1600000000, "Căn hộ studio"),
            _pricing_row("Chung cư", "1 ngủ", 41, 45, 1700000000, 2300000000, "Căn hộ 1 phòng ngủ"),
            _pricing_row("Chung cư", "1 ngủ + 1", 47, 52, 2000000000, 2500000000, "Căn hộ 1 phòng ngủ cộng"),
            _pricing_row("Chung cư", "2 ngủ", 64, 70, 3000000000, 3500000000, "Căn hộ 2 phòng ngủ"),
            _pricing_row("Chung cư", "2 ngủ + 1", 74, 77, 3500000000, 4300000000, "Căn hộ 2 phòng ngủ cộng"),
            _pricing_row("Chung cư", "3 ngủ", 76, 82, 3500000000, 4800000000, "Căn hộ 3 phòng ngủ"),
            _pricing_row("Chung cư", "3 ngủ + 1", 88, 100.6, None, None, "Căn hộ 3 phòng ngủ cộng", price_note="Đã bán hết"),
        ],
        "sales_policies": [
            {"no": 1, "type": "Quà tặng", "content": "Tặng 2 năm phí để xe ô tô"},
            {"no": 2, "type": "Quà tặng", "content": "Quà tặng ban công xanh trị giá 30 triệu đồng"},
            {"no": 3, "type": "Quà tặng", "content": "Voucher lên tới 50% dịch vụ Vingroup"},
            {"no": 4, "type": "Chiết khấu", "content": "Thanh toán linh hoạt, chiết khấu lên tới 16,5% khi thanh toán sớm"},
        ],
        "amenities": [
            {"name": "Vườn Nhật", "category": "Cảnh quan", "size": "6.208 m²"},
            {"name": "Bể bơi Olympic 4 mùa", "category": "Thể thao & Sức khỏe"},
            {"name": "Nhà để xe 5 tầng", "category": "Tiện ích nội khu"},
            {"name": "Phòng Gym", "category": "Thể thao & Sức khỏe"},
            {"name": "Sân thể thao", "category": "Thể thao & Sức khỏe"},
            {"name": "Khu vui chơi trẻ em", "category": "Tiện ích ngoài trời"},
        ],
        "images": {
            "gallery": [],
            "location_maps": [],
            "master_plan": [],
            "floor_plans": _floor_plan_slots("the-zenpark", ["R1.01", "R1.02", "R1.03", "R1.05"]),
            "interior": [],
        },
        "contact": {"hotline": "+84915976556", "phone": "091 597 6556", "business_hours": "24/7"},
    }


def build_the_pavilion() -> dict[str, Any]:
    """Source: https://vinhomeoceanpark.com.vn/the-pavilion (retrieved 2026-08-08)."""
    return {
        "project": {
            "id": "the-pavilion",
            "name": "The Pavilion",
            "full_name": "The Pavilion - Vinhomes Ocean Park",
            "parent_project_id": "vinhomes-ocean-park",
            "sub_zone": "The Ocean View",
            "developer": "Vinhomes",
            "location": {
                "district": "Quận Gia Lâm",
                "city": "Hà Nội",
                "within": "Vinhomes Ocean Park",
            },
            "description": "The Pavilion là 'ốc đảo xanh giữa lòng Thành phố Biển Ocean City', thuộc phân khu The Ocean View, Vinhomes Ocean Park.",
            "overview": {
                "towers": ["P1", "P2", "P3", "P4"],
                "towers_on_sale": ["P1", "P2", "P3", "P4"],
                "total_units": "hơn 2.600 căn",
                "unit_types": "Studio, 1 ngủ, 1 ngủ+1, 2 ngủ, 3 ngủ",
                "area_range": "27 – 98,4m²",
                "floors": "30 – 32 tầng",
                "handover": "Từ tháng 3/2024",
                "ownership": "Sở hữu không thời hạn",
            },
            "location_highlights": [
                "Mặt đường Lý Thánh Tông rộng 40m",
            ],
        },
        "pricing": [
            _pricing_row("Chung cư", "Studio", 27, 35, 1400000000, 1600000000, "Căn hộ studio"),
            _pricing_row("Chung cư", "1 ngủ", 35, 47, 1600000000, 2300000000, "Căn hộ 1 phòng ngủ"),
            _pricing_row("Chung cư", "1 ngủ + 1", 43, 48, 2000000000, 2300000000, "Căn hộ 1 phòng ngủ cộng"),
            _pricing_row("Chung cư", "2 ngủ", 53, 74, 2400000000, 3300000000, "Căn hộ 2 phòng ngủ"),
            _pricing_row("Chung cư", "3 ngủ", 78, 99.5, 4100000000, 5100000000, "Căn hộ 3 phòng ngủ"),
        ],
        "tower_details": {
            "P4": {
                "subdivision": "The Pavilion",
                "parent_sub_zone": "The Ocean View",
                "scale": "30 tầng nổi và 2 tầng hầm",
                "floor_use": [
                    "Tầng 1–2: shophouse",
                    "Tầng 3–13 và 15–30: căn hộ",
                    "Tầng 14: phòng lánh nạn",
                ],
                "road_adjacency": "Kề đường nội khu rộng 17 m; không trực tiếp bám mặt đường Lý Thánh Tông",
                "boundaries": [
                    "Phía Đông Bắc: trường học",
                    "Phía Đông Nam: khu thấp tầng BF3 và The Royal Sail",
                    "Phía Tây Nam: tiện ích nội khu và tòa P3",
                    "Phía Tây Bắc: tòa P1",
                ],
                "source_name": "Vinhomes Market — Tòa P4 Vinhomes Ocean Park",
                "source_url": "https://market.vinhomes.vn/blog/toa-p4-vinhomes-ocean-park",
            }
        },
        "sales_policies": [
            {"no": 1, "type": "Chiết khấu", "content": "Chiết khấu lên tới 9%"},
            {"no": 2, "type": "Quà tặng", "content": "Tặng miễn phí gói Premium Smart Home"},
            {"no": 3, "type": "Vay vốn", "content": "Hỗ trợ vay 0% lãi suất, ân hạn nợ gốc đến tháng 6/2025"},
            {"no": 4, "type": "Quà tặng", "content": "Quà tặng trị giá lên tới 150 triệu đồng"},
        ],
        "amenities": [
            {"name": "Botanic Garden", "category": "Cảnh quan"},
            {"name": "Hồ cảnh quan", "category": "Cảnh quan"},
            {"name": "Đảo Yoga", "category": "Thể thao & Sức khỏe"},
            {"name": "Khu vui chơi trẻ em", "category": "Tiện ích ngoài trời"},
            {"name": "Bể trị liệu", "category": "Thể thao & Sức khỏe"},
        ],
        "images": {
            "gallery": [],
            "location_maps": [],
            "master_plan": [],
            "floor_plans": _floor_plan_slots("the-pavilion", ["P1", "P2", "P3", "P4"]),
            "interior": [],
        },
        "contact": {"hotline": "+84915976556", "phone": "091 597 6556", "business_hours": "24/7"},
    }


def build_the_senique_hanoi() -> dict[str, Any]:
    """Source: https://vinhomeoceanpark.com.vn/the-senique-hanoi (retrieved 2026-08-08).

    The Senique is the only sub-zone NOT developed by Vinhomes/Mitsubishi/Masterise — its
    developer is CapitaLand Development. Per-unit-type prices are all "pending update" on the
    source page, with only a starting price of 68 million/sqm — no specific min/max price is
    inferred, to avoid giving customers incorrect advice.
    """
    return {
        "project": {
            "id": "the-senique-hanoi",
            "name": "The Senique Hanoi",
            "full_name": "The Senique Hanoi - Vinhomes Ocean Park",
            "parent_project_id": "vinhomes-ocean-park",
            "developer": "Công ty Cổ phần đầu tư phát triển kinh doanh Bình Minh (thành viên CapitaLand Development)",
            "location": {
                "district": "Quận Gia Lâm",
                "city": "Hà Nội",
                "within": "Vinhomes Ocean Park",
                "area_hectares": 2.2,
            },
            "description": "The Senique Hanoi là khu căn hộ cao cấp tọa lạc tại vị trí trung tâm Vinhomes Ocean Park, dự án đầu tiên theo mô hình Compound (khu khép kín) tại Ocean Park.",
            "overview": {
                "towers": ["The Senique 1", "The Senique 2", "The Senique Premier"],
                "towers_on_sale": ["The Senique 1", "The Senique 2", "The Senique Premier"],
                "total_units": 2152,
                "unit_types": "1BR, 2BR, 3BR, 4BR, Duplex, Penthouse",
                "floors": 37,
                "handover": "Quý 2/2027",
                "ownership": "Sở hữu không thời hạn",
                "starting_price_per_sqm": "68 triệu đồng/m²",
            },
            "location_highlights": [
                "Kế cận đường Đại Tây Dương rộng 40m",
                "Gần tuyến Metro số 08",
                "Gần cao tốc đi Hải Phòng",
                "Bao quanh bởi trường học, khu bán lẻ và hồ nước, tầm nhìn 4 hướng",
            ],
        },
        "pricing": [
            _pricing_row("Chung cư", "1BR", 42, 42, None, None, "Căn hộ 1 phòng ngủ", price_note="Đang cập nhật"),
            _pricing_row("Chung cư", "2BR", 54, 81, None, None, "Căn hộ 2 phòng ngủ", price_note="Đang cập nhật"),
            _pricing_row("Chung cư", "3BR", 83, 108, None, None, "Căn hộ 3 phòng ngủ", price_note="Đang cập nhật"),
            _pricing_row("Chung cư", "4BR", 154, 188, None, None, "Căn hộ 4 phòng ngủ", price_note="Đang cập nhật"),
            _pricing_row("Chung cư", "Duplex", 118, 190, None, None, "Căn hộ thông tầng", price_note="Đang cập nhật"),
            _pricing_row("Chung cư", "Penthouse", 352, 432, None, None, "Căn hộ penthouse", price_note="Đang cập nhật"),
        ],
        "sales_policies": [
            {"no": 1, "type": "Vay vốn", "content": "Hỗ trợ vay ngân hàng, chiết khấu khoảng 9%, lãi suất 0% cho 30% giá trị căn hộ đến khi bàn giao"},
            {"no": 2, "type": "Thanh toán", "content": "Thanh toán tiêu chuẩn: chiết khấu khoảng 11%"},
            {"no": 3, "type": "Thanh toán", "content": "Thanh toán nhanh: chiết khấu khoảng 12%"},
        ],
        "amenities": [
            {"name": "Bể bơi 50m", "category": "Thể thao & Sức khỏe"},
            {"name": "Jacuzzi", "category": "Thể thao & Sức khỏe"},
            {"name": "Vườn BBQ", "category": "Tiện ích ngoài trời"},
            {"name": "Phòng Gym", "category": "Thể thao & Sức khỏe"},
            {"name": "Sân Golf 3D", "category": "Tiện ích trong nhà"},
            {"name": "Phòng Party", "category": "Tiện ích trong nhà"},
            {"name": "Không gian Co-working", "category": "Tiện ích trong nhà"},
            {"name": "Cổng an ninh giám sát 24/7", "category": "An toàn & Bảo an"},
        ],
        "amenities_summary": "60 tiện ích độc bản gồm 26 tiện ích ngoài trời và 34 tiện ích trong nhà",
        "images": {
            "gallery": [],
            "location_maps": [],
            "master_plan": [],
            "floor_plans": _floor_plan_slots(
                "the-senique-hanoi", ["The Senique 1", "The Senique 2", "The Senique Premier"]
            ),
            "interior": [],
        },
        "contact": {"hotline": "+84915976556", "phone": "091 597 6556", "business_hours": "24/7"},
    }


def main() -> None:
    SEED_DIR.mkdir(parents=True, exist_ok=True)

    builders = {
        "the_beverly.json": build_the_beverly,
        "the_london.json": build_the_london,
        "the_paris.json": build_the_paris,
        "the_zenpark.json": build_the_zenpark,
        "the_pavilion.json": build_the_pavilion,
        "the_senique_hanoi.json": build_the_senique_hanoi,
    }

    for filename, builder in builders.items():
        data = builder()
        out_path = SEED_DIR / filename
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {filename}: {len(data['pricing'])} dong gia, {len(data['amenities'])} tien ich")

    print(f"\nDa ghi {len(builders)} file vao {SEED_DIR}")


if __name__ == "__main__":
    main()
