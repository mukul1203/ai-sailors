---
title: StoryQuest Copilot
emoji: 📖
colorFrom: green
colorTo: yellow
sdk: gradio
sdk_version: 5.49.1
python_version: "3.12"
app_file: app.py
pinned: false
license: mit
short_description: A book-grounded story game for children aged 6 to 9
---

# StoryQuest Copilot

A story game for children aged 6 to 9 that answers questions only from the pages a child has
already read. It plays *The Jungle Book* with the M5 agent (planner, read-only tools, grounded
answer, code checks and a critic) on Qwen3-8B, with hybrid BM25 + bge retrieval.

Source code, design and evaluation: https://github.com/mukul1203/ai-sailors

This is a read-only demo: book upload and review are off, and sessions and traces are kept only
until the Space restarts.
