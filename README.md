# Jarvis Prototype

A local Python voice assistant prototype with:

- Push-to-talk microphone input
- Spoken replies
- Optional webcam vision for questions like "what do you see?"
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

4. Edit `.env` and set `OPENAI_API_KEY`.

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
- Type `c` to take a webcam snapshot and ask a question about it.
- Type `q` to quit.

## Notes

This prototype records audio only when you press `m`. It uses the webcam only when you press `c`.
