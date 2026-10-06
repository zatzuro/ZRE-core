import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import updater

class TestBuildUpdater(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.root_patch=patch.object(updater,'ROOT',self.root);self.root_patch.start()
        (self.root/'version.json').write_text(json.dumps({'version':'2.6.5.1'}))
    def tearDown(self):self.root_patch.stop();self.temp.cleanup()
    def test_restart_stays_on_newer_test_build_without_persisting_channel(self):
        with patch.object(updater,'_fetch_json',return_value={'version':'2.6.5','archive_ref':'release-2.6.5'}),patch.object(updater,'_download') as download:
            self.assertFalse(updater.update_if_available());download.assert_not_called()
        self.assertEqual(updater._read_local_version(),'2.6.5.1')
    def test_future_stable_upgrade_is_not_blocked(self):
        with patch.object(updater,'_fetch_json',return_value={'version':'2.6.6'}),patch.object(updater,'_download',side_effect=RuntimeError('expected download')) as download:
            updater.update_if_available();download.assert_called_once()
    def test_restore_stable_explicitly_allows_lower_version(self):
        with patch.object(updater,'_fetch_json',return_value={'version':'2.6.5'}),patch.object(updater,'_download',side_effect=RuntimeError('expected download')) as download:
            updater.update_if_available(restore_stable=True);download.assert_called_once()
    def test_invalid_test_ref_does_not_download(self):
        with patch.object(updater,'_fetch_json') as fetch:
            self.assertFalse(updater.update_if_available(test_ref='main'));fetch.assert_not_called()
    def test_test_manifest_and_archive_are_pinned_to_same_commit(self):
        sha='a'*40;manifest={'version':'2.6.5.1','channel':'development','archive_ref':'develop/2.6.5.1'}
        with patch.object(updater,'_fetch_json',side_effect=[{'sha':sha},manifest]) as fetch,patch.object(updater,'_download',side_effect=RuntimeError('expected download')) as download:
            updater.update_if_available(test_ref='develop/2.6.5.1')
            self.assertIn(sha,fetch.call_args_list[1].args[0]);self.assertIn('/zip/'+sha,download.call_args.args[0])
    def test_manifest_channel_mismatch_rejected(self):
        with patch.object(updater,'_fetch_json',side_effect=[{'sha':'a'*40},{'version':'2.6.5.1','channel':'stable'}]),patch.object(updater,'_download') as download:
            self.assertFalse(updater.update_if_available(test_ref='develop/2.6.5.1'));download.assert_not_called()
    def test_copy_preserves_environment_data_and_local_configuration(self):
        package=self.root/'package';package.mkdir();(package/'version.json').write_text('{"version":"2.6.5.1"}')
        for folder in ('.venv','data','session_logs','reports'):
            old=self.root/folder;old.mkdir();(old/'marker').write_text('user data')
            new=package/folder;new.mkdir();(new/'marker').write_text('must not overwrite')
        (self.root/'local-settings.json').write_text('user settings')
        updater._copy_program_tree(package)
        for folder in ('.venv','data','session_logs','reports'):self.assertEqual((self.root/folder/'marker').read_text(),'user data')
        self.assertEqual((self.root/'local-settings.json').read_text(),'user settings')
    def test_copy_failure_restores_program_and_version(self):
        package=self.root/'package';package.mkdir();(package/'a.py').write_text('new');(package/'version.json').write_text('{"version":"2.6.6"}')
        (self.root/'a.py').write_text('old');original=updater.shutil.copy2
        def copy(src,dst,*args,**kwargs):
            if Path(src)==package/'version.json':raise OSError('disk failure')
            return original(src,dst,*args,**kwargs)
        with patch.object(updater.shutil,'copy2',side_effect=copy):
            with self.assertRaises(OSError):updater._copy_program_tree(package)
        self.assertEqual((self.root/'a.py').read_text(),'old');self.assertEqual(updater._read_local_version(),'2.6.5.1')

if __name__=='__main__':unittest.main()
