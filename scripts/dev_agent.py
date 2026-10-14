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

SYSTEM_INSTRUCTION = """Eres HIVEX DevAgent, un ingeniero senior autónomo de software e IA.
Tu objetivo es resolver con precisión y pulcritud las tareas de desarrollo, corrección de bugs, nuevas features y refactorización solicitadas por Juanma.

Reglas fundamentales de trabajo:
1. Explora y lee siempre el código antes de modificarlo para entender el contexto existente.
2. Realiza cambios quirúrgicos y limpios con replace_file_content.
3. Tras modificar código, ejecuta siempre la suite de pruebas ('pytest tests/ -q') para verificar que no hay regresiones.
4. Si un test falla, analiza el traceback, arregla el fallo y vuelve a verificar.
5. Al concluir, presenta un resumen conciso y profesional de los cambios implementados y los tests pasados.
"""

def execute_agent_loop(
    task: str,
    api_key: str,
    max_steps: int = 15,
    chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    reply_to_message_id: Optional[int] = None
) -> str:
    """Bucle agente de razonamiento y ejecución con Gemini."""
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-pro",
        "gemini-1.5-flash"
    ]
    
    contents: List[Dict[str, Any]] = [
        {
            "role": "user",
            "parts": [{"text": f"TAREA DE DESARROLLO:\n{task}\n\nPor favor, investiga los archivos pertinentes, aplica los cambios necesarios, corre los tests para verificar y concluye con un resumen."}]
        }
    ]

    print(f"🚀 Iniciando HIVEX DevAgent para la tarea: {task}")
    send_telegram_update(
        f"🤖 <b>DevAgent Activo:</b> Comenzando investigación autónoma para:\n<i>{html.escape(task)}</i>",
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
                "maxOutputTokens": 4096
            }
        }

        resp_data = None
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                with httpx.Client(timeout=60.0) as client:
                    r = client.post(url, json=payload)
                    if r.status_code == 200:
                        resp_data = r.json()
                        break
                    elif r.status_code in (429, 503):
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
        text_parts = [p["text"] for p in parts if "text" in p]

        if text_parts:
            print("DevAgent:", " ".join(text_parts))

        if not function_calls:
            print("✅ El DevAgent ha completado la tarea sin más llamadas a herramientas.")
            final_summary = "\n".join(text_parts)
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
                f"{icon} <b>[Paso {step}/{max_steps}]</b> {fname} {target_desc}",
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

        # Añadir respuestas de función al historial
        contents.append({
            "role": "function",
            "parts": function_response_parts
        })

    limit_msg = "DevAgent alcanzó el límite de pasos máximos (15). Por favor revisa los logs."
    send_telegram_update(f"⏳ {limit_msg}", chat_id, bot_token, reply_to_message_id)
    return limit_msg

def main():
    parser = argparse.ArgumentParser(description="HIVEX DevAgent Autonomous Runner")
    parser.add_argument("--task", type=str, required=True, help="Descripción de la tarea de desarrollo")
    parser.add_argument("--chat-id", type=str, default="", help="Chat ID de Telegram para actualizaciones en vivo")
    parser.add_argument("--message-id", type=str, default="", help="Message ID de Telegram para responder")
    parser.add_argument("--telegram-token", type=str, default="", help="Token del bot de Telegram")
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Error: Se requiere GEMINI_API_KEY o GOOGLE_API_KEY en el entorno.", file=sys.stderr)
        sys.exit(1)

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
