import base64
import contextlib
import io
import json
import unittest

from tests.support import problem,workspace
from ctf_engine.cli import main


class CLITest(unittest.TestCase):
    def setUp(self):
        self.temp,self.root,self.state,self.h=workspace();self.addCleanup(self.temp.cleanup)

    def call(self,*args):
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            return main(["--root",str(self.root),*args])

    def test_operator_commands(self):
        self.assertEqual(self.call("init-run","--mock"),0)
        self.assertEqual(self.call("init-run","--mock"),2)
        for cid in ("c001","c002","c003"):problem(self.root,self.state,self.h,cid)
        self.assertEqual(self.call("pause","c001"),0)
        self.assertEqual(self.call("resume","c001"),0)
        self.assertEqual(self.call("freeze","c001"),0)
        self.assertEqual(self.call("requeue","c001","--profile","general-sol"),0)
        self.assertEqual(self.call("stop","c001","--hard"),0)
        self.assertEqual(self.call("resume","c001"),2)
        self.assertEqual(self.call("solved","c002","--by","team"),0)
        self.assertEqual(self.call("drop","c003"),0)
        self.assertEqual(self.call("status","--json"),0)
        self.assertEqual(self.call("quota","--remaining","19"),0)
        self.assertEqual(self.call("quota","--remaining","101"),2)
        self.assertEqual(self.call("snapshot"),0)
        self.assertEqual(self.call("export","c002"),0)
        self.assertEqual(self.call("recover"),0)
        self.assertTrue(list((self.root/"reports/run-snapshots").glob("*.db")))
        self.assertEqual(self.call("shutdown","--graceful"),0)

    def test_import_batch_and_extension(self):
        folder=self.root/"batch/test";files=folder/"files";files.mkdir(parents=True)
        (folder/"challenge.toml").write_text('id="c004"\ntitle="Batch fixture"\ncategory="crypto"\n')
        (files/"payload.txt").write_bytes(base64.b64encode(b"TEST{batch}"))
        self.assertEqual(self.call("import-batch",str(folder.parent)),0)
        self.assertEqual(self.call("import-batch",str(folder.parent)),2)
        self.assertEqual(self.call("extend","c004","--reason","no primitive"),2)
        with self.state.tx() as c:c.execute("UPDATE challenges SET primitive=1 WHERE id='c004'")
        self.assertEqual(self.call("extend","c004","--reason","concrete primitive"),0)
        self.assertEqual(self.call("extend","c004","--reason","again"),2)
        self.assertEqual(self.call("import",str(files),"--id","c005","--title","Single import"),0)
