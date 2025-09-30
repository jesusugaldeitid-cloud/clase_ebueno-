# -*- coding: utf-8 -*-
"""
Script para configurar routers Cisco desde CSV.
Mejorado: ahora ir_a_enable detecta "Password:" y envía la clave si existe.
"""

import serial
import time
import pandas as pd
import os
import re
import glob

DEBUG = True  # Cambia a False si no quieres trazas en pantalla
CARPETA_CSV = r"C:\Users\jesus\OneDrive\Documentos\CODIGOS\clase_ebueno"
COLUMNAS_REQUERIDAS = {"Serie", "Port", "Device", "User", "Password", "Ip-domain"}
COLUMNA_BAUD_OPCIONAL = "Baud"
BAUD_POR_DEFECTO = 9600

try:
    from serial.tools import list_ports
except Exception:
    list_ports = None


# ---------------- Utilidades ----------------
def limpiar_consola():
    if not DEBUG:
        os.system("cls" if os.name == "nt" else "clear")


def leer_hasta_prompt(conexion, timeout=3.0):
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
    try:
        _ = conexion.read(conexion.in_waiting or 0)
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
    Si pide Password, se manda la clave del CSV.
    """
    _ = conexion.read(conexion.in_waiting or 0)
    conexion.write(b"enable\r\n")
    time.sleep(0.4)

    salida = conexion.read(conexion.in_waiting or 0).decode(errors="ignore")

    # Caso: pide contraseña
    if re.search(r"[Pp]assword", salida):
        if DEBUG:
            print("[DEBUG] Router pide contraseña de enable")
        if clave_enable:
            conexion.write((clave_enable + "\r\n").encode())
            time.sleep(0.5)
            salida += conexion.read(conexion.in_waiting or 0).decode(errors="ignore")
        else:
            print("⚠ El router pide contraseña de enable pero no hay clave en el CSV")

    salida += leer_hasta_prompt(conexion, timeout=3.0)
    if DEBUG:
        print(f"[DEBUG enable] {salida}")
    return salida


def buscar_serial(canal_serial):
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
        encontrados = [f"COM{i}" for i in range(3, 21)]
    if DEBUG:
        print(f"[DEBUG] Puertos candidatos: {encontrados}")
    return encontrados


def probar_puerto(puerto, baudrate=BAUD_POR_DEFECTO, timeout=1.0):
    try:
        canal = serial.Serial(puerto, baudrate=baudrate, timeout=timeout)
        time.sleep(2)
        _ = canal.read(canal.in_waiting or 0)
        canal.write(b"\r\n")
        time.sleep(0.3)
        _ = canal.read(canal.in_waiting or 0)
        serie = buscar_serial(canal)
        if serie:
            return canal, serie
        canal.close()
        return None, None
    except Exception:
        return None, None


def autodetectar_conexion(baudrate=BAUD_POR_DEFECTO):
    for p in puertos_disponibles():
        canal, serie = probar_puerto(p, baudrate=baudrate)
        if canal and serie:
            return canal, p, serie
    return None, None, None


def aplicar_config(puerto, hostname, usuario, clave, dominio, serie_csv, baudrate=BAUD_POR_DEFECTO):
    canal = None
    puerto_real = puerto
    try:
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

        if not serie_detectada or str(serie_detectada).strip().upper() != str(serie_csv).strip().upper():
            print(f"⚠ Serie no válida. Detectada={serie_detectada}, CSV={serie_csv}. Saltando.")
            canal.close()
            return False

        # Configuración
        ir_a_enable(canal, clave_enable=clave if clave else None)
        ejecutar_comando(canal, "configure terminal", pausa=0.5)
        ejecutar_comando(canal, f"hostname {hostname}", pausa=0.5)
        ejecutar_comando(canal, f"username {usuario} privilege 15 secret {clave}", pausa=0.6)
        ejecutar_comando(canal, f"ip domain-name {dominio}", pausa=0.4)
        ejecutar_comando(canal, "crypto key generate rsa modulus 1024", pausa=3.0)
        ejecutar_comando(canal, "line vty 0 4", pausa=0.3)
        ejecutar_comando(canal, "login local", pausa=0.2)
        ejecutar_comando(canal, "transport input ssh", pausa=0.2)
        ejecutar_comando(canal, "transport output ssh", pausa=0.2)
        ejecutar_comando(canal, "end", pausa=0.3)
        ejecutar_comando(canal, "write memory", pausa=1.6)

        # Confirmación
        ejecutar_comando(canal, "", pausa=0.3)
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
    if os.path.isfile(preferido):
        return pd.read_csv(preferido, encoding="utf-8"), preferido
    archivos = glob.glob(os.path.join(carpeta, "*.csv"))
    if not archivos:
        raise FileNotFoundError(f"No se encontró ningún .csv en: {carpeta}")
    return pd.read_csv(archivos[0], encoding="utf-8"), archivos[0]


def validar_columnas(df):
    cols = set(df.columns.str.strip())
    faltantes = COLUMNAS_REQUERIDAS - cols
    if faltantes:
        raise ValueError(f"Faltan columnas requeridas: {sorted(faltantes)}")


# ---------------- Menús ----------------
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


def proceso_desde_csv():
    try:
        tabla_datos, ruta_archivo = cargar_csv_auto(CARPETA_CSV)
        validar_columnas(tabla_datos)
    except Exception as e:
        print(f"\n❌ ERROR al cargar CSV: {e}")
        return
    if COLUMNA_BAUD_OPCIONAL not in tabla_datos.columns:
        tabla_datos[COLUMNA_BAUD_OPCIONAL] = BAUD_POR_DEFECTO
    print("\n📂 Dispositivos encontrados en el archivo:")
    print(tabla_datos)
    cola = [
        (str(f["Port"]).strip(), str(f["Device"]).strip(), str(f["User"]).strip(),
         str(f["Password"]).strip(), str(f["Ip-domain"]).strip(), str(f["Serie"]).strip(),
         int(f[COLUMNA_BAUD_OPCIONAL]) if str(f[COLUMNA_BAUD_OPCIONAL]).isdigit() else BAUD_POR_DEFECTO)
        for _, f in tabla_datos.iterrows()
    ]
    ok, fail = [], []
    for idx, (p, dev, u, pas, dom, serie, baud) in enumerate(cola, start=1):
        print(f"\n➡ Dispositivo {idx}: {dev} (Serie={serie}) | Port={p} | Baud={baud}")
        input("Conecte el equipo y ENTER...")
        if aplicar_config(p, dev, u, pas, dom, serie, baudrate=baud):
            ok.append(dev)
        else:
            fail.append(dev)
    print("\n📊 Resumen:")
    print(f"✅ Configurados: {ok}")
    print(f"⚠ Fallidos: {fail}")


# ---------------- Main ----------------
if __name__ == "__main__":
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
