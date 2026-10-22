import json

import pytest

from simple_train.core.roster import Loco, Roster, export_loco, import_loco


def test_take_cvs_works_out_the_address():
    loco = Loco(name="Class 08")
    loco.take_cvs({1: 3, 7: 51, 8: 65, 17: 192, 18: 144, 29: 38})
    assert (loco.address, loco.long_address, loco.address_text) == (144, True, "0144")
    assert loco.manufacturer == "Gaugemaster" and loco.decoder_version == 51
    loco.take_cvs({29: 6})
    assert (loco.address, loco.long_address) == (3, False)


def test_restore_order():
    loco = Loco(name="x", cvs={1: 3, 3: 9, 7: 51, 8: 65, 17: 192, 18: 144, 29: 38, 2: 4})
    assert loco.restore_writes() == [(2, 4), (3, 9), (17, 192), (18, 144), (1, 3), (29, 38)]


def test_save_and_load_with_backup(tmp_path):
    path = tmp_path / "roster.json"
    roster = Roster(path)
    roster.add(Loco(name="Duck", address=144, long_address=True, cvs={3: 20}))
    roster.add(Loco(name="Ant", address=5))
    again = Roster(path)
    assert [loco.name for loco in again.sorted()] == ["Ant", "Duck"]
    assert again.find_by_address(144, True).cvs == {3: 20}
    assert again.find_by_address(144, False) is None
    path.write_text("not json")  # a damaged roster falls back to the backup
    assert len(Roster(path).locos) == 1


def test_export_import(tmp_path):
    loco = Loco(name="Duck", cvs={3: 20})
    export_loco(loco, tmp_path / "duck.train.json")
    copy = import_loco(tmp_path / "duck.train.json")
    assert copy.name == "Duck" and copy.cvs == {3: 20} and copy.id != loco.id
    (tmp_path / "other.json").write_text(json.dumps({"hello": 1}))
    with pytest.raises(ValueError):
        import_loco(tmp_path / "other.json")


def test_bad_values_dropped():
    loco = Loco.from_json({"name": "x", "address": "lots", "cvs": {"3": 300, "4": 5, "x": 1}})
    assert loco.address == 3 and loco.cvs == {4: 5}
