"""Run once:  python generate_images.py
Needs OPENAI_API_KEY in your environment. Images are saved to ./assets and reused (no repeat cost)."""
import base64
import os
from pathlib import Path

from openai import OpenAI

client = OpenAI()
OUT = Path(__file__).parent / "assets"
OUT.mkdir(exist_ok=True)

STYLE = "dark futuristic digital art, neon cyan and magenta glow, deep purple background, cinematic lighting, no text"
PROMPTS = {
    "hero": f"A glowing holographic shield floating above a stack of insurance documents, data streams flowing into it, {STYLE}",
    "forensics": f"A giant magnifying glass revealing glowing hidden patterns on a paper document, forensic analysis, {STYLE}",
    "network": f"An abstract glowing neural network brain made of light nodes and connections, {STYLE}",
    "documents": f"Floating paper documents dissolving into glowing digital binary particles, {STYLE}",
}

import urllib.request

for name, prompt in PROMPTS.items():
    path = OUT / f"{name}.png"
    if path.exists():
        print("skip", name)
        continue
    print("generating", name, "...")
    try:
        r = client.images.generate(model="gpt-image-1", prompt=prompt, size="1024x1024")
    except Exception as e:
        print("gpt-image-1 failed:", e)
        print("-> trying dall-e-3")
        r = client.images.generate(model="dall-e-3", prompt=prompt, size="1024x1024")
    item = r.data[0]
    if getattr(item, "b64_json", None):
        path.write_bytes(base64.b64decode(item.b64_json))
    else:  # dall-e-3 returns a temporary URL
        urllib.request.urlretrieve(item.url, path)

print("done ->", OUT)
