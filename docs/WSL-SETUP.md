# Schritt 2 — WSL2, Ubuntu und USB für den alten iPod einrichten

[← Übersicht](../README.md) · [Weiter: SSLv3 für iPhone OS 1.x](IPOD1-SSLV3-RESCUE.md) · [Extraktion](END-TO-END-RECOVERY.md#2-rohbackup-und-pruefsummen)

**Getestete Kombination:** Windows 11, WSL2 mit Ubuntu 24.04 LTS, `usbipd-win` 5.3, `usbmuxd` 1.1.1, Ubuntu-`ifuse` 1.1.4, iPod touch 1 / iPhone OS 1.1.5. Diese Anleitung ist nicht automatisch für andere Betriebssystemstände oder Geräte geeignet.

**Schutzregel:** iPod weder synchronisieren noch zurücksetzen, aktualisieren, jailbreaken oder darauf Dateien verändern. Vor dem ersten Zugriff genug Akkuladung sicherstellen.

## 1. Windows PowerShell (als Administrator)

```powershell
wsl --install -d Ubuntu-24.04
```

Falls Windows einen Neustart verlangt, diesen durchführen, Ubuntu starten und Benutzerkonto einrichten. Bereits installierte WSL-Umgebungen prüfen:

```powershell
wsl --update
wsl --list --verbose
```

USB-Passthrough für WSL installieren:

```powershell
winget install --interactive --exact dorssel.usbipd-win
usbipd --version
```

**Wichtig:** Normale USB-Geräte werden nicht automatisch an WSL weitergereicht.

## 2. Ubuntu (WSL-Terminal)

```bash
sudo apt-get update
sudo apt-get install -y git rsync python3-mutagen ffmpeg
git clone https://github.com/K-Cosmo/iPod-Audio-Rescue.git "$HOME/iPod-Audio-Rescue"
cd "$HOME/iPod-Audio-Rescue"
bash scripts/install-requirements.sh
```

Der Installer prüft, ob Ubuntu 24.04 unter WSL verwendet wird, installiert die Werkzeuge `libimobiledevice-utils`, `ifuse`, `usbmuxd`, `usbutils`, `fuse` und blockiert die als problematisch bekannte **ifuse-Version 1.2.0**. Bei einem Fehler nicht blind weiterarbeiten. Das Installationsskript greift noch **nicht** auf den iPod zu.

Python/FFmpeg prüfen:

```bash
python3 --version
python3 -c "import mutagen; print('mutagen gefunden')"
ffmpeg -version | head -1
ffmpeg -hide_banner -encoders | grep libmp3lame
```

## 3. USB-Gerät identifizieren und durchreichen

iPod an Windows anschließen. In einer **PowerShell als Administrator**:

```powershell
usbipd list
```

In der Ausgabe die **tatsächliche BUSID** des Apple-Geräts ablesen; niemals eine Beispiel-ID ungeprüft verwenden.

```powershell
usbipd bind --busid X-Y
usbipd attach --wsl --busid X-Y
```

`X-Y` in beiden Zeilen durch die reale BUSID ersetzen. Ubuntu sollte dabei bereits gestartet sein.

Im **Ubuntu-Terminal**:

```bash
lsusb
idevice_id -l
ideviceinfo --simple --key DeviceClass
```

Beim alten **iPhone OS 1.1.5** kann eine einfache Geräteabfrage funktionieren, während eine verschlüsselte Lockdown-Sitzung mit `SSL error (-5)` scheitert. Das ist **kein Grund**, die Firmware zu verändern. Weiter mit [isoliertem GnuTLS-/libimobiledevice-SSLv3-Build](IPOD1-SSLV3-RESCUE.md).

Bei anderen, moderneren iPods zunächst prüfen, ob der reguläre `ideviceinfo`-Weg bereits funktioniert; den SSLv3-Build **nicht pauschal übernehmen**.

## 4. Read-only Mount nach bestätigter Verbindung

Für das hier erprobte iPod1,1/OS-1.1.5-Gerät zunächst **die komplette SSLv3-Anleitung** abarbeiten. Danach in Ubuntu:

```bash
export LIMD_LIB="$HOME/ipod-rescue-gnutls/lib"
export SSL3_LIB="$HOME/ipod-rescue-ssl3/lib"
export GNUTLS_SYSTEM_PRIORITY_FILE="$HOME/ipod-gnutls-isolated.conf"
export LD_LIBRARY_PATH="$SSL3_LIB:$LIMD_LIB"

MNT="$HOME/ipod-media"
mkdir -p "$MNT"
mountpoint -q "$MNT" && { echo "ABBRUCH: bereits gemountet" >&2; exit 1; }

ifuse -o ro "$MNT"
findmnt --mountpoint "$MNT" -o TARGET,SOURCE,FSTYPE,OPTIONS
```

Das Ergebnis muss einen tatsächlich vorhandenen **FUSE-Mount mit `ro`** zeigen. Dann:

```bash
findmnt -n -o OPTIONS --mountpoint "$MNT" | grep -Eq '(^|,)ro(,|$)' \
  || { echo "ABBRUCH: Kein read-only-Mount" >&2; exit 1; }
test -f "$MNT/iTunes_Control/iTunes/iTunesDB" \
  || { echo "ABBRUCH: iTunesDB nicht gefunden, Pfade prüfen" >&2; exit 1; }
```

Falls die Datenbank bei deinem Modell anders liegt, **nicht** blind einen anderen Verzeichnisnamen erfinden; Inventar prüfen. `ro` schränkt FUSE-Schreibzugriffe ein, beweist aber nicht, dass das Gerät intern niemals Protokollstatus verändert.

**Weiter:** [Vollständiges Originalbackup und SHA-256-Prüfung](END-TO-END-RECOVERY.md#2-rohbackup-und-pruefsummen).

## 5. Nach gesichertem Backup trennen

Erst nach Abschluss des Auslesens und Verifizieren der Rohkopie:

```bash
fusermount -u "$HOME/ipod-media"
```

In Windows PowerShell:

```powershell
usbipd detach --busid X-Y
```

`X-Y` wiederum durch die zuvor ermittelte tatsächliche BUSID ersetzen.

## Quellen und Sicherheit

- [Microsoft: USB-Geräte in WSL verbinden](https://learn.microsoft.com/en-us/windows/wsl/connect-usb)
- [usbipd-win](https://github.com/dorssel/usbipd-win)
- [libimobiledevice](https://github.com/libimobiledevice/libimobiledevice)
- [ifuse](https://github.com/libimobiledevice/ifuse)
- [Spezifische SSLv3-Anleitung und Isolationshinweise](IPOD1-SSLV3-RESCUE.md)

Die im Rettungsfall verwendete SSLv3-Konfiguration ist **absichtlich veraltet und unsicher**. Sie darf nicht systemweit oder für Netzwerkdienste aktiviert werden.
