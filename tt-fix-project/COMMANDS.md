# TT FIX Project — Command Reference

Everything run so far, organized by purpose. One-time setup vs. things
you'll run every session are marked separately.

---

## 1. One-time machine setup

```powershell
# Set PowerShell to allow venv activation scripts (one-time per Windows account)
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

- **Python 3.11** installed from python.org (alongside your existing 3.13) — needed originally for `quickfix` wheel compatibility, kept since it's what the venv is built on now.
- **Git for Windows** installed from git-scm.com.
- (No longer needed: Visual Studio Build Tools "Desktop development with C++" — that was for compiling `quickfix`, which we abandoned in favor of `simplefix`. Harmless to leave installed.)

```powershell
# Confirm both Python versions are visible
py -0
```

---

## 2. Repo setup (one-time, already done)

```powershell
cd "C:\Fincoursa\TT FIX\tt-fix-project"

# Create venv on Python 3.11 specifically
py -3.11 -m venv venv
venv\Scripts\activate
python --version   # should print Python 3.11.x

# Upgrade pip tooling
python -m pip install --upgrade pip setuptools wheel

# Install the actual dependencies (final working set)
pip install -r requirements.txt
# equivalent to: pip install simplefix streamlit pandas python-dotenv
```

```powershell
# Git identity (if not already set globally on this machine)
git config --global user.name "Your Name"
git config --global user.email "you@example.com"

# Connect to GitHub remote (already done)
git remote add origin https://github.com/radipide/TT-FIX-project-1.git
git branch -M main
```

---

## 3. Every time you sit down to work

```powershell
cd "C:\Fincoursa\TT FIX\tt-fix-project"
venv\Scripts\activate
```

You'll know it worked when the prompt shows `(venv)` at the start.

---

## 4. Config setup (one-time, redo if .env is lost/reset)

```powershell
copy config.example.env .env
```

Then edit `.env` and fill in real values:
```
SENDER_COMP_ID=<from TT>
TARGET_COMP_ID=TT
ACCOUNT=<from TT — required on every order, not a login username>
TT_PASSWORD=<from TT>
HOST=<TT SIM or UAT host — NOT the placeholder example domain>
PORT=<TT SIM or UAT port>
FIX_VERSION=FIX.4.4          # confirm with TT — 4.2 vs 4.4
HEARTBEAT_INTERVAL=30
DEFAULT_SYMBOL=ES            # confirm exact CME symbol format with TT
```

`.env` is gitignored — it never gets committed, and needs to be redone if you ever re-clone the repo on a new machine.

---

## 5. Running things

**Dashboard** (market data + order entry UI):
```powershell
streamlit run src\dashboard.py
```
Opens at `http://localhost:8501`.

**Mock TT acceptor** (lets you test without real credentials — run in its own terminal, leave it running):
```powershell
python src\mock_acceptor.py
```

**Latency harness** — against the mock (default):
```powershell
python scripts\measure_latency.py --count 200
```
Against real TT, once `.env` has real SIM/UAT values:
```powershell
python scripts\measure_latency.py --count 200 --real
```
Writes results to `data\latency_run.csv`.

**Full local test loop** (three terminals, all with venv activated):
1. `python src\mock_acceptor.py`
2. `streamlit run src\dashboard.py` — click Connect, Subscribe, place test orders
3. `python scripts\measure_latency.py --count 200` — get latency numbers

---

## 6. Git workflow (every commit — one branch, small and often)

```powershell
git status                 # see what changed
git diff                   # see exact changes before staging
git add <specific-file>    # or: git add -A for everything
git commit -m "type: short description of why, not just what"
git push
```

---

## 7. Diagnostic commands used while debugging

```powershell
# Check what's actually in a file without opening an editor
type src\config.py
findstr "SOME_STRING" src\dashboard.py

# List directory contents
dir
dir src

# Redirect full command output to a file (for long error messages)
pip install quickfix > install_log.txt 2>&1
notepad install_log.txt
```

---

## 8. What you still need from TT / your manager

These aren't commands — they're the blockers on everything past local
mock testing:

- [ ] SIM credentials: `SENDER_COMP_ID`, `TARGET_COMP_ID`, `ACCOUNT`, `TT_PASSWORD`, `HOST`, `PORT`
- [ ] UAT credentials (same fields, separate environment)
- [ ] Confirmation: FIX 4.2 or 4.4 for your actual session
- [ ] Confirmation: exact CME symbol format TT's gateway expects (e.g. `ES` vs `ESZ6`)
- [ ] Whether market data entitlement is separate from order routing entitlement

Once those land, the only commands that change are filling in `.env`
and adding `--real` to the latency script — everything else (dashboard,
git workflow) stays the same.
