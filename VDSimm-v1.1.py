import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
import os
import threading
import time
import struct

class ErasureCodedStorage:
    def __init__(self):
        self.num_data_drives = 142
        self.num_local_parity = 10
        self.num_global_parity = 2
        self.num_hot_spares = 2
        self.total_drives = 156
        self.drive_size = 1024 * 1024  # 1MB
        self.chunk_size = 4096  # 4KB chunks
        
        # Local groups: 10 groups of 14 data drives each
        self.local_groups = []
        for i in range(10):
            start = i * 14
            end = start + 14
            self.local_groups.append({
                'data_drives': list(range(start, end)),
                'parity_drive': 142 + i  # Drives 142-151
            })
        
        # Global parity drives: 152, 153
        self.global_parity_drives = [152, 153]
        
        # Hot spares: 154, 155
        self.hot_spare_drives = [154, 155]
        
        # Dnode configuration: 4 Dnodes of 39 drives each (156/4 = 39)
        # Each Dnode gets mixed data, local parity, and at most 1 global parity
        self.dnodes = self._configure_dnodes()
        
        self.drives = []
        self.drive_status = [True] * self.total_drives  # True = online
        self.drive_data_preview = ['00000000'] * self.total_drives  # Hex preview
        self.storage_path = "./storage_Sim1"
        
    def _configure_dnodes(self):
        """Configure 4 Dnodes with balanced distribution"""
        dnodes = []
        
        # Dnode 0: Data 0-34, Local Parity 142-144, Global Parity 152
        dnodes.append({
            'id': 0,
            'drives': list(range(0, 35)) + [142, 143, 144, 152] + [154],  # 40 drives
            'name': 'Dnode-0'
        })
        
        # Dnode 1: Data 35-69, Local Parity 145-147, Global Parity 153
        dnodes.append({
            'id': 1,
            'drives': list(range(35, 70)) + [145, 146, 147, 153] + [155],  # 40 drives
            'name': 'Dnode-1'
        })
        
        # Dnode 2: Data 70-104, Local Parity 148-150
        dnodes.append({
            'id': 2,
            'drives': list(range(70, 105)) + [148, 149, 150],  # 38 drives
            'name': 'Dnode-2'
        })
        
        # Dnode 3: Data 105-141, Local Parity 151
        dnodes.append({
            'id': 3,
            'drives': list(range(105, 142)) + [151],  # 38 drives
            'name': 'Dnode-3'
        })
        
        return dnodes
    
    def initialize_drives(self):
        """Create 156 1MB binary files filled with zeros"""
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)
        
        for i in range(self.total_drives):
            filepath = os.path.join(self.storage_path, f"drive_{i:03d}.data")
            with open(filepath, 'wb') as f:
                f.write(b'\x00' * self.drive_size)
            self.drives.append(filepath)
        
        self._update_all_previews()
        return True
    
    def get_drive_type(self, drive_id):
        """Determine the type of drive"""
        if drive_id < 142:
            # Find which local group
            for group_id, group in enumerate(self.local_groups):
                if drive_id in group['data_drives']:
                    return f"Data (Group {group_id})"
            return "Data"
        elif 142 <= drive_id <= 151:
            group_id = drive_id - 142
            return f"Local Parity {group_id}"
        elif drive_id in self.global_parity_drives:
            return f"Global Parity {drive_id - 152}"
        elif drive_id in self.hot_spare_drives:
            return f"Hot Spare {drive_id - 154}"
        return "Unknown"
    
    def get_dnode_for_drive(self, drive_id):
        """Get which Dnode contains this drive"""
        for dnode in self.dnodes:
            if drive_id in dnode['drives']:
                return dnode['id']
        return None
    
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
            
            # Pad to drive size
            drive_data = drive_data.ljust(self.drive_size, b'\x00')
            
            # Write to drive
            filepath = self.drives[drive_id]
            with open(filepath, 'wb') as f:
                f.write(drive_data)
            
            self._update_preview(drive_id)
            
            if progress_callback:
                progress_callback(drive_id, self.total_drives)
        
        # Calculate local parity for each group
        for group_id, group in enumerate(self.local_groups):
            self._calculate_local_parity(group, chunks_per_drive, progress_callback)
        
        # Calculate global parity
        self._calculate_global_parity(chunks_per_drive, progress_callback)
        
        # Clear hot spares
        for spare_id in self.hot_spare_drives:
            filepath = self.drives[spare_id]
            with open(filepath, 'wb') as f:
                f.write(b'\x00' * self.drive_size)
            self._update_preview(spare_id)
        
        return True, "Data written successfully"
    
    def _calculate_local_parity(self, group, chunks_per_drive, progress_callback):
        """Calculate local parity for a group of drives"""
        parity_drive = group['parity_drive']
        data_drives = group['data_drives']
        
        parity_data = b''
        
        for chunk_idx in range(chunks_per_drive):
            chunks = []
            for drive_id in data_drives:
                if self.drive_status[drive_id]:
                    filepath = self.drives[drive_id]
                    with open(filepath, 'rb') as f:
                        f.seek(chunk_idx * self.chunk_size)
                        chunk = np.frombuffer(f.read(self.chunk_size), dtype=np.uint8)
                        if len(chunk) == self.chunk_size:
                            chunks.append(chunk)
            
            parity_chunk = self.calculate_parity(chunks)
            parity_data += parity_chunk.tobytes()
        
        # Pad to drive size
        parity_data = parity_data.ljust(self.drive_size, b'\x00')
        
        # Write parity
        filepath = self.drives[parity_drive]
        with open(filepath, 'wb') as f:
            f.write(parity_data)
        
        self._update_preview(parity_drive)
        
        if progress_callback:
            progress_callback(parity_drive, self.total_drives)
    
    def _calculate_global_parity(self, chunks_per_drive, progress_callback):
        """Calculate global parity using Reed-Solomon-like approach"""
        # Global Parity 0: Simple XOR of all data drives
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
        
        parity0_data = parity0_data.ljust(self.drive_size, b'\x00')
        filepath = self.drives[152]
        with open(filepath, 'wb') as f:
            f.write(parity0_data)
        self._update_preview(152)
        
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
                            # Apply galois field multiplication
                            weighted_chunk = ((chunk * (drive_id + 1)) % 256).astype(np.uint8)
                            chunks.append(weighted_chunk)
            
            parity_chunk = self.calculate_parity(chunks)
            parity1_data += parity_chunk.tobytes()
        
        parity1_data = parity1_data.ljust(self.drive_size, b'\x00')
        filepath = self.drives[153]
        with open(filepath, 'wb') as f:
            f.write(parity1_data)
        self._update_preview(153)
        
        if progress_callback:
            progress_callback(153, self.total_drives)
    
    def _update_preview(self, drive_id):
        """Update the hex preview for a drive"""
        filepath = self.drives[drive_id]
        with open(filepath, 'rb') as f:
            first_bytes = f.read(4)
            if len(first_bytes) == 4:
                hex_str = ''.join(f'{b:02X}' for b in first_bytes)
                self.drive_data_preview[drive_id] = hex_str
            else:
                self.drive_data_preview[drive_id] = '00000000'
    
    def _update_all_previews(self):
        """Update previews for all drives"""
        for i in range(self.total_drives):
            self._update_preview(i)
    
    def rebuild_drive(self, failed_drive):
        """Rebuild a failed drive using parity"""
        # Determine which group the drive belongs to
        group_id = None
        for gid, group in enumerate(self.local_groups):
            if failed_drive in group['data_drives']:
                group_id = gid
                break
        
        if group_id is not None:
            # Rebuild using local parity
            group = self.local_groups[group_id]
            self._rebuild_using_local_parity(failed_drive, group)
        elif failed_drive in [g['parity_drive'] for g in self.local_groups]:
            # Rebuild local parity
            for group in self.local_groups:
                if failed_drive == group['parity_drive']:
                    chunks_per_drive = self.drive_size // self.chunk_size
                    self._calculate_local_parity(group, chunks_per_drive, None)
                    break
        elif failed_drive in self.global_parity_drives:
            # Rebuild global parity
            chunks_per_drive = self.drive_size // self.chunk_size
            self._calculate_global_parity(chunks_per_drive, None)
        
        self._update_preview(failed_drive)
    
    def _rebuild_using_local_parity(self, failed_drive, group):
        """Rebuild a data drive using its local parity"""
        parity_drive = group['parity_drive']
        data_drives = group['data_drives']
        
        rebuilt_data = b''
        chunks_per_drive = self.drive_size // self.chunk_size
        
        for chunk_idx in range(chunks_per_drive):
            chunks = []
            
            # Read parity chunk
            with open(self.drives[parity_drive], 'rb') as f:
                f.seek(chunk_idx * self.chunk_size)
                parity_chunk = np.frombuffer(f.read(self.chunk_size), dtype=np.uint8)
            
            chunks.append(parity_chunk)
            
            # Read all other data chunks in the group
            for drive_id in data_drives:
                if drive_id != failed_drive and self.drive_status[drive_id]:
                    with open(self.drives[drive_id], 'rb') as f:
                        f.seek(chunk_idx * self.chunk_size)
                        chunk = np.frombuffer(f.read(self.chunk_size), dtype=np.uint8)
                        if len(chunk) == self.chunk_size:
                            chunks.append(chunk)
            
            # XOR all chunks to get the missing chunk
            rebuilt_chunk = self.calculate_parity(chunks)
            rebuilt_data += rebuilt_chunk.tobytes()
        
        # Write rebuilt data
        with open(self.drives[failed_drive], 'wb') as f:
            f.write(rebuilt_data)
    
    def check_data_integrity(self):
        """Check if data can be recovered with current drive failures"""
        offline_drives = [i for i, status in enumerate(self.drive_status) if not status]
        
        if len(offline_drives) == 0:
            return True, "All drives online", []
        
        # Check each local group
        vulnerable_groups = []
        for group_id, group in enumerate(self.local_groups):
            group_failures = 0
            parity_failed = False
            
            for drive_id in group['data_drives']:
                if not self.drive_status[drive_id]:
                    group_failures += 1
            
            if not self.drive_status[group['parity_drive']]:
                parity_failed = True
            
            if group_failures > 1 or (group_failures == 1 and parity_failed):
                vulnerable_groups.append(group_id)
        
        # Check global parity
        global_parity_failures = sum(1 for gp in self.global_parity_drives if not self.drive_status[gp])
        
        if len(vulnerable_groups) > 0 and global_parity_failures >= 2:
            return False, f"Data loss in groups: {vulnerable_groups}", vulnerable_groups
        
        if len(vulnerable_groups) > 2:
            return False, f"Too many group failures: {vulnerable_groups}", vulnerable_groups
        
        return True, f"Recoverable with {len(offline_drives)} failures", vulnerable_groups
    
    def check_dnode_failure_impact(self, dnode_id):
        """Check what happens if an entire Dnode fails"""
        dnode = self.dnodes[dnode_id]
        failed_drives = dnode['drives']
        
        # Temporarily mark all drives in Dnode as failed
        original_status = self.drive_status.copy()
        for drive_id in failed_drives:
            self.drive_status[drive_id] = False
        
        can_recover, message, vulnerable = self.check_data_integrity()
        
        # Restore original status
        self.drive_status = original_status
        
        return can_recover, message, vulnerable


class StorageGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Erasure Coded Storage System - 142+4 with Dnodes")
        self.root.geometry("1600x1000")
        
        self.storage = ErasureCodedStorage()
        self.drive_buttons = []
        self.dnode_frames = []
        self.dnode_enabled = [True, True, True, True]
        
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
        ttk.Button(control_frame, text="Rebuild Failed Drives", 
                   command=self.rebuild_all).pack(side=tk.LEFT, padx=5)
        
        # Status label
        self.status_label = ttk.Label(control_frame, text="Ready", 
                                      font=("Arial", 10, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=20)
        
        # Progress bar
        self.progress = ttk.Progressbar(control_frame, length=200, mode='determinate')
        self.progress.pack(side=tk.LEFT, padx=5)
        
        # Main canvas with scrollbar
        main_container = ttk.Frame(self.root)
        main_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        canvas = tk.Canvas(main_container, bg="white")
        scrollbar_y = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollbar_x = ttk.Scrollbar(main_container, orient="horizontal", command=canvas.xview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        
        main_container.grid_rowconfigure(0, weight=1)
        main_container.grid_columnconfigure(0, weight=1)
        
        # Create Dnode groups
        self.drives_frame = scrollable_frame
        self.create_dnode_layout()
        
        # Info panel
        info_frame = ttk.Frame(self.root, padding="10")
        info_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        ttk.Label(info_frame, text="Legend:", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(info_frame, text="🟢 Online", foreground="green").pack(side=tk.LEFT, padx=10)
        ttk.Label(info_frame, text="🔴 Offline", foreground="red").pack(side=tk.LEFT, padx=10)
        ttk.Label(info_frame, text="Data: 0-141 | Local Parity: 142-151 | Global: 152-153 | Spares: 154-155").pack(side=tk.LEFT, padx=20)
    
    def create_dnode_layout(self):
        """Create Dnode groups with drive buttons"""
        for dnode_id, dnode in enumerate(self.storage.dnodes):
            # Create Dnode frame
            dnode_container = ttk.LabelFrame(self.drives_frame, text=dnode['name'], 
                                            padding="10")
            dnode_container.grid(row=dnode_id // 2, column=dnode_id % 2, 
                               padx=10, pady=10, sticky="nsew")
            
            # Dnode control buttons
            control_frame = ttk.Frame(dnode_container)
            control_frame.pack(side=tk.TOP, fill=tk.X, pady=5)
            
            ttk.Button(control_frame, text="Disable Dnode", 
                      command=lambda did=dnode_id: self.toggle_dnode(did)).pack(side=tk.LEFT, padx=5)
            ttk.Button(control_frame, text="Test Failure Impact", 
                      command=lambda did=dnode_id: self.test_dnode_failure(did)).pack(side=tk.LEFT, padx=5)
            
            # Drive grid
            drives_grid = ttk.Frame(dnode_container)
            drives_grid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            
            # Create buttons for drives in this Dnode
            columns = 10
            for idx, drive_id in enumerate(dnode['drives']):
                row = idx // columns
                col = idx % columns
                
                # Create frame for each drive
                drive_frame = tk.Frame(drives_grid, relief=tk.RAISED, borderwidth=2)
                drive_frame.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
                
                # Drive button
                btn = tk.Button(drive_frame, text=f"D{drive_id}\n0000", 
                               width=8, height=3,
                               bg="lightgreen",
                               font=("Courier", 8),
                               command=lambda x=drive_id: self.toggle_drive(x))
                btn.pack(fill=tk.BOTH, expand=True)
                
                # Store button reference
                if len(self.drive_buttons) <= drive_id:
                    self.drive_buttons.extend([None] * (drive_id - len(self.drive_buttons) + 1))
                self.drive_buttons[drive_id] = btn
                
                # Tooltip
                self.create_tooltip(btn, drive_id)
            
            self.dnode_frames.append(dnode_container)
    
    def create_tooltip(self, widget, drive_id):
        """Create hover tooltip for drive info"""
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            
            dnode_id = self.storage.get_dnode_for_drive(drive_id)
            label = tk.Label(tooltip, 
                           text=f"Drive {drive_id}\n"
                                f"{self.storage.get_drive_type(drive_id)}\n"
                                f"Dnode: {dnode_id}\n"
                                f"First 4 bytes: {self.storage.drive_data_preview[drive_id]}",
                           background="lightyellow", relief=tk.SOLID, borderwidth=1,
                           font=("Courier", 9))
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
            self.update_all_drive_displays()
            self.status_label.config(text="Storage initialized - 156 drives ready")
            messagebox.showinfo("Success", 
                              "Storage system initialized\n"
                              "142 data drives\n"
                              "10 local parity drives\n"
                              "2 global parity drives\n"
                              "2 hot spares")
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
        self.update_all_drive_displays()
        
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
    
    def toggle_dnode(self, dnode_id):
        """Toggle entire Dnode online/offline"""
        self.dnode_enabled[dnode_id] = not self.dnode_enabled[dnode_id]
        
        dnode = self.storage.dnodes[dnode_id]
        for drive_id in dnode['drives']:
            self.storage.drive_status[drive_id] = self.dnode_enabled[dnode_id]
            self.update_drive_display(drive_id)
        
        status = "enabled" if self.dnode_enabled[dnode_id] else "disabled"
        self.status_label.config(text=f"Dnode-{dnode_id} {status}")
        
        self.root.after(100, self.check_integrity_silent)
    
    def test_dnode_failure(self, dnode_id):
        """Test what happens if this Dnode fails"""
        can_recover, message, vulnerable = self.storage.check_dnode_failure_impact(dnode_id)
        
        dnode = self.storage.dnodes[dnode_id]
        result = f"Dnode-{dnode_id} Failure Test\n\n"
        result += f"Drives in Dnode: {len(dnode['drives'])}\n"
        result += f"Can recover data: {can_recover}\n"
        result += f"Status: {message}\n"
        
        if vulnerable:
            result += f"\nVulnerable local groups: {vulnerable}"
        
        if can_recover:
            messagebox.showinfo("Dnode Failure Test", result)
        else:
            messagebox.showwarning("Dnode Failure Test", result)
    
    def update_drive_display(self, drive_id):
        """Update the visual display of a drive button"""
        if drive_id >= len(self.drive_buttons) or self.drive_buttons[drive_id] is None:
            return
        
        btn = self.drive_buttons[drive_id]
        online = self.storage.drive_status[drive_id]
        preview = self.storage.drive_data_preview[drive_id]
        
        # Update text
        btn.config(text=f"D{drive_id}\n{preview}")
        
        # Update color based on status
        if online:
            # Check if drive has data
            if preview != '00000000':
                btn.config(bg="lightgreen", fg="black")
            else:
                btn.config(bg="white", fg="black")
        else:
            btn.config(bg="red", fg="white")
    
    def update_all_drive_displays(self):
        """Update all drive displays"""
        for drive_id in range(self.storage.total_drives):
            self.update_drive_display(drive_id)
    
    def check_integrity(self):
        """Check data integrity and show message"""
        can_recover, message, vulnerable = self.storage.check_data_integrity()
        
        offline_count = sum(1 for status in self.storage.drive_status if not status)
        
        result = f"{message}\n"
        result += f"Offline drives: {offline_count}\n"
        
        if vulnerable:
            result += f"Vulnerable groups: {vulnerable}"
        
        if can_recover:
            messagebox.showinfo("Data Integrity", result)
        else:
            messagebox.showwarning("Data Integrity", result)
        
        self.status_label.config(text=message)
    
    def check_integrity_silent(self):
        """Check integrity without showing message box"""
        can_recover, message, vulnerable = self.storage.check_data_integrity()
        self.status_label.config(text=message)
    
    def rebuild_all(self):
        """Rebuild all failed drives"""
        offline_drives = [i for i, status in enumerate(self.storage.drive_status) 
                         if not status]
        
        if len(offline_drives) == 0:
            messagebox.showinfo("Rebuild", "No drives to rebuild")
            return
        
        can_recover, message, vulnerable = self.storage.check_data_integrity()
        
        if not can_recover:
            messagebox.showerror("Rebuild Failed", 
                               f"Cannot rebuild - data loss detected\n{message}")
            return
        
        # Simulate rebuild process
        self.status_label.config(text=f"Rebuilding {len(offline_drives)} drive(s)...")
        
        def rebuild_animation():
            for i, drive_id in enumerate(offline_drives):
                # Rebuild drive
                self.storage.rebuild_drive(drive_id)
                
                # Bring drive back online
                self.storage.drive_status[drive_id] = True
                self.root.after(0, self.update_drive_display, drive_id)
                
                progress = ((i + 1) / len(offline_drives)) * 100
                self.root.after(0, lambda p=progress: self.progress.config(value=p))
                
                time.sleep(0.2)  # Simulate rebuild time
            
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
