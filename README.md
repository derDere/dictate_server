# dictate_server

Diktier-Tool für Windows: Text auf dem iPhone ins Mikrofon sprechen (oder tippen) und er landet direkt in der aktiven Windows-Anwendung — ohne Kabel, ohne Cloud.

Die Idee dahinter: iOS-Diktierfunktion ist sehr gut, aber der Text landet auf dem Handy. Mit `dictate_server` öffnest du eine Webseite auf dem iPhone, diktierst dort deinen Text, tippst auf **Senden** — und der Text wird per `Ctrl+V` in das Fenster eingefügt, das gerade auf dem PC aktiv ist. Editor, Browser, Chat, egal.

<!-- Screenshot hier einfügen -->

---

## Voraussetzungen

- Windows 10/11
- Python 3.13
- iPhone (oder anderes Gerät) im selben WLAN

## Installation

```
pip install -r requirements.txt
```

## Starten

```
pythonw main.py
```

Das Fenster öffnet sich zentriert, der Server startet sofort.
`pythonw` verhindert ein Konsolenfenster. Für die Entwicklung geht auch `python main.py`.

---

## Verwendung

### Einmalig: Als Web-App zum Homescreen hinzufügen

1. QR-Code im Fenster mit Safari scannen
2. Teilen-Button → **"Zum Home-Bildschirm"** → **Hinzufügen**

Die App öffnet sich dann ohne Safari-Chrome (keine URL-Leiste) wie eine native App.

### Tägliche Nutzung

1. `dictate_server` auf dem PC öffnen (läuft im Hintergrund)
2. Dictate-App auf dem iPhone öffnen
3. Die angezeigte **PIN** im Desktop-Fenster eintippen → **Connect**
4. Das Textfeld auf dem iPhone antippen → Mikrofon-Taste drücken → diktieren
5. **Senden** — der Text wird direkt in die aktive Windows-Anwendung eingefügt

| Button | Funktion |
|--------|----------|
| **Senden** | Text in die aktive Windows-App einfügen (Clipboard + Ctrl+V), Textfeld leeren |
| **Leeren** | Textfeld leeren (mit Bestätigung) |
| **Enter** | Enter-Taste in der aktiven Windows-App simulieren |

Der Server ist nur für Geräte im selben Netzwerk erreichbar. Pro Sitzung ist genau ein Gerät autorisiert — ein neues Gerät verbindet sich mit einem eigenen PIN.

---

## Fenster-Übersicht

Das Desktop-Fenster ist bewusst klein gehalten:

- **QR-Code** — zum schnellen Öffnen der Seite auf dem Handy
- **URL** — kopierbar, z.B. um sie per Chat ans Handy zu schicken
- **PIN-Feld + Connect** — neues Gerät autorisieren
- **Last Text** — letzten gesendeten Text in einem Popup anzeigen
- **Stop/Start** — Server manuell stoppen und wieder starten
