#!/usr/bin/env python3
"""
Convert SVG logo to base64 PNG for Cognito UI customization.
Requires: pip install cairosvg pillow
"""
import base64
from io import BytesIO
from pathlib import Path

try:
    import cairosvg
    from PIL import Image
except ImportError:
    print("Installing required packages...")
    import subprocess
    subprocess.run(["pip", "install", "cairosvg", "pillow"], check=True)
    import cairosvg
    from PIL import Image

# Read SVG
svg_path = Path(__file__).parent / "cognito-logo.svg"
svg_data = svg_path.read_text()

# Convert SVG to PNG (200x200)
png_data = cairosvg.svg2png(bytestring=svg_data.encode('utf-8'), output_width=200, output_height=200)

# Optimize with PIL
img = Image.open(BytesIO(png_data))
# Convert to RGB if needed (Cognito prefers no alpha)
if img.mode == 'RGBA':
    background = Image.new('RGB', img.size, (255, 255, 255))
    background.paste(img, mask=img.split()[3])  # 3 is the alpha channel
    img = background

# Save optimized PNG
output = BytesIO()
img.save(output, format='PNG', optimize=True)
png_optimized = output.getvalue()

# Convert to base64
base64_str = base64.b64encode(png_optimized).decode('utf-8')

# Output for CDK
output_file = Path(__file__).parent / "cognito-logo-base64.txt"
output_file.write_text(base64_str)

print(f"✅ Logo converted successfully!")
print(f"   Size: {len(png_optimized)} bytes")
print(f"   Base64 size: {len(base64_str)} characters")
print(f"   Saved to: {output_file}")
print(f"\n   Cognito max logo size: 100KB")
print(f"   Current size: {len(png_optimized) / 1024:.2f}KB")

if len(png_optimized) > 100 * 1024:
    print("   ⚠️  WARNING: Logo exceeds 100KB limit!")
else:
    print("   ✅ Logo size is within limits")
