#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
import cairo
import math
import datetime
from datetime import timedelta
import os

# Pillow kütüphanesini içe aktaralım
try:
    from PIL import Image
except ImportError:
    print("HATA: Pillow kütüphanesi bulunamadı.")
    print("Lütfen kurun: pip install Pillow")
    exit(1)


# --- Sabitler ---
SYNODIC_MONTH = 29.530588853
REFERENCE_NEW_MOON_UTC = datetime.datetime(2023, 1, 21, 20, 53, tzinfo=datetime.timezone.utc)
MOON_IMAGE_FILENAME = "moon.png" # Ay resminin dosya adı

# --- Ay Evresi Hesaplama Fonksiyonu ---
# (Değişiklik yok)
def calculate_moon_phase(date_utc):
    delta = date_utc - REFERENCE_NEW_MOON_UTC
    days_since_reference = delta.total_seconds() / (24 * 60 * 60)
    current_cycle_days = days_since_reference % SYNODIC_MONTH
    phase_value = current_cycle_days / SYNODIC_MONTH
    if phase_value < 0:
        phase_value += 1.0
    return phase_value

# --- Ay Evresi Adlandırma Fonksiyonu ---
# (Değişiklik yok)
def get_phase_name(phase_value):
    epsilon = 0.02
    if phase_value < epsilon or phase_value > (1.0 - epsilon): return "Yeni Ay"
    if abs(phase_value - 0.5) < epsilon: return "Dolunay"
    if abs(phase_value - 0.25) < epsilon: return "İlk Dördün"
    if abs(phase_value - 0.75) < epsilon: return "Son Dördün"
    if 0.0 < phase_value < 0.25: return "Hilal (Büyüyen)"
    if 0.25 < phase_value < 0.5: return "Şişkin Ay (Büyüyen)"
    if 0.5 < phase_value < 0.75: return "Şişkin Ay (Küçülen)"
    if 0.75 < phase_value < 1.0: return "Hilal (Küçülen)"
    return "Bilinmeyen Evre"

# --- Ay Gölge Maskesi Çizim Fonksiyonu ---
# (Değişiklik yok, aynı koordinatları kullanacak)
def draw_shadow_mask(widget_width, widget_height, cr, phase_value):
    padding = 5
    drawable_height = widget_height - 90
    radius = min(widget_width, drawable_height) / 2 - padding
    center_x = widget_width / 2
    center_y = drawable_height / 2 + padding
    cr.set_source_rgba(0.0, 0.0, 0.0, 0.70)
    epsilon = 1e-6
    if abs(phase_value - 0.0) < epsilon or abs(phase_value - 1.0) < epsilon:
        cr.arc(center_x, center_y, radius, 0, 2 * math.pi); cr.fill(); return
    elif abs(phase_value - 0.5) < epsilon: return
    phase_angle_rad = phase_value * 2.0 * math.pi
    terminator_scale_x = math.cos(phase_angle_rad)
    cr.new_path()
    if 0.0 < phase_value < 0.5:
        if phase_value <= 0.25 + epsilon:
            cr.arc(center_x, center_y, radius, math.pi / 2.0, 3.0 * math.pi / 2.0)
            cr.save(); cr.translate(center_x, center_y); cr.scale(terminator_scale_x, 1.0)
            cr.arc(0, 0, radius, -math.pi / 2.0, math.pi / 2.0); cr.restore()
        else:
            cr.arc(center_x, center_y, radius, math.pi / 2.0, 3.0 * math.pi / 2.0)
            cr.save(); cr.translate(center_x, center_y); cr.scale(abs(terminator_scale_x), 1.0)
            cr.arc_negative(0, 0, radius, 3.0 * math.pi / 2.0, math.pi / 2.0); cr.restore()
    else:
        if phase_value <= 0.75 + epsilon:
            cr.arc(center_x, center_y, radius, -math.pi / 2.0, math.pi / 2.0)
            cr.save(); cr.translate(center_x, center_y); cr.scale(abs(terminator_scale_x), 1.0)
            cr.arc_negative(0, 0, radius, math.pi / 2.0, -math.pi / 2.0); cr.restore()
        else:
            cr.arc(center_x, center_y, radius, -math.pi / 2.0, math.pi / 2.0)
            cr.save(); cr.translate(center_x, center_y); cr.scale(terminator_scale_x, 1.0)
            cr.arc(0, 0, radius, math.pi / 2.0, 3.0 * math.pi / 2.0); cr.restore()
    cr.fill()


# --- Ana GTK Pencere Sınıfı ---
class MoonPhaseWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Ay Widget")
        # ... (Pencere ayarları aynı) ...
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_default_size(200, 280)

        self.has_alpha = False
        screen = self.get_screen()
        rgba_visual = screen.get_rgba_visual()
        if rgba_visual is not None and screen.is_composited():
            self.set_visual(rgba_visual)
            self.has_alpha = True

        self.dragging = False
        self.drag_start_x, self.drag_start_y = 0, 0
        self.window_start_x, self.window_start_y = 0, 0

        # --- Ay Resmini ve Bounding Box'ı Yükle ---
        self.moon_texture_pixbuf = None
        self.moon_bbox = None # (left, top, right, bottom)
        self.moon_bbox_width = 0
        self.moon_bbox_height = 0
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            image_path = os.path.join(script_dir, MOON_IMAGE_FILENAME)

            # 1. Pillow ile bbox bul
            with Image.open(image_path) as img:
                # Alfa kanalını al (veya RGBA'ya çevir)
                try:
                    alpha = img.getchannel('A')
                    self.moon_bbox = alpha.getbbox()
                    if self.moon_bbox:
                        l, t, r, b = self.moon_bbox
                        self.moon_bbox_width = r - l
                        self.moon_bbox_height = b - t
                        print(f"Ay Bounding Box bulundu: {self.moon_bbox}")
                        print(f"BBox Boyutları: {self.moon_bbox_width}x{self.moon_bbox_height}")
                    else:
                        print("Uyarı: Resimde saydam olmayan alan bulunamadı (getbbox None döndü).")
                        # Bbox yoksa, tüm resmi kullanmayı dene (eski davranış)
                        self.moon_bbox_width = img.width
                        self.moon_bbox_height = img.height
                        self.moon_bbox = (0, 0, img.width, img.height)

                except (ValueError, IndexError):
                    # Muhtemelen Alfa kanalı yoktu
                    print("Uyarı: Resimde Alfa kanalı bulunamadı. Tüm resim kullanılacak.")
                    self.moon_bbox_width = img.width
                    self.moon_bbox_height = img.height
                    self.moon_bbox = (0, 0, img.width, img.height)


            # 2. GdkPixbuf ile yükle (çizim için)
            self.moon_texture_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
            print(f"'{MOON_IMAGE_FILENAME}' GdkPixbuf olarak başarıyla yüklendi.")

        except FileNotFoundError:
             print(f"HATA: Ay resmi bulunamadı: {image_path}")
        except GLib.Error as e:
            print(f"HATA: Ay resmi GdkPixbuf olarak yüklenemedi: {e}")
        except Exception as e:
             print(f"Beklenmedik HATA: Ay resmi yüklenirken: {e}")


        # ... (Olay bağlantıları ve widget oluşturma aynı) ...
        self.connect("destroy", Gtk.main_quit)
        self.connect("draw", self.on_window_draw)
        self.connect("button-press-event", self.on_button_press)
        self.connect("motion-notify-event", self.on_motion_notify)
        self.connect("button-release-event", self.on_button_release)

        self.fixed = Gtk.Fixed()
        self.add(self.fixed)

        self.phase_label = Gtk.Label(name="phase-label")
        self.phase_label.set_use_markup(True)
        self.phase_label.set_halign(Gtk.Align.CENTER)
        self.phase_label.set_valign(Gtk.Align.START)
        self.fixed.put(self.phase_label, 10, 200)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.CENTER)
        backward_button = Gtk.Button(label="<")
        forward_button = Gtk.Button(label=">")
        backward_button.connect("clicked", self.on_backward_clicked)
        forward_button.connect("clicked", self.on_forward_clicked)
        button_box.pack_start(backward_button, False, False, 0)
        button_box.pack_start(forward_button, False, False, 0)
        self.fixed.put(button_box, 10, 240)

        # ... (CSS aynı) ...
        css_provider = Gtk.CssProvider()
        css = """
        #phase-label { color: white; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.8); }
        button { padding: 2px 6px; font-size: small; }
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.current_display_date = datetime.datetime.now(datetime.timezone.utc)
        self.update_phase()

    def update_phase(self):
        # (Konumlandırma dışında değişiklik yok)
        # ... (kod aynı) ...
        self.current_phase_value = calculate_moon_phase(self.current_display_date)
        phase_name = get_phase_name(self.current_phase_value)
        illumination_percent = (1 - math.cos(self.current_phase_value * 2 * math.pi)) / 2 * 100
        date_str = self.current_display_date.strftime("%Y-%m-%d")
        self.phase_label.set_markup(f"<small>{date_str}</small>\n<b>{phase_name}</b>\n<small>%{illumination_percent:.1f}</small>")
        width = self.get_size()[0]
        min_w, nat_w = self.phase_label.get_preferred_width()
        lbl_x = max(0, (width - nat_w) / 2)
        self.fixed.move(self.phase_label, int(lbl_x), 200)
        btn_box = self.fixed.get_children()[-1]
        min_w_btn, nat_w_btn = btn_box.get_preferred_width()
        btn_x = max(0, (width - nat_w_btn) / 2)
        self.fixed.move(btn_box, int(btn_x), 240)
        self.queue_draw()

    def on_window_draw(self, widget, cr):
        # 1. Arka Planı Temizle
        if self.has_alpha: cr.set_source_rgba(0.0, 0.0, 0.0, 0.0)
        else: cr.set_source_rgb(0.0, 0.0, 0.1)
        cr.set_operator(cairo.OPERATOR_SOURCE); cr.paint(); cr.set_operator(cairo.OPERATOR_OVER)

        # 2. Ay Resmini Bounding Box'a Göre Çiz (eğer yüklendiyse)
        if self.moon_texture_pixbuf and self.moon_bbox and self.moon_bbox_width > 0:
            width = widget.get_allocated_width()
            height = widget.get_allocated_height()
            padding = 5
            drawable_height = height - 90
            # Hedef çap ve yarıçap
            target_diameter = min(width, drawable_height) - 2 * padding
            target_radius = target_diameter / 2
            center_x = width / 2
            center_y = drawable_height / 2 + padding

            # Kaynak bbox bilgileri
            bbox_left, bbox_top, bbox_right, bbox_bottom = self.moon_bbox
            source_width = self.moon_bbox_width
            source_height = self.moon_bbox_height # Yüksekliği de kullanabiliriz ama genellikle Ay dairesel

            # Ölçek faktörünü hesapla (genişliğe göre sığdır)
            scale = target_diameter / source_width

            cr.save() # Durumu kaydet (clip, translate, scale için)

            # --- Hedef Daire Alanını Kırp ---
            cr.arc(center_x, center_y, target_radius, 0, 2 * math.pi)
            cr.clip()

            # --- Ölçekleme ve Konumlandırma ---
            # Hedef dairenin sol üst köşesine git
            cr.translate(center_x - target_radius, center_y - target_radius)
            # Hesaplanan ölçeği uygula
            cr.scale(scale, scale)
            # Pixbuf'ın bbox'ının sol üst köşesini (0,0)'a getirmek için geri çevir
            cr.translate(-bbox_left, -bbox_top)

            # --- Pixbuf'ı Kaynak Olarak Ayarla ve Çiz ---
            Gdk.cairo_set_source_pixbuf(cr, self.moon_texture_pixbuf, 0, 0)
            # İyi kalite için filtre ayarla (isteğe bağlı)
            cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            cr.paint() # Tüm kaynağı boya (kırpma ve dönüşümler doğru alanı çizecek)

            cr.restore() # Kırpmayı ve dönüşümleri geri al

            # 3. Gölge Maskesini Ay Resminin Üzerine Çiz
            # Gölge maskesi de aynı hedef koordinatları kullanmalı
            draw_shadow_mask(width, height, cr, self.current_phase_value)

        elif self.moon_texture_pixbuf:
             # Bbox bulunamadı ama resim var, eski yöntemle çiz (opsiyonel)
             # Veya sadece hata göster
             cr.set_source_rgb(1, 0.5, 0); cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
             cr.set_font_size(12); cr.move_to(10, 50); cr.show_text("Ay bbox bulunamadı!")
        else:
            # Resim yüklenemedi hatası
            cr.set_source_rgb(1, 0, 0); cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(12); cr.move_to(10, 50); cr.show_text("Ay resmi yüklenemedi!")

        return False

    # --- Sürükleme ve Buton Olay İşleyicileri ---
    # (Değişiklik yok)
    # ... (kod aynı) ...
    def on_button_press(self, widget, event):
        if event.button == 1: self.dragging=True; self.drag_start_x, self.drag_start_y = event.x_root, event.y_root; self.window_start_x, self.window_start_y = self.get_position(); return True
        return False
    def on_motion_notify(self, widget, event):
        if self.dragging: current_x, current_y = event.x_root, event.y_root; self.move(self.window_start_x + (current_x - self.drag_start_x), self.window_start_y + (current_y - self.drag_start_y)); return True
        return False
    def on_button_release(self, widget, event):
        if event.button == 1 and self.dragging: self.dragging = False; return True
        return False
    def on_backward_clicked(self, widget): self.current_display_date -= timedelta(days=1); self.update_phase()
    def on_forward_clicked(self, widget): self.current_display_date += timedelta(days=1); self.update_phase()

# --- Ana Program Akışı ---
if __name__ == "__main__":
    win = MoonPhaseWindow()
    win.show_all()
    Gtk.main()
