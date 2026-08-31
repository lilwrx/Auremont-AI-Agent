"""The inventory summary sentence's total has to match the listings carousel under it.

`_INVENTORY_PRESENTATION_RULES` asks the model for exactly one summary line carrying the
total number of matching units, while each unit renders as its own `listings` card.
Counting the list is the part the model gets wrong: observed in production writing "Có
tổng cộng 4 căn 2 phòng ngủ và 2PN+1 còn trống tại The Sapphire" directly above a carousel
of 8 real cards (S1-0203/0402/0104/0303 and S2-0203/0401/0303/0104).

`correct_unit_count` recomputes that number from the final listings instead. The other
half of this file is the harder half: the cases it must NOT touch, because a scoped
sub-count rewritten to the carousel length turns a true sentence into a false one.
"""

from backend.ai.answer_cleanup import correct_unit_count


def test_rewrites_the_reported_miscount_to_the_real_card_count():
    answer = (
        "Có tổng cộng 4 căn 2 phòng ngủ và 2PN+1 còn trống tại The Sapphire, "
        "với mức giá từ 2,82 tỷ đồng đến 3,40 tỷ đồng."
    )

    corrected = correct_unit_count(answer, 8)

    assert corrected.startswith("Có tổng cộng 8 căn 2 phòng ngủ")
    assert "từ 2,82 tỷ đồng đến 3,40 tỷ đồng" in corrected


def test_leaves_an_already_correct_total_untouched():
    answer = "Có tổng cộng 8 căn 2 phòng ngủ còn trống, giá từ 2,82 tỷ đến 3,40 tỷ đồng."

    assert correct_unit_count(answer, 8) == answer


def test_corrects_a_total_spelled_out_as_a_word():
    """Vietnamese routinely spells small counts ("bốn căn"), so digits alone would miss."""
    assert correct_unit_count("Hiện có bốn căn 2PN còn trống ạ.", 8) == "Hiện có 8 căn 2PN còn trống ạ."


def test_leaves_a_floor_scoped_subcount_alone():
    """The sharpest failure mode: "Có 2 căn tại tầng 12" is a count of ONE floor and can be
    true while the grand total is 4. Rewriting it would manufacture a falsehood, which is
    worse than the miscount this function exists to fix."""
    answer = "Có 2 căn tại tầng 12, diện tích 63,5 m²."

    assert correct_unit_count(answer, 4) == answer


def test_leaves_a_status_scoped_subcount_alone():
    answer = "Có 4 căn còn trống, và 4 căn khác đã bán."

    assert correct_unit_count(answer, 8) == answer


def test_ignores_numbers_that_are_not_unit_counts():
    """A bedroom count, a price and a percentage all carry digits; none is a unit total."""
    for answer in (
        "Giá căn này là 3,4 tỷ đồng ạ.",
        "Chính sách chiết khấu 3% cho khách tiên phong.",
        "Mỗi căn đều có ban công hướng Nam.",
    ):
        assert correct_unit_count(answer, 5) == answer


def test_leaves_a_zero_result_answer_alone():
    """ "không còn căn nào" is correct prose carrying no number to fix; forcing "0 căn"
    into it would read worse than leaving it."""
    answer = "Hiện không còn căn nào khớp yêu cầu ạ."

    assert correct_unit_count(answer, 0) == answer
