"""What survives from one turn into the next turn's prompt.

A listing card's figures are visible on screen but live in the `listings` column, not in
`content`. Anything the next turn needs in order to resolve "căn này" has to be put back
into the history here, or the model answers a follow-up about a specific unit with no idea
which unit it is.
"""

from backend.repositories.message import history_for_pipeline


class _FakeMessage:
    def __init__(self, sender: str, content: str, listings: list[dict] | None = None):
        self.sender = sender
        self.content = content
        self.listings = listings


def test_history_carries_the_unit_code_of_a_displayed_card():
    """The regression this exists for: the bot showed OCP1-BE3-0201 on a card, was asked
    "căn này nằm ở tầng bao nhiêu?" one turn later, and asked the customer to supply the
    mã căn it had just shown them — because the code never entered its context."""
    history = history_for_pipeline(
        [
            _FakeMessage(
                "agent",
                "Dạ, The Beverly hiện có 1 căn 2 phòng ngủ 71.5 m2, giá 3.17 tỷ đồng.",
                [{"unit_code": "OCP1-BE3-0201", "tower": "BE3", "unit_type": "2PN"}],
            )
        ]
    )

    assert "OCP1-BE3-0201" in history[0]["content"]
    assert "BE3" in history[0]["content"]
    assert "3.17 tỷ đồng" in history[0]["content"], "the original answer text must survive"


def test_history_lists_every_displayed_unit_once():
    history = history_for_pipeline(
        [
            _FakeMessage(
                "agent",
                "Hai lựa chọn ạ.",
                [
                    {"unit_code": "OCP1-BE3-0201", "tower": "BE3"},
                    {"unit_code": "OCP1-BE3-0201", "tower": "BE3"},
                    {"unit_code": "OCP1-ZR1-0301", "tower": "ZR1"},
                ],
            )
        ]
    )

    assert history[0]["content"].count("OCP1-BE3-0201") == 1
    assert "OCP1-ZR1-0301" in history[0]["content"]


def test_history_leaves_turns_without_a_live_unit_untouched():
    """A catalogue card carries no mã căn, and most turns carry no card at all — neither
    should gain an annotation promising an identity that does not exist."""
    history = history_for_pipeline(
        [
            _FakeMessage("customer", "giá bao nhiêu?"),
            _FakeMessage("agent", "Khoảng 3 tỷ ạ.", [{"project_name": "The Beverly", "unit_type": "2PN"}]),
        ]
    )

    assert history[0]["content"] == "giá bao nhiêu?"
    assert history[1]["content"] == "Khoảng 3 tỷ ạ."


def test_history_preserves_sender_and_order():
    history = history_for_pipeline(
        [
            _FakeMessage("customer", "xin chào"),
            _FakeMessage("agent", "Dạ em nghe ạ."),
        ]
    )

    assert [turn["sender"] for turn in history] == ["customer", "agent"]
