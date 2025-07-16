import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import csv
import os
import subprocess
import webbrowser
from PIL import Image, ImageTk

PREVIEW_WIDTH = 240
PREVIEW_HEIGHT = 135

class DupeCheckerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dupe Checker")

        self.duplicates = []
        self.preview_index = 0

        self.csv_cancelled = False
        self.preview_cancelled = False

        self.preview_images = {}  # indexed by row
        self.setup_gui()

    def setup_gui(self):
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Import CSV", command=self.import_csv).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel CSV Import", command=self.cancel_csv_import).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Generate Previews", command=self.generate_previews).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel Image Preview Generation", command=self.cancel_preview_generation).pack(side=tk.LEFT, padx=5)

        self.status_label = tk.Label(self.root, text="Status: Ready")
        self.status_label.pack(pady=5)

        columns = ("name", "path", "size", "duration", "preview")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings", height=20)
        self.tree.pack(fill=tk.BOTH, expand=True)

        for col, w in zip(columns, [200, 300, 100, 100, 80]):
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=w)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Open in Explorer", command=self.open_in_explorer)
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<Double-1>", self.on_double_click)

    def show_context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.menu.post(event.x_root, event.y_root)

    def open_in_explorer(self):
        selected = self.tree.selection()
        if selected:
            path = self.tree.item(selected[0], "values")[1]
            folder = os.path.dirname(path)
            webbrowser.open(f'file:///{folder}')

    def on_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            index = self.tree.index(item)
            if index in self.preview_images:
                self.show_image_popup(self.preview_images[index])

    def show_image_popup(self, photo):
        top = tk.Toplevel(self.root)
        top.title("Preview")
        lbl = tk.Label(top, image=photo)
        lbl.image = photo
        lbl.pack()

    # CSV Import
    def import_csv(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file_path:
            self.duplicates.clear()
            self.preview_images.clear()
            self.preview_index = 0
            self.tree.delete(*self.tree.get_children())
            self.csv_cancelled = False
            threading.Thread(target=self.load_csv, args=(file_path,)).start()

    def cancel_csv_import(self):
        self.csv_cancelled = True

    def load_csv(self, file_path):
        seen_names = set()
        seen_sizes = set()
        count = 0
        with open(file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if self.csv_cancelled:
                    self.update_status("CSV import cancelled.")
                    return
                if len(row) < 3:
                    continue
                name, path, size_str = row[0].strip(), row[1].strip(), row[2].strip()
                try:
                    size = int(size_str)
                except:
                    size = 0
                duration = self.get_duration(path)
                if name in seen_names or size_str in seen_sizes:
                    self.duplicates.append({"name": name, "path": path, "size": size, "duration": duration})
                    self.root.after(0, self.insert_tree_item, name, path, size, duration, "")
                seen_names.add(name)
                seen_sizes.add(size_str)
                count += 1
                if count % 50 == 0:
                    self.update_status(f"Imported {count} lines...")
        self.update_status(f"CSV load completed. Total: {count}")

    def insert_tree_item(self, name, path, size, duration, preview):
        self.tree.insert("", tk.END, values=(
            name,
            path,
            self.format_size(size),
            self.format_duration(duration),
            preview
        ))

    # Preview Generation
    def generate_previews(self):
        if not self.duplicates:
            messagebox.showinfo("Info", "No duplicates loaded.")
            return
        self.preview_cancelled = False
        threading.Thread(target=self._generate_previews).start()

    def cancel_preview_generation(self):
        self.preview_cancelled = True

    def _generate_previews(self):
        total = len(self.duplicates)
        while self.preview_index < total:
            if self.preview_cancelled:
                self.update_status(f"Preview generation cancelled at {self.preview_index}/{total}")
                return
            file = self.duplicates[self.preview_index]
            preview_path = f"preview_{self.preview_index}.jpg"
            halfway = float(file["duration"])/2 if file["duration"] else 1
            self.extract_frame(file["path"], preview_path, halfway)
            try:
                img = Image.open(preview_path).resize((PREVIEW_WIDTH, PREVIEW_HEIGHT))
                photo = ImageTk.PhotoImage(img)
                self.preview_images[self.preview_index] = photo
                self.root.after(0, self.update_tree_preview, self.preview_index, "✔")
            except:
                pass
            self.preview_index += 1
            if self.preview_index % 5 == 0:
                self.update_status(f"Generated {self.preview_index}/{total} previews")
        self.update_status("Preview generation completed.")

    def update_tree_preview(self, index, preview_mark):
        iid = self.tree.get_children()[index]
        values = list(self.tree.item(iid, "values"))
        values[4] = preview_mark
        self.tree.item(iid, values=values)

    # Utilities
    def format_size(self, size):
        try:
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size < 1024:
                    return f"{size:.2f} {unit}"
                size /= 1024
            return f"{size:.2f} PB"
        except:
            return str(size)

    def format_duration(self, seconds):
        try:
            seconds = int(float(seconds))
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"
        except:
            return "0:00"

    def get_duration(self, filepath):
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of",
                 "default=noprint_wrappers=1:nokey=1", filepath],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return float(result.stdout.strip())
        except:
            return 0

    def extract_frame(self, filepath, output, timestamp):
        try:
            subprocess.run(
                ["ffmpeg", "-ss", str(timestamp), "-i", filepath,
                 "-vframes", "1", "-s", f"{PREVIEW_WIDTH}x{PREVIEW_HEIGHT}", "-y", output],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except:
            pass

    def update_status(self, msg):
        self.root.after(0, self.status_label.config, {"text": f"Status: {msg}"})

if __name__ == "__main__":
    root = tk.Tk()
    app = DupeCheckerApp(root)
    root.mainloop()
