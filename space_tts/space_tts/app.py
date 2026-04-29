import os
import tempfile
from pathlib import Path

import gradio as gr

from . import model_loader


def generate(text: str):
    """Generate speech for `text` using the loaded model.

    Returns a path to a WAV file that Gradio can play.
    """
    # model_loader.generate returns either bytes or a path-like
    out = model_loader.generate(text)

    # If bytes, write to temp file
    if isinstance(out, (bytes, bytearray)):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(out)
        return path

    # If a path-like, return str path
    try:
        return str(Path(out))
    except Exception:
        return None


title = "Samantha TTS — Persistent voice generator"
description = (
    "This Space serves Samantha's single cloned voice. "
    "Replace `space_tts/model_loader.py` with your model's loader code or drop a `model/samantha.wav` file."
)

with gr.Blocks(title=title) as demo:
    gr.Markdown(f"## {title}\n\n{description}")
    txt = gr.Textbox(label="Text to speak", lines=4, placeholder="Type something Samantha would say...")
    btn = gr.Button("Generate")
    audio = gr.Audio(label="Generated speech")

    btn.click(fn=generate, inputs=txt, outputs=audio)


if __name__ == "__main__":
    # Local dev server
    demo.queue().launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
