from src.citations import attribute

SOURCES = [
    "Open the printer cover. Remove the jammed paper.",
    "Remove the jammed paper, wipe the platen roller and reload the paper.",
    "Check the switch port link light and ping the gateway.",
]


def test_step_cites_best_matching_sources_up_to_two():
    text, matched, unmatched = attribute("1. Remove the jammed paper.", SOURCES)
    assert text == "1. Remove the jammed paper. [1] [2]"
    assert (matched, unmatched) == (1, 0)


def test_weak_secondary_match_is_not_cited():
    sources = [
        "Close the cover until it clicks, then run a test print from the service menu.",
        "Reseat the cassette until it clicks and close the doors. Run the dispense test from the menu.",
    ]
    text, _, _ = attribute("1. Close the cover until it clicks, then run a test print from the service menu.", sources)
    assert text.endswith("menu. [1]")


def test_model_markers_are_stripped_and_replaced():
    text, matched, _ = attribute("1. Ping the gateway. [1] [9]", SOURCES)
    assert text == "1. Ping the gateway. [3]" and matched == 1


def test_unsupported_step_is_left_uncited_and_counted():
    text, matched, unmatched = attribute("1. Replace the motherboard battery.", SOURCES)
    assert text == "1. Replace the motherboard battery."
    assert (matched, unmatched) == (0, 1)


def test_non_step_lines_are_untouched_and_bullets_work():
    answer = "Here is what to do:\n- Wipe the platen roller.\nGood luck."
    text, matched, unmatched = attribute(answer, SOURCES)
    assert text.splitlines() == ["Here is what to do:", "- Wipe the platen roller. [2]", "Good luck."]
    assert (matched, unmatched) == (1, 0)


def test_no_sources_leaves_every_step_unmatched():
    text, matched, unmatched = attribute("1. Do something.\n2. Do another thing.", [])
    assert (matched, unmatched) == (0, 2) and "[" not in text
