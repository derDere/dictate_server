# dictate_server
Lightweight local web server that receives text from any device on the LAN and injects it into the active Windows application via clipboard.

# AI START

**Erstelle eine Windows-Anwendung (`dictate_server.py`) mit folgenden Anforderungen:**

Die App ist eine reine Windows-Anwendung. Sie besteht aus zwei Teilen die gleichzeitig laufen: einem `tkinter`-Fenster und einem eingebetteten Flask-Webserver der in einem separaten Thread läuft.

**Tkinter-Fenster:**
- Start/Stop-Button für den Webserver
- Zeigt die aktuelle LAN-IP und den Port an (z.B. `http://192.168.x.x:8765`)
- Zeigt den zuletzt empfangenen und eingetippten Text an
- Zeigt einen QR-Code des Links an (via `qrcode` Library, als Bild direkt im Tkinter-Fenster gerendert) damit man die URL bequem mit dem iPhone scannen kann
- Die LAN-IP soll automatisch über eine UDP-Socket-Methode ermittelt werden die zuverlässig die echte LAN-IP liefert und nicht 127.0.0.1

**Webserver (läuft nur solange der Start-Button aktiv ist):**
- Lauscht auf `0.0.0.0:8765`, ist aber nur im lokalen Netz erreichbar das heißt es muss auf die lan ip gefiltert werden!
- es ist nur ein client erlaubt! wenn die seite geladen wird muss im fenster ein code eingegeben werden der auf der seite angezeigt wird sonst ist der client nicht erlaubt!
- Liefert eine einzige HTML-Seite mit: großem scrollbarem Textarea-Feld, einem "Senden"-Button und einem "Leeren"-Button
- Das HTML/CSS soll mobilfreundlich sein (große Buttons, volle Breite) da es vom iPhone aufgerufen wird der text im textfeld kan klein bleiben da die idee ist das recht viel eingegeben wird. der clear button sollte nicht zu groß sein und ein confirm haben 

**Beim Senden (POST-Request) – wichtig: muss auch funktionieren wenn das Tkinter-Fenster minimiert oder im Hintergrund ist:**
1. Aktuellen Clipboard-Inhalt in eine Variable sichern via `win32clipboard` (pywin32)
2. Den gesendeten Text in die Zwischenablage legen via `win32clipboard`
3. `Ctrl+V` simulieren via `pyautogui.hotkey('ctrl', 'v')` – das funktioniert unter Windows auch wenn die eigene App nicht im Fokus ist
4. Kurze Pause (ca. 300ms) damit das Einfügen abgeschlossen ist
5. Den ursprünglichen Clipboard-Inhalt via `win32clipboard` wiederherstellen
6. Den eingetippten Text ans Tkinter-Fenster melden (zur Anzeige)
7. HTTP 200 zurückgeben, Textarea im Browser leeren

**Dependencies:** `http.server`, `pyautogui`, `pywin32`, `qrcode[pil]`, `pillow` – alle per pip installierbar unter Python 3.13 auf Windows.
