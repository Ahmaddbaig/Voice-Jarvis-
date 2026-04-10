# Jarvis Prototype

A local Python voice assistant prototype with:

- Switchable backend: local Ollama or OpenAI API
- Push-to-talk microphone input
- Spoken replies
- Always-on webcam vision that keeps the latest frame ready for every request
- A polished, concise assistant persona inspired by a capable home AI, without cloning or impersonating a movie actor's exact voice

## Setup

1. Create a virtual environment.

   Windows PowerShell:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   macOS:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies.

   Windows PowerShell:

   ```powershell
   pip install -r requirements.txt
   ```

   macOS:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Create your local environment file.

   Windows PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

   macOS:

   ```bash
   cp .env.example .env
   ```

4. Edit `.env`.

For free local use with Ollama:

- Keep `ASSISTANT_PROVIDER=ollama`
- Install Ollama
- Pull a Gemma model such as `gemma3:4b`

Example:

```bash
ollama pull gemma3:4b
```

For OpenAI:

- Set `ASSISTANT_PROVIDER=openai`
- Set `OPENAI_API_KEY`

## Run

```powershell
python .\src\jarvis.py
```

On macOS:

```bash
python src/jarvis.py
```

Controls:

- Type a message and press Enter for text chat.
- Type `m` to record from the microphone.
- Type `c` to ask a question directly about the live camera view.
- Type `s` to check camera status.
- Type `q` to quit.

## Notes

This prototype records audio only when you press `m`. By default it keeps the webcam open while the app is running, and it sends the latest frame with each request so the assistant can answer with current visual context. Set `JARVIS_ALWAYS_SEE=false` in `.env` if you want the camera used only for `c` prompts.

When `ASSISTANT_PROVIDER=ollama`, chat and camera vision run locally through Ollama. Local speech output uses the system TTS engine through `pyttsx3`. Microphone transcription still requires OpenAI in this version.
