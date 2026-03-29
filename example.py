"""
example.py – Demonstrates how to use the ai_browser package.

Quick-start
-----------
1. Install dependencies:
        pip install -r requirements.txt
        playwright install chromium

2. First run – log in to Google AI Studio (browser window will open):
        python example.py --login

3. Subsequent runs – headless (no window):
        python example.py
"""

import argparse

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
        "--screenshot",
        metavar="PATH",
        default="",
        help="Save a screenshot to this path after the response (e.g. debug.png).",
    )
    args = parser.parse_args()

    headless = not args.login

    print(f"[example] Starting AI Studio client (headless={headless}) …")
    with AIStudio(headless=headless) as ai:
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
