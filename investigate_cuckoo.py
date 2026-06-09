"""
investigate_cuckoo.py - find the Bambu client cert and test the write route.

Background: there is no separate cuckoo proxy process.  The cert attachment
happens inside Electron's net module using the Windows certificate store
(non-exportable key).  We therefore cannot route through a proxy port.

The reliable alternative: PowerShell Invoke-RestMethod uses .NET/WinHTTP,
which can pick a cert from the Windows store by thumbprint — including keys
marked non-exportable.  This script finds the right cert and confirms the
route works with a read-only GET /captain.

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

API_URL = "https://192.168.68.78:8888"
PROBE_PATH = "/captain"


# ---------------------------------------------------------------------------
# 1. List certs in CurrentUser\My via PowerShell
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
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception as e:
        print(f"  (cert enumeration failed: {e})")
        return []


def find_bambu_certs(certs: list[dict]) -> list[dict]:
    hits = []
    for c in certs:
        sub = (c.get("Subject") or "").lower()
        iss = (c.get("Issuer") or "").lower()
        if any(kw in sub or kw in iss for kw in ("bambu", "bbl", "farm")):
            hits.append(c)
    return hits


# ---------------------------------------------------------------------------
# 2. Sniff JWT from DevTools (reuse bambu_api logic)
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
# 3. Test the PowerShell Invoke-RestMethod route
# ---------------------------------------------------------------------------

def ps_get(url: str, thumbprint: str, jwt: str | None) -> str:
    auth_header = ""
    if jwt:
        auth_header = f"'Authorization' = 'Bearer {jwt}'; "
    ps = f"""
    $cert = Get-Item 'Cert:\\CurrentUser\\My\\{thumbprint}'
    $headers = @{{ {auth_header}'x-bbl-sec-ver' = '1' }}
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
# Report
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("CUCKOO INVESTIGATION  (round 3 — PowerShell / cert store)")
    print("=" * 70)

    print("\n[1] Certificates in CurrentUser\\My:")
    certs = list_user_certs()
    if not certs:
        print("    (none found or PowerShell failed)")
    for c in certs:
        flag = "  <-- BAMBU?" if c in find_bambu_certs(certs) else ""
        print(f"    {c['Thumbprint'][:16]}...  {c['Subject'][:55]}  exp {c['NotAfter']}{flag}")

    bambu_certs = find_bambu_certs(certs)
    if not bambu_certs and certs:
        print("\n    No cert with 'bambu/bbl/farm' in subject/issuer.")
        print("    Will test ALL certs with a private key.")
        candidates = [c for c in certs if c.get("HasPrivKey")]
    else:
        candidates = bambu_certs

    print(f"\n[2] Sniffing JWT from client ...")
    jwt = sniff_jwt()
    print(f"    JWT sniffed: {'yes (' + jwt[:20] + '...)' if jwt else 'no (timed out)'}")

    print(f"\n[3] Testing PowerShell route with {len(candidates)} candidate cert(s) ...")
    url = f"{API_URL}{PROBE_PATH}"
    winner = None
    for c in candidates:
        thumb = c["Thumbprint"]
        print(f"\n    cert: {thumb[:16]}...  {c['Subject'][:55]}")
        result = ps_get(url, thumb, jwt)
        print(f"    result: {result[:200]}")
        if result and "ERROR" not in result and "TIMEOUT" not in result and "error" not in result.lower():
            winner = (thumb, c["Subject"])

    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    if winner:
        thumb, subject = winner
        print(f"""
    PowerShell route WORKS with cert thumbprint:
        {thumb}  ({subject})

    This is the transport to use in bambu_api.py.
    Copy the thumbprint above and report back — the code will be updated.
""")
    else:
        print("""
    PowerShell route did not succeed with any cert.

    Possible next steps:
      a) The Bambu cert is in LocalMachine\\My rather than CurrentUser\\My.
         Re-run: Set-Location Cert:\\LocalMachine\\My and check.
      b) The cert subject uses different keywords than bambu/bbl/farm.
      c) Try driving the client via DevTools (Runtime.evaluate in main process).

    Paste this full output back to proceed.
""")


if __name__ == "__main__":
    main()
