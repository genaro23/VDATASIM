import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
import os
import threading
import time
import json

class ErasureCodedStorage:
    def __init__(self):
        # Total drives: 484 (11 Dnodes × 44 drives)
        self.total_drives = 484
        self.drive_size = 1024 * 1024  # 1MB
        self.chunk_size = 4096  # 4KB chunks
        
        # 11 sets of 142+4 configuration (each Dnode group has 44 drives)
        # Per Dnode: 32 data + 2 local parity + 1 global parity + 9 data = 44
        # Actually: Let's do 38 data + 3 local parity + 1 global parity + 2 spares = 44
        self.dnodes_count = 11
        self.drives_per_dnode = 44
        
        # Total configuration across all Dnodes:
        # 418 data drives (38 per Dnode × 11)
        # 33 local parity drives (3 per Dnode × 11)
        # 11 global parity drives (1 per Dnode)
        # 22 hot spares (2 per Dnode × 11)
        
        self.data_drives_per_dnode = 38
        self.local_parity_per_dnode = 3
        self.global_parity_per_dnode = 1
        self.spares_per_dnode = 2
        
        # Configure local groups within each Dnode (3 groups of ~13 data drives)
        self.local_group_size = 13
        
        self.drives = []
        self.drive_status = [True] * self.total_drives  # True = online
        self.drive_data_preview = ['00000000'] * self.total_drives  # Hex preview
        self.storage_path = "./storage"
        
        # File storage tracking
        self.stored_files = []  # List of stored file metadata
        
        # High availability mode
        self.ha_mode = False
        
        # Configure drive layout
        self.dnodes = self._configure_dnodes()
        
    def _configure_dnodes(self):
        """Configure 11 Dnodes with balanced distribution"""
        dnodes = []
        
        for dnode_id in range(self.dnodes_count):
            base_drive = dnode_id * self.drives_per_dnode
            
            # Data drives: 0-37 within Dnode
            data_drives = list(range(base_drive, base_drive + 38))
            
            # Local parity drives: 38-40 within Dnode (3 local parity)
            local_parity_drives = list(range(base_drive + 38, base_drive + 41))
            
            # Global parity drive: 41 within Dnode
            global_parity_drive = base_drive + 41
            
            # Hot spares: 42-43 within Dnode
            spare_drives = list(range(base_drive + 42, base_drive + 44))
            
            # Organize data drives into 3 local groups
            local_groups = []
            for i in range(3):
                start_idx = i * 13
                end_idx = min(start_idx + 13, 38)
                group_data = data_drives[start_idx:end_idx]
                local_groups.append({
                    'data_drives': group_data,
                    'parity_drive': local_parity_drives[i] if i < len(local_parity_drives) else None
                })
            
            dnodes.append({
                'id': dnode_id,
                'name': f'Dnode-{dnode_id}',
                'data_drives': data_drives,
                'local_groups': local_groups,
                'local_parity_drives': local_parity_drives,
                'global_parity_drive': global_parity_drive,
                'spare_drives': spare_drives,
                'all_drives': list(range(base_drive, base_drive + 44))
            })
        
        return dnodes
    
    def get_all_data_drives(self):
        """Get list of all data drives across all Dnodes"""
        all_data = []
        for dnode in self.dnodes:
            all_data.extend(dnode['data_drives'])
        return all_data
    
    def get_all_local_parity_drives(self):
        """Get list of all local parity drives"""
        all_local = []
        for dnode in self.dnodes:
            all_local.extend(dnode['local_parity_drives'])
        return all_local
    
    def get_all_global_parity_drives(self):
        """Get list of all global parity drives"""
        return [dnode['global_parity_drive'] for dnode in self.dnodes]
    
    def initialize_drives(self):
        """Create 484 1MB binary files filled with zeros"""
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
        for dnode in self.dnodes:
            if drive_id in dnode['data_drives']:
                return "Data"
            elif drive_id in dnode['local_parity_drives']:
                return "Local Parity"
            elif drive_id == dnode['global_parity_drive']:
                return "Global Parity"
            elif drive_id in dnode['spare_drives']:
                return "Hot Spare"
        return "Unknown"
    
    def get_dnode_for_drive(self, drive_id):
        """Get which Dnode contains this drive"""
        return drive_id // self.drives_per_dnode
    
    def calculate_parity(self, data_chunks):
        """Calculate XOR parity for given data chunks"""
        if len(data_chunks) == 0:
            return np.zeros(self.chunk_size, dtype=np.uint8)
        
        parity = np.zeros(self.chunk_size, dtype=np.uint8)
        for chunk in data_chunks:
            parity ^= chunk
        return parity
    
    def get_available_capacity(self):
        """Calculate available storage capacity"""
        if self.ha_mode:
            # In HA mode: 2 data drives per Dnode can participate
            # With 11 Dnodes = 22 drives, 18 data + 4 parity
            usable_drives = 18
            stripe_size = 22  # 18 data + 4 parity
        else:
            # Normal mode: all data drives
            usable_drives = len(self.get_all_data_drives())
            online_count = sum(1 for d in self.get_all_data_drives() if self.drive_status[d])
            usable_drives = min(usable_drives, online_count)
        
        return usable_drives * self.drive_size
    
    def write_files(self, input_files, progress_callback=None):
        """Write multiple files to the storage system"""
        if not input_files:
            return False, "No files selected"
        
        # Calculate total size
        total_size = sum(os.path.getsize(f) for f in input_files)
        available = self.get_available_capacity()
        
        if total_size > available:
            return False, f"Files too large. Total: {total_size/(1024*1024):.2f}MB, Available: {available/(1024*1024):.2f}MB"
        
        # Concatenate all files with metadata
        combined_data = b''
        file_metadata = []
        
        for filepath in input_files:
            filename = os.path.basename(filepath)
            with open(filepath, 'rb') as f:
                file_data = f.read()
            
            file_size = len(file_data)
            file_metadata.append({
                'name': filename,
                'size': file_size,
                'offset': len(combined_data)
            })
            
            # Add file header (filename length + filename + file size)
            filename_bytes = filename.encode('utf-8')
            header = struct.pack('I', len(filename_bytes)) + filename_bytes + struct.pack('Q', file_size)
            combined_data += header + file_data
        
        self.stored_files = file_metadata
        
        # Pad to chunk boundary
        padded_size = ((len(combined_data) + self.chunk_size - 1) // self.chunk_size) * self.chunk_size
        combined_data = combined_data.ljust(padded_size, b'\x00')
        
        if self.ha_mode:
            return self._write_data_ha_mode(combined_data, progress_callback)
        else:
            return self._write_data_normal_mode(combined_data, progress_callback)
    
    def _write_data_normal_mode(self, data, progress_callback):
        """Write data in normal mode using all data drives"""
        num_chunks = len(data) // self.chunk_size
        
        # Get all available data drives
        data_drives = self.get_all_data_drives()
        available_drives = [d for d in data_drives if self.drive_status[d]]
        
        if len(available_drives) == 0:
            return False, "No data drives available"
        
        chunks_per_drive = (num_chunks + len(available_drives) - 1) // len(available_drives)
        
        # Distribute data across drives
        chunk_index = 0
        drive_chunk_map = {}  # Track which chunks go to which drive
        
        for drive_id in available_drives:
            drive_data = b''
            drive_chunks = []
            
            for _ in range(chunks_per_drive):
                if chunk_index < num_chunks:
                    start = chunk_index * self.chunk_size
                    end = start + self.chunk_size
                    drive_data += data[start:end]
                    drive_chunks.append(chunk_index)
                    chunk_index += 1
                else:
                    drive_data += b'\x00' * self.chunk_size
            
            # Pad to drive size
            drive_data = drive_data.ljust(self.drive_size, b'\x00')
            
            # Write to drive
            filepath = self.drives[drive_id]
            with open(filepath, 'wb') as f:
                f.write(drive_data)
            
            drive_chunk_map[drive_id] = drive_chunks
            self._update_preview(drive_id)
            
            if progress_callback:
                progress_callback(drive_id, self.total_drives)
        
        # Calculate local parity for each Dnode
        for dnode in self.dnodes:
            for group in dnode['local_groups']:
                self._calculate_local_parity_group(group, chunks_per_drive, progress_callback)
        
        # Calculate global parity for each Dnode
        for dnode in self.dnodes:
            self._calculate_global_parity_dnode(dnode, chunks_per_drive, progress_callback)
        
        # Clear hot spares
        for dnode in self.dnodes:
            for spare_id in dnode['spare_drives']:
                filepath = self.drives[spare_id]
                with open(filepath, 'wb') as f:
                    f.write(b'\x00' * self.drive_size)
                self._update_preview(spare_id)
        
        return True, f"Wrote {len(data)/(1024*1024):.2f}MB across {len(available_drives)} drives"
    
    def _write_data_ha_mode(self, data, progress_callback):
        """Write data in HA mode - limit to 2 drives per Dnode (22 total drives)"""
        # In HA mode: Use 2 data drives from each Dnode
        # Stripe = 18 data chunks + 4 parity chunks (2 local, 2 global)
        
        num_chunks = len(data) // self.chunk_size
        drives_per_stripe = 18  # Data chunks
        parity_per_stripe = 4   # 2 local + 2 global
        
        # Select 2 data drives from each Dnode (prefer first 2 in each)
        selected_drives = []
        for dnode in self.dnodes:
            available_in_dnode = [d for d in dnode['data_drives'][:2] if self.drive_status[d]]
            selected_drives.extend(available_in_dnode[:2])
        
        if len(selected_drives) < 18:
            return False, f"HA mode requires 18 drives (2 per Dnode), only {len(selected_drives)} available"
        
        # Use first 18 drives for data
        selected_drives = selected_drives[:18]
        
        # Distribute data in stripes
        stripe_index = 0
        chunk_index = 0
        
        while chunk_index < num_chunks:
            # Distribute one chunk to each of the 18 drives
            for i, drive_id in enumerate(selected_drives):
                if chunk_index < num_chunks:
                    start = chunk_index * self.chunk_size
                    end = start + self.chunk_size
                    chunk_data = data[start:end]
                    
                    # Append to drive (in stripe order)
                    filepath = self.drives[drive_id]
                    with open(filepath, 'r+b') as f:
                        f.seek(stripe_index * self.chunk_size)
                        f.write(chunk_data)
                    
                    chunk_index += 1
                else:
                    break
            
            stripe_index += 1
        
        # Update previews for written drives
        for drive_id in selected_drives:
            self._update_preview(drive_id)
            if progress_callback:
                progress_callback(drive_id, self.total_drives)
        
        # Calculate HA parity (2 local, 2 global across the stripe)
        self._calculate_ha_parity(selected_drives, stripe_index, progress_callback)
        
        return True, f"HA Mode: Wrote {len(data)/(1024*1024):.2f}MB across {len(selected_drives)} drives with 18% overhead"
    
    def _calculate_local_parity_group(self, group, chunks_per_drive, progress_callback):
        """Calculate local parity for a group of drives"""
        if group['parity_drive'] is None:
            return
        
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
    
    def _calculate_global_parity_dnode(self, dnode, chunks_per_drive, progress_callback):
        """Calculate global parity for a Dnode"""
        global_parity_drive = dnode['global_parity_drive']
        data_drives = dnode['data_drives']
        
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
                            # Apply weighted XOR for diversity
                            # FIX: Use modulo to keep weight in uint8 range
                            weight = np.uint8((drive_id % 255) + 1)
                            # Use numpy operations to maintain uint8 type
                            weighted = ((chunk.astype(np.uint16) * weight) % 256).astype(np.uint8)
                            chunks.append(weighted)
            
            parity_chunk = self.calculate_parity(chunks)
            parity_data += parity_chunk.tobytes()
        
        # Pad to drive size
        parity_data = parity_data.ljust(self.drive_size, b'\x00')
        
        filepath = self.drives[global_parity_drive]
        with open(filepath, 'wb') as f:
            f.write(parity_data)
        
        self._update_preview(global_parity_drive)
        
        if progress_callback:
            progress_callback(global_parity_drive, self.total_drives)
    
    def _calculate_ha_parity(self, data_drives, num_stripes, progress_callback):
        """Calculate parity for HA mode"""
        # Use first 2 Dnodes for local parity, next 2 for global parity
        local_parity_drives = []
        global_parity_drives = []
        
        for i, dnode in enumerate(self.dnodes[:4]):
            if i < 2:
                local_parity_drives.append(dnode['local_parity_drives'][0])
            else:
                global_parity_drives.append(dnode['global_parity_drive'])
        
        # Calculate local parity (XOR of first 9 and last 9 drives)
        for parity_idx, parity_drive in enumerate(local_parity_drives):
            parity_data = b''
            start_drive = parity_idx * 9
            end_drive = start_drive + 9
            
            for stripe_idx in range(num_stripes):
                chunks = []
                for drive_id in data_drives[start_drive:end_drive]:
                    filepath = self.drives[drive_id]
                    with open(filepath, 'rb') as f:
                        f.seek(stripe_idx * self.chunk_size)
                        chunk = np.frombuffer(f.read(self.chunk_size), dtype=np.uint8)
                        if len(chunk) == self.chunk_size:
                            chunks.append(chunk)
                
                parity_chunk = self.calculate_parity(chunks)
                parity_data += parity_chunk.tobytes()
            
            parity_data = parity_data.ljust(self.drive_size, b'\x00')
            with open(self.drives[parity_drive], 'wb') as f:
                f.write(parity_data)
            self._update_preview(parity_drive)
        
        # Calculate global parity (all 18 drives)
        for parity_drive in global_parity_drives:
            parity_data = b''
            
            for stripe_idx in range(num_stripes):
                chunks = []
                for drive_id in data_drives:
                    filepath = self.drives[drive_id]
                    with open(filepath, 'rb') as f:
                        f.seek(stripe_idx * self.chunk_size)
                        chunk = np.frombuffer(f.read(self.chunk_size), dtype=np.uint8)
                        if len(chunk) == self.chunk_size:
                            chunks.append(chunk)
                
                parity_chunk = self.calculate_parity(chunks)
                parity_data += parity_chunk.tobytes()
            
            parity_data = parity_data.ljust(self.drive_size, b'\x00')
            with open(self.drives[parity_drive], 'wb') as f:
                f.write(parity_data)
            self._update_preview(parity_drive)
    
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
    
    def check_data_integrity(self):
        """Check if data can be recovered with current drive failures"""
        offline_drives = [i for i, status in enumerate(self.drive_status) if not status]
        
        if len(offline_drives) == 0:
            return True, "All drives online", []
        
        vulnerable_dnodes = []
        
        # Check each Dnode
        for dnode in self.dnodes:
            dnode_failures = [d for d in offline_drives if d in dnode['all_drives']]
            
            if len(dnode_failures) == 0:
                continue
            
            # Check if we can recover
            data_failures = [d for d in dnode_failures if d in dnode['data_drives']]
            local_parity_failures = [d for d in dnode_failures if d in dnode['local_parity_drives']]
            global_parity_failure = dnode['global_parity_drive'] in dnode_failures
            
            # Count failures per local group
            max_group_failures = 0
            for group in dnode['local_groups']:
                group_failures = sum(1 for d in group['data_drives'] if not self.drive_status[d])
                max_group_failures = max(max_group_failures, group_failures)
            
            # Risk assessment
            if max_group_failures > 2:
                vulnerable_dnodes.append(dnode['id'])
            elif max_group_failures == 2 and len(local_parity_failures) > 0:
                vulnerable_dnodes.append(dnode['id'])
        
        if len(vulnerable_dnodes) > 0:
            return False, f"Data at risk in Dnodes: {vulnerable_dnodes}", vulnerable_dnodes
        
        return True, f"Recoverable with {len(offline_drives)} failures", []


class StorageGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Multi-File Erasure Coded Storage - 484 Drives / 11 Dnodes")
        self.root.geometry("1800x1000")
        
        self.storage = ErasureCodedStorage()
        self.drive_buttons = {}
        self.drive_frames = {}  # Store frames for border highlighting
        self.dnode_frames = []
        self.dnode_enabled = [True] * 11
        
        self.setup_ui()
        
    def setup_ui(self):
        # Top control panel
        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(side=tk.TOP, fill=tk.X)
        
        ttk.Button(control_frame, text="Initialize Storage", 
                   command=self.initialize_storage).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Load Files", 
                   command=self.load_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Check Integrity", 
                   command=self.check_integrity).pack(side=tk.LEFT, padx=5)
        
        # HA Mode toggle
        self.ha_var = tk.BooleanVar(value=False)
        ha_check = ttk.Checkbutton(control_frame, text="Enable Dnode High Availability (18% overhead)", 
                                   variable=self.ha_var, command=self.toggle_ha_mode)
        ha_check.pack(side=tk.LEFT, padx=15)
        
        # Status label
        self.status_label = ttk.Label(control_frame, text="Ready", 
                                      font=("Arial", 10, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=20)
        
        # Progress bar
        self.progress = ttk.Progressbar(control_frame, length=300, mode='determinate')
        self.progress.pack(side=tk.LEFT, padx=5)
        
        # Main canvas with scrollbars
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
        
        # Create Dnode layout
        self.drives_frame = scrollable_frame
        self.create_dnode_layout()
        
        # Info panel
        info_frame = ttk.Frame(self.root, padding="10")
        info_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        ttk.Label(info_frame, text="Legend:", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        
        # Color legend with actual colored frames
        legend_frame = tk.Frame(info_frame)
        legend_frame.pack(side=tk.LEFT, padx=10)
        
        # Create color swatches
        self._create_legend_item(legend_frame, "Online", "#90EE90", "black")
        self._create_legend_item(legend_frame, "Offline", "#FF4444", "white")
        self._create_legend_item(legend_frame, "Local Parity", "#9370DB", "white")
        self._create_legend_item(legend_frame, "Global Parity", "#1E90FF", "white")
        
        ttk.Label(info_frame, text="484 drives | 11 Dnodes × 44 drives | 38 data + 3 local + 1 global + 2 spare per Dnode").pack(side=tk.LEFT, padx=20)
    
    def _create_legend_item(self, parent, text, bg_color, fg_color):
        """Create a legend item with colored background"""
        frame = tk.Frame(parent, bg=bg_color, relief=tk.RAISED, borderwidth=2)
        frame.pack(side=tk.LEFT, padx=3)
        label = tk.Label(frame, text=f"  {text}  ", bg=bg_color, fg=fg_color, font=("Arial", 9))
        label.pack(padx=2, pady=2)
    
    def create_dnode_layout(self):
        """Create Dnode groups with drive buttons"""
        # Arrange in 3 columns
        columns = 3
        
        for dnode_id, dnode in enumerate(self.storage.dnodes):
            row = dnode_id // columns
            col = dnode_id % columns
            
            # Create Dnode frame
            dnode_container = ttk.LabelFrame(self.drives_frame, text=dnode['name'], 
                                            padding="5")
            dnode_container.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            
            # Dnode control buttons
            control_frame = ttk.Frame(dnode_container)
            control_frame.pack(side=tk.TOP, fill=tk.X, pady=3)
            
            ttk.Button(control_frame, text="Toggle Dnode", 
                      command=lambda did=dnode_id: self.toggle_dnode(did)).pack(side=tk.LEFT, padx=3)
            
            status_label = ttk.Label(control_frame, text="✓ Online", foreground="green")
            status_label.pack(side=tk.LEFT, padx=5)
            
            # Drive grid (44 drives in 11 columns × 4 rows)
            drives_grid = tk.Frame(dnode_container, bg="gray90")
            drives_grid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            
            grid_cols = 11
            for idx, drive_id in enumerate(dnode['all_drives']):
                grid_row = idx // grid_cols
                grid_col = idx % grid_cols
                
                # Create frame for each drive (for border highlighting)
                drive_container = tk.Frame(drives_grid, relief=tk.RAISED, borderwidth=3, bg="white")
                drive_container.grid(row=grid_row, column=grid_col, padx=2, pady=2, sticky="nsew")
                
                # Create button - use Label instead of Button for better color control on macOS
                btn = tk.Label(drive_container, text=f"{drive_id}\n0000", 
                               width=8, height=2,
                               bg="white",
                               relief=tk.RAISED,
                               borderwidth=1,
                               font=("Courier", 8, "bold"),
                               cursor="hand2")
                btn.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
                
                # Bind click event
                btn.bind("<Button-1>", lambda e, x=drive_id: self.toggle_drive(x))
                
                self.drive_buttons[drive_id] = btn
                self.drive_frames[drive_id] = drive_container
                
                # Tooltip
                self.create_tooltip(btn, drive_id)
            
            self.dnode_frames.append((dnode_container, status_label))
    
    def create_tooltip(self, widget, drive_id):
        """Create hover tooltip for drive info"""
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            
            dnode_id = self.storage.get_dnode_for_drive(drive_id)
            drive_type = self.storage.get_drive_type(drive_id)
            
            label = tk.Label(tooltip, 
                           text=f"Drive {drive_id}\n"
                                f"{drive_type}\n"
                                f"Dnode: {dnode_id}\n"
                                f"Data: {self.storage.drive_data_preview[drive_id]}",
                           background="#FFFACD", relief=tk.SOLID, borderwidth=1,
                           font=("Courier", 9), justify=tk.LEFT, padx=5, pady=5)
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
        self.status_label.config(text="Initializing 484 drives...")
        self.root.update()
        
        def init_thread():
            if self.storage.initialize_drives():
                self.root.after(0, self.init_complete)
        
        threading.Thread(target=init_thread, daemon=True).start()
    
    def init_complete(self):
        """Called when initialization completes"""
        self.update_all_drive_displays()
        self.status_label.config(text="Storage initialized - 484 drives ready")
        messagebox.showinfo("Success", 
                          "Storage system initialized\n"
                          "11 Dnodes × 44 drives\n"
                          "418 data | 33 local parity | 11 global parity | 22 spares")
    
    def load_files(self):
        """Load multiple files and distribute across drives"""
        filepaths = filedialog.askopenfilenames(title="Select files to store")
        if not filepaths:
            return
        
        total_size = sum(os.path.getsize(f) for f in filepaths)
        
        confirm = messagebox.askyesno("Confirm", 
                                     f"Load {len(filepaths)} files?\n"
                                     f"Total size: {total_size/(1024*1024):.2f}MB\n"
                                     f"HA Mode: {self.storage.ha_mode}")
        if not confirm:
            return
        
        self.status_label.config(text=f"Writing {len(filepaths)} files...")
        self.progress['value'] = 0
        self.root.update()
        
        def progress_callback(current, total):
            self.progress['value'] = (current / total) * 100
            self.update_drive_display(current)
            self.root.update()
        
        def write_thread():
            success, message = self.storage.write_files(filepaths, progress_callback)
            self.root.after(0, lambda: self.write_complete(success, message))
        
        threading.Thread(target=write_thread, daemon=True).start()
    
    def write_complete(self, success, message):
        """Called when write operation completes"""
        self.status_label.config(text=message)
        self.progress['value'] = 100
        
        self.update_all_drive_displays()
        
        if success:
            messagebox.showinfo("Success", message)
        else:
            messagebox.showerror("Error", message)
    
    def toggle_drive(self, drive_id):
        """Toggle drive online/offline status"""
        self.storage.drive_status[drive_id] = not self.storage.drive_status[drive_id]
        self.update_drive_display(drive_id)
        self.check_integrity_silent()
    
    def toggle_dnode(self, dnode_id):
        """Toggle entire Dnode online/offline"""
        self.dnode_enabled[dnode_id] = not self.dnode_enabled[dnode_id]
        
        dnode = self.storage.dnodes[dnode_id]
        for drive_id in dnode['all_drives']:
            self.storage.drive_status[drive_id] = self.dnode_enabled[dnode_id]
            self.update_drive_display(drive_id)
        
        # Update Dnode status label
        _, status_label = self.dnode_frames[dnode_id]
        if self.dnode_enabled[dnode_id]:
            status_label.config(text="✓ Online", foreground="green")
        else:
            status_label.config(text="✗ Offline", foreground="red")
        
        self.check_integrity_silent()
    
    def toggle_ha_mode(self):
        """Toggle high availability mode"""
        self.storage.ha_mode = self.ha_var.get()
        mode = "ENABLED" if self.storage.ha_mode else "DISABLED"
        overhead = "18%" if self.storage.ha_mode else "~8.5%"
        
        self.status_label.config(text=f"HA Mode {mode} - Overhead: {overhead}")
        
        messagebox.showinfo("HA Mode", 
                          f"High Availability Mode: {mode}\n"
                          f"Overhead: {overhead}\n"
                          f"Max drives per stripe: {'22 (2 per Dnode)' if self.storage.ha_mode else 'All available'}")
    
    def update_drive_display(self, drive_id):
        """Update visual display of a drive button"""
        if drive_id not in self.drive_buttons:
            return
        
        btn = self.drive_buttons[drive_id]
        frame = self.drive_frames[drive_id]
        online = self.storage.drive_status[drive_id]
        preview = self.storage.drive_data_preview[drive_id]
        drive_type = self.storage.get_drive_type(drive_id)
        
        # Update text
        btn.config(text=f"{drive_id}\n{preview[-4:]}")
        
        # Update color based on type and status using specific hex colors
        if not online:
            # Offline - Red
            btn.config(bg="#FF4444", fg="white")
            frame.config(bg="#FF4444")
        elif drive_type == "Local Parity":
            # Local Parity - Medium Purple
            btn.config(bg="#9370DB", fg="white")
            frame.config(bg="#9370DB")
        elif drive_type == "Global Parity":
            # Global Parity - Dodger Blue
            btn.config(bg="#1E90FF", fg="white")
            frame.config(bg="#1E90FF")
        elif preview != '00000000':
            # Online with data - Light Green
            btn.config(bg="#90EE90", fg="black")
            frame.config(bg="#90EE90")
        else:
            # Online empty - White
            btn.config(bg="white", fg="black")
            frame.config(bg="white")
        
        # Force update
        btn.update_idletasks()
        frame.update_idletasks()
    
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
        result += f"HA Mode: {'ENABLED' if self.storage.ha_mode else 'DISABLED'}"
        
        if vulnerable:
            result += f"\nVulnerable Dnodes: {vulnerable}"
        
        if can_recover:
            messagebox.showinfo("Data Integrity", result)
        else:
            messagebox.showwarning("Data Integrity", result)
        
        self.status_label.config(text=message)
    
    def check_integrity_silent(self):
        """Check integrity without message box"""
        can_recover, message, vulnerable = self.storage.check_data_integrity()
        self.status_label.config(text=message)


def main():
    root = tk.Tk()
    app = StorageGUI(root)
    root.mainloop()


if __name__ == "__main__":
    import struct
    main()
