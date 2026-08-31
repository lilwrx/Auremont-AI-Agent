"""RiskCheck — the rule set deciding whether an answer needs the HITL card.

This is the gate that stops an AI-generated price or commitment reaching a customer
unread, so these tests pin the detection rules themselves rather than the confirmation
workflow around them (that lives in tests/test_api/test_hitl.py). A silent regression
here — one broken regex, one mistyped keyword — would let priced answers through with
nothing to catch it.

The module deliberately prefers a false positive to a miss, so the "over-matches" class
below asserts that bias holds rather than treating it as a defect.
"""

import pytest

from backend.services.risk_service import detect_commitment_risk


class TestMoneyWithUnit:
    @pytest.mark.parametrize(
        "answer",
        [
            "Giá căn 2PN là 3,6 tỷ đồng.",
            "Căn này 600 triệu.",
            "Chênh 50 nghìn mỗi m2.",
            "Tổng 3.600.000.000 VND.",
            "Giá 2 tỉ.",
        ],
    )
    def test_amount_followed_by_a_currency_unit_is_risky(self, answer):
        assert detect_commitment_risk(answer) is True

    def test_the_same_amounts_are_caught_without_diacritics(self):
        """Sales staff typing on a phone in front of a customer routinely drop accents."""
        assert detect_commitment_risk("Gia can 2PN la 3,6 ty dong.") is True
        assert detect_commitment_risk("Can nay 600 trieu.") is True

    def test_a_measurement_is_not_money(self):
        assert detect_commitment_risk("Diện tích 68 m2, ban công hướng Đông.") is False


class TestBareLargeNumber:
    def test_nine_digits_reads_as_a_price(self):
        assert detect_commitment_risk("Giá 3600000000") is True

    def test_eight_digits_does_not(self):
        """Short codes stay quiet — otherwise every unit code raises the card."""
        assert detect_commitment_risk("Mã căn 12345678") is False

    def test_digits_inside_a_unit_code_do_not_trip_it(self):
        assert detect_commitment_risk("Mã căn A-12345678 còn trống.") is False


class TestPercentage:
    @pytest.mark.parametrize("answer", ["Chiết khấu 5%.", "Lãi suất 8,5 %/năm.", "Hỗ trợ 70%."])
    def test_percentages_are_risky(self, answer):
        assert detect_commitment_risk(answer) is True


class TestCommitmentKeywords:
    @pytest.mark.parametrize(
        "answer",
        [
            "Bên em cam kết bàn giao đúng hạn.",
            "Chúng tôi đảm bảo chất lượng.",
            "Anh chị ký hợp đồng trong tuần này nhé.",
            "Khách đặt cọc để giữ chỗ.",
            "Bên em hỗ trợ vay ngân hàng.",
            "Sổ hồng lâu dài.",
            "Thanh toán theo tiến độ.",
            "Pháp lý dự án đã hoàn thiện.",
        ],
    )
    def test_commitment_wording_is_risky_even_with_no_number(self, answer):
        assert detect_commitment_risk(answer) is True

    def test_keyword_matching_ignores_case(self):
        """`strip_diacritics` lowercases, so an answer shouting the promise still matches."""
        assert detect_commitment_risk("Bên em CAM KẾT bàn giao đúng hạn.") is True

    def test_keyword_matching_ignores_diacritics(self):
        assert detect_commitment_risk("Ben em cam ket ban giao dung han.") is True


class TestNonRiskyAnswers:
    @pytest.mark.parametrize(
        "answer",
        [
            "Dự án có hồ bơi, phòng gym và công viên nội khu.",
            "Tòa BE1 có 20 tầng.",
            "Căn hộ 2 phòng ngủ hướng Đông Nam.",
            "Dự án nằm ở Gia Lâm, Hà Nội.",
        ],
    )
    def test_descriptive_answers_need_no_confirmation(self, answer):
        assert detect_commitment_risk(answer) is False

    @pytest.mark.parametrize("answer", ["", "   ", "\n\t "])
    def test_empty_input_is_not_risky(self, answer):
        assert detect_commitment_risk(answer) is False


class TestDeliberateOverMatching:
    """The module documents a false-positive bias: an unnecessary card costs one click,
    a missed price commitment can become a contract dispute. These pin that trade-off so
    a future "fix" to the noise has to be a deliberate decision, not an accident."""

    def test_a_ten_digit_phone_number_also_trips_the_bare_number_rule(self):
        assert detect_commitment_risk("Liên hệ hotline 0901234567.") is True

    def test_an_everyday_use_of_a_commitment_word_still_matches(self):
        assert detect_commitment_risk("Em chắc chắn sẽ gửi anh tài liệu ngay.") is True
