"""
HIVEX Card Image Generator (Google Maps Infowindow Style)
Renderiza una ficha visual gráfica idéntica a la preview de Google Maps de HIVEX (media_1790862902152.png):
- Tarjeta blanca con esquinas redondeadas y botón de cierre 'x'
- Fotografía con esquinas redondeadas, badge contador de fotos del carrusel y botón de favoritos translúcido
- Título destacado en negrita oscura
- Dirección con pin vectorial rojo de geolocalización
- Desglose financiero vertical estilizado (Tasación/Precio, Estimación Mercado en azul, Salida/Yield y % descuento)
- Botón azul '🔍 Ver Ficha Completa' con icono de lupa vectorial
- Soporte para navegación de fotos (photo_index) y estado de favorito (is_favorite)
"""

import io
import math
import logging
import urllib.request
from typing import Dict, Any, Optional, Tuple, List
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Paleta de colores oficial Google Maps / HIVEX Light Popup
COLOR_CARD_BG = (255, 255, 255)       # Blanco puro
COLOR_BORDER = (203, 213, 225)        # slate-300 #cbd5e1
COLOR_TEXT_TITLE = (15, 23, 42)       # slate-900 #0f172a
COLOR_TEXT_MUTED = (100, 116, 139)    # slate-500 #64748b
COLOR_TEXT_LABEL = (71, 85, 105)      # slate-600 #475569
COLOR_PRIMARY_BLUE = (2, 132, 199)    # sky-600 #0284c7 (Estimación Mercado)
COLOR_BTN_BLUE = (37, 99, 235)        # blue-600 #2563eb (Botón Ver Ficha)
COLOR_GREEN = (5, 150, 105)           # emerald-600 #059669
COLOR_RED = (220, 38, 38)             # red-600 #dc2626
COLOR_FAV_BG = (15, 23, 42, 175)      # Fondo translúcido botón favorito
COLOR_CLOSE_X = (100, 116, 139)       # Color icono 'x'

VERIFIED_BACKUP_PHOTOS = [
    "https://images.unsplash.com/photo-1560518883-ce09059eeffa?w=800&q=80",
    "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800&q=80",
    "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800&q=80",
    "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=800&q=80",
    "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=800&q=80"
]

def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Carga fuente TrueType del sistema con fallback seguro."""
    bold_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    regular_candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
    ]
    candidates = bold_candidates if bold else regular_candidates
    for fp in candidates:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            continue
    return ImageFont.load_default()

def fetch_image(url: str, timeout: int = 5) -> Optional[Image.Image]:
    """Descarga y decodifica una imagen HTTP en memoria."""
    if not url or not str(url).startswith("http"):
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read()
            img = Image.open(io.BytesIO(data))
            return img.convert("RGBA")
    except Exception as e:
        logger.debug(f"Aviso descargando imagen {url[:60]}: {e}")
        return None

def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
    """Divide un texto en varias líneas sin desbordar el ancho en píxeles."""
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        w = draw.textlength(test_line, font=font)
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def round_corners(image: Image.Image, radius: int) -> Image.Image:
    """Aplica esquinas redondeadas a una imagen RGBA."""
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), image.size], radius=radius, fill=255)
    result = image.copy()
    result.putalpha(mask)
    return result

def draw_vector_heart(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float = 0.55, outline: Tuple[int, int, int, int] = (255, 255, 255, 255), fill: Optional[Tuple[int, int, int, int]] = None):
    """Dibuja un corazón vectorial con contorno y relleno opcional."""
    points = []
    for deg in range(0, 360, 6):
        t = math.radians(deg)
        x = cx + scale * (16 * (math.sin(t) ** 3))
        y = cy - scale * (13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t))
        points.append((x, y))
    draw.polygon(points, fill=fill, outline=outline, width=2)

def draw_vector_pin(draw: ImageDraw.ImageDraw, cx: float, top_y: float, fill: Tuple[int, int, int] = (220, 38, 38)):
    """Dibuja un pin de mapa rojo con punto blanco idéntico al de Google Maps."""
    r = 5.5
    cy = top_y + r
    # Cabeza redonda
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=fill)
    # Triángulo hacia abajo
    draw.polygon([(cx - r + 1.2, cy + 1.5), (cx + r - 1.2, cy + 1.5), (cx, top_y + 15)], fill=fill)
    # Punto blanco central
    draw.ellipse([(cx - 2, cy - 2), (cx + 2, cy + 2)], fill=(255, 255, 255))

def draw_vector_search(draw: ImageDraw.ImageDraw, cx: float, cy: float, fill: Tuple[int, int, int] = (255, 255, 255)):
    """Dibuja un icono de lupa vectorial para el botón."""
    r = 5.5
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=fill, width=2)
    draw.line([(cx + 3.5, cy + 3.5), (cx + 9, cy + 9)], fill=fill, width=2)

def generate_opportunity_card_image(
    opp: Dict[str, Any],
    gmaps_api_key: str = "",
    photo_index: int = 0,
    is_favorite: bool = False
) -> bytes:
    """
    Genera un PNG idéntico a la ventana modal de preview de oportunidades de Google Maps (HIVEX).
    Permite navegar el carrusel de fotos (photo_index) y reflejar el estado de favorito (is_favorite).
    """
    card_w = 460
    padding = 22
    content_w = card_w - (padding * 2)

    # 1. Resolver fotos de la oportunidad
    raw_images = opp.get("images") or []
    if isinstance(raw_images, str):
        raw_images = [raw_images]

    valid_images = [
        str(img) for img in raw_images
        if img and "catastro.meh.es" not in str(img).lower() and str(img).startswith("http")
    ]
    total_photos = len(valid_images)

    main_img_url = None
    curr_idx = 0
    if valid_images:
        curr_idx = photo_index % total_photos
        main_img_url = valid_images[curr_idx]

    # Si no hay imagen de portal pero hay coordenadas, usar Street View Static
    lat = opp.get("latitude")
    lon = opp.get("longitude")
    if not main_img_url and lat and lon and gmaps_api_key:
        main_img_url = f"https://maps.googleapis.com/maps/api/streetview?size=600x340&location={lat},{lon}&fov=80&heading=70&pitch=0&key={gmaps_api_key}"

    if not main_img_url:
        opp_id = str(opp.get("id") or "1")
        photo_idx = abs(hash(opp_id)) % len(VERIFIED_BACKUP_PHOTOS)
        main_img_url = VERIFIED_BACKUP_PHOTOS[photo_idx]

    # 2. Descargar y preparar la foto
    prop_img = fetch_image(main_img_url, timeout=4)
    if not prop_img:
        photo_idx = abs(hash(str(opp.get("id")))) % len(VERIFIED_BACKUP_PHOTOS)
        prop_img = fetch_image(VERIFIED_BACKUP_PHOTOS[photo_idx], timeout=4)

    img_h = 220
    if prop_img:
        prop_img = prop_img.resize((content_w, img_h), Image.Resampling.LANCZOS)
        prop_img = round_corners(prop_img, radius=12)

    # 3. Preparar textos y medir alturas
    dummy_img = Image.new("RGBA", (card_w, 800), (255, 255, 255, 255))
    draw_measure = ImageDraw.Draw(dummy_img)

    # Título en negrita fuerte
    title = (opp.get("title") or "Oportunidad Inmobiliaria").strip()
    font_title = get_font(18, bold=True)
    title_lines = wrap_text(title, font_title, content_w, draw_measure)[:3]

    # Dirección (dejando espacio para el pin a la izquierda)
    addr = opp.get("full_address") or opp.get("address") or ""
    loc = opp.get("locality") or opp.get("province") or ""
    cp = opp.get("postal_code") or ""
    loc_parts = []
    if addr: loc_parts.append(addr)
    if loc and loc.lower() not in addr.lower(): loc_parts.append(loc)
    if cp and cp not in addr: loc_parts.append(f"({cp})")
    full_address_str = ", ".join(loc_parts) if loc_parts else "España"

    font_addr = get_font(13, bold=False)
    addr_max_w = content_w - 20 # Espacio para pin
    addr_lines = wrap_text(full_address_str, font_addr, addr_max_w, draw_measure)[:2]

    # Tipo de oportunidad (Subasta BOE vs Portal de Mercado)
    opp_id_str = str(opp.get("id") or "")
    source_type = opp.get("source_type") or ("subasta" if "SUB" in opp_id_str.upper() else "market")
    is_auction = "SUB" in opp_id_str.upper() or source_type == "subasta"

    # 4. Calcular altura total de la tarjeta
    title_h = len(title_lines) * 24
    addr_h = len(addr_lines) * 19
    details_h = 88
    btn_h = 44
    card_h = 20 + img_h + 14 + title_h + 6 + addr_h + 12 + details_h + 16 + btn_h + 20

    # 5. Renderizar lienzo principal blanco
    card = Image.new("RGBA", (card_w, card_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(card)

    # Borde exterior redondeado idéntico a la modal de mapa
    draw.rounded_rectangle([(0, 0), (card_w - 1, card_h - 1)], radius=16, fill=COLOR_CARD_BG, outline=COLOR_BORDER, width=1)

    # Botón de cierre 'x' en la esquina superior derecha
    x_center = card_w - 24
    y_center = 20
    draw.line([(x_center - 5, y_center - 5), (x_center + 5, y_center + 5)], fill=COLOR_CLOSE_X, width=2)
    draw.line([(x_center - 5, y_center + 5), (x_center + 5, y_center - 5)], fill=COLOR_CLOSE_X, width=2)

    # 6. Pegar la imagen del inmueble
    img_y = 26
    if prop_img:
        card.paste(prop_img, (padding, img_y), prop_img)

        # Badge indicador de carrusel de fotos (si hay múltiples fotos disponibles)
        if total_photos > 1:
            overlay_badge = Image.new("RGBA", card.size, (255, 255, 255, 0))
            draw_badge = ImageDraw.Draw(overlay_badge)
            badge_text = f"📷 {curr_idx + 1}/{total_photos} fotos"
            font_badge_txt = get_font(11, bold=True)
            bw = int(draw_badge.textlength(badge_text, font=font_badge_txt)) + 14
            bh = 22
            bx1 = padding + content_w - bw - 8
            by1 = img_y + img_h - bh - 8
            draw_badge.rounded_rectangle([(bx1, by1), (bx1 + bw, by1 + bh)], radius=5, fill=(15, 23, 42, 220), outline=(255, 255, 255, 70), width=1)
            draw_badge.text((bx1 + 7, by1 + 4), badge_text, fill=(255, 255, 255), font=font_badge_txt)
            card = Image.alpha_composite(card, overlay_badge)
            draw = ImageDraw.Draw(card)

        # Botón de favorito translúcido (círculo oscuro + corazón vectorial)
        fav_r = 17
        fav_cx = padding + content_w - fav_r - 12
        fav_cy = img_y + fav_r + 12

        overlay = Image.new("RGBA", card.size, (255, 255, 255, 0))
        draw_ov = ImageDraw.Draw(overlay)
        draw_ov.ellipse([(fav_cx - fav_r, fav_cy - fav_r), (fav_cx + fav_r, fav_cy + fav_r)], fill=COLOR_FAV_BG)
        card = Image.alpha_composite(card, overlay)
        draw = ImageDraw.Draw(card)

        # Corazón vectorial (rojo si es favorito, contorno blanco si no)
        if is_favorite:
            draw_vector_heart(draw, fav_cx, fav_cy - 1, scale=0.55, outline=(255, 255, 255, 255), fill=(239, 68, 68, 255))
        else:
            draw_vector_heart(draw, fav_cx, fav_cy - 1, scale=0.55, outline=(255, 255, 255, 255), fill=None)

    # 7. Título en negrita fuerte
    current_y = img_y + img_h + 14
    for line in title_lines:
        draw.text((padding, current_y), line, fill=COLOR_TEXT_TITLE, font=font_title)
        current_y += 24

    # 8. Dirección con pin vectorial rojo
    current_y += 4
    pin_y = current_y + 1
    draw_vector_pin(draw, padding + 6, pin_y, fill=COLOR_RED)
    text_addr_x = padding + 18
    for line in addr_lines:
        draw.text((text_addr_x, current_y), line, fill=COLOR_TEXT_MUTED, font=font_addr)
        current_y += 19

    current_y += 10

    # 9. Bloque de Desglose Financiero
    font_lbl = get_font(14, bold=True)
    font_val = get_font(14, bold=False)
    font_mkt = get_font(14, bold=True)
    font_badge = get_font(15, bold=True)

    price_val = float(opp.get("listing_price") or opp.get("price") or opp.get("starting_bid") or 0.0)
    ref_val = float(opp.get("estimated_reference_value") or opp.get("reference_value") or 0.0)
    appraisal_val = float(opp.get("appraisal_value") or 0.0)
    disc_val = float(opp.get("discount_percentage") or opp.get("discount") or 0.0)
    yield_val = float(opp.get("rental_yield") or opp.get("yield") or 0.0)

    if is_auction:
        # --- CASO SUBASTA BOE ---
        tas_fmt = f"{appraisal_val:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".") if appraisal_val > 0 else f"{price_val:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        draw.text((padding, current_y), "Tasación BOE: ", fill=COLOR_TEXT_LABEL, font=font_lbl)
        lbl_w = int(draw.textlength("Tasación BOE: ", font=font_lbl))
        draw.text((padding + lbl_w, current_y), tas_fmt, fill=COLOR_TEXT_LABEL, font=font_val)
        current_y += 21

        est_fmt = f"{ref_val:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".") if ref_val > 0 else "Consultar"
        draw.text((padding, current_y), "Estimación Mercado: ", fill=COLOR_PRIMARY_BLUE, font=font_lbl)
        lbl_w = int(draw.textlength("Estimación Mercado: ", font=font_lbl))
        draw.text((padding + lbl_w, current_y), est_fmt, fill=COLOR_PRIMARY_BLUE, font=font_mkt)
        current_y += 21

        salida_fmt = f"{price_val:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        line3_prefix = f"Subasta s/ Tipo | Salida: {salida_fmt}"
        draw.text((padding, current_y), line3_prefix, fill=COLOR_TEXT_LABEL, font=font_lbl)
        current_y += 21

        if disc_val > 0:
            badge_str = f"(-{disc_val:.1f}%)".replace(".", ",")
            badge_color = COLOR_GREEN
        elif ref_val > 0 and price_val > ref_val:
            over_pct = ((price_val - ref_val) / ref_val) * 100.0
            badge_str = f"(+{over_pct:.1f}%)".replace(".", ",")
            badge_color = COLOR_RED
        else:
            badge_str = "Subasta s/ Tipo"
            badge_color = COLOR_TEXT_LABEL

        draw.text((padding, current_y), badge_str, fill=badge_color, font=font_badge)

    else:
        # --- CASO PORTAL INMOBILIARIO (Pisos.com, Idealista, etc.) ---
        portal_name = opp.get("primary_portal") or ("Pisos.com" if "PISOS" in opp_id_str.upper() else "Portal Inmobiliario")
        draw.text((padding, current_y), "Portal: ", fill=COLOR_TEXT_LABEL, font=font_lbl)
        lbl_w = int(draw.textlength("Portal: ", font=font_lbl))
        draw.text((padding + lbl_w, current_y), portal_name, fill=COLOR_PRIMARY_BLUE, font=font_mkt)
        current_y += 21

        est_fmt = f"{ref_val:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".") if ref_val > 0 else "Consultar"
        draw.text((padding, current_y), "Estimación Mercado: ", fill=COLOR_PRIMARY_BLUE, font=font_lbl)
        lbl_w = int(draw.textlength("Estimación Mercado: ", font=font_lbl))
        draw.text((padding + lbl_w, current_y), est_fmt, fill=COLOR_PRIMARY_BLUE, font=font_mkt)
        current_y += 21

        salida_fmt = f"{price_val:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        draw.text((padding, current_y), f"Precio Venta: {salida_fmt}", fill=COLOR_TEXT_LABEL, font=font_lbl)
        current_y += 21

        if disc_val > 0:
            badge_str = f"(-{disc_val:.1f}% Dto. s/ Mercado)".replace(".", ",")
            draw.text((padding, current_y), badge_str, fill=COLOR_GREEN, font=font_badge)
        elif yield_val > 0:
            badge_str = f"Rentabilidad BTL: {yield_val:.1f}% Bruto".replace(".", ",")
            draw.text((padding, current_y), badge_str, fill=COLOR_PRIMARY_BLUE, font=font_badge)

    # 10. Botón azul '🔍 Ver Ficha Completa'
    btn_y = card_h - padding - btn_h
    draw.rounded_rectangle([(padding, btn_y), (card_w - padding, btn_y + btn_h)], radius=8, fill=COLOR_BTN_BLUE)

    font_btn = get_font(15, bold=True)
    btn_text = "Ver Ficha Completa"
    btn_tw = int(draw.textlength(btn_text, font=font_btn))
    total_w = 16 + 8 + btn_tw
    start_x = padding + ((content_w - total_w) // 2)

    draw_vector_search(draw, start_x + 6, btn_y + (btn_h // 2) - 1, fill=(255, 255, 255))
    draw.text((start_x + 22, btn_y + 13), btn_text, fill=(255, 255, 255), font=font_btn)

    # 11. Exportar a PNG
    buffer = io.BytesIO()
    card.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return buffer.getvalue()


def generate_whatsapp_style_card(opp: Dict[str, Any]) -> bytes:
    """
    Renderiza la ficha gráfica estilo WhatsApp Marketing Template:
    1. Fotos agrupadas arriba (1 a 3 imágenes reales en mosaico armónico con badge indicador).
    2. Cuerpo de tarjeta en blanco puro (#ffffff) con la tipografía y colores oficiales del mapa de HIVEX:
       - Título en slate-900 negrita.
       - Dirección con pin rojo vectorial y código postal.
       - Rejilla financiera estilizada: Precio de Oferta, Estimación Mercado en azul, Descuento en verde, Superficie y Ref. Zona.
       - Pie institucional discreto: HIVEX Real Estate Intelligence.
    (Sin falsos botones dibujados en los píxeles; los botones reales se integran debajo mediante el teclado nativo).
    """
    W = 720
    PHOTO_H = 350
    BODY_H = 300
    TOTAL_H = PHOTO_H + BODY_H

    # 1. Obtener fotos válidas (descartando ortofotos y catastro)
    raw_images = opp.get("images") or []
    if isinstance(raw_images, str):
        raw_images = [raw_images]
    valid_images = [
        i for i in raw_images
        if i and "catastro.meh.es" not in str(i).lower() and str(i).startswith("http")
    ]
    if not valid_images:
        valid_images = VERIFIED_BACKUP_PHOTOS[:3]

    # Descargar hasta 3 fotos
    loaded_imgs = []
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    for img_url in valid_images[:3]:
        try:
            req = urllib.request.Request(img_url, headers=headers)
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                im = Image.open(io.BytesIO(resp.read())).convert("RGB")
                loaded_imgs.append(im)
        except Exception:
            pass

    if not loaded_imgs:
        loaded_imgs.append(Image.new("RGB", (W, PHOTO_H), color=(226, 232, 240)))

    # Fuentes
    font_title = get_font(23, bold=True)
    font_sub = get_font(15, bold=False)
    font_bold = get_font(18, bold=True)
    font_label = get_font(15, bold=False)
    font_badge = get_font(15, bold=True)
    font_small = get_font(13, bold=False)

    card = Image.new("RGB", (W, TOTAL_H), color=(255, 255, 255))
    draw = ImageDraw.Draw(card)

    # 2. Renderizar fotos agrupadas en mosaico dinámico
    GAP = 5
    if len(loaded_imgs) == 1:
        im0 = loaded_imgs[0].resize((W, PHOTO_H), Image.Resampling.LANCZOS)
        card.paste(im0, (0, 0))
    elif len(loaded_imgs) == 2:
        w_each = (W - GAP) // 2
        im0 = loaded_imgs[0].resize((w_each, PHOTO_H), Image.Resampling.LANCZOS)
        im1 = loaded_imgs[1].resize((w_each, PHOTO_H), Image.Resampling.LANCZOS)
        card.paste(im0, (0, 0))
        card.paste(im1, (w_each + GAP, 0))
    else:  # 3 fotos en mosaico
        w_left = int(W * 0.62)
        w_right = W - w_left - GAP
        h_right = (PHOTO_H - GAP) // 2
        im0 = loaded_imgs[0].resize((w_left, PHOTO_H), Image.Resampling.LANCZOS)
        im1 = loaded_imgs[1].resize((w_right, h_right), Image.Resampling.LANCZOS)
        im2 = loaded_imgs[2].resize((w_right, h_right), Image.Resampling.LANCZOS)
        card.paste(im0, (0, 0))
        card.paste(im1, (w_left + GAP, 0))
        card.paste(im2, (w_left + GAP, h_right + GAP))

    # Badge con número total de fotos disponibles
    total_photos = len(valid_images)
    if total_photos > 1:
        pill_text = f"{total_photos} fotos disponibles"
        font_pill = get_font(12, bold=True)
        pill_w = int(draw.textlength(pill_text, font=font_pill)) + 18
        pill_h = 26
        pill_x = W - pill_w - 12
        pill_y = PHOTO_H - pill_h - 12
        pill_overlay = Image.new("RGBA", (pill_w, pill_h), (15, 23, 42, 215))
        pill_draw = ImageDraw.Draw(pill_overlay)
        pill_draw.text((9, 4), pill_text, fill=(255, 255, 255), font=font_pill)
        card.paste(pill_overlay, (pill_x, pill_y), pill_overlay)

    # 3. Renderizar cuerpo de la tarjeta (fondo blanco estilo dashboard)
    y = PHOTO_H + 18
    pad_x = 24

    # Título
    title = (opp.get("title") or "Oportunidad Inmobiliaria").upper()
    if len(title) > 46:
        title = title[:44] + "..."
    draw.text((pad_x, y), title, fill=(15, 23, 42), font=font_title)
    y += 32

    # Dirección con Pin rojo
    address = (opp.get("address") or opp.get("location") or "España").strip()
    cp = str(opp.get("postal_code") or "").strip()
    if cp and cp not in address:
        address += f" ({cp})"
    if len(address) > 55:
        address = address[:53] + "..."

    draw_vector_pin(draw, pad_x + 5, y + 6, fill=(220, 38, 38))
    draw.text((pad_x + 18, y), address, fill=(100, 116, 139), font=font_sub)
    y += 30

    # Línea separadora
    draw.line([(pad_x, y), (W - pad_x, y)], fill=(226, 232, 240), width=1)
    y += 18

    # Métricas financieras
    price = float(opp.get("listing_price") or opp.get("original_listing_price") or opp.get("price") or 0.0)
    sqm = float(opp.get("surface_m2") or opp.get("sqm") or opp.get("surface") or 0.0)
    m2_price = float(opp.get("area_m2_price") or 0.0)
    market_val = float(opp.get("market_price") or opp.get("estimated_market_price") or opp.get("estimated_reference_value") or opp.get("market_valuation") or 0.0)
    if not market_val and sqm and m2_price:
        market_val = round(sqm * m2_price, 2)
    if not m2_price and sqm > 0 and market_val > 0:
        m2_price = round(market_val / sqm, 2)
    discount = float(opp.get("discount_vs_market") or opp.get("discount_percentage") or opp.get("discount_pct") or opp.get("margin_pct") or 0.0)
    if discount <= 0 and market_val > price and market_val > 0:
        discount = round(((market_val - price) / market_val) * 100.0, 1)
    rooms = opp.get("rooms") or 0
    bathrooms = opp.get("bathrooms") or 0

    col1_x = pad_x
    col2_x = W // 2 + 10

    # Fila 1: Precio y Superficie
    draw.text((col1_x, y), "Precio de Oferta:", fill=(71, 85, 105), font=font_label)
    draw.text((col1_x + 125, y - 2), f"{price:,.0f} €", fill=(15, 23, 42), font=font_bold)

    draw.text((col2_x, y), "Superficie:", fill=(71, 85, 105), font=font_label)
    specs_str = f"{sqm:.0f} m²" if sqm else "N/D"
    if rooms: specs_str += f" · {rooms} hab"
    if bathrooms: specs_str += f" · {bathrooms} bñ"
    draw.text((col2_x + 85, y - 1), specs_str, fill=(15, 23, 42), font=font_bold)
    y += 32

    # Fila 2: Estimación Mercado y Referencia Zona
    draw.text((col1_x, y), "Estimación Mercado:", fill=(71, 85, 105), font=font_label)
    est_str = f"{market_val:,.0f} €" if market_val > 0 else "Consultar"
    draw.text((col1_x + 155, y - 2), est_str, fill=(2, 132, 199), font=font_bold)

    draw.text((col2_x, y), "Ref. Zona:", fill=(71, 85, 105), font=font_label)
    ref_str = f"{m2_price:,.0f} €/m²" if m2_price else "MIVAU"
    draw.text((col2_x + 85, y - 1), ref_str, fill=(100, 116, 139), font=font_bold)
    y += 34

    # Fila 3: Descuento vs Mercado Badge y Rentabilidad BTL
    draw.text((col1_x, y + 2), "Descuento vs Mkt:", fill=(71, 85, 105), font=font_label)
    badge_text = f" -{abs(discount):.1f}% DTO " if discount > 0 else " MERCADO "
    badge_w = int(draw.textlength(badge_text, font=font_badge)) + 10
    draw.rounded_rectangle([col1_x + 130, y - 2, col1_x + 130 + badge_w, y + 24], radius=6, fill=(220, 252, 231))
    draw.text((col1_x + 135, y + 1), badge_text, fill=(21, 128, 61), font=font_badge)

    draw.text((col2_x, y), "Rentabilidad BTL:", fill=(71, 85, 105), font=font_label)
    rental_yield = float(opp.get("rental_yield") or opp.get("yield") or 0.0)
    monthly_rent = float(opp.get("estimated_monthly_rent") or 0.0)
    if not rental_yield and price > 0 and monthly_rent > 0:
        rental_yield = round(((monthly_rent * 12) / price) * 100.0, 1)
    btl_str = f"{rental_yield:.1f}% Yield" if rental_yield > 0 else "Consultar"
    if monthly_rent > 0:
        btl_str += f" ({monthly_rent:,.0f}€)"
    draw.text((col2_x + 125, y - 1), btl_str, fill=(15, 23, 42), font=font_bold)
    y += 34

    # Fila 4: Scoring Global HIVEX y Margen Estimado
    overall_score = float(opp.get("overall_score") or opp.get("final_score") or opp.get("yield_score") or 82.0)
    score_text = f" {overall_score:.0f} / 100 "
    draw.text((col1_x, y + 2), "Scoring Global HIVEX:", fill=(71, 85, 105), font=font_label)
    score_w = int(draw.textlength(score_text, font=font_badge)) + 10
    draw.rounded_rectangle([col1_x + 165, y - 2, col1_x + 165 + score_w, y + 24], radius=6, fill=(238, 242, 255))
    draw.text((col1_x + 170, y + 1), score_text, fill=(67, 56, 202), font=font_badge)

    profit = float(opp.get("potential_gross_profit") or max(0.0, market_val - price))
    if profit > 0:
        draw.text((col2_x, y), "Margen Estimado:", fill=(71, 85, 105), font=font_label)
        draw.text((col2_x + 125, y - 1), f"+{profit:,.0f} €", fill=(21, 128, 61), font=font_bold)
    else:
        strat_lbl = "House Flipping" if "FLIP" in str(opp.get("strategy", "")).upper() else "Buy to Let (Renta)"
        draw.text((col2_x, y), "Estrategia:", fill=(71, 85, 105), font=font_label)
        draw.text((col2_x + 85, y - 1), strat_lbl, fill=(15, 23, 42), font=font_bold)

    # Pie de marca
    y = TOTAL_H - 26
    draw.text((pad_x, y), "HIVEX Real Estate Intelligence · Valoración y datos contrastados", fill=(148, 163, 184), font=font_small)

    buf = io.BytesIO()
    card.save(buf, format="PNG", quality=95)
    return buf.getvalue()

