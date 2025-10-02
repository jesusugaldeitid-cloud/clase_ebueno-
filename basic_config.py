# -*- coding: utf-8 -*-
"""
Configura routers Cisco desde CSV.
- Si cambias Device en el CSV (p.ej. Router1 -> R_<SERIE>), el username se sincroniza con ese Device.
- Autodetecta COM si Port=auto.
- Valida la Serie con 'show inventory' antes de aplicar.
- Maneja prompt 'Password:' al hacer 'enable'.
- CSV debe estar en UTF-8.

Requisitos:
  pip install pyserial pandas
"""

import serial
import time
import pandas as pd
import os
import re
import glob

# ---------- Parámetros ----------
CARPETA_CSV = r"C:\Users\jesus\OneDrive\Documentos\CODIGOS\clase_ebueno"
COLUMNAS_REQUERIDAS = {"Serie", "Port", "Device", "User", "Password", "Ip-domain"}
COLUMNA_BAUD_OPCIONAL = "Baud"
BAUD_POR_DEFECTO = 9600

# Sincronizar el User con el Device cuando cambias el nombre
SYNC_USER_WITH_DEVICE = True          # True = User se volverá igual a Device
SYNC_ONLY_IF_R_PREFIX = True          # True = solo sincroniza si Device empieza con "R_"

# (Opcional) activar prints de depuración
DEBUG = True

# Opcional: detectar puertos por sistema
try:
    from serial.tools import list_ports
except Exception:
    list_ports = None


# ---------- Utilidades ----------
def limpiar_consola():
    if not DEBUG:
        os.system("cls" if os.name == "nt" else "clear")


def leer_hasta_prompt(conexion, timeout=3.0):
    """
    Lee del puerto hasta detectar un prompt típico (> o #) o agotar timeout.
    """
    fin = time.time() + timeout
    buf = ""
    while time.time() < fin:
        time.sleep(0.2)
        chunk = conexion.read(conexion.in_waiting or 0).decode(errors="ignore")
        if chunk:
            buf += chunk
            if re.search(r"[>#]\s*$", buf):
                break
    return buf


def ejecutar_comando(conexion, instruccion, pausa=1.0):
    """
    Envía un comando con CRLF, espera 'pausa' y lee lo disponible del buffer.
    Luego intenta leer un poco más por si aparece el prompt.
    """
    try:
        _ = conexion.read(conexion.in_waiting or 0)  # drenar buffer previo
        conexion.write((instruccion + "\r\n").encode())
        time.sleep(pausa)
        salida = conexion.read(conexion.in_waiting or 0).decode(errors="ignore")
        salida += leer_hasta_prompt(conexion, timeout=1.2)
        if DEBUG:
            print(f"[DEBUG enviar] {instruccion!r}\n[DEBUG resp]\n{salida}\n---")
        return salida
    except Exception as e:
        msg = f"[ERROR al enviar '{instruccion}']: {e}"
        print(msg)
        return msg


def ir_a_enable(conexion, clave_enable=None):
    """
    Entra a modo privilegiado.
    Si el router pide 'Password:', envía la clave (si se proporcionó).
    """
    _ = conexion.read(conexion.in_waiting or 0)
    conexion.write(b"enable\r\n")
    time.sleep(0.4)

    salida = conexion.read(conexion.in_waiting or 0).decode(errors="ignore")

    # Si pide password
    if re.search(r"[Pp]assword", salida):
        if DEBUG:
            print("[DEBUG] Router pide contraseña de enable")
        if clave_enable:
            conexion.write((clave_enable + "\r\n").encode())
            time.sleep(0.5)
            salida += conexion.read(conexion.in_waiting or 0).decode(errors="ignore")
        else:
            # Enviar Enter vacío por si no hay clave configurada
            conexion.write(b"\r\n")
            time.sleep(0.4)
            salida += conexion.read(conexion.in_waiting or 0).decode(errors="ignore")

    salida += leer_hasta_prompt(conexion, timeout=3.0)
    if DEBUG:
        print(f"[DEBUG enable] {salida}")
    return salida


def buscar_serial(canal_serial):
    """
    Intenta obtener No. de serie vía 'show inventory'.
    Soporta variantes 'SN:', 'Serial Number' o 'S/N'.
    """
    ejecutar_comando(canal_serial, "terminal length 0", pausa=0.3)
    resp = ejecutar_comando(canal_serial, "show inventory", pausa=2.8)

    m = re.search(r"SN:\s*([A-Z0-9]+)", resp)
    if m:
        return m.group(1).strip()

    m = re.search(r"(Serial Number|S/N)\s*[:#]?\s*([A-Z0-9]+)", resp, flags=re.IGNORECASE)
    if m:
        return m.group(2).strip()

    return None


def puertos_disponibles():
    encontrados = []
    if list_ports:
        try:
            encontrados = [p.device for p in list_ports.comports()]
        except Exception:
            encontrados = []
    if not encontrados:
        # Fallback típico
        encontrados = [f"COM{i}" for i in range(3, 21)]
    if DEBUG:
        print(f"[DEBUG] Puertos candidatos: {encontrados}")
    return encontrados


def probar_puerto(puerto, baudrate=BAUD_POR_DEFECTO, timeout=1.0):
    """
    Abre el puerto, espera, intenta 'show inventory' y regresa (canal, serie) si tiene respuesta.
    Cierra y devuelve (None, None) si falla o no es Cisco.
    """
    try:
        canal = serial.Serial(puerto, baudrate=baudrate, timeout=timeout)
        time.sleep(2)  # estabilizar

        # Pequeña lectura inicial para limpiar banner
        _ = canal.read(canal.in_waiting or 0)

        # Enter para obtener prompt
        canal.write(b"\r\n")
        time.sleep(0.3)
        _ = canal.read(canal.in_waiting or 0)

        serie = buscar_serial(canal)
        if serie:
            if DEBUG:
                print(f"[DEBUG] {puerto}: Cisco detectado, serie={serie}")
            return canal, serie

        # Si no devolvió serie, igual se pudo abrir pero no respondió como Cisco
        canal.close()
        if DEBUG:
            print(f"[DEBUG] {puerto}: abierto pero sin 'show inventory' válido")
        return None, None
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] {puerto}: no se pudo abrir ({e})")
        return None, None


def autodetectar_conexion(baudrate=BAUD_POR_DEFECTO):
    if DEBUG:
        print(f"[DEBUG] Autodetección con baud={baudrate}")
    for p in puertos_disponibles():
        if DEBUG:
            print(f"[DEBUG] Probando {p}…")
        canal, serie = probar_puerto(p, baudrate=baudrate)
        if canal and serie:
            if DEBUG:
                print(f"[DEBUG] ¡Encontrado! Puerto={p}, Serie={serie}")
            return canal, p, serie
    if DEBUG:
        print("[DEBUG] No se encontró equipo Cisco en puertos probados.")
    return None, None, None


def aplicar_config(puerto, hostname, usuario, clave, dominio, serie_csv, baudrate=BAUD_POR_DEFECTO):
    """
    Si puerto == 'auto', intenta autodetectar. Valida serie antes de configurar.
    Aplica hostname, usuario, domain, SSH y guarda.
    """
    canal = None
    puerto_real = puerto
    try:
        # 1) Autodetectar o abrir COM específico
        if str(puerto).strip().lower() == "auto":
            print("🔎 Buscando puerto automáticamente...")
            canal, puerto_real, serie_detectada = autodetectar_conexion(baudrate=baudrate)
            if not canal:
                print("❌ No se encontró ningún puerto válido.")
                return False
        else:
            canal = serial.Serial(puerto, baudrate=baudrate, timeout=1)
            puerto_real = puerto
            time.sleep(2)
            serie_detectada = buscar_serial(canal)

        print(f"\n🔗 Conectado en {puerto_real} (baud {baudrate}). Serie detectada: {serie_detectada or 'N/A'}")

        # 2) Validaciones de serie
        if not serie_detectada:
            print("⚠ No se pudo leer la serie con 'show inventory'. Saltando configuración.")
            canal.close()
            return False

        if str(serie_detectada).strip().upper() != str(serie_csv).strip().upper():
            print(f"⚠ Serie no coincide. Equipo={serie_detectada} | CSV={serie_csv}. Saltando configuración.")
            canal.close()
            return False

        # 3) Configuración (modo privilegiado + conf t)
        ir_a_enable(canal, clave_enable=clave if clave else None)
        ejecutar_comando(canal, "terminal length 0", pausa=0.3)
        ejecutar_comando(canal, "configure terminal", pausa=0.5)

        # Hostname
        ejecutar_comando(canal, f"hostname {hostname}", pausa=0.5)

        # Usuario (ya viene sincronizado si aplica)
        if usuario and clave:
            ejecutar_comando(canal, f"username {usuario} privilege 15 secret {clave}", pausa=0.6)

        # Dominio y SSH
        if dominio:
            ejecutar_comando(canal, f"ip domain-name {dominio}", pausa=0.4)
        ejecutar_comando(canal, "no ip domain-lookup", pausa=0.2)
        ejecutar_comando(canal, "service password-encryption", pausa=0.2)

        if dominio:
            ejecutar_comando(canal, "crypto key generate rsa modulus 1024", pausa=3.2)
            ejecutar_comando(canal, "line vty 0 4", pausa=0.3)
            ejecutar_comando(canal, "login local", pausa=0.2)
            ejecutar_comando(canal, "transport input ssh", pausa=0.2)
            ejecutar_comando(canal, "transport output ssh", pausa=0.2)
            ejecutar_comando(canal, "exit", pausa=0.2)
            ejecutar_comando(canal, "ip ssh version 2", pausa=0.3)

        ejecutar_comando(canal, "end", pausa=0.3)
        ejecutar_comando(canal, "write memory", pausa=1.5)

        # 4) Confirmar
        ejecutar_comando(canal, "", pausa=0.3)  # Enter para “repintar”
        echo = canal.read(canal.in_waiting or 0).decode(errors="ignore")
        m = re.search(r"\n([A-Za-z0-9\-_]+)#\s*$", echo)
        host_visto = m.group(1) if m else "NO_DETECTADO"
        print(f"✅ Configuración aplicada. Prompt actual: {host_visto}#")

        canal.close()
        return True

    except Exception as e:
        if canal:
            try:
                canal.close()
            except Exception:
                pass
        print(f"❌ Error al configurar {hostname} ({puerto_real}): {e}")
        return False


def cargar_csv_auto(carpeta):
    preferido = os.path.join(carpeta, "Data.csv")
    if DEBUG:
        print(f"[DEBUG] Buscando CSV preferido: {preferido}")
    if os.path.isfile(preferido):
        if DEBUG: print("[DEBUG] CSV preferido encontrado. Leyendo UTF-8…")
        return pd.read_csv(preferido, encoding="utf-8"), preferido

    archivos = glob.glob(os.path.join(carpeta, "*.csv"))
    if DEBUG:
        print(f"[DEBUG] CSVs encontrados: {archivos}")
    if not archivos:
        raise FileNotFoundError(f"No se encontró ningún .csv en: {carpeta}")

    if DEBUG:
        print(f"[DEBUG] Usando {archivos[0]} (UTF-8)")
    return pd.read_csv(archivos[0], encoding="utf-8"), archivos[0]


def validar_columnas(df):
    cols = set(df.columns.str.strip())
    faltantes = COLUMNAS_REQUERIDAS - cols
    if faltantes:
        raise ValueError(
            f"El CSV no contiene las columnas requeridas: {sorted(faltantes)}\n"
            f"Columnas presentes: {sorted(cols)}"
        )


# ---------- Flujo principal ----------
def ver_opciones():
    limpiar_consola()
    print("=== MENÚ PRINCIPAL ===")
    print("1. Mandar comandos manualmente")
    print("2. Hacer configuraciones iniciales desde CSV")
    print("0. Salir")


def modo_interactivo():
    puerto_usr = input("🔌 Puerto serial (ej. COM4 o 'auto'): ").strip()
    baud = input(f"🛠  Baudrate (enter={BAUD_POR_DEFECTO}): ").strip()
    baud = int(baud) if baud.isdigit() else BAUD_POR_DEFECTO

    sesion = None
    try:
        if puerto_usr.lower() == "auto":
            sesion, puerto_real, _ = autodetectar_conexion(baudrate=baud)
            if not sesion:
                print("❌ No se pudo autodetectar un puerto válido.")
                input("ENTER para volver al menú...")
                return
            print(f"\n✅ Conectado automáticamente en {puerto_real} (baud {baud})")
        else:
            sesion = serial.Serial(puerto_usr, baudrate=baud, timeout=1)
            time.sleep(2)
            print(f"\n✅ Conectado en {puerto_usr} (baud {baud})")

        print("👉 Escribe comandos. Para salir usa 'salir'.\n")
        while True:
            cmd_linea = input("📥 Comando: ").strip()
            if cmd_linea.lower() == "salir":
                print("👋 Saliendo del modo interactivo...")
                break
            respuesta = ejecutar_comando(sesion, cmd_linea, pausa=2)
            print(f"\n📤 Respuesta:\n{respuesta}")
        sesion.close()
    except Exception as e:
        if sesion:
            try: sesion.close()
            except: pass
        print(f"❌ Error: {e}")
    input("ENTER para volver al menú...")


def proceso_desde_csv():
    limpiar_consola()
    try:
        tabla_datos, ruta_archivo = cargar_csv_auto(CARPETA_CSV)
        validar_columnas(tabla_datos)
    except Exception as e:
        print(f"\n❌ ERROR al cargar CSV: {e}")
        input("ENTER para volver al menú...")
        return

    # Asegurar columna Baud
    if COLUMNA_BAUD_OPCIONAL not in tabla_datos.columns:
        tabla_datos[COLUMNA_BAUD_OPCIONAL] = BAUD_POR_DEFECTO

    print("\n📂 Dispositivos encontrados en el archivo:")
    print(tabla_datos)

    # Construir cola con sincronización de usuario
    cola_de_trabajo = []
    for _, f in tabla_datos.iterrows():
        port   = str(f["Port"]).strip()
        device = str(f["Device"]).strip()
        user   = str(f["User"]).strip()
        pwd    = str(f["Password"]).strip()
        domain = str(f["Ip-domain"]).strip()
        serie  = str(f["Serie"]).strip()
        baud   = int(f[COLUMNA_BAUD_OPCIONAL]) if str(f[COLUMNA_BAUD_OPCIONAL]).strip().isdigit() else BAUD_POR_DEFECTO

        if SYNC_USER_WITH_DEVICE and (not SYNC_ONLY_IF_R_PREFIX or device.startswith("R_")):
            user_final = device
        else:
            user_final = user

        cola_de_trabajo.append((port, device, user_final, pwd, domain, serie, baud))

    print("\n📋 Lista de dispositivos y sus configuraciones:")
    for (p, dev, u, pas, dom, serie, baud) in cola_de_trabajo:
        print(f"Port={p} | Hostname={dev} | User={u} | Dom={dom} | Serie={serie} | Baud={baud}")
    input("ENTER para continuar...")

    ok, fail = [], []

    for idx, (p, dev, u, pas, dom, serie, baud) in enumerate(cola_de_trabajo, start=1):
        limpiar_consola()
        print(f"\n➡ Dispositivo {idx}: {dev} (Serie esperada: {serie}) | Port={p} | Baud={baud}")
        input("Conecte el equipo y ENTER...")

        if aplicar_config(p, dev, u, pas, dom, serie, baudrate=baud):
            ok.append(dev)
        else:
            fail.append(dev)

        print("=================================================")
        input("ENTER para continuar...")

    limpiar_consola()
    print("📊 Resumen:")
    print(f"✅ Configurados ({len(ok)}): {ok}")
    print(f"⚠ Fallidos ({len(fail)}): {fail}")
    input("ENTER para volver al menú...")


# ---------- Main ----------
if __name__ == "__main__":
    if DEBUG:
        print(f"[DEBUG] Iniciando. CSV en: {CARPETA_CSV}")
    while True:
        ver_opciones()
        opt = input("Selecciona una opción: ").strip()
        if opt == "1":
            modo_interactivo()
        elif opt == "2":
            proceso_desde_csv()
        elif opt == "0":
            print("👋 Saliendo...")
            break
        else:
            print("❌ Opción inválida.")
            input("ENTER para continuar...")
