"""
investigate_cuckoo.py - test whether the server just needs https + JWT,
or whether it genuinely requires a client certificate.

The baseline `http://` probe returned HTTP 400 "Client sent an HTTP request
to an HTTPS server" — meaning the server accepted our TCP connection and
responded.  This suggests it may not be enforcing mutual TLS after all, and
the earlier CERTIFICATE_REQUIRED error was simply us trying the wrong scheme.

This script:
  [1] Sniffs a JWT from the running client.
  [2] Tests GET /captain with https + verify=False + JWT (the simplest route).
  [3] If that fails, tries PowerShell Invoke-RestMethod with each cert in
      CurrentUser\\My as a fallback.

Run on the Windows box with the client open:
    python investigate_cuckoo.py
"""

import json
import subprocess
import sys
import time

from bambu_client import ensure_client, get_page_ws

try:
    import websocket
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websocket-client"])
    import websocket

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_BASE = "https://192.168.68.78:8888"
PROBE_PATH = "/captain"


# ---------------------------------------------------------------------------
# Sniff JWT
# ---------------------------------------------------------------------------

def sniff_jwt(timeout: int = 40) -> str | None:
    ensure_client(verbose=False)
    ws_url = get_page_ws()
    if not ws_url:
        return None
    ws = websocket.create_connection(ws_url, max_size=None)
    mid = [0]

    def send(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))

    send("Network.enable")
    ws.settimeout(timeout + 2)
    deadline = time.time() + timeout
    token = None
    try:
        while time.time() < deadline and token is None:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                break
            for event in ("Network.requestWillBeSent", "Network.responseReceived"):
                if msg.get("method") != event:
                    continue
                if event == "Network.requestWillBeSent":
                    hdrs = msg.get("params", {}).get("request", {}).get("headers", {})
                else:
                    hdrs = msg.get("params", {}).get("response", {}).get("requestHeaders", {})
                auth = hdrs.get("Authorization") or hdrs.get("authorization", "")
                if auth.startswith("Bearer "):
                    token = auth[len("Bearer "):]
    finally:
        ws.close()
    return token


# ---------------------------------------------------------------------------
# Test 1: plain https + verify=False + JWT
# ---------------------------------------------------------------------------

def test_https_direct(jwt: str | None) -> tuple[bool, str]:
    headers = {"x-bbl-sec-ver": "1"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    url = f"{API_BASE}{PROBE_PATH}"
    try:
        r = requests.get(url, headers=headers, verify=False, timeout=10)
        summary = f"HTTP {r.status_code}  body[:200]={r.text[:200]!r}"
        return r.ok, summary
    except requests.exceptions.SSLError as e:
        return False, f"SSLError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Test 2: PowerShell Invoke-RestMethod with cert from store
# ---------------------------------------------------------------------------

def list_user_certs() -> list[dict]:
    ps = r"""
    Get-ChildItem Cert:\CurrentUser\My | ForEach-Object {
        [PSCustomObject]@{
            Thumbprint = $_.Thumbprint
            Subject    = $_.Subject
            Issuer     = $_.Issuer
            NotAfter   = $_.NotAfter.ToString("yyyy-MM-dd")
            HasPrivKey = $_.HasPrivateKey
        }
    } | ConvertTo-Json -Compress
    """
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True, stderr=subprocess.DEVNULL)
        data = json.loads(out.strip())
        return [data] if isinstance(data, dict) else data
    except Exception as e:
        print(f"  (cert enumeration failed: {e})")
        return []


def ps_get(url: str, thumbprint: str, jwt: str | None) -> str:
    auth_line = f"'Authorization' = 'Bearer {jwt}'; " if jwt else ""
    ps = f"""
    $cert = Get-Item 'Cert:\\CurrentUser\\My\\{thumbprint}'
    $headers = @{{ {auth_line}'x-bbl-sec-ver' = '1' }}
    try {{
        $r = Invoke-RestMethod -Uri '{url}' -Certificate $cert `
             -Headers $headers -SkipCertificateCheck -Method GET
        $r | ConvertTo-Json -Depth 5 -Compress
    }} catch {{
        Write-Output "ERROR: $($_.Exception.Message)"
    }}
    """
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True, stderr=subprocess.STDOUT, timeout=15)
        return out.strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"subprocess error: {e}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("TRANSPORT TEST")
    print("=" * 70)

    print(f"\n[1] Sniffing JWT (up to 40s — client must be polling) ...")
    jwt = sniff_jwt()
    if jwt:
        print(f"    Got JWT: {jwt[:30]}...")
    else:
        print("    No JWT captured — tests will run without auth (may get 401).")

    print(f"\n[2] Test: https + verify=False + JWT  ->  GET {API_BASE}{PROBE_PATH}")
    ok, summary = test_https_direct(jwt)
    print(f"    {summary}")

    if ok:
        print("""
======================================================================
RESULT: DIRECT HTTPS WORKS
======================================================================
The server does NOT require mutual TLS — https + verify=False + JWT is
sufficient.  The earlier CERTIFICATE_REQUIRED error was a red herring
(likely hit when no JWT was present, or when using a wrong scheme).

Fix for bambu_api.py — change the BASE_URL line to:
    BASE_URL = "https://192.168.68.78:8888"   # already correct
and remove/ignore CUCKOO_PROXY.  The existing _post() will work as-is.

Also check: is CUCKOO_PROXY = None in bambu_api.py?  If so it already
passes proxies=None to requests and should work immediately.
""")
        return

    print("\n    Direct https failed. Trying PowerShell with cert store ...")
    print(f"\n[3] Listing certs in CurrentUser\\My ...")
    certs = list_user_certs()
    if not certs:
        print("    No certs found.")
    else:
        for c in certs:
            print(f"    {c['Thumbprint'][:20]}...  {c['Subject'][:55]}  exp {c['NotAfter']}"
                  f"  privkey={c.get('HasPrivKey')}")

    candidates = [c for c in certs if c.get("HasPrivKey")]
    print(f"\n[4] Testing PowerShell route with {len(candidates)} cert(s) ...")
    url = f"{API_BASE}{PROBE_PATH}"
    ps_winner = None
    for c in candidates:
        thumb = c["Thumbprint"]
        print(f"\n    cert: ...{thumb[-16:]}  {c['Subject'][:55]}")
        result = ps_get(url, thumb, jwt)
        print(f"    result: {result[:300]}")
        if result and "ERROR" not in result and "TIMEOUT" not in result:
            ps_winner = (thumb, c["Subject"])
            break

    print("\n" + "=" * 70)
    print("RESULT")
    print("=" * 70)
    if ps_winner:
        thumb, subject = ps_winner
        print(f"""
    PowerShell Invoke-RestMethod works with thumbprint:
        {thumb}
    Subject: {subject}

    bambu_api.py will be updated to use subprocess + PowerShell for writes.
    Paste this output back to get the updated code.
""")
    else:
        print("""
    Neither direct https nor PowerShell with any cert worked.
    Paste this full output back — next step is driving the client via DevTools.
""")


if __name__ == "__main__":
    main()
