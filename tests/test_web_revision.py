"""Mutation preconditions come from displayed controls even when background state has advanced."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

HTML = (Path(__file__).resolve().parent.parent / "web/index.html").read_text()


class DisplayedRevision(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_pause_uses_the_displayed_revision_when_global_state_is_newer(self):
        function = re.search(r"async function setPaused\(.*?^}", HTML, re.S | re.M).group(0)
        script = """
let payload, pauseArmed=true, pauseMsg='', base='/', state={rooms:[{name:'demo',revision:'latest-background-state'}]};
function draw(){}; function refreshMsg(){}; async function load(){}; function setTimeout(){};
async function fetch(url, options){payload=JSON.parse(options.body);return {json:async()=>({ok:false,conflict:true,error:'changed'})};}
""" + function + "\nsetPaused('demo',true,'displayed-control-revision').then(()=>console.log(JSON.stringify({payload,pauseMsg})));"
        output = json.loads(subprocess.run([shutil.which("node"), "-e", script], text=True, capture_output=True, check=True).stdout)
        self.assertEqual(output["payload"]["revision"], "displayed-control-revision")
        self.assertTrue(output["pauseMsg"].startswith("Not saved:"))
        self.assertIn("setPaused(r.name, false, r.revision)", HTML)
        self.assertIn("setPaused(r.name, true, r.revision)", HTML)


if __name__ == "__main__":
    unittest.main()
