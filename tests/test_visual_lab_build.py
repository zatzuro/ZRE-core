"""Visual Lab static build contract: cannot call productive runtime or publish private data."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from build_visual_lab import build


class VisualLabBuildTests(unittest.TestCase):
    def test_build_isolated_and_source_unchanged(self):
        original=(ROOT/"web"/"app.js").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"lab"
            build(out,"develop/visual-lab-web","TESTSHA000")
            self.assertEqual((ROOT/"web"/"app.js").read_bytes(),original)
            self.assertTrue((out/"index.html").exists())
            self.assertTrue((out/"dashboard.html").exists())
            index=(out/"dashboard.html").read_text(encoding="utf-8")
            adapter=(out/"static"/"app.js").read_text(encoding="utf-8")
            self.assertNotIn('"/static/',index)
            self.assertNotIn("session_archive.js",index)
            self.assertNotIn("new WebSocket",adapter)
            self.assertNotIn("fetch('/version",adapter)
            self.assertIn("window.ZREVisualLab.start(render)",adapter)
            self.assertIn("ZRE VISUAL LAB · DATOS SIMULADOS",index)
            self.assertIn("visual_lab.js",index)
            manifest=json.loads((out/"lab_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["sha"],"TESTSHA000")
            for asset in ("practice.js","practice.css","quali.js","quali.css","race_v2.js","race_v2.css","black_theme.css"):
                self.assertEqual((out/"static"/asset).read_bytes(),(ROOT/"web"/asset).read_bytes())
            for path in out.rglob("*.js"):
                subprocess.run(["node","--check",str(path)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            # Only public frontend asset types and the four shell/meta files.
            self.assertFalse(list(out.rglob("*.sqlite")))
            self.assertFalse(list(out.rglob("*.db")))


if __name__=="__main__":
    unittest.main()
