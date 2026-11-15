"""Client for older TP-Link ISP firmwares (e.g. Archer C5v from Turkish Telekom) that tplinkrouterc6u does not detect.

Their web UI logs in with /cgi/login?UserName=<rsa>&Passwd=<rsa(base64(pw))>&Action=1&LoginStatus=0 (PKCS#1 v1.5,
1024-bit key from /cgi/getParm, which has no "seq"), then (if the firmware has one) reads a token from the index page and talks plain
/cgi?<types> requests, like the MR200 client.
"""
import base64
import re
import time
from binascii import hexlify

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
from tplinkrouterc6u.client.mr200 import TPLinkMR200Client
from tplinkrouterc6u.common.exception import AuthorizeError, ClientException

LOGIN_ERRORS = {71233: "wrong username or password", 71234: "bad login request"}


class LegacyCgiClient(TPLinkMR200Client):
    ROUTER_NAME = "TP-Link legacy CGI"

    def supports(self) -> bool:
        try:
            self._get_params()
            return True
        except ClientException:
            return False

    @staticmethod
    def detect(host: str, timeout: int = 10) -> bool:
        """The login page posts to /cgi/login?UserName= and /cgi/getParm has no "seq" (the newer MR login has one)."""
        import requests
        try:
            page = requests.get(host, timeout=timeout).text
            if "cgi/login?UserName=" not in page:
                return False
            parm = requests.post(f"{host}/cgi/getParm", headers={"Referer": host + "/"}, timeout=timeout).text
            return 'nn="' in parm and "seq" not in parm
        except requests.RequestException:
            return False

    SESSION_REUSE = 120  # seconds; a call that fails gets a fresh login from the Router wrapper anyway

    def authorize(self) -> None:
        # Logging in again on every call would also throw a person out of the web UI each time.
        if getattr(self, "_authed_at", 0) > time.monotonic() - self.SESSION_REUSE:
            return
        self._get_params()
        cipher = PKCS1_v1_5.new(RSA.construct((self._nn, self._ee)))

        def enc(data: bytes) -> str:
            return hexlify(cipher.encrypt(data)).decode().rjust(256, "0")

        name = enc(self.username.encode())
        pw = enc(base64.b64encode(self.password.encode()))
        r = self.req.post(f"{self.host}/cgi/login?UserName={name}&Passwd={pw}&Action=1&LoginStatus=0",
                          timeout=self.timeout)
        m = re.search(r"\$\.ret=(\d+)", r.text)
        ret = int(m.group(1)) if m else -1
        if ret != 0:
            raise AuthorizeError(f"login refused ({ret}: {LOGIN_ERRORS.get(ret, 'unknown')})")
        self.req.post(f"{self.host}/cgi/info", timeout=self.timeout)
        # Some firmwares add a TokenID next to the session cookie; the Archer C5v uses the cookie alone.
        page = self.req.get(self.host, timeout=self.timeout).text
        m = re.search(r'token\s*=\s*"([^"]+)"', page)
        if m:
            self.req.headers["TokenID"] = m.group(1)
        self._authed_at = time.monotonic()

    # ----- reads the generic MR code gets wrong on these firmwares -----

    def _gl(self, oid: str, gs: bool = False) -> list[dict]:
        """All instances of an object: [{"_stack": "1,1,0,0,0,0", attr: value, ...}]."""
        r, _ = self.req_act([self.ActItem(self.ActItem.GS if gs else self.ActItem.GL, oid)])
        err = re.search(r"\[error\](\d+)", r.text)
        if err and err.group(1) != "0":
            self._authed_at = 0
            raise ClientException(f"{oid}: router error {err.group(1)}")
        out = []
        for block in r.text.split("\n["):
            head, _, body = block.lstrip("[").partition("\n")
            m = re.match(r"([\d,]+)\]\d+$", head.strip())
            if not m:
                continue
            item = {"_stack": m.group(1)}
            for line in body.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    item[k] = v
            out.append(item)
        return out

    def wifi_networks(self) -> list[dict]:
        """Each SSID with band, channel, on/off; index = WLANConfiguration number."""
        return [{"index": int(w["_stack"].split(",")[1]), "ssid": w.get("SSID", ""), "band": w.get("X_TP_Band", ""),
                 "enabled": w.get("enable") == "1", "channel": w.get("channel", ""), "standard": w.get("standard", "")}
                for w in self._gl("LAN_WLAN")]

    def stations(self) -> list[dict]:
        """Associated Wi-Fi clients with signal (dBm) and last rate (Mbps), with the SSID index they are on."""
        out = []
        for s in self._gl("LAN_WLAN_ASSOC_DEV", gs=True):
            sig = s.get("X_TT_SignalStrength") or s.get("X_TP_SignalStrength") or s.get("signalStrength") or ""
            out.append({"mac": s.get("associatedDeviceMACAddress", "").upper(),
                        "network_index": int(s["_stack"].split(",")[1]),
                        "signal_dbm": int(sig) if sig.lstrip("-").isdigit() else None,
                        "rate_mbps": int(s["lastDataTransmitRate"]) if s.get("lastDataTransmitRate", "").isdigit() else None,
                        "packets_sent": int(s["X_TP_TotalPacketsSent"]) if s.get("X_TP_TotalPacketsSent", "").isdigit() else None})
        return out

    def hosts(self) -> list[dict]:
        """Every host the router knows (LAN_HOST_ENTRY), merged with Wi-Fi band and signal."""
        nets = {n["index"]: n for n in self.wifi_networks()}
        stas = {s["mac"]: s for s in self.stations()}
        out = []
        for h in self._gl("LAN_HOST_ENTRY"):
            mac = h.get("MACAddress", "").upper()
            m = re.search(r"WLANConfiguration\.(\d+)", h.get("layer2Interface", ""))
            net = nets.get(int(m.group(1))) if m else None
            sta = stas.get(mac, {})
            out.append({"hostname": h.get("hostName", ""), "ip": h.get("IPAddress", ""), "mac": mac,
                        "active": h.get("active") == "1",
                        "connection": f"wifi {net['band']}" if net else ("wired" if h.get("interfaceType") == "Ethernet" else h.get("interfaceType", "")),
                        "ssid": net["ssid"] if net else None,
                        "signal_dbm": sta.get("signal_dbm"), "rate_mbps": sta.get("rate_mbps"),
                        "address_source": h.get("addressSource", ""),
                        "lease_seconds_left": int(h["leaseTimeRemaining"]) if h.get("leaseTimeRemaining", "").isdigit() else None})
        return out

    def logs(self) -> list[dict]:
        """System log, newest first: time, severity (0 emerg .. 7 debug), module, message."""
        lines = self.req.get(f"{self.host}/cgi/log", timeout=self.timeout).text.split("\r\n")
        out = []
        for line in lines[1:]:
            m = re.match(r"([\d-]+\s[\d:]+)\s\[(\d)\]\s(\w+):\s(.*)", line)
            if m:
                out.append({"time": m.group(1), "severity": int(m.group(2)), "module": m.group(3).upper(),
                            "message": m.group(4)})
        return out[::-1]

    def internet(self) -> dict:
        """Enabled WAN connections (PPP and IP) and the LAN address; the generic IPv4 read picks the ISP's
        management line on these firmwares instead of the internet one."""
        wans = []
        for oid in ("WAN_PPP_CONN", "WAN_IP_CONN"):
            for w in self._gl(oid, gs=True):
                if w.get("enable") != "1":
                    continue
                up = w.get("uptime", "")
                wans.append({"name": w.get("name", ""), "status": w.get("connectionStatus", ""),
                             "type": "PPPoE" if oid == "WAN_PPP_CONN" else "IP",
                             "external_ip": w.get("externalIPAddress", ""), "dns": w.get("DNSServers", ""),
                             "uptime_seconds": int(up) if up.isdigit() else None,
                             "ipv6_enabled": w.get("X_TP_IPv6Enabled") == "1"})
        lan = next((i for i in self._gl("LAN_IP_INTF", gs=True) if i.get("enable") == "1"), {})
        return {"wan": wans, "lan_ip": lan.get("IPInterfaceIPAddress", ""), "lan_mask": lan.get("IPInterfaceSubnetMask", "")}
