#!/usr/bin/env python3
"""Fixture test: build a messy folder, run probe -> survey -> execute -> verify, assert the safety invariants."""
import json, os, shutil, subprocess, sys, tempfile

S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


def run(*cmd, ok=True):
    r = subprocess.run([sys.executable, *cmd], capture_output=True, text=True)
    if ok and r.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return r


def w(p, data=b"x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def main():
    tmp = tempfile.mkdtemp(prefix="declutter-test-")
    T = os.path.join(tmp, "target"); W = os.path.join(T, "_declutter")
    w(f"{T}/report.pdf", b"pdf-A" * 100)
    w(f"{T}/report copy.pdf", b"pdf-A" * 100)            # exact duplicate
    w(f"{T}/Screenshot 2025-01-01 at 1.png", b"png1")
    w(f"{T}/notes.txt", b"hello")
    w(f"{T}/.env", b"TOKEN=abc")                          # secret by name
    w(f"{T}/proj/main.py", b"print(1)")
    w(f"{T}/proj/venv/lib/site.py", b"site" * 1000)       # env bloat inside a project
    w(f"{T}/proj/id_rsa", b"-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----\n")  # secret by content
    w(f"{T}/Archive/old.txt", b"old")
    w(f"{T}/Archive/report.pdf", b"different")            # collision target for a move
    os.symlink("/nonexistent", f"{T}/dead-link")
    os.makedirs(f"{T}/Photos", exist_ok=True)

    run(f"{S}/probe.py", T, "--work", W)
    run(f"{S}/survey.py", T, "--work", W)
    summary = json.load(open(f"{W}/summary.json"))
    assert summary["duplicate_groups"] == 1, summary
    assert summary["secret_candidates"] >= 2, summary
    secrets = open(f"{W}/secrets.tsv").read()
    assert ".env" in secrets and "proj/id_rsa" in secrets, secrets
    assert "proj/venv" in open(f"{W}/bloat.tsv").read()

    with open(f"{W}/mapping.tsv", "w") as f:
        f.write("action\tsource\tdestination\treason\n")
        f.write("move\treport.pdf\tArchive\tcollides with existing Archive/report.pdf\n")
        f.write("delete\treport copy.pdf\t\texact dup of report.pdf\n")
        f.write("move\tScreenshot 2025-01-01 at 1.png\tScreenshots/2025\t\n")
        f.write("keep\tnotes.txt\t\tactive\n")
        f.write("vault\t.env\t\tsecret\n")
        f.write("vault\tproj/id_rsa\t\tprivate key\n")
        f.write("delete\tproj/venv\t\tdependency dir\n")
        f.write("move\tproj\tCode\tproject\n")
        f.write("delete\tdead-link\t\tdead symlink\n")
        f.write("move\tPhotos\tMedia\tempty dir\n")

    # dry run must change nothing
    before = sorted(os.listdir(T))
    run(f"{S}/execute.py", "--work", W)
    assert sorted(os.listdir(T)) == before, "dry run changed the tree"

    # bad rows are rejected before anything runs
    bad = f"{W}/bad.tsv"
    open(bad, "w").write("action\tsource\tdestination\treason\nmove\t../escape\tX\t\n")
    r = run(f"{S}/execute.py", "--work", W, "--mapping", bad, "--apply", ok=False)
    assert r.returncode == 2 and sorted(os.listdir(T)) == before, "path escape was not rejected"
    open(bad, "w").write("action\tsource\tdestination\treason\nnuke\tnotes.txt\t\t\n")
    r = run(f"{S}/execute.py", "--work", W, "--mapping", bad, "--apply", ok=False)
    assert r.returncode == 2, "unknown action was not rejected"

    run(f"{S}/execute.py", "--work", W, "--apply")
    assert os.path.exists(f"{T}/Archive/report (2).pdf"), "collision suffix not applied"
    assert os.path.exists(f"{T}/Archive/report.pdf") and open(f"{T}/Archive/report.pdf", "rb").read() == b"different", "overwrote!"
    assert os.path.exists(f"{T}/_Review-Before-Trash/report copy.pdf"), "delete did not stage"
    assert os.path.exists(f"{T}/_Review-Before-Trash/proj/venv/lib/site.py"), "nested delete lost relative path"
    assert os.path.exists(f"{T}/Code/proj/main.py") and not os.path.exists(f"{T}/Code/proj/venv"), "child not routed before parent"
    assert os.path.exists(f"{T}/_Vault/.env") and os.path.exists(f"{T}/_Vault/proj__id_rsa"), "vault naming"
    assert os.path.exists(f"{T}/Screenshots/2025/Screenshot 2025-01-01 at 1.png")
    assert os.path.exists(f"{T}/notes.txt")
    assert os.path.islink(f"{T}/_Review-Before-Trash/dead-link"), "symlink not moved as a link"
    assert os.path.isdir(f"{T}/Media/Photos")
    assert not os.path.exists(f"{T}/proj") and not os.path.exists(f"{T}/report.pdf")

    r = run(f"{S}/verify.py", "--work", W)
    v = json.load(open(f"{W}/verify.json"))
    assert v["missing"] == 0, v
    # simulate a loss and confirm verify catches it
    os.remove(f"{T}/_Review-Before-Trash/report copy.pdf")
    r = run(f"{S}/verify.py", "--work", W, ok=False)
    assert r.returncode == 1 and json.load(open(f"{W}/verify.json"))["missing"] == 1, "verify missed a loss"

    src = open(f"{S}/execute.py").read()
    for forbidden in ("unlink(", "rmdir(", "rmtree(", "os.remove(", "shutil.move("):
        assert forbidden not in src, f"execute.py contains {forbidden}"
    shutil.rmtree(tmp)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
