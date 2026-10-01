import asyncio
import os
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server import iracing_bridge as bridge
from server.race_director import select_rival
from server.setup_engineer import SetupEngineer
from server.strategy_engine import StrategyInputs, calculate_strategy
import updater


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.assets = []
        self.build = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if 'id' in fields:
            self.ids.append(fields['id'])
        if tag == 'meta' and fields.get('name') == 'zre-build':
            self.build = fields.get('content')
        if tag in ('script', 'link'):
            value = fields.get('src') or fields.get('href', '')
            if value.startswith('/static/'):
                self.assets.append(value)


class AssetAndUpdaterTests(unittest.TestCase):
    def test_active_setup_stint_is_recovered_before_session_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            source = bridge.DashboardSource(force_demo=True)
            source.setup_engineer = SetupEngineer(folder)
            source.stint_active = True
            source.last_fuel = 45.0
            source.last_session_time = 200.0
            source.setup_engineer.start_stint(
                {'car':'McLaren','track':'Spa','layout':'GP','session':'Practice','driver':'Santiago'},
                {'source':'SDK','parameters':{'Aero':{'Wing':8.5}},'flatParameters':{'Aero.Wing':8.5},'metadata':{'setupName':'test'},'fingerprint':'test'},
                {},
                fuel_start=55.0,
                session_time=100.0,
            )
            saved = source.finalize_setup_stint_before_reset('test')
            self.assertIsNotNone(saved)
            self.assertIsNone(source.setup_engineer.current)
            self.assertIsNotNone(source.setup_engineer.last_report_path)
            self.assertTrue(source.setup_engineer.last_report_path.exists())
            self.assertEqual(source.setup_engineer.last_report_path.name, 'ZRE_SETUP_REPORT_mclaren_spa_gp_Stint01.md')

    def test_html_contract(self):
        page = PageParser()
        page.feed((bridge.WEB_ROOT / 'index.html').read_text(encoding='utf-8'))
        self.assertEqual(len(page.ids), len(set(page.ids)))
        ref_name=os.environ.get("GITHUB_REF_NAME","")
        head_ref=os.environ.get("GITHUB_HEAD_REF","")
        if ref_name.startswith("work/") or head_ref.startswith("work/"):
            self.assertGreaterEqual(updater._version_tuple(page.build),updater._version_tuple(bridge.APP_VERSION))
        else:
            self.assertEqual(page.build, bridge.APP_VERSION)
        self.assertTrue(page.assets)
        for asset in page.assets:
            self.assertTrue((bridge.WEB_ROOT / asset.split('/static/', 1)[1].split('?')[0]).is_file())
            self.assertIn(f'v={page.build}', asset)

    def test_update_from_broken_install_preserves_data_and_commits_last(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'download'
            target = root / 'installed'
            source.mkdir()
            target.mkdir()
            (source / 'web').mkdir()
            (source / 'web' / 'index.html').write_text('new', encoding='utf-8')
            (source / 'version.json').write_text('{"version":"2.4.3"}', encoding='utf-8')
            for name in ('data', '.venv', '.git'):
                (target / name).mkdir()
                (target / name / 'retain').write_text('yes', encoding='utf-8')
            for name in ('dashboard.log', 'session_replay.jsonl'):
                (target / name).write_text('retain', encoding='utf-8')
            (target / 'version.json').write_text('{"version":"2.3.3"}', encoding='utf-8')
            original = updater.ROOT
            updater.ROOT = target
            try:
                with patch.object(updater.shutil, 'copy2', side_effect=OSError('interrupted')):
                    with self.assertRaises(OSError):
                        updater._copy_program_tree(source)
                self.assertEqual((target / 'version.json').read_text(), '{"version":"2.3.3"}')
                updater._copy_program_tree(source)
            finally:
                updater.ROOT = original
            self.assertEqual((target / 'web' / 'index.html').read_text(), 'new')
            self.assertEqual((target / 'version.json').read_text(), '{"version":"2.4.3"}')
            for name in ('data', '.venv', '.git'):
                self.assertEqual((target / name / 'retain').read_text(), 'yes')
            for name in ('dashboard.log', 'session_replay.jsonl'):
                self.assertEqual((target / name).read_text(), 'retain')


class StrategyTests(unittest.TestCase):
    def scenario(self, **changes):
        params = dict(remaining_time_seconds=36000, average_lap_seconds=80,
                      pit_loss_seconds=30, base_stint_laps=37, extended_stint_laps=38)
        params.update(changes)
        return calculate_strategy(StrategyInputs(**params))

    def test_time_based_scenarios(self):
        result = self.scenario()
        self.assertEqual((result.base.projected_laps, result.base.stops_remaining), (445, 12))
        self.assertEqual((result.extended.projected_laps, result.extended.stops_remaining), (445, 11))
        self.assertTrue(result.extension.avoidable)
        self.assertEqual(result.extension.extra_laps_needed, 1)

    def test_recalculate_pace_pit_fuel_and_stint(self):
        initial = self.scenario(remaining_time_seconds=18000, current_lap=210)
        slower = self.scenario(remaining_time_seconds=18000, current_lap=210, average_lap_seconds=90)
        longer_stop = self.scenario(remaining_time_seconds=18000, current_lap=210, pit_loss_seconds=120)
        self.assertLess(slower.base.projected_laps, initial.base.projected_laps)
        self.assertLessEqual(longer_stop.base.projected_laps, initial.base.projected_laps)
        low_fuel = self.scenario(remaining_time_seconds=18000, current_lap=210,
                                 current_fuel_liters=12, consumption_liters_per_lap=3)
        self.assertEqual(low_fuel.base.current_autonomy_laps, 4)
        self.assertEqual(low_fuel.base.stop_estimates[0].lap, 214)
        after_stop = self.scenario(remaining_time_seconds=17000, current_lap=214,
                                   stops_completed=1, current_fuel_liters=111,
                                   consumption_liters_per_lap=3)
        self.assertEqual(after_stop.base.current_autonomy_laps, 37)
        self.assertEqual(after_stop.base.stop_estimates[0].lap, 251)
        smaller_tank = self.scenario(remaining_time_seconds=18000,
                                     current_fuel_liters=90, tank_capacity_liters=90,
                                     consumption_liters_per_lap=3)
        self.assertEqual(smaller_tank.extended.stint_laps, 30)
        self.assertFalse(smaller_tank.extension.extra_laps_available)

    def test_extra_lap_reduces_remaining_extension(self):
        before = self.scenario(pit_loss_seconds=0, remaining_time_seconds=36000,
                               current_lap=0, stops_completed=0)
        after = self.scenario(pit_loss_seconds=0, remaining_time_seconds=36000-38*80,
                              current_lap=38, stops_completed=1,
                              target_total_stops=before.target_total_stops)
        self.assertLess(after.extension.extra_laps_needed, before.extension.extra_laps_needed)

    def test_rival_position_before_physical_gap(self):
        rows = [dict(idx=1, pos=8, isPlayer=True, gapSeconds=0),
                dict(idx=2, pos=9, gapSeconds=30),
                dict(idx=3, pos=18, gapSeconds=1)]
        self.assertEqual(select_rival(rows, 1).idx, 2)
        self.assertEqual(select_rival(rows, 1, 3).idx, 3)


class SocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application(middlewares=[bridge.no_cache_middleware])
        app['source'] = bridge.DashboardSource(force_demo=True)
        app.router.add_get('/', bridge.index)
        app.router.add_get('/version', bridge.version_status)
        app.router.add_get('/ws', bridge.websocket)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_open_close_reload_reconnect(self):
        for _ in range(5):
            async with self.client.ws_connect('/ws') as ws:
                packet = await asyncio.wait_for(ws.receive_json(), 3)
                self.assertTrue(packet['demo'])
                self.assertTrue(packet['connected'])
                self.assertIn('raceDirector', packet)
                self.assertIn('enduranceStrategy', packet)
            response = await self.client.get('/')
            self.assertEqual(response.status, 200)
            self.assertIn('no-store', response.headers['Cache-Control'])
            await response.read()
        async with self.client.ws_connect('/ws') as ws:
            await ws.receive_json()
            ws._response.close()  # Simulate a dropped transport.
        async with self.client.ws_connect('/ws') as ws:
            self.assertTrue((await ws.receive_json())['connected'])

    async def test_hold_connection(self):
        async with self.client.ws_connect('/ws') as ws:
            for _ in range(40):
                packet = await asyncio.wait_for(ws.receive_json(), 3)
                self.assertEqual(packet['appVersion'], bridge.APP_VERSION)

    async def test_non_object_json_does_not_close_socket(self):
        async with self.client.ws_connect('/ws') as ws:
            await ws.receive_json()
            await ws.send_json([{'type': 'settings'}])
            await ws.send_json(None)
            await ws.send_json({'type': 'settings', 'key': 'role', 'value': 'driver'})
            self.assertTrue((await asyncio.wait_for(ws.receive_json(), 3))['connected'])
            self.assertTrue((await asyncio.wait_for(ws.receive_json(), 3))['connected'])
