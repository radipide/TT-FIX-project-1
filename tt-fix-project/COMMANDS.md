# TT FIX Project — Command Reference (Updated)

Everything from the original setup, plus everything added since (two-session
UAT config, SSL diagnostics, spread strategy dashboard).

---

## 1. One-time machine setup

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
py -0   # confirm Python 3.11 is installed alongside 3.13
```

---

## 2. Repo setup (one-time, already done)

```powershell
cd "C:\Fincoursa\TT FIX\tt-fix-project"
py -3.11 -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt   # simplefix, streamlit, pandas, python-dotenv
```

```powershell
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git remote add origin https://github.com/radipide/TT-FIX-project-1.git
git branch -M main
```

---

## 3. Every session

```powershell
cd "C:\Fincoursa\TT FIX\tt-fix-project"
venv\Scripts\activate
```

Confirm it worked — prompt should show `(venv)`.

---

## 4. Config setup

```powershell
copy config.example.env .env
notepad .env
```

Fill in (two-session structure — order routing and market data are separate):
```
SENDER_COMP_ID=
ON_BEHALF_OF_SUB_ID=
OR_TARGET_COMP_ID=
OR_PASSWORD=
ACCOUNT=
MD_TARGET_COMP_ID=
MD_PASSWORD=
```
`OR_HOST`/`OR_PORT`/`MD_HOST`/`MD_PORT` already default to TT's real public UAT endpoints — only override if told to use something different (e.g. stunnel).

**Verify `.env` is actually git-ignored (do this once, cheap insurance):**
```powershell
git check-ignore .env
```
Should print `.env` back. If it prints nothing, stop and fix `.gitignore` before going further.

---

## 5. Running things

**Main dashboard** (order routing + market data, manual instrument entry):
```powershell
streamlit run src\dashboard.py
```

**Strategy dashboard** (HO*42-CL / BZ-CL spreads, rolling stats, entry/exit signals):
```powershell
streamlit run src\strategy_dashboard.py
```

**Mock TT acceptor** (local testing without real credentials):
```powershell
python src\mock_acceptor.py
```

**Latency harness:**
```powershell
python scripts\measure_latency.py --count 200          # against mock
python scripts\measure_latency.py --count 200 --real   # against real TT
```

---

## 6. Network / SSL diagnostics (use if a real connection fails)

**Basic TCP reachability, bypassing TLS entirely:**
```powershell
Test-NetConnection -ComputerName fixorderrouting-ext-uat-cert.trade.tt -Port 11502
Test-NetConnection -ComputerName fixmarketdata-ext-uat-cert.trade.tt -Port 11503
```
Check `TcpTestSucceeded` — if `False`, it's a network/firewall/whitelisting issue, not a code issue.

**TLS handshake test, independent of our Python code** (run in Git Bash, not PowerShell):
```bash
openssl s_client -connect fixorderrouting-ext-uat-cert.trade.tt:11502
openssl s_client -connect fixmarketdata-ext-uat-cert.trade.tt:11503
```
If this also fails the same way, the problem is environmental (network/server-side), not in `fix_session.py`.

---

## 7. Git workflow (every commit)

```powershell
git status
git diff
git add <specific-file>      # prefer this over -A
git commit -m "type: why, not just what"
git push
```

---

## 8. Diagnostic commands used while debugging

```powershell
type src\config.py
findstr "SOME_STRING" src\dashboard.py
dir
dir src
pip install quickfix > install_log.txt 2>&1
notepad install_log.txt
```

---

## 9. Skill file (Claude Code auto-loads this in the repo)

Location: `.claude/skills/git-hygiene/SKILL.md` — covers git safety (never
blind `git add -A`, always `git status`/`git pull` first) and code
discipline (no overengineering, minimize latency in the FIX/order path).

---

## 10. What's still open

- [ ] Confirm `SENDER_COMP_ID` (your own identity, not TT's Remote Comp ID)
- [ ] Confirm literal `ON_BEHALF_OF_SUB_ID` value — `AJUAT` or `33986`
- [ ] Both session passwords in `.env` (never here in chat)
- [ ] Real TT connection still untested past TLS handshake — last attempt
      failed at handshake stage (timeout / EOF), likely IP whitelisting or
      firewall — see section 6 diagnostics
- [ ] Exact CME symbol format for HO/CL/BZ (month codes etc.)
- [ ] Decide on a stop-loss for the spread strategy (currently only a 0.5σ
      reversion exit + 90-min time exit — no price-based downside limit)
