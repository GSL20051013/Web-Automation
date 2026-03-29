"""
example.py – Demonstrates how to use the ai_browser package.

Quick-start
-----------
1. Install dependencies:
        pip install -r requirements.txt

   Google Chrome must be installed on your system (https://www.google.com/chrome/).
   No extra `playwright install` step is needed – Playwright uses the system Chrome directly.

2. First run – log in to Google AI Studio (browser window will open):
        python example.py --login

3. Subsequent runs – headless (no window):
        python example.py

Advanced usage examples
-----------------------
# Set a system instruction before chatting:
        python example.py --system "You are a helpful pirate. Respond in pirate speak."

# Adjust temperature (0.0 = deterministic, 2.0 = very creative):
        python example.py --temperature 0.7

# Set thinking level (None, Low, Medium, High):
        python example.py --thinking High

# Enable grounding with Google Search:
        python example.py --grounding

# Enable grounding with Google Maps:
        python example.py --maps-grounding

# Enable URL context (model can read URLs in the prompt):
        python example.py --url-context

# Enable code execution (model can run Python code):
        python example.py --code-execution

# Enable function calling:
        python example.py --function-calling

# Define function declarations (JSON file or inline JSON):
        python example.py --function-declarations '[{"name":"get_weather","description":"Get weather","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}]'

# Enable structured output:
        python example.py --structured-output

# Provide a JSON schema for structured output:
        python example.py --output-schema '{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}'

# Attach a file to the prompt:
        python example.py --file /path/to/image.png --prompt "Describe this image."

# Save a debug screenshot:
        python example.py --screenshot debug.png
"""

import argparse
import json

import ai_browser
from ai_browser import AIStudio


def main() -> None:
    parser = argparse.ArgumentParser(description="ai_browser example – Google AI Studio")
    parser.add_argument(
        "--login",
        action="store_true",
        help="Open a visible browser window so you can log in (required on first run).",
    )
    parser.add_argument(
        "--prompt",
        default="Explain what a large language model is in one short paragraph.",
        help="Prompt to send to the AI.",
    )
    parser.add_argument(
        "--system",
        metavar="TEXT",
        default="",
        help="System instructions to set before sending the prompt.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Model temperature in [0.0, 2.0]. Lower = more deterministic.",
    )
    parser.add_argument(
        "--thinking",
        choices=list(ai_browser.THINKING_LEVELS),
        default=None,
        metavar="LEVEL",
        help="Thinking level for supported models (None/Low/Medium/High).",
    )
    parser.add_argument(
        "--grounding",
        action="store_true",
        help="Enable Grounding with Google Search.",
    )
    parser.add_argument(
        "--maps-grounding",
        action="store_true",
        help="Enable Grounding with Google Maps.",
    )
    parser.add_argument(
        "--url-context",
        action="store_true",
        help="Enable URL Context (model can fetch and read URLs in the prompt).",
    )
    parser.add_argument(
        "--code-execution",
        action="store_true",
        help="Enable Code Execution (model can run Python code).",
    )
    parser.add_argument(
        "--function-calling",
        action="store_true",
        help="Enable Function Calling tool.",
    )
    parser.add_argument(
        "--function-declarations",
        metavar="JSON",
        default="",
        help=(
            "JSON array of FunctionDeclaration objects. "
            "Automatically enables function calling."
        ),
    )
    parser.add_argument(
        "--structured-output",
        action="store_true",
        help="Enable Structured Outputs.",
    )
    parser.add_argument(
        "--output-schema",
        metavar="JSON",
        default="",
        help=(
            "JSON schema for structured output. "
            "Automatically enables structured outputs."
        ),
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        default="",
        help="Path to a file (image, video, audio, document) to attach to the prompt.",
    )
    parser.add_argument(
        "--screenshot",
        metavar="PATH",
        default="",
        help="Save a screenshot to this path after the response (e.g. debug.png).",
    )
    args = parser.parse_args()

    headless = not args.login

    print(f"[example] Starting AI Studio client (headless={headless}) …")
    with AIStudio(headless=False) as ai:

        # Optional: set system instructions.
        if args.system:
            print(f"[example] Setting system instructions: {args.system!r}")
            ai.set_system_instructions(args.system)

        # Optional: adjust temperature.
        if args.temperature is not None:
            print(f"[example] Setting temperature to {args.temperature}")
            ai.set_temperature(args.temperature)

        # Optional: set thinking level.
        if args.thinking is not None:
            print(f"[example] Setting thinking level to {args.thinking!r}")
            ai.set_thinking_level(args.thinking)

        # Optional: enable grounding with Google Search.
        if args.grounding:
            print("[example] Enabling Grounding with Google Search …")
            ai.set_grounding(True)

        # Optional: enable grounding with Google Maps.
        if args.maps_grounding:
            print("[example] Enabling Grounding with Google Maps …")
            ai.set_maps_grounding(True)

        # Optional: enable URL context.
        if args.url_context:
            print("[example] Enabling URL Context …")
            ai.set_url_context(True)

        # Optional: enable code execution.
        if args.code_execution:
            print("[example] Enabling Code Execution …")
            ai.set_code_execution(True)

        # Optional: enable function calling.
        if args.function_calling and not args.function_declarations:
            print("[example] Enabling Function Calling …")
            ai.set_function_calling(True)

        # Optional: set function declarations (also enables function calling).
        if args.function_declarations:
            # Validate JSON early so parser.error() can print a clean CLI error
            # before the browser is started, giving a better user experience.
            try:
                json.loads(args.function_declarations)
            except json.JSONDecodeError as exc:
                parser.error(f"--function-declarations is not valid JSON: {exc}")
            print("[example] Setting function declarations …")
            ai.set_function_declarations(args.function_declarations)

        # Optional: enable structured output.
        if args.structured_output and not args.output_schema:
            print("[example] Enabling Structured Outputs …")
            ai.set_structured_output(True)

        # Optional: set output schema (also enables structured output).
        if args.output_schema:
            # Validate JSON early so parser.error() can print a clean CLI error
            # before the browser is started, giving a better user experience.
            try:
                json.loads(args.output_schema)
            except json.JSONDecodeError as exc:
                parser.error(f"--output-schema is not valid JSON: {exc}")
            print("[example] Setting structured output schema …")
            ai.set_structured_output_schema(args.output_schema)

        # Optional: attach a file.
        if args.file:
            print(f"[example] Uploading file: {args.file!r}")
            ai.upload_file(args.file)

        # Show token count before sending (if available).
        tokens = ai.get_token_count()
        if tokens is not None:
            print(f"[example] Current token count: {tokens}")

        print(f"[example] Sending prompt: {args.prompt!r}\n")
        response = ai.chat(args.prompt)
        print("=== AI Response ===")
        print(response)
        print("===================")

        if args.screenshot:
            ai.screenshot(args.screenshot)
            print(f"\n[example] Screenshot saved to {args.screenshot}")


if __name__ == "__main__":
    main()
