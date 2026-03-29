# Web-Automation — ai_browser

A Python package that lets **local servers and personal apps** use AI without
any API key.  It drives a real browser (Google Chrome via
[Playwright](https://playwright.dev/python/)) to automate AI websites, so you
get full model access through your regular Google account at zero cost.

---

## Supported AI websites

| Class | Website |
|---|---|
| `AIStudio` | [Google AI Studio](https://aistudio.google.com/prompts/new_chat) |

---

## Installation

```bash
pip install -r requirements.txt
```

Google Chrome must be installed on your system.  Download it from
<https://www.google.com/chrome/> if needed.  No extra `playwright install`
step is required — Playwright uses the system Chrome directly.

---

## Quick-start

### Step 1 – Log in (one-time, visible browser)

On the very first run you need to authenticate with your Google account.
Run with `headless=False` so the browser window appears, then sign in normally:

```bash
python example.py --login
```

Your session (cookies, local storage) is automatically saved to
`~/.ai_browser/AIStudio/`.  You only need to do this once.

### Step 2 – Use the AI (headless, no window)

```python
from ai_browser import AIStudio

with AIStudio() as ai:                         # headless=True by default
    response = ai.chat("What is Python?")
    print(response)
```

---

## API reference

### `AIStudio(headless, profile_dir, timeout, response_timeout)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `headless` | `bool` | `True` | Hide the browser window. Set `False` for debugging or first-time login. |
| `profile_dir` | `str \| None` | `~/.ai_browser/AIStudio` | Where to persist the browser profile (login session). |
| `timeout` | `int` | `60000` | Navigation / element-wait timeout in milliseconds. |
| `response_timeout` | `int` | `180000` | Maximum time to wait for a response in milliseconds. |

#### Methods

| Method | Description |
|---|---|
| `start()` | Launch the browser. Returns `self`. |
| `stop()` | Close the browser and release resources. |
| `chat(prompt: str) → str` | Send a prompt and return the AI's response. |
| `new_chat()` | Navigate to a fresh empty chat session. |
| `screenshot(path: str)` | Save a PNG screenshot (useful for debugging). |

`AIStudio` also works as a **context manager** (`with AIStudio() as ai: …`).

---

## Usage in a local server

```python
from flask import Flask, request, jsonify
from ai_browser import AIStudio

app = Flask(__name__)
ai = AIStudio()

@app.route("/ask", methods=["POST"])
def ask():
    prompt = request.json["prompt"]
    return jsonify({"response": ai.chat(prompt)})

if __name__ == "__main__":
    ai.start()
    try:
        app.run(port=5000)
    finally:
        ai.stop()
```

---

## Debugging tips

* Run with `headless=False` to watch the browser and identify issues.
* Call `ai.screenshot("debug.png")` at any point to capture the page.
* Use `--screenshot debug.png` with `example.py`.

---

## How it works

1. A Google Chrome browser is launched with a **persistent user-data directory**
   so that your Google login is kept between runs.
2. The script navigates to `https://aistudio.google.com/prompts/new_chat`.
3. It locates the prompt input area, types your text, and clicks **Run**.
4. It polls the page until the model finishes generating (the stop indicator
   disappears and the response text stabilises for 2 seconds).
5. The final response text is returned as a plain Python string.
