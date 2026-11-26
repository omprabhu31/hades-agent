from agent.macro.house_route import HouseVisits, gift_done, mirror_done, rack_done, ready_for_action


def test_ordinary_cycle_and_reentry_are_new_visits():
    v = HouseVisits()
    v.observe("DeathArea")
    assert v.pending("gift")
    v.record("gift", done=True)
    assert not v.pending("gift")
    v.observe("DeathAreaBedroom")
    v.observe("DeathArea")          # walked back to the Hall: a new visit
    assert v.pending("gift")


def test_same_map_frames_do_not_start_visits():
    v = HouseVisits()
    for _ in range(5):
        v.observe("RoomPreRun")
    assert v.visit == 1


def test_leaving_the_house_and_returning_is_a_new_visit():
    v = HouseVisits()
    v.observe("RoomPreRun")
    v.record("rack", done=True)
    v.observe(None)                 # a run
    v.observe("RoomPreRun")
    assert v.pending("rack")


def test_proven_no_action_retries_once_then_stops():
    v = HouseVisits()
    v.observe("DeathArea")
    v.record("gift", gift_done({"status": "target_unreachable"}))
    assert v.pending("gift")
    v.record("gift", gift_done({"status": "target_unreachable"}))
    assert not v.pending("gift")


def test_possible_actions_latch():
    assert gift_done({"status": "unconfirmed"}) and gift_done({"status": "gifted"})
    assert gift_done({"status": "no_nectar"})          # final, nothing to retry
    assert not rack_done({"status": "menu_unavailable"}) and rack_done({"status": "close_timeout"})
    assert mirror_done([{"name": "x"}]) and not mirror_done([])


def test_ready_for_action():
    assert ready_for_action({"hud": True, "screens": [], "screen": "InGameUI"})
    assert not ready_for_action({"hud": False, "screens": []})
    assert not ready_for_action({"hud": True, "screens": ["Dialog"]})
    assert not ready_for_action({"hud": True, "screens": [], "screen": "LoadScreen"})
