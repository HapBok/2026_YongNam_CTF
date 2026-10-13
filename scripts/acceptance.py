#!/usr/bin/env python3
"""Run required local suites, stress and rehearsal and persist honest evidence."""
import argparse
import io
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
from ctf_engine.common import atomic_json,now
from ctf_engine.fingerprint import calculate
import stress
import rehearse


def main():
    p=argparse.ArgumentParser();p.add_argument("--repeat",type=int,default=3);a=p.parse_args()
    rounds=[]
    for i in range(a.repeat):
        suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"),top_level_dir=str(ROOT))
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        rounds.append({"round":i+1,"tests":result.testsRun,"passed":result.wasSuccessful(),"failures":[str(t) for t,_ in result.failures+result.errors]})
        if not result.wasSuccessful():break
    load=stress.execute(1000)
    atomic_json(ROOT/"reports/stress.json",load)
    rehearsal=rehearse.execute()
    report={"timestamp":now(),"build_fingerprint":calculate(ROOT),"rounds":rounds,"stress":load,"rehearsal":rehearsal,"live_model_tests":False,"passed":len(rounds)==a.repeat and all(r["passed"] for r in rounds) and load["passed"] and rehearsal["passed"]}
    atomic_json(ROOT/"reports/acceptance.json",report)
    print("LOCAL ACCEPTANCE:","PASS" if report["passed"] else "FAIL")
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
