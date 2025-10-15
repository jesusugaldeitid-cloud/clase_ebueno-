# -*- coding: utf-8 -*-
"""
PRACTICA_2.py

Requisitos:
  pip install pyserial textfsm

Funciones:
  - Leer 'show ip interface brief' por consola (o TXT), parsear (TextFSM + fallback),
    imprimir tabla y guardar CSV (Data_P2.csv) SIN duplicados (sobrescribe).
  - Fallback: si no hay consola ni TXT, mostrar Data_P2.csv / Data.csv / show_ip_int_brief.csv.
  - Modo manual para mandar comandos; al enviar 'show ip int brief' (o alias) lo parsea y
    SOBRESCRIBE el CSV (snapshot limpio).
  - Comando ':ip' en modo manual para configurar IP v4 en una interfaz.
  - HOSTNAME: se detecta y se guarda como primera columna del CSV/tabla.
"""

import sys, io, os, csv, time, re
import textfsm

# Forzar UTF-8 en Windows (bordes)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ======== Config archivos ========
OUT_CSV = "Data_P2.csv"                 # CSV de salida principal
TXT_FALLBACK = "show_ip_int_brief.txt"  # TXT opcional con salida del comando

# ======== Template TextFSM estable ========
TPL = r"""
# Cisco IOS - show ip interface brief
Value Required INTERFACE (\S+)
Value Required IPADDR (\S+)
Value Required OK (\S+)
Value Required METHOD (\S+)
Value Required STATUS (administratively down|up|down|deleted|reset|testing|unknown)
Value Required PROTOCOL (up|down)

Start
  ^\s*Interface\s+IP-Address\s+OK\?\s+Method\s+Status\s+Protocol\s*$ -> Continue
  ^${INTERFACE}\s+${IPADDR}\s+${OK}\s+${METHOD}\s+${STATUS}\s+${PROTOCOL}\s*$ -> Record
"""

# ======== Fallback regex (por si TextFSM falla) ========
_HDR_RE = re.compile(r"^\s*Interface\s+IP-Address\s+OK\?\s+Method\s+Status\s+Protocol\s*$", re.I)
_ROW_RE = re.compile(
    r"^(?P<INTERFACE>\S+)\s+"
    r"(?P<IPADDR>\S+)\s+"
    r"(?P<OK>\S+)\s+"
    r"(?P<METHOD>\S+)\s+"
    r"(?P<STATUS>administratively\ down|up|down|deleted|reset|testing|unknown)\s+"
    r"(?P<PROTOCOL>up|down)\s*$",
    re.I
)

# ======== Utilidades de tabla ========
def print_table(headers, rows):
    w = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            w[i] = max(w[i], len(str(c)))

    def line(l, m, r, fill='─'):
        return l + m.join(fill * (x + 2) for x in w) + r

    def row(vals):
        return '│' + '│'.join(f' {str(v).ljust(w[i])} ' for i, v in enumerate(vals)) + '│'

    print(line('┌', '┬', '┐'))
    print(row(headers))
    print(line('├', '┼', '┤'))
    for r in rows:
        print(row(r))
    print(line('└', '┴', '┘'))

# ======== CSV helpers ========
def save_csv(headers, rows, path=OUT_CSV, append=False):
    """Guarda CSV. Si append=False (por defecto), sobrescribe (snapshot limpio)."""
    exists = os.path.exists(path)
    mode = "a" if append and exists else "w"
    with open(path, mode, newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if mode == "w" or (mode == "a" and not exists):
            w.writerow(headers)
        w.writerows(rows)
    return os.path.abspath(path)

def read_csv_any(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        headers = [h.strip() for h in next(r, [])]
        rows = [[c.strip() for c in row] for row in r]
    return headers, rows

# ======== Parseadores ========
def parse_textfsm(text):
    tpl = io.StringIO(TPL.replace("\r", ""))   # fuerza LF limpio
    fsm = textfsm.TextFSM(tpl)
    rows = fsm.ParseText(text or "")
    return list(fsm.header), rows

def parse_fallback_regex(text):
    headers = ["INTERFACE","IPADDR","OK","METHOD","STATUS","PROTOCOL"]
    rows = []
    seen_hdr = False
    for line in (text or "").splitlines():
        line = line.rstrip()
        if not seen_hdr:
            if _HDR_RE.match(line):
                seen_hdr = True
            continue
        m = _ROW_RE.match(line)
        if m:
            d = m.groupdict()
            rows.append([d["INTERFACE"], d["IPADDR"], d["OK"], d["METHOD"], d["STATUS"], d["PROTOCOL"]])
        else:
            if line.strip().endswith("#"):   # llegó el prompt
                break
    return headers, rows

# ======== Hostname helpers ========
_HOST_PROMPT_RE = re.compile(r"^\s*([A-Za-z0-9._\-]+)\s*[>#]\s*$", re.M)

def infer_hostname_from_text(text: str):
    """Busca el hostname en el prompt (líneas que terminan con # o >)."""
    if not text:
        return None
    for line in reversed(text.splitlines()):
        m = _HOST_PROMPT_RE.match(line)
        if m:
            return m.group(1)
    return None

def add_hostname_column(headers, rows, hostname):
    """Inserta la columna HOSTNAME al inicio si no existe."""
    hn = hostname or "UNKNOWN"
    if headers and (headers[0] != "HOSTNAME"):
        headers.insert(0, "HOSTNAME")
        for r in rows:
            r.insert(0, hn)
    else:
        # si ya existiera, rellena vacíos
        if "HOSTNAME" in headers:
            idx = headers.index("HOSTNAME")
            for r in rows:
                if len(r) <= idx:
                    r.extend([""] * (idx + 1 - len(r)))
                if not r[idx]:
                    r[idx] = hn
        else:
            headers.insert(0, "HOSTNAME")
            for r in rows:
                r.insert(0, hn)
    return headers, rows

def fetch_hostname_via_serial(ser):
    """Pregunta al equipo por el hostname (show run | include ^hostname), con fallback a 'show version'."""
    try:
        out = send_and_read(ser, "show running-config | include ^hostname", 0.8)
        m = re.search(r"^hostname\s+(\S+)", out, re.M)
        if m:
            return m.group(1)
        out2 = send_and_read(ser, "show version | include uptime", 0.8)
        m2 = re.search(r"^(\S+)\s+uptime is", out2, re.M)
        if m2:
            return m2.group(1)
    except Exception:
        pass
    return None

# ======== Puertos COM ========
def list_ports():
    try:
        import serial.tools.list_ports as lp
    except Exception:
        return []
    return list(lp.comports())

def choose_port_interactive(default=None):
    ports = list_ports()
    if not ports:
        print("\nNo hay puertos COM detectados.")
        return None
    print("\nPuertos detectados:")
    for i, p in enumerate(ports, 1):
        print(f"  {i}) {p.device} - {p.description}")
    if default:
        print(f"Enter = usar por defecto: {default}")
    sel = input("Elige número o escribe COMx manualmente: ").strip()
    if sel == "" and default:
        return default
    if sel.upper().startswith("COM"):
        return sel.upper()
    try:
        idx = int(sel) - 1
        if 0 <= idx < len(ports):
            return ports[idx].device
    except:
        pass
    return None

def detect_port():
    """Devuelve un puerto COM probable o None (preferencia USB-Serial)."""
    ports = list_ports()
    prefer = ("usb","ftdi","prolific","ch340","uart","silicon","manhattan")
    for p in ports:
        blob = f"{p.description} {p.manufacturer or ''} {p.hwid or ''}".lower()
        if any(k in blob for k in prefer):
            return p.device
    return ports[0].device if ports else None

# ======== Inventario (Data.csv) ========
def read_inventory_first_row(path="Data.csv"):
    """
    Lee la primera fila útil de Data.csv (inventario) y devuelve dict con
    'Port' y 'Baud' si existen. Si no existe o no trae esas columnas, regresa {}.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                return { (k or "").strip(): (v or "").strip() for k, v in row.items() }
    except Exception:
        pass
    return {}

# ======== Serial helpers ========
def try_serial():
    try:
        import serial, serial.tools.list_ports
    except ImportError:
        return None

    inv = read_inventory_first_row("Data.csv")
    port = (inv.get("Port") or inv.get("PORT") or inv.get("port") or "").strip()
    baud = (inv.get("Baud") or inv.get("BAUD") or inv.get("baud") or "").strip()
    try:
        baudrate = int(baud) if baud else 9600
    except:
        baudrate = 9600

    if not port or port.lower() == "auto":
        port = detect_port()

    if not port:
        port = choose_port_interactive()
    if not port:
        return None

    try:
        import serial
        with serial.Serial(port=port, baudrate=baudrate, timeout=1) as ser:
            time.sleep(1.8)
            send_and_read(ser, "terminal length 0", 0.4)
            out = send_and_read(ser, "show ip interface brief", 2.0)
            host = fetch_hostname_via_serial(ser) or infer_hostname_from_text(out)
            if host:
                return f"__HOSTNAME__={host}\n<<<SEP>>>\n{out}" if out.strip() else None
            else:
                return out if out.strip() else None
    except PermissionError:
        print(f"\n⚠ Acceso denegado al puerto. Quizá está en uso. Elige otro:")
        newp = choose_port_interactive()
        if not newp:
            return None
        try:
            with serial.Serial(port=newp, baudrate=baudrate, timeout=1) as ser:
                time.sleep(1.8)
                send_and_read(ser, "terminal length 0", 0.4)
                out = send_and_read(ser, "show ip interface brief", 2.0)
                host = fetch_hostname_via_serial(ser) or infer_hostname_from_text(out)
                if host:
                    return f"__HOSTNAME__={host}\n<<<SEP>>>\n{out}" if out.strip() else None
                else:
                    return out if out.strip() else None
        except Exception as e:
            print("No se pudo abrir el nuevo puerto:", e)
            return None
    except Exception:
        return None

def try_file(path=TXT_FALLBACK):
    return open(path, "r", encoding="utf-8", errors="ignore").read() if os.path.exists(path) else None

# ======== Modo manual ========
ALIASES_SHOW = {
    "show ip interface brief",
    "show ip int brief",
    "sh ip interface brief",
    "sh ip int br",
    "sh ip int bri",
    "sho ip int br",
}

def send_and_read(ser, cmd, wait=1.0):
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait)
    data = ser.read(ser.in_waiting or 1).decode(errors="ignore")
    time.sleep(0.3)
    data += ser.read(ser.in_waiting or 1).decode(errors="ignore")
    return data

def _configure_ip_on_open_serial(ser, iface, ip, mask, save=False):
    send_and_read(ser, "", 0.2)
    send_and_read(ser, "enable", 0.2)                  # si pide pass, tecleas en el equipo
    send_and_read(ser, "terminal length 0", 0.2)
    send_and_read(ser, "configure terminal", 0.2)
    send_and_read(ser, f"interface {iface}", 0.2)
    send_and_read(ser, f"ip address {ip} {mask}", 0.2)
    send_and_read(ser, "no shutdown", 0.3)
    send_and_read(ser, "end", 0.2)
    if save:
        send_and_read(ser, "write memory", 0.8)
    # verificación
    out = send_and_read(ser, "show ip interface brief", 2.0)
    try:
        headers, rows = parse_textfsm(out)
    except Exception:
        headers, rows = parse_fallback_regex(out)

    host = fetch_hostname_via_serial(ser) or infer_hostname_from_text(out)
    headers, rows = add_hostname_column(headers, rows, host)

    if rows:
        print("\n📋 Estado actual (post-config):\n")
        print_table(headers, rows)
        save_csv(headers, rows, OUT_CSV, append=False)  # snapshot (NO duplica)
        print(f"\n💾 CSV actualizado: {os.path.abspath(OUT_CSV)}")
    else:
        print(out)

def manual_commands_mode():
    """Modo interactivo: enviar comandos, parsear 'show ip int brief' y guardar CSV; comando ':ip' para configurar IP."""
    try:
        import serial
    except Exception:
        print("\n(No tienes pyserial instalado para modo manual)")
        return

    inv = read_inventory_first_row("Data.csv")
    port = (inv.get("Port") or "").strip() if inv else ""
    baud = (inv.get("Baud") or "").strip() if inv else ""
    try:
        baudrate = int(baud) if baud else 9600
    except:
        baudrate = 9600

    if not port or port.lower() == "auto":
        port = detect_port()
    if not port:
        port = choose_port_interactive()

    while True:
        if not port:
            print("\nNo hay puerto seleccionado.")
            port = choose_port_interactive()
            if not port:
                return

        try:
            with serial.Serial(port=port, baudrate=baudrate, timeout=1) as ser:
                time.sleep(1.5)
                send_and_read(ser, "terminal length 0", 0.3)
                print(f"\n🔗 Modo manual en {port} (baud {baudrate}). Escribe ':salir' para terminar.")
                print("   • Envía 'show ip interface brief' (o alias) para parsear y GUARDAR (sobrescribe) Data_P2.csv.")
                print("   • Comando especial ':ip' para configurar IP v4 en una interfaz.\n")
                while True:
                    cmd = input("> ").strip()
                    if cmd == "" or cmd.lower() == ":salir":
                        return
                    if cmd.lower() == ":ip":
                        iface = input("Interfaz (ej. GigabitEthernet0/1): ").strip()
                        ip    = input("IP (ej. 192.168.1.10): ").strip()
                        mask  = input("Máscara (ej. 255.255.255.0): ").strip()
                        save  = input("¿guardar config (write mem)? (s/n): ").strip().lower() == "s"
                        try:
                            _configure_ip_on_open_serial(ser, iface, ip, mask, save)
                        except Exception as e:
                            print("Error configurando IP:", e)
                        continue

                    out = send_and_read(ser, cmd, wait=2.0)
                    norm = " ".join(cmd.lower().split())
                    if norm in ALIASES_SHOW:
                        try:
                            headers, rows = parse_textfsm(out)
                        except Exception as e:
                            print("⚠ TextFSM falló, fallback regex:", e)
                            headers, rows = parse_fallback_regex(out)

                        host = fetch_hostname_via_serial(ser) or infer_hostname_from_text(out)
                        headers, rows = add_hostname_column(headers, rows, host)

                        if rows:
                            print("\n📊 Resultado (TextFSM/regex):\n")
                            print_table(headers, rows)
                            path = save_csv(headers, rows, OUT_CSV, append=False)  # SOBRESCRIBE snapshot
                            print(f"\n💾 CSV actualizado: {path}\n")
                        else:
                            print("\n(Sin filas parseadas; salida cruda)\n")
                            print(out)
                    else:
                        print("\n--- Salida ---\n")
                        print(out)
                        print("\n--------------\n")
        except PermissionError:
            print(f"\n⚠ {port} en uso / acceso denegado. Elige otro.")
            port = choose_port_interactive()
            continue
        except Exception as e:
            print(f"\nNo se pudo abrir el puerto {port}: {e}")
            port = choose_port_interactive()
            continue

# ======== Mostrar CSV si existe ========
def mostrar_csv_si_existe():
    for p in (OUT_CSV, "Data.csv", "show_ip_int_brief.csv"):
        if os.path.exists(p):
            headers, rows = read_csv_any(p)
            print(f"\n📊 Desde {p}:\n")
            print_table(headers, rows)
            return True
    return False

# ======== Main ========
def main():
    # 1) serial -> 2) TXT -> 3) CSV
    raw = try_serial() or try_file()
    hostname = None
    text = raw
    if raw and isinstance(raw, str) and raw.startswith("__HOSTNAME__="):
        parts = raw.split("\n<<<SEP>>>\n", 1)
        hostname = parts[0].split("=", 1)[1].strip()
        text = parts[1] if len(parts) > 1 else ""

    if not text:
        if mostrar_csv_si_existe():
            ans = input("\n¿Entrar a modo de comandos manuales? (s/n): ").strip().lower()
            if ans == "s":
                manual_commands_mode()
            return
        print("⚠ No pude leer por serial ni encontré 'show_ip_int_brief.txt'.")
        print("   Conecta el cable consola, crea ese TXT con la salida, o deja un CSV (Data_P2.csv / Data.csv).")
        return

    # Parseo robusto
    try:
        headers, rows = parse_textfsm(text)
    except Exception as e:
        print("⚠ TextFSM falló, usando fallback regex. Detalle:", e)
        headers, rows = parse_fallback_regex(text)

    if not rows:
        print("⚠ No se obtuvieron filas. Salida cruda:\n")
        print(text)
        return

    # Hostname (si venimos de TXT u otra fuente)
    if hostname is None:
        hostname = infer_hostname_from_text(text)
    headers, rows = add_hostname_column(headers, rows, hostname)

    print("\n📊 Resultado:\n")
    print_table(headers, rows)
    out_csv = save_csv(headers, rows, OUT_CSV, append=False)  # sobrescribe
    print(f"\n💾 CSV guardado: {out_csv}")

    # Modo manual opcional
    ans = input("\n¿Entrar a modo de comandos manuales? (s/n): ").strip().lower()
    if ans == "s":
        manual_commands_mode()

if __name__ == "__main__":
    main()
