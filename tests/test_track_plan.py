from simple_train.core import nce, track_plan as tp
from simple_train.core.simulator import SimulatedCommandStation
from simple_train.core.throttle import ThrottleSender


def test_routes_and_rotation():
    assert tp.Tile(0, 0, tp.STRAIGHT).routes() == [(0, 4)]
    assert tp.Tile(0, 0, tp.STRAIGHT, rotation=2).routes() == [(2, 6)]
    assert tp.Tile(0, 0, tp.CURVE, rotation=7).routes() == [(7, 2)]
    point = tp.Tile(0, 0, tp.POINT_RIGHT)
    assert point.routes() == [(0, 4)]
    point.thrown = True
    assert point.routes() == [(0, 3)]
    assert point.ends() == {0, 3, 4}
    assert tp.Tile(0, 0, tp.POINT_LEFT).routes(all_routes=True)[1] == (0, 5)
    assert tp.Tile(0, 0, tp.BUFFER, rotation=4).routes() == [(4,)]


def test_loose_ends():
    plan = tp.Plan()
    a = tp.Tile(5, 5, tp.STRAIGHT)
    b = tp.Tile(6, 5, tp.STRAIGHT)
    plan.put(a)
    plan.put(b)
    assert plan.loose_ends(a) == [4] and plan.loose_ends(b) == [0]
    plan.put(tp.Tile(7, 4, tp.STRAIGHT, rotation=1))  # a diagonal leaving b's right end doesn't meet it
    assert plan.loose_ends(b) == [0]
    plan.put(tp.Tile(7, 5, tp.CURVE, rotation=4))  # in from the left, out to the top-right corner
    assert plan.loose_ends(b) == []


def test_accessory_commands():
    point = tp.Tile(0, 0, tp.POINT_LEFT, address=12)
    assert point.command(thrown=False) == bytes((0xAD, 0, 12, 3, 0))
    assert point.command(thrown=True) == bytes((0xAD, 0, 12, 4, 0))
    point.inverted = True
    assert point.command(thrown=True)[3] == 3
    assert tp.accessory_command(2044, True)[1:3] == bytes((7, 252))


def test_sender_sets_points():
    station = SimulatedCommandStation()
    sender = ThrottleSender(nce.NceConnection(station))
    sender.accessory(12, tp.accessory_command(12, closed=True), "Point 12")
    sender.accessory(12, tp.accessory_command(12, closed=False), "Point 12")
    sender.stop()
    assert station.accessories[12] == 4


def test_save_load(tmp_path):
    plan = tp.Plan(name="Test")
    plan.put(tp.Tile(1, 2, tp.POINT_RIGHT, rotation=3, address=7, name="Yard", thrown=True))
    plan.put(tp.Tile(2, 2, tp.LABEL, text="Fochabers"))
    path = tmp_path / "plan.json"
    tp.save(plan, path)
    tp.save(plan, path)  # second save makes the backup
    again = tp.load(path)
    assert again.get(1, 2) == plan.get(1, 2) and again.get(2, 2).text == "Fochabers"
    path.write_text("broken")
    assert tp.load(path).name == "Test"


def test_duplicates_and_drag_lines():
    plan = tp.Plan()
    plan.put(tp.Tile(0, 0, tp.POINT_LEFT, address=3))
    plan.put(tp.Tile(4, 0, tp.POINT_RIGHT, address=3))
    assert list(plan.duplicate_addresses()) == [3]
    assert list(tp.tiles_between((0, 0), (4, 1))) == [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
    assert list(tp.tiles_between((0, 0), (3, 3))) == [(0, 0), (1, 1), (2, 2), (3, 3)]
    assert list(tp.tiles_between((2, 5), (2, 2))) == [(2, 5), (2, 4), (2, 3), (2, 2)]
    assert tp.direction_of(1, -1) == 1


def test_sample_plan_has_no_gaps():
    from plan_sample import sample_plan

    plan = sample_plan()
    gaps = {tile.place: plan.loose_ends(tile) for tile in plan.tiles.values()
            if plan.loose_ends(tile) and tile.kind != tp.BUFFER}
    assert gaps == {}
