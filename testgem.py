
from google import genai
from google.genai import types
import os

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

MODEL = "gemini-3-flash-preview"  # Use the same model that passed your text test

image_path = "scan_id_genuine.jpg"

try:
    with open(image_path, "rb") as f:
        image_data = f.read()

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            "Analyze this test document image. Return a short description.",
            types.Part.from_bytes(
                data=image_data,
                mime_type="image/jpeg"
            )
        ]
    )

    print("IMAGE TEST SUCCESSFUL")
    print(response.text)

except Exception as e:
    print("IMAGE TEST FAILED")
    print("Error type:", type(e).__name__)
    print("Error details:", repr(e))
