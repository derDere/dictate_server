# Online Gateway — Konzept & Implementierung

> Feature-Branch: `claude/add-online-gateway-server-Rj4Bl`  
> Neue Dateien: `online_server.py`, `gateway_client.py`, `config.py`, `requirements-gateway.txt`  
> Geänderte Dateien: `gui.py`, `requirements.txt`

---

## Motivation

`dictate_server` läuft bisher nur im lokalen Netzwerk (LAN). PC und Handy müssen sich
im gleichen WLAN befinden. Das Feature **Online Gateway** hebt diese Einschränkung auf:
Ein leichtgewichtiger Relay-Server auf einem öffentlich erreichbaren Host vermittelt die
Verbindung — Handy und PC können sich in völlig unterschiedlichen Netzwerken befinden.

### Sicherheitsziele

| Ziel | Umsetzung |
|---|---|
| Server sieht den Pairing-Code nie | Nur SHA-256-Ableitung wird übertragen |
| Server sieht den Klartext nie | AES-256-GCM-Verschlüsselung, E2E |
| PC muss aktiv bestätigen | User muss Code manuell eintippen |
| Brute-Force-Schutz | Max. 10 Fehlversuche pro Verbindung, Code läuft nach 120 s ab |
| Verwechslungsschutz | O↔0 und I↔1 werden gleichgesetzt; L bleibt (Großschrift eindeutig) |

---

## Konzept

### Rollen

```
┌──────────────┐      WebSocket       ┌─────────────────┐      WebSocket       ┌─────────┐
│  PC-App      │ ──────────────────── │  Gateway-Server  │ ──────────────────── │  Handy  │
│ (Windows)    │                      │  (public host)   │     (Browser)        │         │
└──────────────┘                      └─────────────────┘                       └─────────┘
```

- **Gateway-Server** — reines Relay. Vermittelt Verbindungen, sieht nur verschlüsselte Blobs.
- **PC-App** — verbindet sich automatisch, wenn Gateway-Modus eingeschaltet ist.
- **Handy-Browser** — öffnet die Gateway-URL, generiert den Code, verschlüsselt Text.

### Ablauf Schritt für Schritt

```
1.  PC-App startet  →  WebSocket-Verbindung zum Gateway  →  sendet {type: "pc_register"}
2.  Handy öffnet Gateway-URL  →  pollt /has_pc bis PC verbunden
3.  Handy-JS generiert zufälligen 6-stelligen Code  (Alphabet: A–Z + 2–9)
4.  Handy zeigt Code groß auf dem Display an
5.  Handy berechnet:  identifier = SHA-256("dictate_pairing_v1:" + code)
6.  Handy generiert ephemeres ECDH P-256-Schlüsselpaar
7.  Handy sendet  →  Gateway:  {type: "phone_pair", identifier, phone_pubkey}
8.  Gateway speichert: pending_phones[identifier] = {ws, pubkey, expires_at}
9.  User liest Code vom Handy-Display, tippt ihn in PC-App ein
10. PC-App normalisiert: 0→O, 1→I  (Verwechslungsschutz)
11. PC berechnet denselben identifier aus dem Code
12. PC generiert ephemeres ECDH P-256-Schlüsselpaar
13. PC sendet  →  Gateway:  {type: "pc_pair", identifier, pc_pubkey}
14. Gateway findet pending_phones[identifier]  →  Treffer!
15. Gateway sendet an PC:     {type: "paired", phone_pubkey}
16. Gateway sendet an Handy:  {type: "paired", pc_pubkey}
17. Beide Seiten berechnen unabhängig voneinander:
      shared_secret = ECDH(own_private_key, peer_public_key)
      session_key   = HKDF-SHA-256(shared_secret, salt=code, info="dictate_session_v1")
18. Ab jetzt: alle Nachrichten AES-256-GCM-verschlüsselt
19. Handy tippt/diktiert Text  →  verschlüsselt  →  Gateway relay  →  PC entschlüsselt  →  inject
```

### Warum der Gateway-Server sicher ist

- Er kennt den Code nicht → kann den identifier nicht umkehren (SHA-256 ist Einwegfunktion).
- Er sieht nur den ECDH-Public-Key (öffentlich per Design, kein Geheimnis).
- Nach dem Pairing leitet er nur verschlüsselte Blobs weiter, ohne Schlüssel oder Klartext.
- Selbst ein kompromittierter Server kann die Sitzungsdaten nicht entschlüsseln.

---

## Dateistruktur

```
dictate_server/
├── online_server.py          ← NEU: Gateway-Server (aiohttp, läuft auf public host)
├── gateway_client.py         ← NEU: PC-seitiger WebSocket-Client + Kryptografie
├── config.py                 ← NEU: JSON-Config-Persistenz
├── requirements-gateway.txt  ← NEU: Abhängigkeiten nur für den Server
├── requirements.txt          ← GEÄNDERT: +websockets, +cryptography
└── gui.py                    ← GEÄNDERT: neuer "Online Gateway"-Bereich
```

---

## Neue Dateien

### `online_server.py` — Gateway-Server

**Verwendung:**
```bash
pip install aiohttp
python online_server.py --host 0.0.0.0 --port 8766
```

**Endpunkte:**

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/` | Handy-UI (HTML + JS) |
| `GET` | `/has_pc` | `{"available": true/false}` — wird vom Handy gepollt |
| `GET` | `/ws` | WebSocket-Endpunkt für PC und Handy |

**Interner Zustand (In-Memory, kein persistenter Speicher):**

```python
active_pcs: set        # WebSocket-Objekte registrierter PC-Clients
pending_phones: dict   # identifier → {ws, pubkey, expires_at}
sessions: dict         # ws → partner_ws  (bidirektional)
pc_attempts: dict      # ws → int  (Brute-Force-Zähler)
```

**WebSocket-Protokoll:**

```
PC  → Server:  {"type": "pc_register"}
Server → PC:   {"type": "pc_registered"}

Handy → Server: {"type": "phone_pair", "identifier": "<sha256>", "phone_pubkey": "<base64>"}

PC  → Server:  {"type": "pc_pair", "identifier": "<sha256>", "pc_pubkey": "<base64>"}
Server → PC:   {"type": "paired", "phone_pubkey": "<base64>"}
               {"type": "pair_failed", "reason": "code_invalid"|"phone_gone"|"too_many_attempts"}
Server → Handy:{"type": "paired", "pc_pubkey": "<base64>"}
               {"type": "pair_expired"}

Beide → Server: {"type": "data", "payload": "<AES-GCM-Blob-base64>"}
Server → Beide: (relay, unverändert)

Server → Handy: {"type": "session_ended"}  (wenn PC-Verbindung bricht)
```

**Sicherheitsparameter:**
```python
MAX_PAIR_ATTEMPTS = 10    # Fehlversuche je PC-Verbindung
PAIR_TTL         = 120    # Sekunden, bis Code abläuft
CLEANUP_INTERVAL = 15     # Sekunden zwischen Ablauf-Checks
```

**Cleanup-Task:**  
Ein `asyncio`-Hintergrund-Task prüft alle 15 Sekunden `pending_phones` auf abgelaufene
Einträge und sendet `pair_expired` an das wartende Handy.

**Deployment hinter Reverse-Proxy (Caddy-Beispiel):**
```
example.com {
    reverse_proxy /ws localhost:8766
    reverse_proxy    localhost:8766
}
```

---

### `gateway_client.py` — PC-seitiger Client

Läuft in einem Hintergrund-Thread mit eigenem `asyncio`-Event-Loop.  
Kommuniziert mit dem GUI-Thread über `state.gui_queue` (Statusmeldungen → GUI)
und `asyncio.Event` (Code-Übergabe GUI → Client).

**Krypto-Stack:**

```
Schlüsselaustausch:  ECDH P-256  (via `cryptography`-Bibliothek)
Schlüsselableitung:  HKDF-SHA-256
  salt = pairing_code  (als UTF-8-Bytes)
  info = b"dictate_session_v1"
  length = 32 Byte
Verschlüsselung:     AES-256-GCM
  iv = 12 Byte zufällig, vorangestellt dem Ciphertext
  payload = base64(iv || ciphertext)
Pairing-Identifier:  SHA-256("dictate_pairing_v1:" + code)
```

**Normalisierung (Verwechslungsschutz):**
```python
code = code.upper().strip().replace("0", "O").replace("1", "I")
```
Diese Normalisierung läuft in `submit_code()`, bevor der Code gespeichert oder der
Identifier abgeleitet wird. Das Handy generiert Codes ohne `0` und `1` (Alphabet `A–Z` + `2–9`),
sodass beide Seiten immer zum gleichen Identifier gelangen.

**Statusmaschine:**

```
DISCONNECTED
    │  connect(url) aufgerufen
    ▼
CONNECTING  ──► (Fehler) ──► DISCONNECTED  (5 s warten, dann erneut)
    │
    │ WebSocket offen, pc_register gesendet
    ▼
WAITING  (bereit, wartet auf Code-Eingabe des Users)
    │
    │ User gibt Code ein → submit_code()
    ▼
PAIRING  (pc_pair gesendet, wartet auf Server-Antwort)
    │                    │
    │ "paired"           │ "pair_failed"
    ▼                    ▼
ACTIVE            PAIR_FAILED → zurück zu WAITING
    │
    │ session_ended / Verbindungsabbruch
    ▼
WAITING / DISCONNECTED (je nach ob WS noch offen)
```

**Öffentliche API (GUI-Thread-sicher):**

| Methode | Beschreibung |
|---|---|
| `connect(url)` | Startet Hintergrund-Thread, verbindet zum Gateway |
| `disconnect()` | Stoppt Thread sauber |
| `submit_code(code)` | Übergibt Pairing-Code, weckt async Event |

---

### `config.py` — Konfigurationspersistenz

Speichert `config.json` neben dem Skript.

```python
# Gespeicherte Schlüssel
{
  "gateway_url": "https://example.com",
  "gateway_enabled": false
}
```

```python
cfg.get("gateway_url")          # Einzelwert lesen
cfg.set("gateway_enabled", True)# Einzelwert schreiben (liest, patcht, schreibt)
cfg.load()                      # Vollständiges Dict
cfg.save(data)                  # Vollständiges Dict speichern
```

---

## Geänderte Dateien

### `gui.py` — Neuer Gateway-Bereich

Am Ende des bestehenden Fensters wurde eine neue Sektion hinzugefügt.
**Alle bestehenden Elemente (QR-Code, URL, PIN, Start/Stop) sind unverändert.**

```
┌──────────────────────────────────────────────┐
│  [QR-Code]                                   │
│  http://192.168.x.x:8765                     │
│  PIN: [______] [Connect]                     │
│  [Last Text]                                  │
│  [Start / Stop]                               │
│  ─────────────────────────────────────────── │
│  Online Gateway                               │
│  [https://example.com          ] [ ON / OFF ] │
│  Verbunden – Code eingeben:  [______] [Pair] │
└──────────────────────────────────────────────┘
```

**ON/OFF-Schalter:**
- `OFF` → dunkelroter Button (`#7f1d1d` / `#fca5a5`)
- `ON`  → dunkelgrüner Button (`#14532d` / `#86efac`)
- Implementiert als `tk.Button` (nicht `ttk.Button`), damit explizite Hintergrundfarbe
  im sv_ttk Dark-Theme korrekt dargestellt wird.

**URL-Feld:**  
Speichert automatisch bei `<Return>` und `<FocusOut>` über `cfg.set()`.  
Kein separater Speicher-Button.

**Status-Label:**

| Zustand | Text | Farbe |
|---|---|---|
| `disconnected` | Nicht verbunden | `#555555` |
| `connecting` | Verbinde... | `#888888` |
| `waiting` | Verbunden – Code eingeben: | `#4caf50` |
| `pairing` | Warte auf Bestätigung... | `#888888` |
| `active` | Aktive Sitzung (E2E) | `#4caf50` |
| `pair_failed` | Falscher Code – nochmal: | `#ef5350` |

**Code-Eingabe + Pair-Button:**  
Immer sichtbar, aber `state="disabled"` wenn kein Code erwartet wird.
Aktivieren sich automatisch wenn Status `waiting` oder `pair_failed`.

**Startup-Restore:**  
Beim Start prüft `App.__init__()` ob `gateway_enabled == True` in der Config gespeichert ist.
Falls ja, wird der Gateway automatisch verbunden ohne Nutzerinteraktion.

### `requirements.txt`

```diff
 pyautogui
 pywin32
 qrcode[pil]
 pillow
 sv-ttk
+websockets>=12.0
+cryptography>=42.0
```

`websockets` und `cryptography` sind nur für den PC-Client (`gateway_client.py`) nötig
und werden auf dem Windows-PC installiert.

### `requirements-gateway.txt` _(neu, Server-only)_

```
aiohttp>=3.9
```

Nur auf dem öffentlichen Gateway-Server nötig. Nicht Teil der Desktop-App-Installation.

---

## Handy-Browser-UI (`online_server.py` → `_PHONE_HTML`)

Das Handy öffnet die Gateway-URL im Browser. Die Seite durchläuft vier Zustände:

### Zustand 1: Laden (kein PC verbunden)
```
     ⟳
  Waiting for PC to connect…
```
Pollt alle 2 Sekunden `/has_pc`. Sobald `available: true`, Übergang zu Zustand 2.

### Zustand 2: Pairing (Code anzeigen)
```
  Enter this code in the PC app:
        OIL2MK
  Waiting for confirmation…
```
JS-Ablauf:
1. `genCode()` — 6 Zufallszeichen aus `ABCDEFGHIJKLMNOPQRSTUVWXYZ23456789`
2. `generateKey()` — ephemeres ECDH P-256-Paar (WebCrypto API)
3. `deriveIdentifier(code)` — `SHA-256("dictate_pairing_v1:" + code)`
4. WebSocket öffnen → `{type: "phone_pair", identifier, phone_pubkey}`
5. Warten auf `{type: "paired", pc_pubkey}`

Bei `pair_expired` oder `pair_failed`: neuer Code, Neustart.

### Zustand 3: Diktier-UI (aktive Sitzung)
```
  [Send]  [Clear]  [Enter]
  ┌───────────────────────┐
  │ Diktierter Text…      │
  └───────────────────────┘
```
`sendText()` verschlüsselt mit AES-256-GCM, sendet als `{type: "data", payload: "<base64>"}`.
`pressEnter()` schickt `{action: "enter"}` verschlüsselt.

### Zustand 4: Sitzung beendet
```
  Session ended
  [gespeicherter Text — readonly]
```
Identisches Verhalten wie beim lokalen LAN-Server (Text bleibt erhalten).

---

## Kryptografische Details

### Pairing-Identifier (Einwegfunktion)

```
identifier = SHA-256("dictate_pairing_v1:" + code)
```
- 256-Bit-Output als Hex-String (64 Zeichen)
- Nicht umkehrbar → Server kann Code nicht rekonstruieren
- Kollisionswahrscheinlichkeit bei 32^6 ≈ 10^9 Codes: vernachlässigbar

### ECDH-Schlüsselaustausch

```
Kurve:        P-256 (NIST, in WebCrypto API nativ unterstützt)
Schlüsselformat:
  - Export: Raw Uncompressed Point (0x04 || X || Y = 65 Byte)
  - Transport: base64-kodiert
  - Import Python: EllipticCurvePublicNumbers(x, y, SECP256R1())
```

### Sitzungsschlüsselableitung

```
HKDF-SHA-256:
  IKM  = ECDH-Shared-Secret (32 Byte)
  salt = pairing_code.encode("utf-8")
  info = b"dictate_session_v1"
  L    = 32 Byte
  → AES-256-GCM-Schlüssel
```
Der Code als HKDF-Salt bindet den Sitzungsschlüssel an den Code. Selbst wenn ein
Angreifer den ECDH-Public-Key abfängt und später den Code erfährt, kann er vergangene
Verbindungen nicht entschlüsseln (da die ephemeren Schlüsselpaare verworfen werden).

### Nachrichtenverschlüsselung

```
Plaintext:   JSON-String  {"action": "send", "text": "..."}
                          {"action": "enter"}
IV:          12 Byte CSPRNG-Zufall (je Nachricht neu)
Ciphertext:  AES-256-GCM(session_key, iv, plaintext, aad=None)
Transport:   base64(iv || ciphertext)  →  als "payload"-Feld im WS-Frame
```

### Code-Alphabet und Normalisierung

```
Handy generiert:  A–Z (alle 26 Buchstaben) + 2–9 (8 Ziffern) = 34 Zeichen
                  0 und 1 werden nie generiert
Kombinationen:    34^6 ≈ 1,6 Milliarden

PC normalisiert:  code.upper().replace("0", "O").replace("1", "I")

Ergebnis:
  User tippt "O" oder "0" → beide gültig
  User tippt "I" oder "1" → beide gültig
  "L" bleibt im Alphabet  → Großschrift eindeutig unterscheidbar von I
```

---

## Installation & Deployment

### PC (Windows)

```bash
pip install -r requirements.txt
pythonw main.py
```

Dann in der App:
1. Gateway-URL eintragen (z.B. `https://mein-server.de`)
2. ON-Schalter drücken → App verbindet sich
3. Handy öffnet die Gateway-URL → Code erscheint
4. Code in PC-App eintippen → Pair drücken → fertig

### Gateway-Server (Linux, öffentlich erreichbar)

```bash
pip install aiohttp
python online_server.py --host 0.0.0.0 --port 8766
```

**Systemd-Unit (Beispiel):**
```ini
[Unit]
Description=Dictate Gateway Server

[Service]
ExecStart=/usr/bin/python3 /opt/dictate/online_server.py --port 8766
Restart=always
User=dictate

[Install]
WantedBy=multi-user.target
```

**Caddy-Konfiguration (mit automatischem TLS):**
```
mein-server.de {
    reverse_proxy /ws localhost:8766
    reverse_proxy    localhost:8766
}
```

**nginx-Konfiguration:**
```nginx
server {
    listen 443 ssl;
    server_name mein-server.de;

    location /ws {
        proxy_pass http://127.0.0.1:8766;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600;
    }

    location / {
        proxy_pass http://127.0.0.1:8766;
    }
}
```

---

## Vollständige Dateiliste der Änderungen

| Datei | Status | Beschreibung |
|---|---|---|
| `online_server.py` | Neu | aiohttp-Gateway-Server + Handy-HTML/JS |
| `gateway_client.py` | Neu | PC-WebSocket-Client, ECDH, AES-GCM |
| `config.py` | Neu | JSON-Config-Persistenz |
| `requirements-gateway.txt` | Neu | `aiohttp>=3.9` für Server |
| `gui.py` | Geändert | Gateway-UI-Sektion, Status-Handling, Auto-Connect |
| `requirements.txt` | Geändert | `+websockets>=12.0`, `+cryptography>=42.0` |
| `DEV/ONLINE_GATEWAY.md` | Neu | Diese Dokumentation |
