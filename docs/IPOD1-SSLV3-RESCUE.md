# iPod touch 1. Generation: reproduzierbarer SSLv3-Rettungsweg

**Schritt-für-Schritt-Rezept für genau den Legacy-Verbindungsfall:** iPod touch (1. Generation), iPhone OS 1.1.5 (Build 4B1), Windows 11 / WSL2 / Ubuntu 24.04. Auf diesem Gerät scheitert der verschlüsselte Lockdown-Handshake mit den gewöhnlichen Ubuntu-Bibliotheken. Das nachfolgende Verfahren baut einen **ausschließlich für diese Rettung vorgesehenen** GnuTLS-/libimobiledevice-Client mit SSLv3-Unterstützung. Danach wurden ein read-only AFC-Mount und ein **unabhängig SHA-256-geprüfter strukturierter Audioexport** erfolgreich durchgeführt. Auch die optionale MP3-Konvertierung wurde abgeschlossen und später **unabhängig mit den Original-Audiodateien per SHA-256 abgeglichen**. **[Projektüberblick](../README.md)** · **[Vollständige Extraktion und Rekonstruktion](END-TO-END-RECOVERY.md)** · **[MP3-How-to](MP3-CONVERSION.md)**.

**Kein generischer Tipp für alle iPods:** Erst Firmware und Gerätemodell feststellen. SSLv3 gilt als unsicher. Niemals systemweite TLS-Regeln lockern, das gepatchte Bibliotheksverzeichnis global in `ld.so.conf` aufnehmen oder mit dieser Konfiguration Netzwerkdienste betreiben. Die Befehle dienen **nur** dazu, das historische Gerät lokal per USB auszulesen.

## 1. Geltungsbereich und nachgewiesene Umgebung

| Merkmal | Bestätigter Wert |
| --- | --- |
| Gerät | Apple iPod touch, 1. Generation |
| ProductType | `iPod1,1` |
| Modellnummer | `MA623` (Geräteausgabe; Verkaufsregion hier irrelevant) |
| Firmware | iPhone OS `1.1.5`, Build `4B1` |
| Host | Windows 11, Ubuntu 24.04 LTS unter WSL2 |
| USB | `usbipd-win` 5.3; `usbmuxd` 1.1.1 |
| FUSE-Client | Ubuntu-`ifuse` 1.1.4 |
| System-`libimobiledevice` | 1.3.0-8.1build3 (OpenSSL 3) |
| Selbst gebautes `libimobiledevice` | Upstream-Tag `1.3.0`, GnuTLS-Backend, SSLv3-Patch |
| Selbst gebautes GnuTLS | Upstream `3.8.3` mit `--enable-ssl3-support` |
| Ubuntu-`libplist` | 2.3.0, erfordert Kompatibilitätskorrektur in libimobiledevice |

Die Anleitung dokumentiert **eine konkret funktionierende Geräte-/Firmware-Kombination**, keine allgemeine Unterstützung aller iPods. Keine UDID, Seriennummer, privaten Schlüssel oder vollständigen Lockdown-Dumps ins öffentliche Repository übernehmen.

## 2. Warum der Standardweg nicht funktioniert

1. USB-Passthrough, usbmuxd und unverschlüsselte Lockdown-Abfragen funktionierten. Die Pairing-Anfrage wurde mit `ValidatePair success` quittiert und die Sitzung mit `Session startup OK` angelegt. Ein Pairing-Fehler war also **nicht** die Ursache des folgenden Abbruchs.
2. Das Ubuntu-Paket `libimobiledevice6` verwendet OpenSSL 3. Der verschlüsselte Handshake scheiterte mit `SSL error (-5)`. Frühere Versuche mit prozessbezogenen OpenSSL-Sicherheitsstufen änderten daran nichts.
3. Upstream `libimobiledevice 1.3.0` unterstützt GnuTLS, aber **nicht** die neueren Konfigurationsschalter `--with-gnutls` / `--without-openssl`. Korrekt ist `--disable-openssl`; die Konfiguration meldet dann `SSL support backend: GnuTLS`.
4. Die unveränderte Version 1.3.0 fordert für GnuTLS hart codiert `VERS-TLS1.0` an. Ubuntu 24.04 blockiert TLS 1.0 standardmäßig über GnuTLS-Prioritäten. Das verursachte reproduzierbar `No or insufficient priorities were set`. Eine auf einen Prozess beschränkte Prioritätenkonfiguration ließ TLS 1.0 zu, der iPod-Handshake schlug **trotzdem** fehl.
5. Ursache des verbleibenden Protokollkonflikts: **iPhone OS 1.x spricht bei diesem Lockdown-Handshake SSLv3, nicht TLS 1.0**. Das ist durch einen Upstream-Fix („Fix iOS 1 SSL connection“, Dezember 2023) dokumentiert.
6. Ubuntu-GnuTLS 3.8.3 bietet SSLv3 im Distributionsbuild nicht an. Der GnuTLS-Quellcode derselben Version unterstützt aber `--enable-ssl3-support`. Nach dem Selbstbau und Wechsel der fest codierten libimobiledevice-Priorität auf `VERS-SSL3.0` funktionierte `ideviceinfo` **mit Exit-Code 0**.
7. Eine unabhängige Build-Hürde: `libimobiledevice 1.3.0` definiert `PLIST_FORMAT_XML` und `PLIST_FORMAT_BINARY` selbst. Mit Ubuntu-`libplist 2.3.0` kommt es zu doppelten Enum-Definitionen. Daher wird nur die lokale Definition entfernt und der öffentliche Typ `plist_format_t` verwendet.

**Wichtig:** Weder eine systemweite Herabstufung von OpenSSL noch ein Firmware-Update/Jailbreak des iPods war erforderlich. Auch eine pauschale Freigabe von SHA-1-Zertifikatssignaturen wurde im erfolgreichen GnuTLS-Build **nicht** vorgenommen (`Allow SHA1 sign: no` im Configure-Bericht).

## 3. Voraussetzungen

Für diese reine Rettungs-WSL waren die Ubuntu-Pakete `libimobiledevice-utils`, `ifuse`, `usbmuxd` und das USB-Passthrough bereits eingerichtet; siehe [WSL-SETUP.md](WSL-SETUP.md). Für die beiden Quellcode-Builds:

```bash
sudo apt-get update
sudo apt-get install -y \
  build-essential git curl gpg xz-utils pkg-config \
  autoconf automake libtool libtool-bin \
  libplist-dev libusbmuxd-dev libgnutls28-dev \
  libgcrypt20-dev libtasn1-6-dev \
  nettle-dev libunistring-dev libidn2-dev
```

Alle nachfolgenden Installationen erfolgen **ohne sudo** unter separaten Präfixen im Home-Verzeichnis. Das ist auch für eine dedizierte WSL einfacher reproduzierbar als das Überlagern von Systempaketen.

## 4. GnuTLS 3.8.3 mit SSLv3 bauen

### 4.1 Originalarchiv herunterladen und prüfen

```bash
mkdir -p "$HOME/ipod-rescue-build/gnutls"
cd "$HOME/ipod-rescue-build/gnutls"

BASE="https://www.gnupg.org/ftp/gcrypt/gnutls/v3.8"
curl -fL "$BASE/gnutls-3.8.3.tar.xz" -o gnutls-3.8.3.tar.xz
curl -fL "$BASE/gnutls-3.8.3.tar.xz.sig" -o gnutls-3.8.3.tar.xz.sig
curl -fL https://gnutls.org/gnutls-release-keyring.gpg -o gnutls-release-keyring.gpg

mkdir -p -m 700 ./gnupg
gpg --homedir ./gnupg --import gnutls-release-keyring.gpg
gpg --homedir ./gnupg \
  --verify gnutls-3.8.3.tar.xz.sig gnutls-3.8.3.tar.xz
```

Im realen Durchlauf war die **kryptografische Signatur gültig**, der Signaturschlüssel von Daiki Ueno bei der Verifikation 2026 aber **abgelaufen**. Eine „Good signature“-Meldung beweist allein nicht die Vertrauenswürdigkeit des importierten Schlüssels: dessen Fingerprint bei einem Neuaufbau unabhängig mit einer offiziellen Quelle abgleichen. Bei unerwarteter/unverifizierbarer Signatur **abbrechen**.

### 4.2 Konfigurieren und installieren

```bash
tar -xf gnutls-3.8.3.tar.xz
cd gnutls-3.8.3

./configure \
  --prefix="$HOME/ipod-rescue-ssl3" \
  --enable-ssl3-support \
  --disable-doc \
  --disable-cxx \
  --disable-libdane \
  --without-p11-kit

# Configure-Zusammenfassung muss "SSL3.0 support: yes" ausgeben.
make -j2
make install
```

### 4.3 Isolierte GnuTLS-Prioritätenkonfiguration und Offline-Prüfung

In der getesteten Ubuntu-Umgebung wirkte eine systemseitige GnuTLS-Sperrliste. Die folgenden Einstellungen gelten **nur für Prozesse**, denen die Umgebungsvariable mitgegeben wird:

```bash
cat > "$HOME/ipod-gnutls-isolated.conf" <<'EOF'
[global]
override-mode = blocklist
EOF

env \
  LD_LIBRARY_PATH="$HOME/ipod-rescue-ssl3/lib" \
  GNUTLS_SYSTEM_PRIORITY_FILE="$HOME/ipod-gnutls-isolated.conf" \
  "$HOME/ipod-rescue-ssl3/bin/gnutls-cli" --list \
  --priority 'NONE:+VERS-SSL3.0:+RSA:+AES-128-CBC:+SHA1:+COMP-NULL' \
  | grep -E 'TLS_RSA_AES_128_CBC_SHA1|Protocols:'
```

**Erfolgskriterium:** `Protocols: VERS-SSL3.0` und `TLS_RSA_AES_128_CBC_SHA1` (SSL3.0). Ein bloßer Exit-Code 0 für die Prioritäteneingabe genügt nicht.

## 5. libimobiledevice 1.3.0 anpassen und bauen

### 5.1 Exakten Quellcodestand verwenden

```bash
mkdir -p "$HOME/ipod-rescue-build"
cd "$HOME/ipod-rescue-build"

git clone https://github.com/libimobiledevice/libimobiledevice.git
cd libimobiledevice
git checkout 1.3.0
git rev-parse --short HEAD
# Getesteter Tag/Checkout begann mit 15f8652.
```

Bei bereits vorhandenem Checkout nur `cd "$HOME/ipod-rescue-build/libimobiledevice"` ausführen, **nicht erneut klonen**.

### 5.2 libplist-2.3-Kompatibilität

Beim ersten `make` zeigten `common/utils.h` und `common/utils.c` die doppelt definierten `PLIST_FORMAT_XML` / `PLIST_FORMAT_BINARY`. Der folgende idempotenzvermeidende Patch bricht bei unerwartetem Quellstand ab:

```bash
cd "$HOME/ipod-rescue-build/libimobiledevice"
python3 - <<'PY'
from pathlib import Path

header = Path("common/utils.h")
source = Path("common/utils.c")
h, c = header.read_text(), source.read_text()

old = (
    "enum plist_format_t {\n"
    "\tPLIST_FORMAT_XML,\n"
    "\tPLIST_FORMAT_BINARY\n"
    "};"
)
if h.count(old) != 1 or h.count("enum plist_format_t") != 2 \
        or c.count("enum plist_format_t") != 1:
    raise SystemExit("ABBRUCH: Unerwarteter Quellcode oder Patch bereits angewendet")

header.write_text(h.replace(old, "").replace("enum plist_format_t", "plist_format_t"))
source.write_text(c.replace("enum plist_format_t", "plist_format_t"))
print("libplist-Kompatibilitätspatch angewendet")
PY
```

Die neuen Enum-Konstanten sind nicht identisch mit der alten numerischen Definition; die betroffenen Stellen verwenden hier jedoch die symbolischen Kennungen. Keine pauschalen C-Datei-Massenänderungen vornehmen.

### 5.3 GnuTLS-Protokoll für iPhone OS 1.x auf SSLv3 stellen

```bash
python3 - <<'PY'
from pathlib import Path

path = Path("src/idevice.c")
src = path.read_text()
old = "NONE:+VERS-TLS1.0:+ANON-DH:+RSA:+AES-128-CBC:+AES-256-CBC:+SHA1:+MD5:+COMP-NULL"
new = old.replace("VERS-TLS1.0", "VERS-SSL3.0")
if src.count(old) != 1:
    raise SystemExit("ABBRUCH: Erwartete GnuTLS-Prioritätenliste nicht eindeutig gefunden")
path.write_text(src.replace(old, new, 1))
print("SSLv3-Patch angewendet")
PY

git diff --check
git diff -- common/utils.h common/utils.c src/idevice.c
```

**Keine allgemeine Upstream-Korrektur:** Dieser Patch ist speziell für das getestete iPhone OS 1.x-Gerät. Er darf nicht unbesehen für moderne iOS-Geräte verwendet werden.

### 5.4 Mit GnuTLS statt OpenSSL kompilieren

```bash
./autogen.sh \
  --prefix="$HOME/ipod-rescue-gnutls" \
  --disable-openssl \
  --enable-debug

# Erwartet: "SSL support backend .....: GnuTLS"
make -j2
make install
```

Bei einem bestehenden konfigurierten Checkout genügte nach dem SSLv3-Quellcodepatch tatsächlich `make -j2 && make install`. Die alten Schalter `--with-gnutls` und `--without-openssl` sind **für den Tag 1.3.0 falsch**.

## 6. Prüfen, dass beide selbst kompilierten Bibliotheken geladen werden

```bash
export LIMD_LIB="$HOME/ipod-rescue-gnutls/lib"
export SSL3_LIB="$HOME/ipod-rescue-ssl3/lib"

LD_LIBRARY_PATH="$SSL3_LIB:$LIMD_LIB" \
  ldd /usr/bin/ideviceinfo | grep -E 'libimobiledevice|libgnutls'
```

**Beide Pfade müssen auf die Home-Verzeichnisse zeigen:**

```text
libimobiledevice-1.0.so.6 => .../ipod-rescue-gnutls/lib/libimobiledevice-1.0.so.6
libgnutls.so.30 => .../ipod-rescue-ssl3/lib/libgnutls.so.30
```

## 7. Nachweis des funktionierenden Lockdown-SSLv3-Handshakes

Der USB-Durchgriff über `usbipd` und ein funktionierender `usbmuxd` werden vorausgesetzt.

```bash
env LD_LIBRARY_PATH="$SSL3_LIB:$LIMD_LIB" \
    GNUTLS_SYSTEM_PRIORITY_FILE="$HOME/ipod-gnutls-isolated.conf" \
    ideviceinfo --simple --key DeviceClass

# Normaler SSL-Handshake; Ausgabe auf die relevanten Gerätefelder reduzieren:
set -o pipefail
env LD_LIBRARY_PATH="$SSL3_LIB:$LIMD_LIB" \
    GNUTLS_SYSTEM_PRIORITY_FILE="$HOME/ipod-gnutls-isolated.conf" \
    ideviceinfo | grep -E '^(ProductType|ProductVersion|BuildVersion|ModelNumber):'
echo "Handshake Exit-Code: $?"
```

Die verifizierte erfolgreiche Sitzung meldete `iPod1,1`, `1.1.5`, `4B1`, `MA623` und **Exit-Code 0**. Der einfache Modus allein hätte den verschlüsselten Handshake nicht bewiesen.

## 8. Read-only AFC-Mount und anschließende Datensicherung

**Nur nach erfolgreichem Handshake**, mit `ifuse` 1.1.4 (nicht 1.2.0) und weiterhin denselben Bibliotheken:

```bash
MNT="$HOME/ipod-media"
mkdir -p "$MNT"
if mountpoint -q "$MNT"; then
  echo "ABBRUCH: Mountpoint bereits belegt" >&2
else
  env LD_LIBRARY_PATH="$SSL3_LIB:$LIMD_LIB" \
      GNUTLS_SYSTEM_PRIORITY_FILE="$HOME/ipod-gnutls-isolated.conf" \
      ifuse -o ro "$MNT"
fi

findmnt --mountpoint "$MNT" -o TARGET,SOURCE,FSTYPE,OPTIONS
```

**Stopp**, sofern `findmnt` keinen FUSE-Mount mit `ro` ausweist. Ein read-only FUSE-Mount verhindert Schreibzugriffe über diese Dateisystemschnittstelle; er beweist keine absolute Schreibfreiheit sämtlicher Geräteprotokolle. Der anschließende nachweislich verwendete rsync-/iTunesDB-/Python-Ablauf steht in der [End-to-End-Anleitung](END-TO-END-RECOVERY.md). Der Rohbestand einschließlich iTunes-Datenbanken muss vor Änderungen der Dateinamen oder Metadaten gesichert werden.

## 9. Sicherheits- und Reproduzierbarkeitshinweise

- SSLv3 ist kryptografisch gebrochen und **nur** für die lokale, zeitlich begrenzte USB-Datenrettung vertretbar. Keinen netzwerkfähigen Dienst damit anbieten und keine globalen TLS-Sicherheitsrichtlinien herabsetzen.
- **Nie** iPod synchronisieren, zurücksetzen, aktualisieren, jailbreaken oder Daten auf dem Gerät verändern, bevor die Sicherung vollständig geprüft wurde.
- Die Pairing-Datei unter `/var/lib/lockdown` kann private Host-/Root-Schlüssel enthalten. Nur lokal und restriktiv gesichert halten; nicht hochladen.
- `ideviceinfo --debug` und ungekürzte `ideviceinfo`-Ausgaben können Zertifikate, Gerätekennung und Seriennummer ausgeben. Nicht in Issues/Commits posten.
- Das beschriebene Verfahren wurde in einer einzigen konkreten WSL-Konfiguration getestet. Builds mit anderen libplist-/GnuTLS-/libimobiledevice-Versionen sind nicht automatisch gleichwertig.
- Der Handshake und laufender Export sind **keine** Bestätigung der Datenintegrität. Nach Abschluss Anzahl, Größen, SHA-256-Prüfungen sowie abspielbare Stichproben prüfen; ein zweites Backup anlegen.

## Upstream-Nachweise

- [libimobiledevice, Quellcode-Tag 1.3.0](https://github.com/libimobiledevice/libimobiledevice/tree/1.3.0)
- [Historischer libimobiledevice-Fix für iOS 1 / SSLv3, Dezember 2023](https://cgit.libimobiledevice.org/libimobiledevice.git/log/src?id=421b6e5264ae0088f90fc58f2c209fbb43e30a00&showmsg=1)
- [libplist-Release 2.3.0 (Formatkonstanten / API-Änderungen)](https://github.com/libimobiledevice/libplist/releases/tag/2.3.0)
- [GnuTLS-Projekt](https://www.gnutls.org/)
- [ifuse](https://github.com/libimobiledevice/ifuse)
