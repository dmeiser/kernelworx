#!/usr/bin/env python3
"""
Convert SVG logo to PNG formats for Cognito Managed Login Branding.
Creates: logo (200x200), favicon (32x32), and base64 encoded versions.
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
svg_path = Path(__file__).parent / "popcorn-logo.svg"
svg_data = svg_path.read_text()

def convert_to_png(width, height, keep_alpha=True):
    """Convert SVG to PNG with specified dimensions."""
    png_data = cairosvg.svg2png(
        bytestring=svg_data.encode('utf-8'),
        output_width=width,
        output_height=height
    )
    
    img = Image.open(BytesIO(png_data))
    
    # Convert to RGB if requested (Cognito form logo prefers no alpha)
    if not keep_alpha and img.mode == 'RGBA':
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    
    # Save to BytesIO
    output = BytesIO()
    img.save(output, format='PNG', optimize=True)
    return output.getvalue()

# Create logo (200x200, no alpha for Cognito form)
print("Creating logo (200x200)...")
logo_png = convert_to_png(200, 200, keep_alpha=False)
logo_path = Path(__file__).parent / "cognito-logo.png"
logo_path.write_bytes(logo_png)

# Create favicon (32x32, with alpha for browser, ICO format)
print("Creating favicon (32x32, ICO format)...")
favicon_png = convert_to_png(32, 32, keep_alpha=True)
favicon_img = Image.open(BytesIO(favicon_png))
favicon_output = BytesIO()
favicon_img.save(favicon_output, format='ICO', sizes=[(32, 32)])
favicon_ico = favicon_output.getvalue()
favicon_path = Path(__file__).parent / "favicon.ico"
favicon_path.write_bytes(favicon_ico)

# Create base64 for logo
logo_base64 = base64.b64encode(logo_png).decode('utf-8')
logo_base64_path = Path(__file__).parent / "cognito-logo-base64.txt"
logo_base64_path.write_text(logo_base64)

# Create base64 for favicon
favicon_base64 = base64.b64encode(favicon_ico).decode('utf-8')
favicon_base64_path = Path(__file__).parent / "favicon-base64.txt"
favicon_base64_path.write_text(favicon_base64)

print(f"\n✅ Conversion complete!")
print(f"   Logo: {logo_path} ({len(logo_png):,} bytes)")
print(f"   Favicon: {favicon_path} ({len(favicon_ico):,} bytes)")
print(f"   Logo base64: {logo_base64_path} ({len(logo_base64):,} chars)")
print(f"   Favicon base64: {favicon_base64_path} ({len(favicon_base64):,} chars)")
print(f"\n   Cognito max logo size: 100KB")
print(f"   Current size: {len(png_optimized) / 1024:.2f}KB")

if len(png_optimized) > 100 * 1024:
    print("   ⚠️  WARNING: Logo exceeds 100KB limit!")
else:
    print("   ✅ Logo size is within limits")
