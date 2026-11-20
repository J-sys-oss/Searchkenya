"""Run the full suite and write measured results to tests/results.json (used to build Chapter 3).
Usage:  python -m tests.run_report"""
import contextlib, io, json, sys, time, unittest, os
from tests.catalog import CATALOG

class Rec(unittest.TextTestResult):
    def startTest(self, t):
        self._t0 = time.perf_counter(); super().startTest(t)
    def _rec(self, t, outcome):
        self.log = getattr(self, "log", {})
        self.log[t.id().replace("tests.", "")] = (outcome, time.perf_counter() - self._t0)
    def addSuccess(self, t): super().addSuccess(t); self._rec(t, "Pass")
    def addFailure(self, t, e): super().addFailure(t, e); self._rec(t, "Fail")
    def addError(self, t, e): super().addError(t, e); self._rec(t, "Error")

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    out = io.StringIO()
    t0 = time.perf_counter()
    with contextlib.redirect_stdout(out):
        res = unittest.TextTestRunner(stream=io.StringIO(), resultclass=Rec, verbosity=0).run(suite)
    total = time.perf_counter() - t0
    known = {c[0] for c in CATALOG}
    missing = [k for k in res.log if k not in known]
    stale = [k for k in known if k not in res.log]
    assert not missing and not stale, f"catalog mismatch: untested-in-catalog={missing} not-run={stale}"
    rows = [{"no": i, "id": f"TC{i:02d}", "key": k, "category": cat, "behaviour": b, "expected": e,
             "result": res.log[k][0], "seconds": round(res.log[k][1], 2)} for i, (k, cat, b, e) in enumerate(CATALOG, 1)]
    metrics = [l.strip() for l in out.getvalue().splitlines() if l.strip().startswith("[")]
    json.dump({"total_seconds": round(total, 1), "tests": rows, "metrics": metrics,
               "run": res.testsRun, "failures": len(res.failures), "errors": len(res.errors)},
              open("tests/results.json", "w"), indent=1)
    print(f"{res.testsRun} tests, {len(res.failures)} failures, {len(res.errors)} errors, {total:.1f}s")
    print("\n".join(metrics))
