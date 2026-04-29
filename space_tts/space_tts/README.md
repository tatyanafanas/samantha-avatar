# Deploying Samantha's persistent TTS on Hugging Face Spaces

This scaffold runs a small Gradio app that exposes a single endpoint/UI for generating Samantha's voice.

Deployment options
- Hugging Face Spaces (recommended): create a private Space, push this `space_tts/` folder and your `model/` subfolder.

How it works (default)
- `space_tts/model_loader.py` looks for `model/samantha.wav` and returns that file for any input text. This makes the Space persistent and cheap: you host one fixed voice file and serve it.

To use a real TTS model
- Replace `space_tts/model_loader.py::generate()` with a call to your chosen TTS runtime (Qwen3-TTS, Coqui, etc.).
- If your model requires API keys, store them as Space secrets and read them via `os.environ`.

Deploy steps
1. Create a new private Space on Hugging Face: https://huggingface.co/new-space
2. Choose "Gradio" as the SDK.
3. Push the contents of `space_tts/` to the Space repository (include `model/samantha.wav` or add model code).
4. In the Space settings, add any required secrets (e.g., `HF_API_KEY`) and set hardware runtime if available.

Notes
- Free Spaces are CPU-only and have execution time limits; pre-loading a single voice file avoids model load latency.
- Keep the cloned-voice WAV private; do not commit it to a public repo unless you want it public.
