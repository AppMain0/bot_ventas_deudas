import asyncio
import difflib
import json
import os
import re
import unicodedata
from datetime import datetime

from dotenv import load_dotenv
from ollama import chat
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MODELO = "qwen3:4b"


# =========================================================
# UTILIDADES
# =========================================================

def normalizar(texto):
    texto = str(texto or "").lower().strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        letra for letra in texto
        if unicodedata.category(letra) != "Mn"
    )
    return re.sub(r"\s+", " ", texto)


def numero(valor):
    if valor is None:
        return None

    if isinstance(valor, (int, float)):
        return float(valor)

    texto = (
        str(valor)
        .replace("S/", "")
        .replace("s/", "")
        .replace("soles", "")
        .strip()
    )

    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")

    match = re.search(r"\d+(?:\.\d+)?", texto)
    return float(match.group()) if match else None


def dinero(valor):
    return f"S/ {float(valor):,.2f}"


def cantidad(valor):
    valor = float(valor)

    if valor.is_integer():
        return str(int(valor))

    return f"{valor:.2f}".rstrip("0").rstrip(".")


def fecha():
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def limpiar_nombre(nombre):
    if not nombre:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(nombre).strip(),
    ).strip(" ,.-")


# =========================================================
# DATOS POR USUARIO
# =========================================================

def archivo_usuario(user_id):
    return f"clientes_{user_id}.json"


def cargar_clientes(user_id):
    ruta = archivo_usuario(user_id)

    if not os.path.exists(ruta):
        return {}

    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except Exception as error:
        print("ERROR LEYENDO DATOS:", error)
        return {}

    if not isinstance(datos, dict):
        return {}

    # Compatibilidad con versiones anteriores.
    if "clientes" in datos and isinstance(datos["clientes"], dict):
        datos = datos["clientes"]

    clientes = {}

    for nombre, info in datos.items():
        if isinstance(info, (int, float)):
            clientes[nombre] = {
                "deuda": float(info),
                "historial": [],
            }

        elif isinstance(info, dict):
            deuda = info.get(
                "deuda",
                info.get(
                    "deuda_total",
                    info.get("saldo", 0),
                ),
            )

            clientes[nombre] = {
                "deuda": float(deuda or 0),
                "historial": info.get("historial", []),
            }

    return clientes


def guardar_clientes(user_id, clientes):
    with open(
        archivo_usuario(user_id),
        "w",
        encoding="utf-8",
    ) as archivo:
        json.dump(
            clientes,
            archivo,
            ensure_ascii=False,
            indent=2,
        )


def borrar_todos_los_datos(user_id):
    ruta = archivo_usuario(user_id)

    if os.path.exists(ruta):
        os.remove(ruta)


# =========================================================
# CLIENTES
# =========================================================

def resolver_cliente(nombre, clientes):
    if not nombre:
        return None

    buscado = normalizar(nombre)

    for cliente in clientes:
        if normalizar(cliente) == buscado:
            return cliente

    mapa = {
        normalizar(cliente): cliente
        for cliente in clientes
    }

    coincidencias = difflib.get_close_matches(
        buscado,
        list(mapa.keys()),
        n=1,
        cutoff=0.80,
    )

    return mapa[coincidencias[0]] if coincidencias else None


def asegurar_cliente(nombre, clientes):
    existente = resolver_cliente(nombre, clientes)

    if existente:
        return existente

    nuevo = limpiar_nombre(nombre).title()

    clientes[nuevo] = {
        "deuda": 0,
        "historial": [],
    }

    return nuevo


# =========================================================
# VENTAS Y PAGOS
# =========================================================

def registrar_venta(user_id, venta):
    clientes = cargar_clientes(user_id)
    cliente = asegurar_cliente(
        venta["cliente"],
        clientes,
    )

    total = float(venta["monto_total"])
    adelanto = float(venta.get("adelanto", 0))
    deuda_generada = max(total - adelanto, 0)

    clientes[cliente]["deuda"] = round(
        clientes[cliente]["deuda"] + deuda_generada,
        2,
    )

    clientes[cliente]["historial"].append({
        "tipo": "venta",
        "fecha": fecha(),
        "peso": venta["peso"],
        "precio_unitario": venta["precio_unitario"],
        "monto_total": total,
        "adelanto": adelanto,
        "deuda_generada": deuda_generada,
        "saldo_despues": clientes[cliente]["deuda"],
    })

    guardar_clientes(user_id, clientes)

    return (
        cliente,
        clientes[cliente]["deuda"],
        deuda_generada,
    )


def registrar_pago(user_id, pago):
    clientes = cargar_clientes(user_id)
    cliente = resolver_cliente(
        pago["cliente"],
        clientes,
    )

    if not cliente:
        return None, None

    monto = float(pago["monto"])
    deuda_anterior = float(clientes[cliente]["deuda"])
    deuda_nueva = max(deuda_anterior - monto, 0)

    clientes[cliente]["deuda"] = round(
        deuda_nueva,
        2,
    )

    clientes[cliente]["historial"].append({
        "tipo": "pago",
        "fecha": fecha(),
        "monto": monto,
        "saldo_antes": deuda_anterior,
        "saldo_despues": deuda_nueva,
    })

    guardar_clientes(user_id, clientes)

    return cliente, deuda_nueva


# =========================================================
# INTERPRETACIÓN DIRECTA
# =========================================================

def extraer_adelanto(texto):
    patrones = [
        r"adelanto\s+(?:de\s+)?(?:s\/\s*)?(\d+(?:[.,]\d+)?)",
        r"adelant[oó]\s+(?:s\/\s*)?(\d+(?:[.,]\d+)?)",
        r"con\s+(\d+(?:[.,]\d+)?)\s+de\s+adelanto",
    ]

    for patron in patrones:
        match = re.search(
            patron,
            texto,
            re.IGNORECASE,
        )

        if match:
            return numero(match.group(1)) or 0

    return 0


def interpretar_venta_directa(texto):
    # Le vendí a Carlos 20 kg a 200 soles
    patron = re.search(
        r"(?:le\s+)?vend[ií]\s+a\s+"
        r"(?P<cliente>.+?)\s+"
        r"(?P<peso>\d+(?:[.,]\d+)?)\s*"
        r"(?:kg|kilos?)\s+"
        r"(?P<conector>a|por)\s+"
        r"(?:s\/\s*)?"
        r"(?P<importe>\d+(?:[.,]\d+)?)",
        texto,
        re.IGNORECASE,
    )

    if patron:
        cliente = limpiar_nombre(
            patron.group("cliente")
        )

        peso = numero(
            patron.group("peso")
        )

        importe = numero(
            patron.group("importe")
        )

        por_kilo = bool(
            re.search(
                r"por\s+kilo|por\s+kg|cada\s+kilo|el\s+kilo",
                texto,
                re.IGNORECASE,
            )
        )

        if por_kilo:
            precio = importe
            total = peso * precio
        else:
            total = importe
            precio = total / peso

        return {
            "tipo": "venta",
            "cliente": cliente,
            "peso": peso,
            "precio_unitario": round(precio, 4),
            "monto_total": round(total, 2),
            "adelanto": extraer_adelanto(texto),
        }

    # Vendí 20 kg a Carlos por 200 soles
    patron = re.search(
        r"vend[ií]\s+"
        r"(?P<peso>\d+(?:[.,]\d+)?)\s*"
        r"(?:kg|kilos?)\s+a\s+"
        r"(?P<cliente>.+?)\s+por\s+"
        r"(?:s\/\s*)?"
        r"(?P<total>\d+(?:[.,]\d+)?)",
        texto,
        re.IGNORECASE,
    )

    if patron:
        peso = numero(
            patron.group("peso")
        )

        total = numero(
            patron.group("total")
        )

        cliente = limpiar_nombre(
            patron.group("cliente")
        )

        return {
            "tipo": "venta",
            "cliente": cliente,
            "peso": peso,
            "precio_unitario": round(total / peso, 4),
            "monto_total": round(total, 2),
            "adelanto": extraer_adelanto(texto),
        }

    # Carlos compró 20 kg por 200
    # Carlos se llevó 20 kg a 10
    patron = re.search(
        r"^(?P<cliente>.+?)\s+"
        r"(?:compr[oó]|se\s+llev[oó])\s+"
        r"(?P<peso>\d+(?:[.,]\d+)?)\s*"
        r"(?:kg|kilos?)\s+"
        r"(?P<conector>a|por)\s+"
        r"(?:s\/\s*)?"
        r"(?P<importe>\d+(?:[.,]\d+)?)",
        texto,
        re.IGNORECASE,
    )

    if patron:
        cliente = limpiar_nombre(
            patron.group("cliente")
        )

        peso = numero(
            patron.group("peso")
        )

        importe = numero(
            patron.group("importe")
        )

        conector = normalizar(
            patron.group("conector")
        )

        if conector == "por":
            total = importe
            precio = total / peso
        else:
            precio = importe
            total = peso * precio

        return {
            "tipo": "venta",
            "cliente": cliente,
            "peso": peso,
            "precio_unitario": round(precio, 4),
            "monto_total": round(total, 2),
            "adelanto": extraer_adelanto(texto),
        }

    return None


def interpretar_pago_directo(texto):
    patrones = [
        (
            r"(?P<cliente>.+?)\s+"
            r"(?:me\s+)?pag[oó]\s+"
            r"(?:s\/\s*)?"
            r"(?P<monto>\d+(?:[.,]\d+)?)"
        ),
        (
            r"(?:pago|abono)\s+"
            r"(?:de\s+)?"
            r"(?:s\/\s*)?"
            r"(?P<monto>\d+(?:[.,]\d+)?)"
            r"\s+(?:de|para)\s+"
            r"(?P<cliente>.+)"
        ),
    ]

    for patron in patrones:
        match = re.search(
            patron,
            texto,
            re.IGNORECASE,
        )

        if match:
            return {
                "tipo": "pago",
                "cliente": limpiar_nombre(
                    match.group("cliente")
                ),
                "monto": numero(
                    match.group("monto")
                ),
            }

    return None


# =========================================================
# CORRECCIONES
# =========================================================

def corregir_pendiente_directo(texto, pendiente):
    t = normalizar(texto)

    if t in {
        "cancelar",
        "cancela",
        "cancelalo",
        "no registrar",
        "no lo registres",
    }:
        return {"cancelar": True}

    nuevo = dict(pendiente)
    numeros = re.findall(
        r"\d+(?:[.,]\d+)?",
        texto,
    )

    if pendiente["tipo"] == "venta":

        if "total" in t and numeros:
            total = numero(numeros[-1])

            nuevo["monto_total"] = total
            nuevo["precio_unitario"] = (
                total / nuevo["peso"]
            )

            return nuevo

        if any(
            frase in t
            for frase in (
                "por kilo",
                "por kg",
                "el kilo",
            )
        ) and numeros:

            precio = numero(numeros[-1])

            nuevo["precio_unitario"] = precio
            nuevo["monto_total"] = (
                nuevo["peso"] * precio
            )

            return nuevo

        if "kg" in t or "kilo" in t:
            match = re.search(
                r"(\d+(?:[.,]\d+)?)\s*(?:kg|kilos?)",
                texto,
                re.IGNORECASE,
            )

            if match:
                peso = numero(
                    match.group(1)
                )

                nuevo["peso"] = peso
                nuevo["monto_total"] = (
                    peso
                    * nuevo["precio_unitario"]
                )

                return nuevo

        if "adelanto" in t and numeros:
            nuevo["adelanto"] = numero(
                numeros[-1]
            )

            return nuevo

    if pendiente["tipo"] == "pago":
        if any(
            palabra in t
            for palabra in (
                "pago",
                "fueron",
                "era",
            )
        ) and numeros:

            nuevo["monto"] = numero(
                numeros[-1]
            )

            return nuevo

    return None


# =========================================================
# QWEN / OLLAMA
# =========================================================

async def interpretar_con_qwen(texto, clientes):
    lista_clientes = list(
        clientes.keys()
    )

    prompt = f"""
Eres el intérprete de un bot peruano de ventas, pagos y deudas.

Devuelve SOLO JSON válido.
No uses markdown.
No expliques tu respuesta.
Nunca inventes información.
La moneda es soles peruanos.

Mensaje:
{texto}

Clientes registrados:
{json.dumps(lista_clientes, ensure_ascii=False)}

Devuelve esta estructura:

{{
  "accion": "venta|pago|deuda_cliente|deudas_todos|historial_cliente|saludo|ayuda|chat|cancelar|desconocido",
  "cliente": null,
  "peso": null,
  "precio_unitario": null,
  "monto_total": null,
  "adelanto": 0,
  "monto": null,
  "respuesta": null,
  "necesita_aclaracion": false,
  "pregunta": null
}}

Reglas:
- "Le vendí a Carlos 20 kg a 200 soles" = monto total 200.
- "Vendí 20 kg a Carlos por 200" = monto total 200.
- "Carlos compró 20 kg por 200" = monto total 200.
- "Carlos se llevó 20 kg a 10" = precio por kilo 10.
- "por kilo", "por kg" o "el kilo" indica precio unitario.
- Con peso + total, calcula precio unitario.
- Con peso + precio unitario, calcula total.
- "Juan me pagó 100" = pago.
- "Cuánto debe Juan" = deuda_cliente.
- "Quién me debe" = deudas_todos.
- "Muéstrame todas las deudas" = deudas_todos.
- "Historial de Juan" = historial_cliente.
- Si falta información necesaria, usa necesita_aclaracion=true.
- Si el usuario conversa, usa chat.
""".strip()

    def llamar_qwen():
        return chat(
            model=MODELO,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            format="json",
            think=False,
            options={
                "temperature": 0.1,
                "top_p": 0.9,
                "repeat_penalty": 1.15,
                "repeat_last_n": 64,
                "num_predict": 250,
                "num_ctx": 4096,
            },
        )

    try:
        respuesta = await asyncio.to_thread(
            llamar_qwen
        )

        return json.loads(
            respuesta.message.content
        )

    except Exception as error:
        print("ERROR QWEN:", error)

        return {
            "accion": "desconocido",
            "cliente": None,
            "peso": None,
            "precio_unitario": None,
            "monto_total": None,
            "adelanto": 0,
            "monto": None,
            "respuesta": None,
            "necesita_aclaracion": False,
            "pregunta": None,
        }


# =========================================================
# INTERFAZ TELEGRAM
# =========================================================

def teclado_confirmacion():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Registrar",
                callback_data="confirmar",
            ),
            InlineKeyboardButton(
                "❌ Cancelar",
                callback_data="cancelar",
            ),
        ]
    ])


def texto_operacion(pendiente):
    if pendiente["tipo"] == "venta":
        deuda = (
            pendiente["monto_total"]
            - pendiente.get("adelanto", 0)
        )

        return (
            "🧾 <b>Revisa la venta</b>\n\n"
            f"👤 Cliente: <b>{pendiente['cliente']}</b>\n"
            f"⚖️ Peso: <b>{cantidad(pendiente['peso'])} kg</b>\n"
            f"💰 Precio/kg: <b>{dinero(pendiente['precio_unitario'])}</b>\n"
            f"🧮 Total: <b>{dinero(pendiente['monto_total'])}</b>\n"
            f"💵 Adelanto: <b>{dinero(pendiente.get('adelanto', 0))}</b>\n"
            f"📌 Deuda de esta venta: <b>{dinero(deuda)}</b>\n\n"
            "¿La registro?"
        )

    if pendiente["tipo"] == "pago":
        return (
            "💵 <b>Revisa el pago</b>\n\n"
            f"👤 Cliente: <b>{pendiente['cliente']}</b>\n"
            f"💰 Pago: <b>{dinero(pendiente['monto'])}</b>\n\n"
            "¿Lo registro?"
        )

    return ""


async def mostrar_pendiente(update, pendiente):
    await update.effective_message.reply_text(
        texto_operacion(pendiente),
        parse_mode="HTML",
        reply_markup=teclado_confirmacion(),
    )


# =========================================================
# CONSULTAS
# =========================================================

def consultar_deuda(nombre, clientes):
    cliente = resolver_cliente(
        nombre,
        clientes,
    )

    if not cliente:
        return (
            f"🤔 No encuentro a "
            f"<b>{nombre}</b>."
        )

    deuda = clientes[cliente]["deuda"]

    if deuda <= 0:
        return (
            f"✅ <b>{cliente}</b> "
            f"no tiene deuda."
        )

    return (
        f"👤 <b>{cliente}</b>\n"
        f"💰 Debe: <b>{dinero(deuda)}</b>"
    )


def todas_las_deudas(clientes):
    lista = [
        (
            cliente,
            float(datos.get("deuda", 0)),
        )
        for cliente, datos in clientes.items()
        if float(datos.get("deuda", 0)) > 0
    ]

    if not lista:
        return "✅ No tienes deudas pendientes."

    lista.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    total = sum(
        deuda
        for _, deuda in lista
    )

    respuesta = [
        "📋 <b>Deudas pendientes</b>\n"
    ]

    respuesta.extend(
        f"• <b>{cliente}</b>: {dinero(deuda)}"
        for cliente, deuda in lista
    )

    respuesta.append(
        f"\n💰 <b>Total por cobrar: "
        f"{dinero(total)}</b>"
    )

    return "\n".join(respuesta)


def historial_cliente(nombre, clientes):
    cliente = resolver_cliente(
        nombre,
        clientes,
    )

    if not cliente:
        return (
            f"🤔 No encuentro a {nombre}."
        )

    historial = clientes[cliente].get(
        "historial",
        [],
    )

    if not historial:
        return (
            f"📭 {cliente} no tiene "
            f"movimientos registrados."
        )

    respuesta = [
        f"📚 <b>Historial de {cliente}</b>\n"
    ]

    for movimiento in historial[-10:]:

        if movimiento.get("tipo") == "venta":
            respuesta.append(
                f"🟢 Venta - "
                f"{movimiento.get('fecha', '')}\n"
                f"   Total: "
                f"{dinero(movimiento.get('monto_total', 0))}"
            )

        elif movimiento.get("tipo") == "pago":
            respuesta.append(
                f"🔵 Pago - "
                f"{movimiento.get('fecha', '')}\n"
                f"   "
                f"{dinero(movimiento.get('monto', 0))}"
            )

    respuesta.append(
        f"\n📌 Saldo actual: "
        f"<b>{dinero(clientes[cliente]['deuda'])}</b>"
    )

    return "\n".join(respuesta)


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "👋 ¡Hola!\n\n"
        "Soy tu bot de ventas y deudas.\n\n"
        "Puedes escribirme de manera natural.\n\n"
        "Ejemplos:\n\n"
        "🟢 Le vendí a Carlos 20 kg a 200 soles\n\n"
        "🟢 Carlos se llevó 20 kg a 10\n\n"
        "💵 Juan me pagó 100 soles\n\n"
        "🔎 ¿Cuánto debe Carlos?\n\n"
        "📋 Muéstrame todas las deudas\n\n"
        "📚 Historial de Carlos\n\n"
        "Antes de registrar una venta o un pago, "
        "te pediré confirmación."
    )


# =========================================================
# BOTONES
# =========================================================

async def botones(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id
    accion = query.data

    if accion == "cancelar":
        context.user_data.pop(
            "pendiente",
            None,
        )

        await query.edit_message_text(
            "❌ Operación cancelada."
        )

        return

    if accion == "confirmar":
        pendiente = context.user_data.get(
            "pendiente"
        )

        if not pendiente:
            await query.edit_message_text(
                "⚠️ No hay una operación pendiente."
            )
            return

        if pendiente["tipo"] == "venta":
            cliente, saldo, deuda = registrar_venta(
                user_id,
                pendiente,
            )

            context.user_data.pop(
                "pendiente",
                None,
            )

            await query.edit_message_text(
                "✅ <b>Venta registrada</b>\n\n"
                f"👤 {cliente}\n"
                f"⚖️ {cantidad(pendiente['peso'])} kg\n"
                f"💰 Precio/kg: "
                f"{dinero(pendiente['precio_unitario'])}\n"
                f"🧮 Total: "
                f"{dinero(pendiente['monto_total'])}\n"
                f"💵 Adelanto: "
                f"{dinero(pendiente.get('adelanto', 0))}\n"
                f"📌 Deuda generada: "
                f"{dinero(deuda)}\n\n"
                f"💰 Deuda total de {cliente}: "
                f"<b>{dinero(saldo)}</b>",
                parse_mode="HTML",
            )

            return

        if pendiente["tipo"] == "pago":
            cliente, saldo = registrar_pago(
                user_id,
                pendiente,
            )

            context.user_data.pop(
                "pendiente",
                None,
            )

            if not cliente:
                await query.edit_message_text(
                    "⚠️ No encontré ese cliente."
                )
                return

            await query.edit_message_text(
                "✅ <b>Pago registrado</b>\n\n"
                f"👤 {cliente}\n"
                f"💵 Pago: "
                f"{dinero(pendiente['monto'])}\n"
                f"📌 Deuda restante: "
                f"<b>{dinero(saldo)}</b>",
                parse_mode="HTML",
            )

            return

    if accion == "borrar_todo":
        borrar_todos_los_datos(
            user_id
        )

        context.user_data.pop(
            "pendiente",
            None,
        )

        await query.edit_message_text(
            "🗑️ Todos tus clientes, deudas "
            "e historiales fueron eliminados."
        )

        return

    if accion == "cancelar_borrado":
        await query.edit_message_text(
            "👍 No se borró nada."
        )


# =========================================================
# BORRAR DATOS
# =========================================================

def quiere_borrar_todo(texto):
    texto = normalizar(texto)

    frases = [
        "borra todas mis deudas",
        "borra mis deudores",
        "borra el registro de mis deudores",
        "elimina todas mis deudas",
        "elimina todos mis clientes",
        "elimina todo",
        "borra todo",
        "reinicia mis datos",
    ]

    return any(
        frase in texto
        for frase in frases
    )


# =========================================================
# MENSAJES
# =========================================================

async def mensaje(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    texto = update.message.text.strip()
    user_id = update.effective_user.id
    clientes = cargar_clientes(user_id)

    # Borrar todo
    if quiere_borrar_todo(texto):
        teclado = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🗑️ Sí, borrar todo",
                    callback_data="borrar_todo",
                ),
                InlineKeyboardButton(
                    "❌ No",
                    callback_data="cancelar_borrado",
                ),
            ]
        ])

        await update.message.reply_text(
            "⚠️ Esto eliminará "
            "<b>todos tus clientes, deudas e historiales</b>.\n\n"
            "¿Seguro?",
            parse_mode="HTML",
            reply_markup=teclado,
        )

        return

    # Corregir operación pendiente
    pendiente = context.user_data.get(
        "pendiente"
    )

    if pendiente:
        correccion = corregir_pendiente_directo(
            texto,
            pendiente,
        )

        if correccion:
            if correccion.get("cancelar"):
                context.user_data.pop(
                    "pendiente",
                    None,
                )

                await update.message.reply_text(
                    "❌ Operación cancelada."
                )

                return

            context.user_data["pendiente"] = correccion

            await update.message.reply_text(
                "✏️ Listo, corregí la operación."
            )

            await mostrar_pendiente(
                update,
                correccion,
            )

            return

    # Venta directa
    venta = interpretar_venta_directa(
        texto
    )

    if venta:
        context.user_data["pendiente"] = venta

        await mostrar_pendiente(
            update,
            venta,
        )

        return

    # Pago directo
    pago = interpretar_pago_directo(
        texto
    )

    if pago:
        cliente = resolver_cliente(
            pago["cliente"],
            clientes,
        )

        if not cliente:
            await update.message.reply_text(
                f"🤔 No encuentro a "
                f"<b>{pago['cliente']}</b> "
                f"entre tus clientes.",
                parse_mode="HTML",
            )

            return

        pago["cliente"] = cliente
        context.user_data["pendiente"] = pago

        await mostrar_pendiente(
            update,
            pago,
        )

        return

    # Si las reglas directas no entienden, usar Qwen
    resultado = await interpretar_con_qwen(
        texto,
        clientes,
    )

    accion = normalizar(
        resultado.get("accion")
    )

    if resultado.get(
        "necesita_aclaracion"
    ):
        await update.message.reply_text(
            resultado.get("pregunta")
            or "Necesito un dato más."
        )

        return

    # Venta interpretada por Qwen
    if accion == "venta":
        cliente = limpiar_nombre(
            resultado.get("cliente")
        )

        peso = numero(
            resultado.get("peso")
        )

        precio = numero(
            resultado.get("precio_unitario")
        )

        total = numero(
            resultado.get("monto_total")
        )

        adelanto = (
            numero(
                resultado.get("adelanto")
            )
            or 0
        )

        if not cliente:
            await update.message.reply_text(
                "¿A qué cliente fue la venta?"
            )
            return

        if not peso:
            await update.message.reply_text(
                "¿Cuántos kilos fueron?"
            )
            return

        if not total and precio:
            total = peso * precio

        if not precio and total:
            precio = total / peso

        if not total or not precio:
            await update.message.reply_text(
                "¿Cuál fue el total "
                "o el precio por kilo?"
            )
            return

        pendiente = {
            "tipo": "venta",
            "cliente": cliente,
            "peso": peso,
            "precio_unitario": round(
                precio,
                4,
            ),
            "monto_total": round(
                total,
                2,
            ),
            "adelanto": round(
                adelanto,
                2,
            ),
        }

        context.user_data["pendiente"] = pendiente

        await mostrar_pendiente(
            update,
            pendiente,
        )

        return

    # Pago interpretado por Qwen
    if accion == "pago":
        nombre = limpiar_nombre(
            resultado.get("cliente")
        )

        monto = numero(
            resultado.get("monto")
        )

        cliente = resolver_cliente(
            nombre,
            clientes,
        )

        if not cliente:
            await update.message.reply_text(
                f"🤔 No encuentro a "
                f"<b>{nombre}</b>.",
                parse_mode="HTML",
            )

            return

        if not monto:
            await update.message.reply_text(
                "¿Cuánto pagó?"
            )

            return

        pendiente = {
            "tipo": "pago",
            "cliente": cliente,
            "monto": monto,
        }

        context.user_data["pendiente"] = pendiente

        await mostrar_pendiente(
            update,
            pendiente,
        )

        return

    # Consultar cliente
    if accion == "deuda_cliente":
        nombre = limpiar_nombre(
            resultado.get("cliente")
        )

        await update.message.reply_text(
            consultar_deuda(
                nombre,
                clientes,
            ),
            parse_mode="HTML",
        )

        return

    # Todas las deudas
    if accion == "deudas_todos":
        await update.message.reply_text(
            todas_las_deudas(clientes),
            parse_mode="HTML",
        )

        return

    # Historial
    if accion == "historial_cliente":
        nombre = limpiar_nombre(
            resultado.get("cliente")
        )

        await update.message.reply_text(
            historial_cliente(
                nombre,
                clientes,
            ),
            parse_mode="HTML",
        )

        return

    # Saludo
    if accion == "saludo":
        await update.message.reply_text(
            "👋 ¡Hola!\n\n"
            "¿Qué venta, pago o deuda "
            "quieres registrar?"
        )

        return

    # Ayuda
    if accion == "ayuda":
        await update.message.reply_text(
            "Puedes decirme cosas como:\n\n"
            "🟢 Le vendí a Carlos "
            "20 kg a 200 soles\n\n"
            "🟢 Carlos se llevó "
            "20 kg a 10\n\n"
            "💵 Juan me pagó 100\n\n"
            "🔎 Cuánto debe Carlos\n\n"
            "📋 Muéstrame todas las deudas\n\n"
            "📚 Historial de Carlos"
        )

        return

    # Conversación
    if accion == "chat":
        respuesta = resultado.get(
            "respuesta"
        )

        await update.message.reply_text(
            respuesta
            or (
                "¿Quieres registrar una venta, "
                "un pago o consultar una deuda?"
            )
        )

        return

    await update.message.reply_text(
        "🤔 No entendí del todo.\n\n"
        "Prueba por ejemplo:\n\n"
        "“Le vendí a Carlos "
        "20 kg por 200 soles”"
    )


# =========================================================
# INICIAR BOT
# =========================================================

def main():
    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            botones
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            mensaje,
        )
    )

    print("Bot encendido...")
    print(f"Modelo de IA: {MODELO}")

    app.run_polling()


if __name__ == "__main__":
    main()