# src/image_utils.py
from PIL import Image, ImageDraw, ImageFont
import io
import logging

logger = logging.getLogger(__name__)

def add_watermark(image_data: bytes, text: str, angle: int = 45, opacity: int = 180) -> bytes | None:
    if not image_data:
        logger.warning("add_watermark: No image data provided.")
        return None

    original_image_data_ref = image_data
    font_path = None

    try:
        base_image = Image.open(io.BytesIO(image_data)).convert("RGBA")
        width, height = base_image.size

        txt_composite_layer = Image.new("RGBA", base_image.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(txt_composite_layer)

        font_size = 1
        selected_font_object = None

        common_fonts = ["arial.ttf", "verdana.ttf", "DejaVuSans.ttf", "sans-serif.ttf"]
        logger.debug(f"Watermark: Attempting to load system fonts: {common_fonts}")
        for f_path_try in common_fonts:
            try:
                selected_font_object = ImageFont.truetype(f_path_try, 10)
                font_path = f_path_try
                logger.info(f"Watermark: Using system font: {font_path} (initial check).")
                break
            except IOError:
                logger.debug(f"Watermark: System font {f_path_try} not found or failed to load.")
                pass

        if not selected_font_object:
            logger.warning("Watermark: No specified system fonts found/loaded.")
            try:
                selected_font_object = ImageFont.load_default()
                font_path = None
                logger.info("Watermark: Successfully loaded Pillow's default bitmap font.")
            except IOError as e_default_font:
                logger.error(f"Watermark CRITICAL: Could not load system fonts OR Pillow's default font: {e_default_font}. Cannot add watermark. Returning original image.")
                return original_image_data_ref

        font_size = int(height * 0.10) # 10% of image height
        logger.info(f"Watermark: Target font size: {font_size}")

        if font_path:
            try:
                selected_font_object = ImageFont.truetype(font_path, font_size)
                logger.info(f"Watermark: Resized system font {font_path} to size {font_size}.")
            except IOError as e_resize:
                logger.warning(f"Watermark: Failed to resize font {font_path} to {font_size}: {e_resize}. Falling back to default bitmap font for drawing.")
                try:
                    selected_font_object = ImageFont.load_default()
                except IOError as e_final_default:
                    logger.error(f"Watermark CRITICAL: Failed to load default font as fallback after resize error: {e_final_default}. Cannot add watermark. Returning original image.")
                    return original_image_data_ref
        else:
            logger.info(f"Watermark: Using default bitmap font. Effective size is fixed, requested size {font_size} might not apply accurately.")

        text_color_fill = (255, 255, 0, opacity) # Bright Yellow for high visibility
        logger.info(f"Watermark: Using text color fill: {text_color_fill}")

        text_left, text_top, text_right, text_bottom = 0,0,0,0
        try:
           bbox = draw.textbbox((0,0), text, font=selected_font_object)
           text_left, text_top, text_right, text_bottom = bbox
           text_width = text_right - text_left
           text_height = text_bottom - text_top
        except AttributeError:
           logger.warning("selected_font_object.getbbox not available, using getsize or approximation.")
           if hasattr(selected_font_object, 'getsize'):
              text_width, text_height = selected_font_object.getsize(text)
           else:
              text_width = int(font_size * len(text) * 0.6)
              text_height = font_size
        logger.info(f"Watermark: Text dimensions (width x height): {text_width} x {text_height} for text '{text}'")

        if text_width <= 0 or text_height <= 0:
            logger.error("Watermark: Calculated text width or height is zero or negative. Aborting watermark. Returning original image.")
            return original_image_data_ref

        padding = 10
        text_canvas_width = text_width + 2 * padding
        text_canvas_height = text_height + 2 * padding

        text_img = Image.new("RGBA", (int(text_canvas_width), int(text_canvas_height)), (255,255,255,0))
        text_draw = ImageDraw.Draw(text_img)
        text_draw.text((-text_left + padding, -text_top + padding), text, font=selected_font_object, fill=text_color_fill)
        logger.info(f"Watermark: Text drawn on its canvas of size {text_img.size}.")

        rotated_text_img = text_img.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        logger.info(f"Watermark: Rotated text image size: {rotated_text_img.size}")

        paste_x = max(0, (width - rotated_text_img.width) // 2)
        paste_y = max(0, (height - rotated_text_img.height) // 2)
        logger.info(f"Watermark: Constrained Pasting at position (x,y): ({paste_x}, {paste_y})")

        txt_composite_layer.paste(rotated_text_img, (paste_x, paste_y), rotated_text_img)
        watermarked_image = Image.alpha_composite(base_image, txt_composite_layer)
        watermarked_image_rgb = watermarked_image.convert("RGB")

        img_byte_arr = io.BytesIO()
        watermarked_image_rgb.save(img_byte_arr, format='JPEG', quality=90)
        watermarked_image_bytes = img_byte_arr.getvalue()

        if len(watermarked_image_bytes) == len(original_image_data_ref) and len(watermarked_image_bytes) > 0 :
            is_identical = True
            if hasattr(Image, 'tobytes') and hasattr(base_image, 'tobytes'):
                try:
                    if watermarked_image_rgb.tobytes() != base_image.convert("RGB").tobytes(): is_identical = False
                except Exception: pass
            if is_identical: logger.warning("Watermark: Output image data is identical to original or size is same.")
        else: logger.info(f"Watermark added successfully. Original size: {len(original_image_data_ref)}, New size: {len(watermarked_image_bytes)}")
        return watermarked_image_bytes
    except FileNotFoundError as e_font_critical:
        logger.error(f"Watermark CRITICAL: Font file not found: {e_font_critical}. Returning original image.", exc_info=True)
        return original_image_data_ref
    except Exception as e_wm:
        logger.error(f"Error adding watermark: {e_wm}. Returning original image.", exc_info=True)
        return original_image_data_ref

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    try:
        from PIL import Image, ImageDraw, ImageFont
        dummy_image = Image.new('RGB', (800, 600), color = (10, 150, 10))
        byte_arr = io.BytesIO(); dummy_image.save(byte_arr, format='JPEG'); original_bytes = byte_arr.getvalue()
        logger.info(f"Created dummy original image ({len(original_bytes)} bytes).")
        watermarked_bytes = add_watermark(original_bytes, "GRRA-Chemor,PK", angle=30, opacity=180)
        if watermarked_bytes and watermarked_bytes != original_bytes:
            import os # Ensure os is imported for path manipulation
            save_path = os.path.join(os.path.dirname(__file__), '..', 'watermarked_test_image_debug.jpg')
            with open(save_path, "wb") as f: f.write(watermarked_bytes)
            logger.info(f"Watermarked image saved as {save_path}. Please check.")
        elif watermarked_bytes == original_bytes: logger.warning("Watermarking returned original image.")
        else: logger.error("Watermarking returned None.")
    except ImportError: logger.error("Pillow (PIL) library is not installed. Cannot run watermark test.")
    except Exception as e_test: logger.error(f"Error in watermark test script: {e_test}", exc_info=True)
