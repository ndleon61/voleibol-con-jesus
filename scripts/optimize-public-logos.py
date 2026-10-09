"""Generate small public previews without changing originals or historical assets."""
from pathlib import Path
from PIL import Image, ImageOps

media = Path(__file__).resolve().parent.parent / "media"
for name in ("los_abusadores", "los_lobos", "polea", "la_furia_roja", "la_ofensiva_aplastante"):
    with Image.open(media / f"{name}.JPG") as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((128, 128))
        target = media / f"preview-{name}.webp"
        image.save(target, "WEBP", quality=78, method=6)
        print(f"{target.name}: {target.stat().st_size} bytes")
