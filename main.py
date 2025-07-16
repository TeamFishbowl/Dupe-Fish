import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import csv
import os
import subprocess
import webbrowser
from PIL import Image, ImageTk
import time

# Preview size config
PREVIEW_WIDTH = 240
PREVIEW_HEIGHT = 135

class DupeCheckerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dupe Checker")
        
        # data structures
        self.files = []
        self.duplicates = []
        self.preview_index = 0

        # control flags
        self.csv_loading_thread = None
        self.csv_cancelled = False
        self.preview_thread = None
        self.preview_cancelled = False

        # GUI
        self.setup_gui()

    def setup_gui(self):
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Import CSV", command=self.import_csv).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel CSV Import", command=self.cancel_csv_import).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Generate Previews", command=self.generate_previews).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel Image Preview Generation", command=self.cancel_preview_generation).pack(side=tk.LEFT, padx=5)

        columns = ("preview", "name", "path", "size", "duration")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings", height=20)
        self.tree.pack(fill=tk.BOTH, expand=True)

        for col in columns:
            self.tree.heading(col, text=col.capitalize())
            if col == "preview":
                self.tree.column(col, width=PREVIEW_WIDTH+20)
            elif col == "path":
                self.tree.column(col, width=300)
            else:
                self.tree.column(col, width=100)

        # right-click menu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Open in Explorer", command=self.open_in_explorer)
        self.tree.bind("<Button-3>", self.show_context_menu)

        # for image previews
        self.preview_images = {}

    def show_context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.menu.post(event.x_root, event.y_root)

    def open_in_explorer(self):
        selected = self.tree.selection()
        if selected:
            path = self.tree.item(selected[0], "values")[2]
            folder = os.path.dirname(path)
            webbrowser.open(f'file:///{folder}')

    # =================
    # CSV Import
    # =================
    def import_csv(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file_path:
            self.files.clear()
            self.duplicates.clear()
            self.tree.delete(*self.tree.get_children())
            self.csv_cancelled = False
            self.csv_loading_thread = threading.Thread(target=self.load_csv, args=(file_path,))
            self.csv_loading_thread.start()

    def cancel_csv_import(self):
        self.csv_cancelled = True

    def load_csv(self, file_path):
        seen_names = set()
        seen_sizes = set()
        with open(file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if self.csv_cancelled:
                    break
                if len(row) < 3:
                    continue
                name, path, size = row[0].strip(), row[1].strip(), row[2].strip()
                if name in seen_names or size in seen_sizes:
                    self.duplicates.append({"name": name, "path": path, "size": size, "duration": "", "preview": None})
                    self.root.after(0, self.insert_tree_item, name, path, size, "", "")
                seen_names.add(name)
                seen_sizes.add(size)
        print("CSV load finished or cancelled.")

    def insert_tree_item(self, name, path, size, duration, preview_id):
        self.tree.insert("", tk.END, values=("", name, path, self.format_size(size), duration))

    def format_size(self, size):
        try:
            size = int(size)
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size < 1024.0:
                    return f"{size:.2f} {unit}"
                size /= 1024.0
            return f"{size:.2f} PB"
        except:
            return size

    # =================
    # Preview Generation
    # =================
    def generate_previews(self):
        if not self.duplicates:
            messagebox.showinfo("Info", "No duplicates loaded.")
            return
        self.preview_cancelled = False
        if not self.preview_thread or not self.preview_thread.is_alive():
            self.preview_thread = threading.Thread(target=self._generate_previews)
            self.preview_thread.start()

    def cancel_preview_generation(self):
        self.preview_cancelled = True

    def _generate_previews(self):
        while self.preview_index < len(self.duplicates):
            if self.preview_cancelled:
                print("Preview generation cancelled.")
                break
            file = self.duplicates[self.preview_index]
            preview_path = f"preview_{self.preview_index}.jpg"
            duration = self.get_duration(file["path"])
            halfway = duration / 2 if duration else 1
            self.extract_frame(file["path"], preview_path, halfway)
            img = Image.open(preview_path).resize((PREVIEW_WIDTH, PREVIEW_HEIGHT))
            photo = ImageTk.PhotoImage(img)
            self.preview_images[self.preview_index] = photo
            self.update_tree_preview(self.preview_index, photo, duration)
            self.preview_index += 1

    def update_tree_preview(self, index, photo, duration):
        iid = self.tree.get_children()[index]
        self.tree.item(iid, image=photo, values=("", self.duplicates[index]["name"], 
                                                self.duplicates[index]["path"], 
                                                self.format_size(self.duplicates[index]["size"]), 
                                                self.format_duration(duration)))
        self.tree.tag_configure(iid, image=photo)

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
        except Exception as e:
            print(f"ffmpeg failed: {e}")

    def format_duration(self, seconds):
        try:
            seconds = int(seconds)
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            if h > 0:
                return f"{h:d}:{m:02d}:{s:02d}"
            else:
                return f"{m:02d}:{s:02d}"
        except:
            return "0:00"

if __name__ == "__main__":
    root = tk.Tk()
    app = DupeCheckerApp(root)
    root.mainloop()
