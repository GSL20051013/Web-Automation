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

`AIStudio` works as a **context manager** (`with AIStudio() as ai: …`) or
with an explicit `start()` / `stop()` lifecycle.

---

### Core methods

| Method | Returns | Description |
|---|---|---|
| `start()` | `self` | Launch the browser. Chainable. |
| `stop()` | `None` | Close the browser and release all resources. |
| `chat(prompt)` | `str` | Send a prompt and return the AI's response text. |
| `new_chat()` | `None` | Navigate to a fresh empty chat session. |
| `screenshot(path)` | `None` | Save a PNG screenshot to *path* (useful for debugging). |
| `get_token_count()` | `int \| None` | Return the current token count shown in the UI, or `None`. |
| `upload_file(path)` | `None` | Attach a local file (image, video, audio, document) to the prompt. |

---

### System instructions

```python
ai.set_system_instructions("You are a concise assistant. Reply in bullet points.")
```

| Method | Description |
|---|---|
| `set_system_instructions(text)` | Set (or clear) the system instructions for the session. Pass `""` to clear. |

---

### Model settings

```python
ai.set_temperature(0.4)
ai.set_thinking_level("High")
```

| Method | Parameters | Description |
|---|---|---|
| `set_temperature(value)` | `value: float` in `[0.0, 2.0]` | Lower = more deterministic; higher = more creative. |
| `set_thinking_level(level)` | `level: str` — one of `"None"`, `"Low"`, `"Medium"`, `"High"` | Internal reasoning budget (supported models only). |

---

### Grounding & search tools

```python
ai.set_grounding(True)          # Google Search
ai.set_maps_grounding(True)     # Google Maps
ai.set_url_context(True)        # fetch URLs mentioned in the prompt
```

| Method | Description |
|---|---|
| `set_grounding(enabled)` | Enable / disable **Grounding with Google Search**. |
| `set_maps_grounding(enabled)` | Enable / disable **Grounding with Google Maps**. |
| `set_url_context(enabled)` | Enable / disable the **URL Context** tool (model reads URLs in the prompt). |

---

### Tool use (function calling & code execution)

#### Code execution

```python
ai.set_code_execution(True)
response = ai.chat("Calculate the first 20 Fibonacci numbers and return them as a list.")
```

| Method | Description |
|---|---|
| `set_code_execution(enabled)` | Enable / disable the **Code Execution** tool (model can run Python code). |

#### Function calling

Enable the toggle without specifying declarations:

```python
ai.set_function_calling(True)
```

Or define your callable functions as a JSON array of
[`FunctionDeclaration`](https://ai.google.dev/api/generate-content#v1beta.FunctionDeclaration)
objects (this also enables function calling automatically):

```python
declarations = [
    {
        "name": "get_weather",
        "description": "Return the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Name of the city."}
            },
            "required": ["city"]
        }
    }
]

import json
ai.set_function_declarations(json.dumps(declarations))
response = ai.chat("What is the weather in Tokyo right now?")
print(response)  # Model will describe a call to get_weather(city="Tokyo")
```

| Method | Description |
|---|---|
| `set_function_calling(enabled)` | Enable / disable the **Function Calling** toggle. |
| `set_function_declarations(json_text)` | Set function declarations (JSON array). Enables function calling automatically. Raises `ValueError` for invalid JSON. |

#### Structured output

Enforce a specific JSON response shape:

```python
schema = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "score": {"type": "number"}
    },
    "required": ["summary", "sentiment", "score"]
}

import json
ai.set_structured_output_schema(json.dumps(schema))
response = ai.chat("Review: 'This product is amazing and works perfectly!'")
print(response)  # JSON conforming to the schema above
```

| Method | Description |
|---|---|
| `set_structured_output(enabled)` | Enable / disable the **Structured Outputs** toggle. |
| `set_structured_output_schema(json_text)` | Set the JSON schema for structured output. Enables structured output automatically. Raises `ValueError` for invalid JSON. |

---

## Example: full tool-use session

```python
import json
from ai_browser import AIStudio

tools = [
    {
        "name": "search_products",
        "description": "Search a product catalogue and return matching items.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        }
    }
]

with AIStudio(headless=True) as ai:
    ai.set_system_instructions("You are a helpful shopping assistant.")
    ai.set_temperature(0.3)
    ai.set_function_declarations(json.dumps(tools))

    response = ai.chat("Find me a pair of red running shoes under $100.")
    print(response)
```

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

## command-line interface (`example.py`)

```
python example.py [OPTIONS]

Options:
  --login                     Open a visible browser for first-time login.
  --prompt TEXT               Prompt to send (default: "Explain what a large language model is …").
  --system TEXT               System instructions.
  --temperature FLOAT         Model temperature [0.0, 2.0].
  --thinking LEVEL            Thinking level: None | Low | Medium | High.
  --grounding                 Enable Grounding with Google Search.
  --maps-grounding            Enable Grounding with Google Maps.
  --url-context               Enable URL Context tool.
  --code-execution            Enable Code Execution tool.
  --function-calling          Enable Function Calling tool.
  --function-declarations JSON  JSON array of FunctionDeclaration objects.
  --structured-output         Enable Structured Outputs.
  --output-schema JSON        JSON schema for structured output.
  --file PATH                 File to attach (image, video, audio, document).
  --screenshot PATH           Save a debug screenshot after the response.
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

