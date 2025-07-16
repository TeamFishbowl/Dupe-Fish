import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import csv
import os
import subprocess
from PIL import Image, ImageTk
import io
import threading
import sys

PREVIEW_WIDTH = 240
PREVIEW_HEIGHT = 135

STARTUPINFO = None
if sys.platform == "win32":
    STARTUPINFO = subprocess.STARTUPINFO()
    STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW

APP_DIR = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__)
FFMPEG_PATH = os.path.join(APP_DIR, "ffmpeg.exe")
FFPROBE_PATH = os.path.join(APP_DIR, "ffprobe.exe")

def format_size(num_bytes):
    try:
        size = float(num_bytes)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
    except:
        return str(num_bytes)

class DupeCheckerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Duplicate Media Checker")
        self.root.geometry("1100x600")

        self.data = []
        self.duplicates = []
        self.tree_images = {}

        self.import_cancelled = False
        self.preview_cancelled = False

        self.status_var = tk.StringVar(value="Ready")

        self.setup_gui()

    def setup_gui(self):
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill="x", pady=5)

        tk.Button(btn_frame, text="Import CSV", command=self.start_import).pack(side="left", padx=5)
        self.cancel_import_btn = tk.Button(btn_frame, text="Cancel Import", command=self.cancel_import, state="disabled")
        self.cancel_import_btn.pack(side="left", padx=5)

        tk.Button(btn_frame, text="Generate Previews", command=self.start_generate_previews).pack(side="left", padx=5)
        self.cancel_preview_btn = tk.Button(btn_frame, text="Cancel Preview", command=self.cancel_preview, state="disabled")
        self.cancel_preview_btn.pack(side="left", padx=5)

        status_label = tk.Label(self.root, textvariable=self.status_var, anchor="w")
        status_label.pack(fill="x", padx=5)

        columns = ("Name", "Path", "Size", "Duration")
        self.tree = ttk.Treeview(self.root, columns=columns, show="tree headings")
        self.tree.heading("#0", text="Preview")
        self.tree.column("#0", width=PREVIEW_WIDTH, stretch=False)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=200, anchor="w")
        self.tree.pack(fill="both", expand=True)

        self.tree.bind("<Button-3>", self.show_context_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Open File Location", command=self.open_file_location)

    def show_context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.menu.post(event.x_root, event.y_root)

    def open_file_location(self):
        selected = self.tree.selection()
        if not selected:
            return
        item = selected[0]
        path = self.tree.item(item, "values")[1]
        name = self.tree.item(item, "values")[0]
        full_path = os.path.join(path, name)
        if os.path.exists(full_path):
            if sys.platform == "win32":
                subprocess.run(['explorer', '/select,', full_path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", full_path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(full_path)])
        else:
            messagebox.showwarning("Warning", "Path does not exist")

    def start_import(self):
        if self.import_cancelled == False and self.import_thread_is_alive():
            messagebox.showinfo("Info", "Import already running")
            return
        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if not file_path:
            return
        self.import_cancelled = False
        self.cancel_import_btn.config(state="normal")
        self.status_var.set("Starting CSV import...")
        self.data.clear()
        self.duplicates.clear()
        self.tree_images.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.import_thread = threading.Thread(target=self.import_csv_worker, args=(file_path,), daemon=True)
        self.import_thread.start()

    def import_thread_is_alive(self):
        return hasattr(self, "import_thread") and self.import_thread.is_alive()

    def cancel_import(self):
        if self.import_thread_is_alive():
            self.import_cancelled = True
            self.status_var.set("Cancelling CSV import...")
            self.cancel_import_btn.config(state="disabled")

    def import_csv_worker(self, file_path):
        try:
            with open(file_path, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for i, row in enumerate(reader):
                    if self.import_cancelled:
                        self.root.after(0, lambda: self.status_var.set("CSV import cancelled"))
                        self.root.after(0, lambda: self.cancel_import_btn.config(state="disabled"))
                        return
                    try:
                        row['Size'] = float(row['Size'])
                        row['Name'] = row['Name'].strip()
                        row['Path'] = row['Path'].strip()
                    except:
                        continue
                    self.data.append(row)
                    if i % 100 == 0:
                        self.root.after(0, lambda i=i: self.status_var.set(f"Imported {i} rows..."))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to import CSV:\n{e}"))
            self.root.after(0, lambda: self.cancel_import_btn.config(state="disabled"))
            return

        size_map = {}
        for d in self.data:
            size_map.setdefault(d['Size'], []).append(d)

        duplicates_set = set()
        for size, files in size_map.items():
            if len(files) > 1:
                duplicates_set.update(map(id, files))

        self.duplicates = [d for d in self.data if id(d) in duplicates_set]

        for i, d in enumerate(self.duplicates):
            d['Duration'], d['Timecode'] = self.get_duration_and_timecode(d['Path'], d['Name'])
            if i % 20 == 0:
                self.root.after(0, lambda i=i: self.status_var.set(f"Processed {i}/{len(self.duplicates)} duplicates..."))

        self.root.after(0, self.populate_treeview)
        self.root.after(0, lambda: self.status_var.set(f"Import complete. {len(self.duplicates)} duplicates found"))
        self.root.after(0, lambda: self.cancel_import_btn.config(state="disabled"))

    def populate_treeview(self):
        self.tree_images.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for d in self.duplicates:
            item = self.tree.insert("", tk.END, text="", image="", values=(
                d['Name'],
                d['Path'],
                format_size(d['Size']),
                d.get('Duration', 'Unknown'),
            ))

    def start_generate_previews(self):
        if not self.duplicates:
            messagebox.showinfo("Info", "No duplicates loaded to generate previews.")
            return
        if self.preview_cancelled == False and hasattr(self, "preview_thread") and self.preview_thread.is_alive():
            messagebox.showinfo("Info", "Preview generation already running")
            return
        self.preview_cancelled = False
        self.cancel_preview_btn.config(state="normal")
        self.status_var.set("Starting preview generation...")
        self.preview_thread = threading.Thread(target=self.generate_previews_worker, daemon=True)
        self.preview_thread.start()

    def cancel_preview(self):
        if hasattr(self, "preview_thread") and self.preview_thread.is_alive():
            self.preview_cancelled = True
            self.status_var.set("Cancelling preview generation...")
            self.cancel_preview_btn.config(state="disabled")

    def generate_previews_worker(self):
        items = self.tree.get_children()
        total = len(items)
        for i, item in enumerate(items):
            if self.preview_cancelled:
                self.root.after(0, lambda: self.status_var.set(f"Preview generation cancelled at {i}/{total}"))
                self.root.after(0, lambda: self.cancel_preview_btn.config(state="disabled"))
                return
            values = self.tree.item(item, "values")
            name, path = values[0], values[1]
            full_path = os.path.join(path, name)
            timecode = next((d['Timecode'] for d in self.duplicates if d['Name'] == name and d['Path'] == path), "00:00:01")
            img = self.get_preview_image(full_path, timecode)
            if img:
                self.tree_images[item] = img
                self.root.after(0, lambda i=item, photo=img: self.tree.item(i, image=photo))
            self.root.after(0, lambda i=i: self.status_var.set(f"Generated previews: {i+1}/{total}"))
        self.root.after(0, lambda: self.status_var.set("Preview generation completed"))
        self.root.after(0, lambda: self.cancel_preview_btn.config(state="disabled"))

    def get_duration_and_timecode(self, path, filename):
        full_path = os.path.join(path, filename)
        if not os.path.isfile(full_path):
            return "Unknown", "00:00:01"
        try:
            duration_raw = subprocess.check_output([
                FFPROBE_PATH, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                full_path
            ], stderr=subprocess.DEVNULL, startupinfo=STARTUPINFO).decode().strip()
            total_seconds = int(float(duration_raw))
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            duration = f"{hours:02}:{minutes:02}:{seconds:02}" if hours > 0 else f"{minutes:02}:{seconds:02}"
            half = total_seconds // 2
            hh, mm, ss = half // 3600, (half % 3600) // 60, half % 60
            return duration, f"{hh:02}:{mm:02}:{ss:02}"
        except:
            return "Unknown", "00:00:01"

    def get_preview_image(self, full_path, timecode):
        try:
            ffmpeg_cmd = [
                FFMPEG_PATH, "-ss", timecode, "-i", full_path, "-frames:v", "1",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-"
            ]
            image_data = subprocess.check_output(ffmpeg_cmd, stderr=subprocess.DEVNULL, startupinfo=STARTUPINFO)
            image = Image.open(io.BytesIO(image_data))
            image = image.resize((PREVIEW_WIDTH, PREVIEW_HEIGHT), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(image)
        except:
            return None

if __name__ == "__main__":
    root = tk.Tk()
    app = DupeCheckerApp(root)
    root.mainloop()
