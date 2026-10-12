"""Cue model tests: identifiers, uniqueness, ordering (Sections 5, 11)."""

from bhs_player.cues.model import (
    ActionType,
    AdvanceMode,
    Cue,
    CueSet,
    validate_identifier,
)


def test_identifier_text_preserved():
    # 12.10 must never become 12.1 (Section 11)
    a = Cue(identifier="12.1")
    b = Cue(identifier="12.10")
    assert a.identifier == "12.1"
    assert b.identifier == "12.10"
    assert a.identifier != b.identifier


def test_identifier_validation():
    assert validate_identifier("12.0")
    assert validate_identifier("12.10")
    assert validate_identifier("47.23")
    assert not validate_identifier("12")
    assert not validate_identifier("12.")
    assert not validate_identifier(".1")
    assert not validate_identifier("abc")
    assert not validate_identifier("12.1.1")


def test_identifiers_unique_detection():
    cs = CueSet(play_name="Clue")
    cs.insert(Cue(identifier="12.0"))
    cs.insert(Cue(identifier="12.1"))
    assert cs.identifiers_unique()
    cs.insert(Cue(identifier="12.0"))
    assert not cs.identifiers_unique()


def test_performance_order_independent_of_identifier_sort():
    cs = CueSet(play_name="Clue")
    cs.insert(Cue(identifier="47.2"))
    cs.insert(Cue(identifier="12.1"))
    cs.insert(Cue(identifier="12.10"))
    order = [c.identifier for c in cs.performance_order()]
    assert order == ["47.2", "12.1", "12.10"]


def test_explicit_insert_between_identifiers_no_reorder():
    cs = CueSet(play_name="Clue")
    cs.insert(Cue(identifier="12.0"))
    cs.insert(Cue(identifier="12.2"))
    middle = Cue(identifier="12.1")
    cs.insert(middle, index=1)
    assert [c.identifier for c in cs.performance_order()] == ["12.0", "12.1", "12.2"]
    # moving 12.10 between 12.1 and 12.2 must keep that position exactly
    late = Cue(identifier="12.10")
    cs.insert(late, index=2)
    assert [c.identifier for c in cs.performance_order()] == [
        "12.0", "12.1", "12.10", "12.2",
    ]


def test_move_reorders_explicitly():
    cs = CueSet(play_name="Clue")
    a, b, c = Cue(identifier="1.0"), Cue(identifier="2.0"), Cue(identifier="3.0")
    for x in (a, b, c):
        cs.insert(x)
    assert cs.move(c.internal_id, 0)
    assert [x.identifier for x in cs.performance_order()] == ["3.0", "1.0", "2.0"]


def test_stable_internal_id_survives_reorder_and_rename():
    cue = Cue(identifier="12.1")
    original_id = cue.internal_id
    cs = CueSet(play_name="Clue", cues=[cue, Cue(identifier="12.2")])
    cs.move(cue.internal_id, 1)
    cue.identifier = "99.5"
    assert cue.internal_id == original_id
    assert cs.by_internal_id(original_id) is cue


def test_loop_on_complete_invalid():
    cue = Cue(identifier="1.0", loop=True, advance_mode=AdvanceMode.ON_COMPLETE)
    assert not cue.loop_config_valid()
    cue2 = Cue(identifier="1.1", loop=True, advance_mode=AdvanceMode.ON_GO)
    assert cue2.loop_config_valid()


def test_segment_validation():
    cue = Cue(identifier="1.0", start_position=1.0, end_position=4.0)
    assert cue.segment_valid(5.0)
    assert not cue.segment_valid(3.5)  # end beyond file
    bad = Cue(identifier="1.1", start_position=4.0, end_position=1.0)
    assert not bad.segment_valid(5.0)
    default = Cue(identifier="1.2")
    assert default.segment_valid(5.0)  # omitted start/end = whole file


def test_stop_fade_targets_use_internal_id():
    target = Cue(identifier="12.0", action=ActionType.PLAY)
    stop = Cue(identifier="12.1", action=ActionType.STOP,
               target_internal_id=target.internal_id)
    cs = CueSet(play_name="Clue", cues=[target, stop])
    resolved = cs.by_internal_id(stop.target_internal_id)
    assert resolved is target
