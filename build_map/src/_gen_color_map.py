from PIL import Image, ImageDraw, ImageFont
import numpy as np
import random
import os

os.chdir('C:\\RP\\map_generator_godot')

print("Loading ProvinceIDMask...")
arr = np.array(Image.open("build_map/src/opengs_export/ProvinceIDMask.png").convert("RGB"))
id_map = arr[:,:,0].astype(np.uint32) + (arr[:,:,1].astype(np.uint32)<<8) + (arr[:,:,2].astype(np.uint32)<<16)

print(f"ID map shape: {id_map.shape}")
print(f"Max ID: {id_map.max()}")

# Generate random colors for each province
random.seed(42)
max_id = int(id_map.max())
print(f"Generating {max_id+1} colors...")
colors = np.zeros((max_id+1, 3), dtype=np.uint8)
for i in range(max_id+1):
    colors[i] = (random.randint(20, 235), random.randint(20, 235), random.randint(20, 235))

# Map IDs to colors using direct indexing
print("Mapping colors to provinces...")
colored_map = colors[id_map]

print("Creating image...")
img = Image.fromarray(colored_map, "RGB")

print("Saving...")
img.save("build_map/src/opengs_export/ProvinceMap_ColorTest.png")

print(f"Done!")
print(f"AEO (id=0) color: RGB{tuple(colors[0])}")
aeo_pixels = (id_map == 0).sum()
print(f"AEO pixels: {aeo_pixels}")

# Annotate the AEO location with label
if aeo_pixels > 0:
    ys, xs = np.where(id_map == 0)
    cx, cy = int(xs.mean()), int(ys.mean())

    draw = ImageDraw.Draw(img)

    # Draw circle around island
    r = 40
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 0), width=4)

    # Draw line to label
    label_x, label_y = cx + 60, cy - 50
    draw.line([(cx + r, cy - r // 2), (label_x, label_y + 14)], fill=(255, 255, 0), width=2)

    # Draw label text
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 28)
    except Exception:
        font = ImageFont.load_default()

    # Shadow for readability
    draw.text((label_x + 2, label_y + 2), "Epstein", fill=(0, 0, 0), font=font)
    draw.text((label_x, label_y), "Epstein", fill=(255, 255, 0), font=font)

    img.save("build_map/src/opengs_export/ProvinceMap_ColorTest.png")
    print(f"Annotated island at ({cx}, {cy}) with label 'Epstein'")
