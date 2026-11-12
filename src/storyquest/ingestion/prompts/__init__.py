from importlib.resources import files


def load_prompt(name: str) -> str:
    return (files("storyquest.ingestion") / "prompts" / f"{name}.txt").read_text()
