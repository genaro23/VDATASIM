import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
import os
import threading
import time

class ErasureCodedStorage:
    def __init__(self):
        self.num_data_drives = 142
        self.num_parity_drives = 4
        self.total_drives = 146
        self.drive_size = 1024 * 1024  # 1MB
        self.chunk_size = 4096  # 4KB chunks
        
        # Group configuration
        self.group_a_size = 71  # Drives 0-70
        self.group_b_size = 71  # Drives 71-141
        
        self.drives = []
        self.drive_status = [True] * self.total_drives  # True = online
        self.drive_usage = [0.0] * self.total_drives  # Percentage used
        self.storage_path = "./storage"
        
    def initialize_drives(self):
        """Create 146 1MB binary files filled with zeros"""
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)
        
        for i in range(self.total_drives):
            filepath = os.path.join(self.storage_path, f"drive_{i:03d}.data")
            with open(filepath, 'wb') as f:
                f.write(b'\x00' * self.drive_size)
            self.drives.append(filepath)
        
        return True
    
    def get_drive_type(self, drive_id):
        """Determine the type of drive"""
        if drive_id < 71:
            return "Data (Group A)"
        elif drive_id < 142:
            return "Data (Group B)"
        elif drive_id == 142:
            return "Local Parity A"
        elif drive_id == 143:
            return "Local Parity B"
        elif drive_id == 144:
            return "Global Parity 0"
        elif drive_id == 145:
            return "Global Parity 1"
        return "Unknown"
    
    def calculate_parity(self, data_chunks):
        """Calculate XOR parity for given data chunks"""
        if len(data_chunks) == 0:
            return np.zeros(self.chunk_size, dtype=np.uint8)
        
        parity = np.zeros(self.chunk_size, dtype=np.uint8)
        for chunk in data_chunks:
            parity ^= chunk
        return parity
    
    def write_data(self, input_file, progress_callback=None):
        """Write input file to the storage system using erasure coding"""
        if not os.path.exists(input_file):
            return False, "Input file not found"
        
        file_size = os.path.getsize(input_file)
        total_capacity = self.num_data_drives * self.drive_size
        
        if file_size > total_capacity:
            return False, f"File too large. Max size: {total_capacity / (1024*1024):.2f}MB"
        
        # Read input file
        with open(input_file, 'rb') as f:
            file_data = f.read()
        
        # Pad to chunk boundary
        padded_size = ((len(file_data) + self.chunk_size - 1) // self.chunk_size) * self.chunk_size
        file_data = file_data.ljust(padded_size, b'\x00')
        
        # Calculate number of chunks per drive
        num_chunks = len(file_data) // self.chunk_size
        chunks_per_drive = (num_chunks + self.num_data_drives - 1) // self.num_data_drives
        
        # Distribute data across drives
        chunk_index = 0
        for drive_id in range(self.num_data_drives):
            drive_data = b''
            for _ in range(chunks_per_drive):
                if chunk_index < num_chunks:
                    start = chunk_index * self.chunk_size
                    end = start + self.chunk_size
                    drive_data += file_data[start:end]
                    chunk_index += 1
                else:
                    drive_data += b'\x00' * self.chunk_size
            
            # Write to drive
            filepath = self.drives[drive_id]
            with open(filepath, 'r+b') as f:
                f.write(drive_data)
            
            # Update usage
            self.drive_usage[drive_id] = (len(drive_data) / self.drive_size) * 100
            
            if progress_callback:
                progress_callback(drive_id, self.total_drives)
        
        # Calculate and write local parity A (Group A: drives 0-70)
        self._calculate_local_parity(0, 71, 142, chunks_per_drive, progress_callback)
        
        # Calculate and write local parity B (Group B: drives 71-141)
        self._calculate_local_parity(71, 142, 143, chunks_per_drive, progress_callback)
        
        # Calculate and write global parity
        self._calculate_global_parity(chunks_per_drive, progress_callback)
        
        return True, "Data written successfully"
    
    def _calculate_local_parity(self, start_drive, end_drive, parity_drive, chunks_per_drive, progress_callback):
        """Calculate local parity for a group of drives"""
        parity_data = b''
        
        for chunk_idx in range(chunks_per_drive):
            chunks = []
            for drive_id in range(start_drive, end_drive):
                if self.drive_status[drive_id]:
                    filepath = self.drives[drive_id]
                    with open(filepath, 'rb') as f:
                        f.seek(chunk_idx * self.chunk_size)
                        chunk = np.frombuffer(f.read(self.chunk_size), dtype=np.uint8)
                        if len(chunk) == self.chunk_size:
                            chunks.append(chunk)
            
            parity_chunk = self.calculate_parity(chunks)
            parity_data += parity_chunk.tobytes()
        
        # Write parity
        filepath = self.drives[parity_drive]
        with open(filepath, 'r+b') as f:
            f.write(parity_data)
        
        self.drive_usage[parity_drive] = (len(parity_data) / self.drive_size) * 100
        
        if progress_callback:
            progress_callback(parity_drive, self.total_drives)
    
    def _calculate_global_parity(self, chunks_per_drive, progress_callback):
        """Calculate global parity using simple XOR (Reed-Solomon simplified)"""
        # Global Parity 0: XOR of all data drives
        parity0_data = b''
        for chunk_idx in range(chunks_per_drive):
            chunks = []
            for drive_id in range(self.num_data_drives):
                if self.drive_status[drive_id]:
                    filepath = self.drives[drive_id]
                    with open(filepath, 'rb') as f:
                        f.seek(chunk_idx * self.chunk_size)
                        chunk = np.frombuffer(f.read(self.chunk_size), dtype=np.uint8)
                        if len(chunk) == self.chunk_size:
                            chunks.append(chunk)
            
            parity_chunk = self.calculate_parity(chunks)
            parity0_data += parity_chunk.tobytes()
        
        filepath = self.drives[144]
        with open(filepath, 'r+b') as f:
            f.write(parity0_data)
        
        self.drive_usage[144] = (len(parity0_data) / self.drive_size) * 100
        
        # Global Parity 1: Weighted XOR for additional protection
        parity1_data = b''
        for chunk_idx in range(chunks_per_drive):
            chunks = []
            for drive_id in range(self.num_data_drives):
                if self.drive_status[drive_id]:
                    filepath = self.drives[drive_id]
                    with open(filepath, 'rb') as f:
                        f.seek(chunk_idx * self.chunk_size)
                        chunk = np.frombuffer(f.read(self.chunk_size), dtype=np.uint8)
                        if len(chunk) == self.chunk_size:
                            # Apply galois field multiplication (simplified)
                            weighted_chunk = ((chunk * (drive_id + 1)) % 256).astype(np.uint8)
                            chunks.append(weighted_chunk)
            
            parity_chunk = self.calculate_parity(chunks)
            parity1_data += parity_chunk.tobytes()
        
        filepath = self.drives[145]
        with open(filepath, 'r+b') as f:
            f.write(parity1_data)
        
        self.drive_usage[145] = (len(parity1_data) / self.drive_size) * 100
        
        if progress_callback:
            progress_callback(145, self.total_drives)
    
    def check_data_integrity(self):
        """Check if data can be recovered with current drive failures"""
        offline_drives = [i for i, status in enumerate(self.drive_status) if not status]
        
        if len(offline_drives) == 0:
            return True, "All drives online"
        
        if len(offline_drives) == 1:
            return True, "Can recover with local or global parity"
        
        # Check if failures are in same group
        group_a_failures = [d for d in offline_drives if d < 71]
        group_b_failures = [d for d in offline_drives if 71 <= d < 142]
        
        if len(group_a_failures) <= 2 and len(group_b_failures) == 0:
            return True, "Can recover using local and global parity (Group A)"
        
        if len(group_b_failures) <= 2 and len(group_a_failures) == 0:
            return True, "Can recover using local and global parity (Group B)"
        
        if len(group_a_failures) <= 1 and len(group_b_failures) <= 1:
            return True, "Can recover with distributed failures"
        
        return False, f"Data loss possible with {len(offline_drives)} drive failures"


class StorageGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Erasure Coded Storage System - 142+4 Configuration")
        self.root.geometry("1400x900")
        
        self.storage = ErasureCodedStorage()
        self.drive_buttons = []
        self.rebuild_active = False
        
        self.setup_ui()
        
    def setup_ui(self):
        # Top control panel
        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(side=tk.TOP, fill=tk.X)
        
        ttk.Button(control_frame, text="Initialize Storage", 
                   command=self.initialize_storage).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Load File", 
                   command=self.load_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Check Integrity", 
                   command=self.check_integrity).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Simulate Rebuild", 
                   command=self.simulate_rebuild).pack(side=tk.LEFT, padx=5)
        
        # Status label
        self.status_label = ttk.Label(control_frame, text="Ready", 
                                      font=("Arial", 10, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=20)
        
        # Progress bar
        self.progress = ttk.Progressbar(control_frame, length=200, mode='determinate')
        self.progress.pack(side=tk.LEFT, padx=5)
        
        # Main canvas with scrollbar
        canvas_frame = ttk.Frame(self.root)
        canvas_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        canvas = tk.Canvas(canvas_frame, bg="white")
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Create drive buttons in a grid
        self.drives_frame = scrollable_frame
        self.create_drive_grid()
        
        # Info panel
        info_frame = ttk.Frame(self.root, padding="10")
        info_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        ttk.Label(info_frame, text="Legend:", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(info_frame, text="🟢 Online", foreground="green").pack(side=tk.LEFT, padx=10)
        ttk.Label(info_frame, text="🔴 Offline", foreground="red").pack(side=tk.LEFT, padx=10)
        ttk.Label(info_frame, text="Group A: 0-70 | Group B: 71-141 | Parity: 142-145").pack(side=tk.LEFT, padx=20)
    
    def create_drive_grid(self):
        """Create a grid of drive buttons"""
        columns = 20
        
        for i in range(self.storage.total_drives):
            row = i // columns
            col = i % columns
            
            # Create frame for each drive
            drive_frame = tk.Frame(self.drives_frame, relief=tk.RAISED, borderwidth=2)
            drive_frame.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
            
            # Drive button
            btn = tk.Button(drive_frame, text=f"D{i}\n0%", 
                           width=6, height=3,
                           bg="lightgreen",
                           command=lambda x=i: self.toggle_drive(x))
            btn.pack(fill=tk.BOTH, expand=True)
            
            self.drive_buttons.append(btn)
            
            # Tooltip on hover
            self.create_tooltip(btn, i)
    
    def create_tooltip(self, widget, drive_id):
        """Create hover tooltip for drive info"""
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            
            label = tk.Label(tooltip, text=f"Drive {drive_id}\n{self.storage.get_drive_type(drive_id)}\n"
                                          f"Usage: {self.storage.drive_usage[drive_id]:.1f}%",
                           background="lightyellow", relief=tk.SOLID, borderwidth=1,
                           font=("Arial", 9))
            label.pack()
            
            widget.tooltip = tooltip
        
        def on_leave(event):
            if hasattr(widget, 'tooltip'):
                widget.tooltip.destroy()
                del widget.tooltip
        
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)
    
    def initialize_storage(self):
        """Initialize the storage system"""
        self.status_label.config(text="Initializing storage...")
        self.root.update()
        
        if self.storage.initialize_drives():
            self.status_label.config(text="Storage initialized")
            messagebox.showinfo("Success", "Storage system initialized with 146 drives")
        else:
            self.status_label.config(text="Initialization failed")
            messagebox.showerror("Error", "Failed to initialize storage")
    
    def load_file(self):
        """Load a file and distribute it across drives"""
        filepath = filedialog.askopenfilename(title="Select file to store")
        if not filepath:
            return
        
        self.status_label.config(text="Writing data...")
        self.progress['value'] = 0
        self.root.update()
        
        def progress_callback(current, total):
            self.progress['value'] = (current / total) * 100
            self.update_drive_display(current)
            self.root.update()
        
        def write_thread():
            success, message = self.storage.write_data(filepath, progress_callback)
            self.root.after(0, lambda: self.write_complete(success, message))
        
        thread = threading.Thread(target=write_thread)
        thread.start()
    
    def write_complete(self, success, message):
        """Called when write operation completes"""
        self.status_label.config(text=message)
        self.progress['value'] = 100
        
        # Update all drive displays
        for i in range(self.storage.total_drives):
            self.update_drive_display(i)
        
        if success:
            messagebox.showinfo("Success", message)
        else:
            messagebox.showerror("Error", message)
    
    def toggle_drive(self, drive_id):
        """Toggle drive online/offline status"""
        self.storage.drive_status[drive_id] = not self.storage.drive_status[drive_id]
        self.update_drive_display(drive_id)
        
        # Check integrity after toggle
        self.root.after(100, self.check_integrity_silent)
    
    def update_drive_display(self, drive_id):
        """Update the visual display of a drive button"""
        btn = self.drive_buttons[drive_id]
        usage = self.storage.drive_usage[drive_id]
        online = self.storage.drive_status[drive_id]
        
        # Update text
        btn.config(text=f"D{drive_id}\n{usage:.0f}%")
        
        # Update color based on status
        if online:
            # Green gradient based on usage
            if usage > 75:
                btn.config(bg="darkgreen", fg="white")
            elif usage > 0:
                btn.config(bg="lightgreen", fg="black")
            else:
                btn.config(bg="white", fg="black")
        else:
            btn.config(bg="red", fg="white")
    
    def check_integrity(self):
        """Check data integrity and show message"""
        can_recover, message = self.storage.check_data_integrity()
        
        offline_count = sum(1 for status in self.storage.drive_status if not status)
        
        if can_recover:
            messagebox.showinfo("Data Integrity", 
                               f"{message}\nOffline drives: {offline_count}")
        else:
            messagebox.showwarning("Data Integrity", 
                                  f"{message}\nOffline drives: {offline_count}")
        
        self.status_label.config(text=message)
    
    def check_integrity_silent(self):
        """Check integrity without showing message box"""
        can_recover, message = self.storage.check_data_integrity()
        self.status_label.config(text=message)
    
    def simulate_rebuild(self):
        """Simulate rebuilding failed drives"""
        offline_drives = [i for i, status in enumerate(self.storage.drive_status) if not status]
        
        if len(offline_drives) == 0:
            messagebox.showinfo("Rebuild", "No drives to rebuild")
            return
        
        can_recover, message = self.storage.check_data_integrity()
        
        if not can_recover:
            messagebox.showerror("Rebuild Failed", 
                               "Cannot rebuild - too many drive failures")
            return
        
        # Simulate rebuild process
        self.status_label.config(text=f"Rebuilding {len(offline_drives)} drive(s)...")
        
        def rebuild_animation():
            for i, drive_id in enumerate(offline_drives):
                # Simulate rebuild delay
                time.sleep(0.5)
                
                # Bring drive back online
                self.storage.drive_status[drive_id] = True
                self.root.after(0, self.update_drive_display, drive_id)
                
                progress = ((i + 1) / len(offline_drives)) * 100
                self.root.after(0, lambda p=progress: self.progress.config(value=p))
            
            self.root.after(0, lambda: self.status_label.config(text="Rebuild complete"))
            self.root.after(0, lambda: messagebox.showinfo("Success", 
                                                           f"Rebuilt {len(offline_drives)} drive(s)"))
        
        thread = threading.Thread(target=rebuild_animation)
        thread.start()


def main():
    root = tk.Tk()
    app = StorageGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
