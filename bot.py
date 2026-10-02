import asyncio
import difflib
import json
import os
import re
import unicodedata
from datetime import datetime

from dotenv import load_dotenv
from ollama import chat

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CONFIGURACIÓN
# =========================================================

load_dotenv()

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

MODELO = "qwen3:4b"


# =========================================================
# FUNCIONES GENERALES
# =========================================================

def normalizar(texto):

    texto = str(texto or "").lower().strip()

    texto = unicodedata.normalize(
        "NFD",
        texto
    )

    texto = "".join(
        letra
        for letra in texto
        if unicodedata.category(letra) != "Mn"
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    return texto


def numero(valor):

    if valor is None:
        return None

    if isinstance(valor, (int, float)):
        return float(valor)

    texto = str(valor)

    texto = texto.replace("S/", "")
    texto = texto.replace("s/", "")
    texto = texto.replace("soles", "")
    texto = texto.strip()

    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")

    match = re.search(
        r"\d+(?:\.\d+)?",
        texto
    )

    if not match:
        return None

    return float(
        match.group()
    )


def dinero(valor):

    return f"S/ {float(valor):,.2f}"


def cantidad(valor):

    valor = float(valor)

    if valor.is_integer():
        return str(int(valor))

    return (
        f"{valor:.2f}"
        .rstrip("0")
        .rstrip(".")
    )


def fecha():

    return datetime.now().strftime(
        "%d/%m/%Y %H:%M"
    )


def limpiar_nombre(nombre):

    if not nombre:
        return ""

    nombre = str(nombre).strip()

    nombre = re.sub(
        r"\s+",
        " ",
        nombre
    )

    return nombre.strip(
        " ,.-"
    )


# =========================================================
# ARCHIVO INDEPENDIENTE PARA CADA USUARIO
# =========================================================

def archivo_usuario(user_id):

    return f"clientes_{user_id}.json"


def cargar_clientes(user_id):

    ruta = archivo_usuario(
        user_id
    )

    if not os.path.exists(ruta):
        return {}

    try:

        with open(
            ruta,
            "r",
            encoding="utf-8"
        ) as archivo:

            datos = json.load(
                archivo
            )

    except Exception as error:

        print(
            "ERROR LEYENDO DATOS:",
            error
        )

        return {}

    if not isinstance(datos, dict):
        return {}

    # Compatibilidad con versiones anteriores
    if (
        "clientes" in datos
        and isinstance(
            datos["clientes"],
            dict
        )
    ):
        datos = datos["clientes"]

    clientes = {}

    for nombre, info in datos.items():

        if isinstance(
            info,
            (int, float)
        ):

            clientes[nombre] = {
                "deuda": float(info),
                "historial": []
            }

        elif isinstance(
            info,
            dict
        ):

            deuda = info.get(
                "deuda",
                info.get(
                    "deuda_total",
                    info.get(
                        "saldo",
                        0
                    )
                )
            )

            clientes[nombre] = {
                "deuda": float(
                    deuda or 0
                ),

                "historial": info.get(
                    "historial",
                    []
                )
            }

    return clientes


def guardar_clientes(
    user_id,
    clientes
):

    with open(
        archivo_usuario(user_id),
        "w",
        encoding="utf-8"
    ) as archivo:

        json.dump(
            clientes,
            archivo,
            ensure_ascii=False,
            indent=2
        )


def borrar_todos_los_datos(
    user_id
):

    ruta = archivo_usuario(
        user_id
    )

    if os.path.exists(ruta):
        os.remove(ruta)


# =========================================================
# CLIENTES
# =========================================================

def resolver_cliente(
    nombre,
    clientes
):

    if not nombre:
        return None

    buscado = normalizar(
        nombre
    )

    # Coincidencia exacta
    for cliente in clientes:

        if normalizar(cliente) == buscado:
            return cliente

    # Coincidencia aproximada
    mapa = {
        normalizar(cliente): cliente
        for cliente in clientes
    }

    coincidencias = difflib.get_close_matches(
        buscado,
        list(mapa.keys()),
        n=1,
        cutoff=0.80
    )

    if coincidencias:

        return mapa[
            coincidencias[0]
        ]

    return None


def asegurar_cliente(
    nombre,
    clientes
):

    existente = resolver_cliente(
        nombre,
        clientes
    )

    if existente:
        return existente

    nuevo = limpiar_nombre(
        nombre
    ).title()

    clientes[nuevo] = {
        "deuda": 0,
        "historial": []
    }

    return nuevo


# =========================================================
# REGISTRAR VENTA
# =========================================================

def registrar_venta(
    user_id,
    venta
):

    clientes = cargar_clientes(
        user_id
    )

    cliente = asegurar_cliente(
        venta["cliente"],
        clientes
    )

    total = float(
        venta["monto_total"]
    )

    adelanto = float(
        venta.get(
            "adelanto",
            0
        )
    )

    deuda_generada = max(
        total - adelanto,
        0
    )

    clientes[
        cliente
    ]["deuda"] += deuda_generada

    clientes[
        cliente
    ]["deuda"] = round(
        clientes[cliente]["deuda"],
        2
    )

    clientes[
        cliente
    ]["historial"].append(
        {
            "tipo": "venta",

            "fecha": fecha(),

            "peso":
                venta["peso"],

            "precio_unitario":
                venta["precio_unitario"],

            "monto_total":
                total,

            "adelanto":
                adelanto,

            "deuda_generada":
                deuda_generada,

            "saldo_despues":
                clientes[cliente]["deuda"]
        }
    )

    guardar_clientes(
        user_id,
        clientes
    )

    return (
        cliente,
        clientes[cliente]["deuda"],
        deuda_generada
    )


# =========================================================
# REGISTRAR PAGO
# =========================================================

def registrar_pago(
    user_id,
    pago
):

    clientes = cargar_clientes(
        user_id
    )

    cliente = resolver_cliente(
        pago["cliente"],
        clientes
    )

    if not cliente:
        return None, None

    monto = float(
        pago["monto"]
    )

    deuda_anterior = float(
        clientes[
            cliente
        ]["deuda"]
    )

    deuda_nueva = max(
        deuda_anterior - monto,
        0
    )

    clientes[
        cliente
    ]["deuda"] = round(
        deuda_nueva,
        2
    )

    clientes[
        cliente
    ]["historial"].append(
        {
            "tipo": "pago",

            "fecha": fecha(),

            "monto":
                monto,

            "saldo_antes":
                deuda_anterior,

            "saldo_despues":
                deuda_nueva
        }
    )

    guardar_clientes(
        user_id,
        clientes
    )

    return (
        cliente,
        deuda_nueva
    )


# =========================================================
# ADELANTO
# =========================================================

def extraer_adelanto(
    texto
):

    patrones = [

        r"adelanto\s+(?:de\s+)?"
        r"(?:s\/\s*)?"
        r"(\d+(?:[.,]\d+)?)",

        r"adelant[oó]\s+"
        r"(?:s\/\s*)?"
        r"(\d+(?:[.,]\d+)?)",

        r"con\s+"
        r"(\d+(?:[.,]\d+)?)"
        r"\s+de\s+adelanto"

    ]

    for patron in patrones:

        match = re.search(
            patron,
            texto,
            re.IGNORECASE
        )

        if match:

            return (
                numero(
                    match.group(1)
                )
                or 0
            )

    return 0


# =========================================================
# INTERPRETAR VENTAS DIRECTAMENTE
# =========================================================

def interpretar_venta_directa(
    texto
):

    # -----------------------------------------------------
    # Le vendí a Carlos 20 kg a 200 soles
    #
    # Total = 200
    # -----------------------------------------------------

    patron = re.search(
        r"(?:le\s+)?vend[ií]\s+a\s+"
        r"(?P<cliente>.+?)\s+"
        r"(?P<peso>\d+(?:[.,]\d+)?)\s*"
        r"(?:kg|kilos?)\s+"
        r"(?P<conector>a|por)\s+"
        r"(?:s\/\s*)?"
        r"(?P<importe>\d+(?:[.,]\d+)?)",
        texto,
        re.IGNORECASE
    )

    if patron:

        cliente = limpiar_nombre(
            patron.group(
                "cliente"
            )
        )

        peso = numero(
            patron.group(
                "peso"
            )
        )

        importe = numero(
            patron.group(
                "importe"
            )
        )

        por_kilo = bool(
            re.search(
                r"por\s+kilo|"
                r"por\s+kg|"
                r"cada\s+kilo|"
                r"el\s+kilo",
                texto,
                re.IGNORECASE
            )
        )

        if por_kilo:

            precio = importe

            total = (
                peso
                * precio
            )

        else:

            total = importe

            precio = (
                total
                / peso
            )

        return {
            "tipo":
                "venta",

            "cliente":
                cliente,

            "peso":
                peso,

            "precio_unitario":
                round(
                    precio,
                    4
                ),

            "monto_total":
                round(
                    total,
                    2
                ),

            "adelanto":
                extraer_adelanto(
                    texto
                )
        }


    # -----------------------------------------------------
    # Vendí 20 kg a Carlos por 200 soles
    # -----------------------------------------------------

    patron = re.search(
        r"vend[ií]\s+"
        r"(?P<peso>\d+(?:[.,]\d+)?)\s*"
        r"(?:kg|kilos?)\s+a\s+"
        r"(?P<cliente>.+?)\s+por\s+"
        r"(?:s\/\s*)?"
        r"(?P<total>\d+(?:[.,]\d+)?)",
        texto,
        re.IGNORECASE
    )

    if patron:

        peso = numero(
            patron.group(
                "peso"
            )
        )

        total = numero(
            patron.group(
                "total"
            )
        )

        cliente = limpiar_nombre(
            patron.group(
                "cliente"
            )
        )

        precio = (
            total
            / peso
        )

        return {
            "tipo":
                "venta",

            "cliente":
                cliente,

            "peso":
                peso,

            "precio_unitario":
                round(
                    precio,
                    4
                ),

            "monto_total":
                round(
                    total,
                    2
                ),

            "adelanto":
                extraer_adelanto(
                    texto
                )
        }


    # -----------------------------------------------------
    # Carlos compró 20 kg por 200
    #
    # Carlos se llevó 20 kg por 200
    #
    # Carlos se llevó 20 kg a 10
    # -----------------------------------------------------

    patron = re.search(
        r"^(?P<cliente>.+?)\s+"
        r"(?:compr[oó]|se\s+llev[oó])\s+"
        r"(?P<peso>\d+(?:[.,]\d+)?)\s*"
        r"(?:kg|kilos?)\s+"
        r"(?P<conector>a|por)\s+"
        r"(?:s\/\s*)?"
        r"(?P<importe>\d+(?:[.,]\d+)?)",
        texto,
        re.IGNORECASE
    )

    if patron:

        cliente = limpiar_nombre(
            patron.group(
                "cliente"
            )
        )

        peso = numero(
            patron.group(
                "peso"
            )
        )

        importe = numero(
            patron.group(
                "importe"
            )
        )

        conector = normalizar(
            patron.group(
                "conector"
            )
        )

        if conector == "por":

            total = importe

            precio = (
                total
                / peso
            )

        else:

            precio = importe

            total = (
                peso
                * precio
            )

        return {
            "tipo":
                "venta",

            "cliente":
                cliente,

            "peso":
                peso,

            "precio_unitario":
                round(
                    precio,
                    4
                ),

            "monto_total":
                round(
                    total,
                    2
                ),

            "adelanto":
                extraer_adelanto(
                    texto
                )
        }


    return None


# =========================================================
# INTERPRETAR PAGOS DIRECTAMENTE
# =========================================================

def interpretar_pago_directo(
    texto
):

    patrones = [

        r"(?P<cliente>.+?)\s+"
        r"(?:me\s+)?pag[oó]\s+"
        r"(?:s\/\s*)?"
        r"(?P<monto>\d+(?:[.,]\d+)?)",

        r"(?:pago|abono)\s+"
        r"(?:de\s+)?"
        r"(?:s\/\s*)?"
        r"(?P<monto>\d+(?:[.,]\d+)?)"
        r"\s+(?:de|para)\s+"
        r"(?P<cliente>.+)"

    ]

    for patron in patrones:

        match = re.search(
            patron,
            texto,
            re.IGNORECASE
        )

        if match:

            return {
                "tipo":
                    "pago",

                "cliente":
                    limpiar_nombre(
                        match.group(
                            "cliente"
                        )
                    ),

                "monto":
                    numero(
                        match.group(
                            "monto"
                        )
                    )
            }

    return None


# =========================================================
# CORREGIR OPERACIÓN PENDIENTE
# =========================================================

def corregir_pendiente_directo(
    texto,
    pendiente
):

    t = normalizar(
        texto
    )


    if t in [
        "cancelar",
        "cancela",
        "cancelalo",
        "no registrar",
        "no lo registres"
    ]:

        return {
            "cancelar": True
        }


    nuevo = dict(
        pendiente
    )


    # =====================================================
    # CORREGIR VENTA
    # =====================================================

    if pendiente[
        "tipo"
    ] == "venta":

        # -----------------------------------------------
        # No, fueron 200 soles en total
        # -----------------------------------------------

        if "total" in t:

            numeros = re.findall(
                r"\d+(?:[.,]\d+)?",
                texto
            )

            if numeros:

                total = numero(
                    numeros[-1]
                )

                nuevo[
                    "monto_total"
                ] = total

                nuevo[
                    "precio_unitario"
                ] = (
                    total
                    / nuevo["peso"]
                )

                return nuevo


        # -----------------------------------------------
        # No, fueron 10 soles por kilo
        # -----------------------------------------------

        if (
            "por kilo" in t
            or "por kg" in t
            or "el kilo" in t
        ):

            numeros = re.findall(
                r"\d+(?:[.,]\d+)?",
                texto
            )

            if numeros:

                precio = numero(
                    numeros[-1]
                )

                nuevo[
                    "precio_unitario"
                ] = precio

                nuevo[
                    "monto_total"
                ] = (
                    nuevo["peso"]
                    * precio
                )

                return nuevo


        # -----------------------------------------------
        # Corregir peso
        # -----------------------------------------------

        if (
            "kg" in t
            or "kilo" in t
        ):

            match = re.search(
                r"(\d+(?:[.,]\d+)?)"
                r"\s*(?:kg|kilos?)",
                texto,
                re.IGNORECASE
            )

            if match:

                peso = numero(
                    match.group(1)
                )

                precio = nuevo[
                    "precio_unitario"
                ]

                nuevo[
                    "peso"
                ] = peso

                nuevo[
                    "monto_total"
                ] = (
                    peso
                    * precio
                )

                return nuevo


        # -----------------------------------------------
        # Corregir adelanto
        # -----------------------------------------------

        if "adelanto" in t:

            numeros = re.findall(
                r"\d+(?:[.,]\d+)?",
                texto
            )

            if numeros:

                nuevo[
                    "adelanto"
                ] = numero(
                    numeros[-1]
                )

                return nuevo


    # =====================================================
    # CORREGIR PAGO
    # =====================================================

    if pendiente[
        "tipo"
    ] == "pago":

        if (
            "pago" in t
            or "fueron" in t
            or "era" in t
        ):

            numeros = re.findall(
                r"\d+(?:[.,]\d+)?",
                texto
            )

            if numeros:

                nuevo[
                    "monto"
                ] = numero(
                    numeros[-1]
                )

                return nuevo


    return None


# =========================================================
# QWEN + OLLAMA
# =========================================================

async def interpretar_con_qwen(
    texto,
    clientes
):

    lista_clientes = list(
        clientes.keys()
    )

    prompt = f"""
Eres el intérprete de un bot peruano para registrar ventas,
pagos y consultar deudas.

Tu única tarea es interpretar el mensaje y devolver JSON.

NO expliques nada.
NO escribas markdown.
NO repitas instrucciones.
Devuelve SOLAMENTE un objeto JSON válido y corto.

Mensaje del usuario:

{texto}

Clientes registrados actualmente:

{json.dumps(lista_clientes, ensure_ascii=False)}

Debes devolver exactamente esta estructura:

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

REGLAS:

1. Nunca inventes datos.

2. La moneda es soles peruanos.

3. "Le vendí a Carlos 20 kg a 200 soles"
significa:
peso = 20
monto_total = 200
precio_unitario = 10

4. "Vendí 20 kg a Carlos por 200 soles"
significa que 200 es el monto total.

5. "Carlos compró 20 kg por 200"
significa que 200 es el monto total.

6. "Carlos se llevó 20 kg a 10"
significa:
precio_unitario = 10
monto_total = 200

7. Si dice explícitamente:
"10 por kilo"
"10 por kg"
"el kilo a 10"
entonces 10 es precio_unitario.

8. Si tienes peso y monto_total,
calcula precio_unitario.

9. Si tienes peso y precio_unitario,
calcula monto_total.

10. "Juan me pagó 100"
es una acción "pago".

11. "Cuánto debe Juan"
es "deuda_cliente".

12. "Quién me debe"
es "deudas_todos".

13. "Muéstrame todas las deudas"
es "deudas_todos".

14. "Historial de Juan"
es "historial_cliente".

15. Si falta información indispensable,
usa:
"necesita_aclaracion": true

16. Si el usuario solo conversa,
usa "chat".

17. Tu respuesta debe ser corta.
Solo JSON.
"""

    def llamar_qwen():

        return chat(
            model=MODELO,

            messages=[
                {
                    "role": "user",
                    "content": prompt
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
                "num_ctx": 4096
            }
        )


    try:

        respuesta = await asyncio.to_thread(
            llamar_qwen
        )

        contenido = (
            respuesta.message.content
        )

        resultado = json.loads(
            contenido
        )

        return resultado


    except Exception as error:

        print(
            "ERROR QWEN:",
            error
        )

        return {
            "accion":
                "desconocido",

            "cliente":
                None,

            "peso":
                None,

            "precio_unitario":
                None,

            "monto_total":
                None,

            "adelanto":
                0,

            "monto":
                None,

            "respuesta":
                None,

            "necesita_aclaracion":
                False,

            "pregunta":
                None
        }


# =========================================================
# BOTONES DE CONFIRMACIÓN
# =========================================================

def teclado_confirmacion():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Registrar",
                    callback_data=
                        "confirmar"
                ),

                InlineKeyboardButton(
                    "❌ Cancelar",
                    callback_data=
                        "cancelar"
                )
            ]
        ]
    )


# =========================================================
# TEXTO DE OPERACIÓN
# =========================================================

def texto_operacion(
    pendiente
):

    if pendiente[
        "tipo"
    ] == "venta":

        deuda = (
            pendiente[
                "monto_total"
            ]
            -
            pendiente.get(
                "adelanto",
                0
            )
        )

        return (
            "🧾 <b>Revisa la venta</b>\n\n"

            f"👤 Cliente: "
            f"<b>{pendiente['cliente']}</b>\n"

            f"⚖️ Peso: "
            f"<b>{cantidad(pendiente['peso'])} kg</b>\n"

            f"💰 Precio/kg: "
            f"<b>{dinero(pendiente['precio_unitario'])}</b>\n"

            f"🧮 Total: "
            f"<b>{dinero(pendiente['monto_total'])}</b>\n"

            f"💵 Adelanto: "
            f"<b>{dinero(pendiente.get('adelanto', 0))}</b>\n"

            f"📌 Deuda de esta venta: "
            f"<b>{dinero(deuda)}</b>\n\n"

            "¿La registro?"
        )


    if pendiente[
        "tipo"
    ] == "pago":

        return (
            "💵 <b>Revisa el pago</b>\n\n"

            f"👤 Cliente: "
            f"<b>{pendiente['cliente']}</b>\n"

            f"💰 Pago: "
            f"<b>{dinero(pendiente['monto'])}</b>\n\n"

            "¿Lo registro?"
        )


async def mostrar_pendiente(
    update,
    pendiente
):

    await update.effective_message.reply_text(
        texto_operacion(
            pendiente
        ),

        parse_mode="HTML",

        reply_markup=
            teclado_confirmacion()
    )


# =========================================================
# CONSULTAR DEUDA
# =========================================================

def consultar_deuda(
    nombre,
    clientes
):

    cliente = resolver_cliente(
        nombre,
        clientes
    )

    if not cliente:

        return (
            f"🤔 No encuentro a "
            f"<b>{nombre}</b>."
        )

    deuda = clientes[
        cliente
    ]["deuda"]

    if deuda <= 0:

        return (
            f"✅ <b>{cliente}</b> "
            f"no tiene deuda."
        )

    return (
        f"👤 <b>{cliente}</b>\n"
        f"💰 Debe: "
        f"<b>{dinero(deuda)}</b>"
    )


# =========================================================
# TODAS LAS DEUDAS
# =========================================================

def todas_las_deudas(
    clientes
):

    lista = []

    for cliente, datos in clientes.items():

        deuda = float(
            datos.get(
                "deuda",
                0
            )
        )

        if deuda > 0:

            lista.append(
                (
                    cliente,
                    deuda
                )
            )

    if not lista:

        return (
            "✅ No tienes deudas "
            "pendientes."
        )

    lista.sort(
        key=lambda x: x[1],
        reverse=True
    )

    total = 0

    respuesta = [
        "📋 <b>Deudas pendientes</b>\n"
    ]

    for cliente, deuda in lista:

        total += deuda

        respuesta.append(
            f"• <b>{cliente}</b>: "
            f"{dinero(deuda)}"
        )

    respuesta.append(
        f"\n💰 <b>Total por cobrar: "
        f"{dinero(total)}</b>"
    )

    return "\n".join(
        respuesta
    )


# =========================================================
# HISTORIAL
# =========================================================

def historial_cliente(
    nombre,
    clientes
):

    cliente = resolver_cliente(
        nombre,
        clientes
    )

    if not cliente:

        return (
            f"🤔 No encuentro a "
            f"{nombre}."
        )

    historial = clientes[
        cliente
    ].get(
        "historial",
        []
    )

    if not historial:

        return (
            f"📭 {cliente} no tiene "
            f"movimientos registrados."
        )

    respuesta = [
        f"📚 <b>Historial de "
        f"{cliente}</b>\n"
    ]

    for movimiento in historial[-10:]:

        if movimiento.get(
            "tipo"
        ) == "venta":

            respuesta.append(
                "🟢 Venta - "
                f"{movimiento.get('fecha', '')}\n"

                f"   Total: "
                f"{dinero(movimiento.get('monto_total', 0))}"
            )


        elif movimiento.get(
            "tipo"
        ) == "pago":

            respuesta.append(
                "🔵 Pago - "
                f"{movimiento.get('fecha', '')}\n"

                f"   "
                f"{dinero(movimiento.get('monto', 0))}"
            )


    respuesta.append(
        f"\n📌 Saldo actual: "
        f"<b>{dinero(clientes[cliente]['deuda'])}</b>"
    )

    return "\n".join(
        respuesta
    )


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👋 ¡Hola!\n\n"

        "Soy tu bot de ventas y deudas.\n\n"

        "Puedes escribirme de manera natural.\n\n"

        "Ejemplos:\n\n"

        "🟢 Le vendí a Carlos "
        "20 kg a 200 soles\n\n"

        "🟢 Carlos se llevó "
        "20 kg a 10\n\n"

        "💵 Juan me pagó "
        "100 soles\n\n"

        "🔎 ¿Cuánto debe Carlos?\n\n"

        "📋 Muéstrame todas "
        "las deudas\n\n"

        "📚 Historial de Carlos\n\n"

        "Antes de registrar una "
        "venta o un pago, "
        "te pediré confirmación."
    )


# =========================================================
# BOTONES
# =========================================================

async def botones(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = (
        update.callback_query
    )

    await query.answer()

    user_id = (
        query.from_user.id
    )

    accion = (
        query.data
    )


    # =====================================================
    # CANCELAR OPERACIÓN
    # =====================================================

    if accion == "cancelar":

        context.user_data.pop(
            "pendiente",
            None
        )

        await query.edit_message_text(
            "❌ Operación cancelada."
        )

        return


    # =====================================================
    # CONFIRMAR
    # =====================================================

    if accion == "confirmar":

        pendiente = (
            context.user_data.get(
                "pendiente"
            )
        )

        if not pendiente:

            await query.edit_message_text(
                "⚠️ No hay una operación pendiente."
            )

            return


        # -------------------------------------------------
        # CONFIRMAR VENTA
        # -------------------------------------------------

        if pendiente[
            "tipo"
        ] == "venta":

            cliente, saldo, deuda = (
                registrar_venta(
                    user_id,
                    pendiente
                )
            )

            context.user_data.pop(
                "pendiente",
                None
            )

            await query.edit_message_text(
                "✅ <b>Venta registrada</b>\n\n"

                f"👤 {cliente}\n"

                f"⚖️ "
                f"{cantidad(pendiente['peso'])} kg\n"

                f"💰 Precio/kg: "
                f"{dinero(pendiente['precio_unitario'])}\n"

                f"🧮 Total: "
                f"{dinero(pendiente['monto_total'])}\n"

                f"💵 Adelanto: "
                f"{dinero(pendiente.get('adelanto', 0))}\n"

                f"📌 Deuda generada: "
                f"{dinero(deuda)}\n\n"

                f"💰 Deuda total de "
                f"{cliente}: "
                f"<b>{dinero(saldo)}</b>",

                parse_mode="HTML"
            )

            return


        # -------------------------------------------------
        # CONFIRMAR PAGO
        # -------------------------------------------------

        if pendiente[
            "tipo"
        ] == "pago":

            cliente, saldo = (
                registrar_pago(
                    user_id,
                    pendiente
                )
            )

            context.user_data.pop(
                "pendiente",
                None
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

                parse_mode="HTML"
            )

            return


    # =====================================================
    # BORRAR TODO
    # =====================================================

    if accion == "borrar_todo":

        borrar_todos_los_datos(
            user_id
        )

        context.user_data.pop(
            "pendiente",
            None
        )

        await query.edit_message_text(
            "🗑️ Todos tus clientes, "
            "deudas e historiales "
            "fueron eliminados."
        )

        return


    # =====================================================
    # CANCELAR BORRADO
    # =====================================================

    if accion == "cancelar_borrado":

        await query.edit_message_text(
            "👍 No se borró nada."
        )

        return


# =========================================================
# DETECTAR SOLICITUD DE BORRADO TOTAL
# =========================================================

def quiere_borrar_todo(
    texto
):

    texto = normalizar(
        texto
    )

    frases = [

        "borra todas mis deudas",

        "borra mis deudores",

        "borra el registro de mis deudores",

        "elimina todas mis deudas",

        "elimina todos mis clientes",

        "elimina todo",

        "borra todo",

        "reinicia mis datos"

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
    context: ContextTypes.DEFAULT_TYPE
):

    texto = (
        update.message.text.strip()
    )

    user_id = (
        update.effective_user.id
    )

    clientes = cargar_clientes(
        user_id
    )


    # =====================================================
    # BORRAR TODO
    # =====================================================

    if quiere_borrar_todo(
        texto
    ):

        teclado = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🗑️ Sí, borrar todo",
                        callback_data=
                            "borrar_todo"
                    ),

                    InlineKeyboardButton(
                        "❌ No",
                        callback_data=
                            "cancelar_borrado"
                    )
                ]
            ]
        )

        await update.message.reply_text(
            "⚠️ Esto eliminará "
            "<b>todos tus clientes, "
            "deudas e historiales</b>.\n\n"
            "¿Seguro?",

            parse_mode="HTML",

            reply_markup=teclado
        )

        return


    # =====================================================
    # SI HAY ALGO PENDIENTE
    # =====================================================

    pendiente = (
        context.user_data.get(
            "pendiente"
        )
    )

    if pendiente:

        correccion = (
            corregir_pendiente_directo(
                texto,
                pendiente
            )
        )

        if correccion:

            if correccion.get(
                "cancelar"
            ):

                context.user_data.pop(
                    "pendiente",
                    None
                )

                await update.message.reply_text(
                    "❌ Operación cancelada."
                )

                return


            context.user_data[
                "pendiente"
            ] = correccion

            await update.message.reply_text(
                "✏️ Listo, corregí la operación."
            )

            await mostrar_pendiente(
                update,
                correccion
            )

            return


    # =====================================================
    # PRIMERO INTENTAR VENTA DIRECTA
    # =====================================================

    venta = interpretar_venta_directa(
        texto
    )

    if venta:

        context.user_data[
            "pendiente"
        ] = venta

        await mostrar_pendiente(
            update,
            venta
        )

        return


    # =====================================================
    # DESPUÉS PAGO DIRECTO
    # =====================================================

    pago = interpretar_pago_directo(
        texto
    )

    if pago:

        cliente = resolver_cliente(
            pago["cliente"],
            clientes
        )

        if not cliente:

            await update.message.reply_text(
                "🤔 No encuentro a "
                f"<b>{pago['cliente']}</b> "
                "entre tus clientes.",

                parse_mode="HTML"
            )

            return


        pago[
            "cliente"
        ] = cliente

        context.user_data[
            "pendiente"
        ] = pago

        await mostrar_pendiente(
            update,
            pago
        )

        return


    # =====================================================
    # SI LAS REGLAS NO ENTIENDEN,
    # USAR QWEN
    # =====================================================

    resultado = (
        await interpretar_con_qwen(
            texto,
            clientes
        )
    )

    accion = normalizar(
        resultado.get(
            "accion"
        )
    )


    # =====================================================
    # FALTA INFORMACIÓN
    # =====================================================

    if resultado.get(
        "necesita_aclaracion"
    ):

        await update.message.reply_text(
            resultado.get(
                "pregunta"
            )
            or
            "Necesito un dato más."
        )

        return


    # =====================================================
    # VENTA DESDE QWEN
    # =====================================================

    if accion == "venta":

        cliente = limpiar_nombre(
            resultado.get(
                "cliente"
            )
        )

        peso = numero(
            resultado.get(
                "peso"
            )
        )

        precio = numero(
            resultado.get(
                "precio_unitario"
            )
        )

        total = numero(
            resultado.get(
                "monto_total"
            )
        )

        adelanto = (
            numero(
                resultado.get(
                    "adelanto"
                )
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

            total = (
                peso
                * precio
            )


        if not precio and total:

            precio = (
                total
                / peso
            )


        if not total or not precio:

            await update.message.reply_text(
                "¿Cuál fue el total "
                "o el precio por kilo?"
            )

            return


        pendiente = {
            "tipo":
                "venta",

            "cliente":
                cliente,

            "peso":
                peso,

            "precio_unitario":
                round(
                    precio,
                    4
                ),

            "monto_total":
                round(
                    total,
                    2
                ),

            "adelanto":
                round(
                    adelanto,
                    2
                )
        }

        context.user_data[
            "pendiente"
        ] = pendiente

        await mostrar_pendiente(
            update,
            pendiente
        )

        return


    # =====================================================
    # PAGO DESDE QWEN
    # =====================================================

    if accion == "pago":

        nombre = limpiar_nombre(
            resultado.get(
                "cliente"
            )
        )

        monto = numero(
            resultado.get(
                "monto"
            )
        )

        cliente = resolver_cliente(
            nombre,
            clientes
        )

        if not cliente:

            await update.message.reply_text(
                f"🤔 No encuentro a "
                f"<b>{nombre}</b>.",

                parse_mode="HTML"
            )

            return


        if not monto:

            await update.message.reply_text(
                "¿Cuánto pagó?"
            )

            return


        pendiente = {
            "tipo":
                "pago",

            "cliente":
                cliente,

            "monto":
                monto
        }

        context.user_data[
            "pendiente"
        ] = pendiente

        await mostrar_pendiente(
            update,
            pendiente
        )

        return


    # =====================================================
    # CONSULTAR DEUDA
    # =====================================================

    if accion == "deuda_cliente":

        nombre = limpiar_nombre(
            resultado.get(
                "cliente"
            )
        )

        await update.message.reply_text(
            consultar_deuda(
                nombre,
                clientes
            ),

            parse_mode="HTML"
        )

        return


    # =====================================================
    # TODAS LAS DEUDAS
    # =====================================================

    if accion == "deudas_todos":

        await update.message.reply_text(
            todas_las_deudas(
                clientes
            ),

            parse_mode="HTML"
        )

        return


    # =====================================================
    # HISTORIAL
    # =====================================================

    if accion == "historial_cliente":

        nombre = limpiar_nombre(
            resultado.get(
                "cliente"
            )
        )

        await update.message.reply_text(
            historial_cliente(
                nombre,
                clientes
            ),

            parse_mode="HTML"
        )

        return


    # =====================================================
    # SALUDO
    # =====================================================

    if accion == "saludo":

        await update.message.reply_text(
            "👋 ¡Hola!\n\n"
            "¿Qué venta, pago o deuda "
            "quieres registrar?"
        )

        return


    # =====================================================
    # AYUDA
    # =====================================================

    if accion == "ayuda":

        await update.message.reply_text(
            "Puedes decirme cosas como:\n\n"

            "🟢 Le vendí a Carlos "
            "20 kg a 200 soles\n\n"

            "🟢 Carlos se llevó "
            "20 kg a 10\n\n"

            "💵 Juan me pagó 100\n\n"

            "🔎 Cuánto debe Carlos\n\n"

            "📋 Muéstrame todas "
            "las deudas\n\n"

            "📚 Historial de Carlos"
        )

        return


    # =====================================================
    # CHAT
    # =====================================================

    if accion == "chat":

        respuesta = resultado.get(
            "respuesta"
        )

        if respuesta:

            await update.message.reply_text(
                respuesta
            )

        else:

            await update.message.reply_text(
                "¿Quieres registrar "
                "una venta, un pago "
                "o consultar una deuda?"
            )

        return


    # =====================================================
    # NO ENTENDIDO
    # =====================================================

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
            start
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
            mensaje
        )
    )


    print(
        "Bot encendido..."
    )

    print(
        f"Modelo de IA: {MODELO}"
    )


    app.run_polling()


if __name__ == "__main__":
    main()