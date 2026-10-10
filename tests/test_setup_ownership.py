"""Critical ownership gates for local, team, rival, and ambiguous iRacing setups."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from server.setup_ownership import resolve_setup_owner, same_confirmed_owner
from server.setup_engineer import SetupEngineer
from server.setup_snapshot import snapshot_from_sdk


def context(**kwargs):
    values=dict(car_idx=8,local_user_id=10,current_user_id=10,
                team_id=99,local_driving=True,auto_mode="driver")
    values.update(kwargs)
    return SimpleNamespace(**values)


def roster(selected_id=10,selected_team=99,local_spectator=False):
    cars=[{"CarIdx":8,"UserID":selected_id,"TeamID":selected_team,
           "CarNumber":"18","UserName":"Driver"}]
    if local_spectator:
        cars.append({"CarIdx":-1,"UserID":10,"TeamID":99,"IsSpectator":True})
    return {"DriverCarIdx":8,"Drivers":cars}


class OwnershipTests(unittest.TestCase):
    def test_own_car_verified(self):
        owner=resolve_setup_owner(context(),roster(),8).payload()
        self.assertTrue(owner["authorized"])
        self.assertEqual(owner["scope"],"own")

    def test_same_verified_local_driver_in_garage_retains_ownership(self):
        owner=resolve_setup_owner(context(local_driving=False),roster(),8)
        self.assertTrue(owner.authorized)
        self.assertEqual(owner.scope,"own")

    def test_forced_driver_does_not_authorize_rival(self):
        owner=resolve_setup_owner(context(local_driving=False),roster(selected_id=40,selected_team=44),8)
        self.assertFalse(owner.authorized)

    def test_local_team_spectator_is_allowed_for_confirmed_car(self):
        owner=resolve_setup_owner(context(local_driving=False,current_user_id=20,auto_mode="spotter"),
                                  roster(selected_id=20,local_spectator=True),8)
        self.assertTrue(owner.authorized)
        self.assertEqual(owner.scope,"team")

    def test_car_selector_without_independent_team_membership_denied(self):
        owner=resolve_setup_owner(context(local_driving=False,current_user_id=20,auto_mode="spotter"),
                                  roster(selected_id=20),8)
        self.assertFalse(owner.authorized)

    def test_ambiguous_or_missing_owner_denied(self):
        self.assertFalse(resolve_setup_owner(context(local_user_id=None),roster(),8).authorized)
        self.assertFalse(resolve_setup_owner(context(car_idx=9),roster(),8).authorized)
        self.assertFalse(resolve_setup_owner(context(local_driving=False,current_user_id=99),
                                             roster(selected_id=98,selected_team=3),8).authorized)

    def test_teammate_relay_preserves_vehicle_identity(self):
        own=resolve_setup_owner(context(),roster(),8).payload()
        teammate=resolve_setup_owner(context(local_driving=False,current_user_id=20,auto_mode="spotter"),
                                     roster(selected_id=20,local_spectator=True),8).payload()
        self.assertTrue(same_confirmed_owner(own,teammate))
        rival={**teammate,"car_idx":9}
        self.assertFalse(same_confirmed_owner(own,rival))

    def test_verified_handoff_persists_outgoing_driver_without_rebinding_setup(self):
        with tempfile.TemporaryDirectory() as root:
            engineer=SetupEngineer(root)
            own=resolve_setup_owner(context(),roster(),8).payload()
            incoming=resolve_setup_owner(context(local_driving=False,current_user_id=20,auto_mode="spotter"),
                                         roster(selected_id=20,local_spectator=True),8).payload()
            engineer.set_owner(own)
            engineer.start_stint({"car":"McLaren","track":"Spa","layout":"GP","driver":"Local"},
                                 snapshot_from_sdk({"Wing":8}))
            engineer.set_owner(incoming)
            saved=engineer.finish_stint({"validLaps":2,"bestLap":90.2})
            self.assertIsNotNone(saved)
            self.assertEqual(saved["session"]["driver"],"Local")
            self.assertEqual(saved["session"]["setupOwner"]["scope"],"own")
            self.assertEqual(saved["setup"]["ownership"]["driver_user_id"],"10")
            self.assertTrue(engineer.last_report_path.exists())

    def test_no_setup_writes_on_unknown_or_rival(self):
        with tempfile.TemporaryDirectory() as root:
            engineer=SetupEngineer(root)
            self.assertIsNone(engineer.import_html_setup("<table><tr><td>Wing</td><td>8</td></tr></table>","a.html"))
            self.assertIsNone(engineer.start_stint({"car":"McLaren"},snapshot_from_sdk({"Wing":8})))
            self.assertIsNone(engineer.export_report({"session":{"car":"McLaren"},"stintNumber":1}))
            self.assertFalse((Path(root)/"reports").exists())

    def test_switch_to_rival_revokes_write(self):
        with tempfile.TemporaryDirectory() as root:
            engineer=SetupEngineer(root)
            owner=resolve_setup_owner(context(),roster(),8).payload()
            engineer.set_owner(owner,{"car":"GT3","track":"Spa","layout":"GP"})
            engineer.start_stint({"car":"GT3","track":"Spa","layout":"GP"},snapshot_from_sdk({"Wing":8}))
            engineer.set_owner({"authorized":False,"reason":"rival"})
            self.assertIsNone(engineer.finish_stint({"validLaps":3}))
            self.assertEqual(list((Path(root)/"data").rglob("*.json")),[])

    def test_valid_team_html_import_persists_with_source_and_owner(self):
        with tempfile.TemporaryDirectory() as root:
            engineer=SetupEngineer(root)
            owner=resolve_setup_owner(context(local_driving=False,current_user_id=20,auto_mode="spotter"),
                                      roster(selected_id=20,local_spectator=True),8).payload()
            engineer.set_owner(owner,{"car":"McLaren","track":"Spa","layout":"GP"})
            imported=engineer.import_html_setup("<h2>Aero</h2><table><tr><td>Wing</td><td>8</td></tr></table>","team.html")
            self.assertIsNotNone(imported)
            self.assertEqual(imported["ownership"]["scope"],"team")
            self.assertEqual(imported["source"],"IRACING_HTML")
            self.assertEqual(len(list((Path(root)/"data").rglob("setup-*.json"))),1)

    def test_no_unverified_historical_auto_export(self):
        with tempfile.TemporaryDirectory() as root:
            engineer=SetupEngineer(root)
            engineer.store.save_stint({"session":{"car":"Legacy","track":"Track","layout":"GP"}})
            next_engineer=SetupEngineer(root)
            self.assertIsNotNone(next_engineer.last_saved)
            self.assertIsNone(next_engineer.last_report_path)


if __name__=="__main__":
    unittest.main()
