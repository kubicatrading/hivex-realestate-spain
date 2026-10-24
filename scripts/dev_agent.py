#!/usr/bin/env python3
"""
HIVEX Autonomous DevAgent Runner
Ejecuta tareas de desarrollo autónomas (lectura, búsqueda, edición de archivos y comandos de prueba)
utilizando la API de Gemini (Google Generative AI) con Function Calling nativo.
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Any
import httpx
import html
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

def send_telegram_update(
    text: str,
    chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    reply_to_message_id: Optional[int] = None
) -> None:
    """Envía actualizaciones de progreso en tiempo real al chat de Telegram del usuario."""
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not chat_id or not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = int(reply_to_message_id)
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(url, json=payload)
    except Exception as e:
        print(f"Aviso: No se pudo enviar actualización a Telegram: {e}")

# -----------------------------------------------------------------------------
# HERRAMIENTAS (TOOLS) DEL DEVAGENT
# -----------------------------------------------------------------------------

def tool_list_files(directory: str = ".") -> str:
    """Lista archivos y directorios respetando exclusiones estándar."""
    target = (REPO_ROOT / directory).resolve()
    if not target.is_relative_to(REPO_ROOT):
        return "Error: Acceso fuera del repositorio no permitido."
    if not target.exists():
        return f"Error: El directorio '{directory}' no existe."
    
    entries = []
    ignored = {".git", "__pycache__", "venv", ".pytest_cache", ".mypy_cache", "node_modules"}
    for item in sorted(target.iterdir()):
        if item.name in ignored:
            continue
        kind = "DIR " if item.is_dir() else "FILE"
        entries.append(f"[{kind}] {item.relative_to(REPO_ROOT)}")
    return "\n".join(entries[:150])

def tool_read_file(path: str, start_line: int = 1, end_line: int = 400) -> str:
    """Lee el contenido de un archivo dentro del repositorio."""
    target = (REPO_ROOT / path).resolve()
    if not target.is_relative_to(REPO_ROOT):
        return "Error: Acceso fuera del repositorio no permitido."
    if not target.exists() or not target.is_file():
        return f"Error: El archivo '{path}' no existe."
    
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        total_lines = len(lines)
        start = max(1, start_line)
        end = min(total_lines, end_line)
        output = [f"File: {path} (Lines {start}-{end} of {total_lines})"]
        for idx in range(start - 1, end):
            output.append(f"{idx + 1:4d}: {lines[idx]}")
        return "\n".join(output)
    except Exception as e:
        return f"Error leyendo archivo: {e}"

def tool_search_code(query: str, directory: str = ".") -> str:
    """Busca ocurrencias de texto o regex dentro de archivos del repositorio."""
    target = (REPO_ROOT / directory).resolve()
    if not target.is_relative_to(REPO_ROOT):
        return "Error: Acceso fuera del repositorio no permitido."
    
    cmd = ["grep", "-rnI", "--exclude-dir=.git", "--exclude-dir=venv", "--exclude-dir=__pycache__", query, str(target)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        out = proc.stdout.strip()
        if not out:
            return "No se encontraron coincidencias."
        # Normalizar rutas relativas al repo
        lines = out.splitlines()
        rel_lines = [l.replace(str(REPO_ROOT) + "/", "") for l in lines]
        return "\n".join(rel_lines[:60])
    except Exception as e:
        return f"Error en búsqueda: {e}"

def tool_replace_file_content(path: str, target_content: str, replacement_content: str) -> str:
    """Reemplaza un bloque de texto exacto dentro de un archivo."""
    target = (REPO_ROOT / path).resolve()
    if not target.is_relative_to(REPO_ROOT):
        return "Error: Acceso fuera del repositorio no permitido."
    if not target.exists() or not target.is_file():
        return f"Error: El archivo '{path}' no existe."
    
    try:
        content = target.read_text(encoding="utf-8")
        if target_content not in content:
            return f"Error: No se encontró target_content exacto en '{path}'. Verifica espacios y saltos de línea."
        count = content.count(target_content)
        if count > 1:
            return f"Error: target_content aparece {count} veces en '{path}'. Debe ser unívoco."
        new_content = content.replace(target_content, replacement_content, 1)
        target.write_text(new_content, encoding="utf-8")
        return f"Éxito: Archivo '{path}' modificado correctamente."
    except Exception as e:
        return f"Error reemplazando contenido: {e}"

def tool_write_file(path: str, content: str) -> str:
    """Crea o sobreescribe un archivo completo dentro del repositorio."""
    target = (REPO_ROOT / path).resolve()
    if not target.is_relative_to(REPO_ROOT):
        return "Error: Acceso fuera del repositorio no permitido."
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Éxito: Archivo '{path}' guardado correctamente."
    except Exception as e:
        return f"Error escribiendo archivo: {e}"

def tool_run_command(command: str) -> str:
    """Ejecuta un comando en la terminal dentro de la raíz del repositorio."""
    # Lista blanca o sanitización básica
    forbidden = ["rm -rf /", ":(){ :|:& };:", "mkfs", "dd if="]
    if any(f in command for f in forbidden):
        return "Error: Comando peligroso bloqueado por seguridad."
    
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120
        )
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return f"Exit code: {proc.returncode}\n{out.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: El comando superó el límite de tiempo de 120s."
    except Exception as e:
        return f"Error ejecutando comando: {e}"

TOOLS_MAP = {
    "list_files": tool_list_files,
    "read_file": tool_read_file,
    "search_code": tool_search_code,
    "replace_file_content": tool_replace_file_content,
    "write_file": tool_write_file,
    "run_command": tool_run_command,
}

GEMINI_TOOLS_DECLARATION = [{
    "functionDeclarations": [
        {
            "name": "list_files",
            "description": "Lista archivos y carpetas del repositorio.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "directory": {"type": "STRING", "description": "Directorio relativo (defecto '.')"}
                }
            }
        },
        {
            "name": "read_file",
            "description": "Lee el contenido con números de línea de un archivo.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING", "description": "Ruta relativa del archivo"},
                    "start_line": {"type": "INTEGER", "description": "Línea inicial (1-indexed)"},
                    "end_line": {"type": "INTEGER", "description": "Línea final"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "search_code",
            "description": "Busca ocurrencias de código o texto con grep.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {"type": "STRING", "description": "Texto a buscar"},
                    "directory": {"type": "STRING", "description": "Directorio relativo donde buscar"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "replace_file_content",
            "description": "Reemplaza un bloque de código exacto en un archivo existente.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING", "description": "Ruta relativa del archivo"},
                    "target_content": {"type": "STRING", "description": "Texto exacto a reemplazar"},
                    "replacement_content": {"type": "STRING", "description": "Nuevo texto de sustitución"}
                },
                "required": ["path", "target_content", "replacement_content"]
            }
        },
        {
            "name": "write_file",
            "description": "Crea o sobreescribe un archivo en el repositorio.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING", "description": "Ruta relativa del archivo"},
                    "content": {"type": "STRING", "description": "Contenido completo del archivo"}
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "run_command",
            "description": "Ejecuta un comando bash en la raíz del repositorio (ej. 'pytest tests/ -v', 'git status', etc.).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "command": {"type": "STRING", "description": "Comando a ejecutar en la terminal"}
                },
                "required": ["command"]
            }
        }
    ]
}]

SYSTEM_INSTRUCTION = """Eres HIVEX DevAgent (núcleo autónomo equivalente a Antigravity), un Ingeniero Principal de Software e IA encargado de mantener, depurar y evolucionar la plataforma HIVEX Real Estate Spain en producción.

MAPA DE ARQUITECTURA DEL REPOSITORIO HIVEX:
- `app/services/telegram_advisor_bot.py`: Bot conversacional de Telegram, autenticación (`verify_or_link_user`), manejo de grupos (`-1003904392737`), comandos (`/dev`, `/alertas`, `/vincular`), memoria conversacional y despacho de fichas visuales.
- `app/engine/advisor_engine.py`: Motor asesor inmobiliario IA, extracción heurística y semántica de criterios (`_parse_query_intent_heuristics`), búsqueda universal de zonas (barrios, urbanizaciones, PAUs, ensanches, CPs, municipios), fallback a portales en vivo (`market_scraper`), scoring y generación de respuestas.
- `app/services/market_scraper.py`: Conector multi-portal en tiempo real (Idealista, Fotocasa, Habitaclia, Pisos.com, Subastas BOE) y gestión de catálogo verificado.
- `app/services/whatsapp_card_renderer.py`: Renderizado gráfico de tarjetas PNG para Telegram/WhatsApp.
- `app/services/alert_engine.py` y `app/services/consultation_alerts_worker.py`: Motor de alertas inmobiliarias y worker diario.
- `app/api/main.py`: Endpoints FastAPI, webhook de Telegram (`/api/v1/telegram/webhook`), endpoints de oportunidades, consultas, autenticación y panel de administración.
- `app/db/models.py` y `app/db/session.py`: Modelos SQLAlchemy (`User`, `PropertyOpportunity`, `UserConsultation`, `TelegramConversationMessage`) y sesión PostgreSQL/SQLite.
- `static/index.html`, `static/app.js`, `static/styles.css`: Frontend web de la plataforma HIVEX.
- `tests/`: Suite de tests unitarios e integración con `pytest`.

PROTOCOLO ESTRICTO DE INGENIERÍA (ANTI-ALUCINACIONES):
1. DIAGNÓSTICO REAL ANTES DE TOCAR CÓDIGO (CÓDIGO + PRODUCCIÓN EN VIVO):
   - Usa `search_code` y `read_file` para localizar exactamente la causa raíz en el código antes de proponer cualquier cambio.
   - Si el usuario reporta que el bot de Telegram, una búsqueda o la web en producción no responde o falla, NO te limites a leer código estático: usa `run_command` para inspeccionar el estado real en producción (`curl -s https://hivex-realestate-spain.vercel.app/api/v1/telegram/status`, `curl -s https://hivex-realestate-spain.vercel.app/api/v1/consultations | head -c 2000`, etc.) y contrasta los datos reales con el código.
   - Nunca adivines nombres de funciones, variables ni rutas; compruébalos leyendo el archivo.
2. CAMBIOS QUIRÚRGICOS Y LIMPIOS:
   - Usa `replace_file_content` únicamente en las líneas necesarias.
   - PROHIBIDO modificar archivos de datos (`app/data/*.json`, `hivex_local.db`) salvo que la tarea pida explícitamente actualizar datos estáticos.
3. VERIFICACIÓN Y LIMPIEZA PRE-COMMIT:
   - Ejecuta `pytest tests/ -q` mediante `run_command` para validar tus cambios.
   - Si al correr `pytest` algún test modifica archivos colaterales como `app/data/verified_market_catalog.json`, `app/data/supadata_backfill_quota.json` o `hivex_local.db`, ejecuta `git checkout -- app/data/ hivex_local.db` antes de terminar para que el commit contenga EXCLUSIVAMENTE tu fix de código.
   - Ejecuta `git status -s` y `git diff --stat` con `run_command` antes de finalizar para confirmar que solo quedan modificados los archivos pertinentes a la tarea.
4. COMUNICACIÓN CLARA CON EL USUARIO:
   - Explica siempre: (a) Cuál era la causa raíz exacta, (b) Qué archivos y líneas has modificado, y (c) Cómo lo has verificado con tests.
"""

def execute_agent_loop(
    task: str,
    api_key: str,
    max_steps: int = 25,
    chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    reply_to_message_id: Optional[int] = None
) -> str:
    """Bucle agente de razonamiento y ejecución con Gemini."""
    models_to_try = [
        "gemini-4-argon",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-2.5-pro",
    ]
    candidate_keys: List[str] = []
    for k in [os.getenv("PAID_GEMINI_API_KEY", ""), api_key, os.getenv("GEMINI_API_KEY", ""), os.getenv("GOOGLE_API_KEY", "")]:
        k_clean = (k or "").strip()
        if k_clean and k_clean not in candidate_keys:
            candidate_keys.append(k_clean)

    unavailable_pairs = set()
    active_model = models_to_try[0]
    
    contents: List[Dict[str, Any]] = [
        {
            "role": "user",
            "parts": [{"text": (
                f"TAREA DE DESARROLLO SOLICITADA POR EL USUARIO DESDE TELEGRAM:\n{task}\n\n"
                "Sigue el protocolo estricto: 1) Investiga el código real y el estado en vivo de producción si aplica, "
                "2) Identifica la causa raíz sin alucinar, 3) Aplica el cambio quirúrgico, 4) Corre pytest, "
                "5) Limpia cualquier archivo colateral en app/data/ o hivex_local.db con git checkout si no era parte de la tarea, "
                "y 6) Devuelve un informe claro y detallado de la solución."
            )}]
        }
    ]

    print(f"🚀 Iniciando HIVEX DevAgent para la tarea: {task}")
    send_telegram_update(
        f"🤖 <b>DevAgent Activo (Gemini 4 Argon):</b> Analizando código para:\n<i>{html.escape(task)}</i>",
        chat_id, bot_token, reply_to_message_id
    )
    
    for step in range(1, max_steps + 1):
        print(f"\n--- [Paso {step}/{max_steps}] Razonando con Gemini ---")
        
        payload = {
            "contents": contents,
            "tools": GEMINI_TOOLS_DECLARATION,
            "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 8192
            }
        }

        resp_data = None
        for model in models_to_try:
            if resp_data is not None:
                break
            for key_idx, cand_key in enumerate(candidate_keys):
                if (model, key_idx) in unavailable_pairs:
                    continue
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={cand_key}"
                try:
                    with httpx.Client(timeout=90.0) as client:
                        r = client.post(url, json=payload)
                        if r.status_code == 200:
                            resp_data = r.json()
                            active_model = model
                            print(f"✅ Respuesta obtenida con modelo: {active_model} (key #{key_idx + 1})")
                            break
                        elif r.status_code in (429, 503):
                            continue
                        elif r.status_code in (403, 404):
                            print(f"Aviso API ({model} con key #{key_idx + 1} devolvió {r.status_code}): probando siguiente credencial/modelo.")
                            unavailable_pairs.add((model, key_idx))
                            continue
                        else:
                            print(f"Aviso API ({model}): {r.status_code} - {r.text[:150]}")
                except Exception as e:
                    print(f"Error de red con modelo {model}: {e}")
                    continue

        if not resp_data:
            err_msg = "Error: No se pudo obtener respuesta válida de Gemini API tras evaluar la cascada de modelos."
            send_telegram_update(f"❌ {err_msg}", chat_id, bot_token, reply_to_message_id)
            return err_msg

        candidate = resp_data.get("candidates", [{}])[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        
        # Guardar en historial la respuesta del modelo
        contents.append(content)

        function_calls = [p["functionCall"] for p in parts if "functionCall" in p]
        text_parts = [p["text"] for p in parts if "text" in p and not p.get("thought")]

        if text_parts:
            thought_text = "\n".join(text_parts).strip()
            print("DevAgent:", thought_text)
            if function_calls and len(thought_text) > 10:
                short_thought = thought_text[:500] + ("..." if len(thought_text) > 500 else "")
                send_telegram_update(
                    f"💭 <i>{html.escape(short_thought)}</i>",
                    chat_id, bot_token, reply_to_message_id
                )

        if not function_calls:
            print("✅ El DevAgent ha completado la tarea sin más llamadas a herramientas.")
            final_summary = "\n".join(text_parts).strip()
            if final_summary:
                try:
                    Path("/tmp/dev_agent_summary.txt").write_text(final_summary, encoding="utf-8")
                except Exception:
                    pass
                send_telegram_update(
                    f"📋 <b>Informe Técnico de DevAgent ({html.escape(active_model)}):</b>\n\n{html.escape(final_summary[:3500])}",
                    chat_id, bot_token, reply_to_message_id
                )
            return final_summary

        # Ejecutar function calls solicitadas
        function_response_parts = []
        for fc in function_calls:
            fname = fc.get("name")
            fargs = fc.get("args") or {}
            print(f"🔧 Ejecutando herramienta: {fname}({json.dumps(fargs, ensure_ascii=False)})")

            # Notificar acción a Telegram
            icons = {
                "read_file": "🔍",
                "replace_file_content": "✏️",
                "write_file": "📝",
                "run_command": "⚡",
                "search_code": "🔎",
                "list_files": "📁"
            }
            icon = icons.get(fname, "🔧")
            target_desc = ""
            if fname in ("read_file", "replace_file_content", "write_file"):
                target_desc = f"<code>{fargs.get('path', '')}</code>"
            elif fname == "run_command":
                target_desc = f"<code>{fargs.get('command', '')}</code>"
            elif fname == "search_code":
                target_desc = f"«{html.escape(fargs.get('query', ''))}»"

            send_telegram_update(
                f"{icon} <b>[Paso {step}/{max_steps} · {html.escape(active_model)}]</b> {fname} {target_desc}",
                chat_id, bot_token, reply_to_message_id
            )
            
            tool_func = TOOLS_MAP.get(fname)
            if not tool_func:
                result_str = f"Error: Herramienta '{fname}' no encontrada."
            else:
                try:
                    result_str = tool_func(**fargs)
                except Exception as ex:
                    result_str = f"Error en ejecución: {ex}"

            # Si es ejecución de comando (ej: pytest) y falló, reportar a Telegram para feedback transparente
            if fname == "run_command" and ("FAILED" in result_str or "AssertionError" in result_str or "exit code 1" in result_str.lower()):
                err_lines = [l for l in result_str.splitlines() if "FAILED" in l or "AssertionError" in l or "Error:" in l][:4]
                err_summary = "\n".join(err_lines)
                send_telegram_update(
                    f"⚠️ <b>Aviso en tests:</b>\n<pre>{html.escape(err_summary)}</pre>\n<i>DevAgent analizando el fallo para autocorregirlo...</i>",
                    chat_id, bot_token, reply_to_message_id
                )

            # Truncar salida si es excesiva
            if len(result_str) > 8000:
                result_str = result_str[:8000] + "\n...[salida truncada]..."

            function_response_parts.append({
                "functionResponse": {
                    "name": fname,
                    "response": {"result": result_str}
                }
            })

        # Añadir respuestas de función al historial (en Gemini generateContent REST API, functionResponse exige role='user')
        contents.append({
            "role": "user",
            "parts": function_response_parts
        })

    # Si se alcanzó max_steps, forzar una llamada final de síntesis SIN herramientas para responder siempre al usuario
    try:
        contents.append({
            "role": "user",
            "parts": [{"text": (
                "Has alcanzado el límite de pasos de exploración. Con toda la información recopilada hasta ahora, "
                "redacta inmediatamente tu diagnóstico técnico completo y la respuesta detallada para el usuario."
            )}]
        })
        synth_payload = {
            "contents": contents,
            "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096}
        }
        for model in models_to_try:
            for key_idx, cand_key in enumerate(candidate_keys):
                if (model, key_idx) in unavailable_pairs:
                    continue
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={cand_key}"
                with httpx.Client(timeout=60.0) as client:
                    r = client.post(url, json=synth_payload)
                    if r.status_code == 200:
                        cand = r.json().get("candidates", [{}])[0]
                        t_parts = [p["text"] for p in cand.get("content", {}).get("parts", []) if "text" in p and not p.get("thought")]
                        final_summary = "\n".join(t_parts).strip()
                        if final_summary:
                            Path("/tmp/dev_agent_summary.txt").write_text(final_summary, encoding="utf-8")
                            send_telegram_update(
                                f"📋 <b>Informe Técnico de DevAgent ({html.escape(model)}):</b>\n\n{html.escape(final_summary[:3500])}",
                                chat_id, bot_token, reply_to_message_id
                            )
                            return final_summary
    except Exception as e_synth:
        print(f"Aviso en síntesis final: {e_synth}")

    limit_msg = "DevAgent alcanzó el límite de pasos máximos (25). Por favor revisa los logs."
    send_telegram_update(f"⏳ {limit_msg}", chat_id, bot_token, reply_to_message_id)
    return limit_msg

def main():
    parser = argparse.ArgumentParser(description="HIVEX DevAgent Autonomous Runner")
    parser.add_argument("--task", type=str, required=True, help="Descripción de la tarea de desarrollo")
    parser.add_argument("--chat-id", type=str, default="", help="Chat ID de Telegram para actualizaciones en vivo")
    parser.add_argument("--message-id", type=str, default="", help="Message ID de Telegram para responder")
    parser.add_argument("--telegram-token", type=str, default="", help="Token del bot de Telegram")
    args = parser.parse_args()

    api_key = os.getenv("PAID_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    bot_token = args.telegram_token or os.getenv("TELEGRAM_BOT_TOKEN")
    msg_id = int(args.message_id) if args.message_id and args.message_id.isdigit() else None

    result = execute_agent_loop(
        task=args.task,
        api_key=api_key,
        chat_id=args.chat_id or None,
        bot_token=bot_token or None,
        reply_to_message_id=msg_id
    )
    print("\n" + "="*60)
    print("RESUMEN FINAL DEVAGENT:")
    print("="*60)
    print(result)

if __name__ == "__main__":
    main()
