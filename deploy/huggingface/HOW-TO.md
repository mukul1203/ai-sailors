# Hugging Face Space (live demo)

The live demo at https://mukilans-storyquest.hf.space is a Gradio-SDK Space on free ZeroGPU
hardware. `app.py` serves the normal FastAPI app and React build on port 7860; the GPU function is
a stub that is never called, because the model runs on the course endpoint.

To rebuild the Space folder:

1. `cd web && npm run build`, then copy `src/`, `config.env`, `LICENSE`, `eval/books/` and
   `web/dist/` into an empty folder, with `app.py`, `requirements.txt` and `space-README.md`
   (renamed `README.md`) from here.
2. Add `seed/content.db` (a published copy of `var/content.db`; only the chapters to play
   included) and `seed/books/<id>/raw.txt`.
3. Space secrets: `LLM_API_KEY`, `LLM_BASE_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL`,
   `LLM_CA_CERT_PEM`, `EMBEDDING_CA_CERT_PEM` (certificate text), `SESSION_SECRET`, `ADMIN_TOKEN`.
   Variables: `READ_ONLY_DEMO=true`, `TRACE_DASHBOARD=true`.
4. Upload with `hf upload <owner>/<space> <folder> --repo-type space`.
