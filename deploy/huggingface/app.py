"""Hugging Face Space entry point: seeds the book data, writes the CA certificates from secrets
and serves the StoryQuest FastAPI app (API and the built React UI) on port 7860."""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.setdefault("DATA_DIR", "/tmp/storyquest"))
CERTS = Path("/tmp/certs")
os.environ.setdefault("LLM_CA_CERT_PATH", str(CERTS / "ca.crt"))
os.environ.setdefault("EMBEDDING_CA_CERT_PATH", str(CERTS / "vm02-ca.crt"))
os.environ.setdefault("OTEL_VIEWER_URL", "")
os.environ.setdefault("RERANKER_PROVIDER", "none")  # M5 does not rerank; keeps the Space light

DATA.mkdir(parents=True, exist_ok=True)
CERTS.mkdir(parents=True, exist_ok=True)
if not (DATA / "content.db").exists():
    shutil.copy(ROOT / "seed" / "content.db", DATA / "content.db")
shutil.copytree(ROOT / "seed" / "books", DATA / "books", dirs_exist_ok=True)
for secret, path in [("LLM_CA_CERT_PEM", "LLM_CA_CERT_PATH"), ("EMBEDDING_CA_CERT_PEM", "EMBEDDING_CA_CERT_PATH")]:
    if os.environ.get(secret):
        Path(os.environ[path]).write_text(os.environ[secret].strip() + "\n")

os.chdir(ROOT)  # settings read config.env from the working directory
sys.path.insert(0, str(ROOT / "src"))

import gradio as gr  # noqa: E402
import uvicorn  # noqa: E402

from storyquest.api.main import create_app  # noqa: E402

try:  # ZeroGPU needs one GPU function; StoryQuest never calls it (the model runs on the course endpoint)
    import spaces

    @spaces.GPU
    def _unused() -> None:
        return None
except ImportError:
    pass

with gr.Blocks(title="StoryQuest Copilot") as info:
    gr.Markdown("StoryQuest Copilot runs at the root of this Space. This page only exists for the host.")

app = gr.mount_gradio_app(create_app(), info, path="/gradio")
uvicorn.run(app, host="0.0.0.0", port=7860)
