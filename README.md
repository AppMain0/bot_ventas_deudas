# 🤖 Telegram Sales & Debt Bot

Bot de Telegram desarrollado en Python para registrar ventas, pagos y deudas utilizando lenguaje natural.

El bot permite llevar un control simple de clientes y saldos pendientes directamente desde Telegram. Para interpretar mensajes utiliza reglas determinísticas para operaciones comunes y un modelo local de inteligencia artificial mediante Ollama y Qwen como respaldo.

---

## ✨ Funcionalidades

- Registrar ventas utilizando lenguaje natural.
- Registrar pagos de clientes.
- Calcular automáticamente precio por kilogramo y monto total.
- Registrar adelantos.
- Consultar la deuda de un cliente.
- Mostrar todas las deudas pendientes.
- Consultar el historial de movimientos de un cliente.
- Corregir una operación antes de registrarla.
- Confirmar o cancelar ventas y pagos mediante botones.
- Eliminar todos los registros con confirmación.
- Buscar clientes aunque el nombre no sea escrito exactamente igual.
- Mantener información independiente para cada usuario de Telegram.
- Utilizar Qwen como fallback cuando las reglas directas no logran interpretar un mensaje.

---

## 💬 Ejemplos de uso

### Registrar una venta

```text
Le vendí a Carlos 20 kg a 200 soles
```

El bot interpreta:

```text
Cliente: Carlos
Peso: 20 kg
Precio/kg: S/ 10.00
Total: S/ 200.00
```

También puede entender:

```text
Vendí 20 kg a Carlos por 200 soles
```

```text
Carlos compró 20 kg por 200
```

```text
Carlos se llevó 20 kg a 10
```

---

### Registrar un adelanto

```text
Le vendí a Carlos 20 kg a 200 soles con 50 de adelanto
```

El bot calculará automáticamente la deuda restante.

---

### Registrar un pago

```text
Carlos me pagó 50
```

Antes de registrar el pago, el bot solicitará confirmación.

---

### Consultar una deuda

```text
Cuánto debe Carlos
```

---

### Consultar todas las deudas

```text
Quién me debe
```

o:

```text
Muéstrame todas las deudas
```

---

### Consultar historial

```text
Historial de Carlos
```

---

## 🧠 Inteligencia artificial

El bot utiliza:

- **Ollama**
- **Qwen3 4B**

Modelo configurado:

```text
qwen3:4b
```

Las operaciones más comunes primero intentan ser interpretadas directamente mediante Python y expresiones regulares.

Si estas reglas no logran entender el mensaje, el bot utiliza Qwen como intérprete de lenguaje natural.

Esto permite reducir el uso innecesario del modelo y hacer más rápidas las operaciones comunes.

---

## 🛠️ Tecnologías

- Python
- Telegram Bot API
- python-telegram-bot
- Ollama
- Qwen3
- python-dotenv
- JSON
- Regex

---

## 📁 Estructura

```text
bot_ventas_deudas/
│
├── bot.py
├── .env
├── .gitignore
└── clientes_<telegram_user_id>.json
```

### `bot.py`

Contiene la lógica principal del bot.

### `.env`

Contiene variables privadas, como el token de Telegram.

Este archivo **no debe subirse a GitHub**.

### `.gitignore`

Evita subir archivos privados o temporales al repositorio.

### `clientes_<telegram_user_id>.json`

Archivo generado automáticamente para almacenar los clientes, movimientos y deudas de cada usuario.

Cada usuario de Telegram mantiene su propia información.

---

## 🚀 Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/AppMain0/bot_ventas_deudas.git
```

Entrar al proyecto:

```bash
cd bot_ventas_deudas
```

---

### 2. Instalar dependencias de Python

```bash
python -m pip install python-telegram-bot ollama python-dotenv
```

---

### 3. Instalar Ollama

Instala Ollama en el equipo donde se ejecutará el bot.

Después descarga el modelo:

```bash
ollama pull qwen3:4b
```

Puedes comprobar los modelos disponibles con:

```bash
ollama list
```

---

## 🔐 Configuración del token

Crea un archivo llamado:

```text
.env
```

Dentro coloca:

```env
TELEGRAM_BOT_TOKEN=TU_TOKEN_DE_TELEGRAM
```

El token puede obtenerse creando un bot mediante **BotFather** en Telegram.

Nunca escribas el token directamente dentro de `bot.py`.

Nunca subas el archivo `.env` a GitHub.

---

## ▶️ Ejecutar el bot

Con Ollama funcionando y el archivo `.env` configurado:

```bash
python bot.py
```

Si todo está correctamente configurado aparecerá:

```text
Bot encendido...
Modelo de IA: qwen3:4b
```

Después puedes abrir Telegram y comenzar a utilizar el bot.

---

## 💾 Almacenamiento

Actualmente la información se almacena localmente mediante archivos JSON.

Cada usuario tiene un archivo independiente:

```text
clientes_<telegram_user_id>.json
```

Ejemplo:

```text
clientes_123456789.json
```

El archivo contiene:

- Clientes.
- Deuda actual.
- Historial de ventas.
- Historial de pagos.

Estos archivos están excluidos de Git mediante `.gitignore`.

---

## 🔒 Seguridad

El token de Telegram se carga mediante una variable de entorno:

```python
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
```

Por seguridad:

- No publiques tokens.
- No subas `.env`.
- Si un token se publica accidentalmente, revócalo inmediatamente desde BotFather.
- No subas los archivos JSON que contienen información de los usuarios.

---

## ⚙️ Flujo del bot

```text
Mensaje de Telegram
        │
        ▼
Interpretación directa con Python
        │
        ├── Entendido ──► Confirmación ──► Guardar
        │
        └── No entendido
                │
                ▼
            Qwen / Ollama
                │
                ▼
          Interpretar mensaje
                │
                ▼
           Confirmación
                │
                ▼
              Guardar
```

---

## 📌 Limitaciones actuales

- Los datos se almacenan localmente en JSON.
- Ollama debe estar ejecutándose para utilizar Qwen.
- El modelo debe estar instalado en el equipo donde corre el bot.
- El bot actualmente utiliza almacenamiento local y no una base de datos externa.
- La interpretación depende de las reglas implementadas y de la respuesta del modelo cuando se utiliza Qwen.

---

## 🔮 Posibles mejoras

- Migrar los datos a PostgreSQL o SQLite.
- Crear reportes de ventas.
- Añadir estadísticas por cliente.
- Añadir ventas por fecha.
- Añadir exportación a Excel.
- Añadir copias de seguridad.
- Crear panel web.
- Desplegar el bot para funcionamiento 24/7.

---

## 👤 Autor

Proyecto desarrollado como bot personal para automatizar el registro y seguimiento de ventas, pagos y deudas mediante Telegram.

---

## 📄 Licencia

Proyecto de uso personal y educativo.