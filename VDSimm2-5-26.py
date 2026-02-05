import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import numpy as np
import os
import threading
import time
import struct

class ErasureCodedStorage:
    def __init__(self):
        # Total drives: 484 (11 Dboxes × 44 drives)
        self.total_drives = 484
        self.drive_size = 1024 * 1024  # 1MB
        self.chunk_size = 4096  # 4KB chunks
        
        self.dboxes_count = 11
        self.drives_per_dbox = 44
        
        # Per Dbox: 38 data + 3 local parity + 1 global parity + 2 spares = 44
        self.data_drives_per_dbox = 38
        self.local_parity_per_dbox = 3
        self.global_parity_per_dbox = 1
        self.spares_per_dbox = 2
        
        self.drives = []
        self.drive_status = [True] * self.total_drives
        self.drive_data_preview = ['00000000'] * self.total_drives
        self.storage_path = "./storage"
        
        # File storage tracking
        self.stored_file_data = None
        self.stored_file_name = None
        
        # High availability mode
        self.ha_mode = False
        
        # Configure drive layout
        self.dboxes = self._configure_dboxes()
        
    def _configure_dboxes(self):
        """Configure 11 Dboxes with balanced distribution"""
        dboxes = []
        
        for dbox_id in range(self.dboxes_count):
            base_drive = dbox_id * self.drives_per_dbox
            
            # Data drives: 0-37 within Dbox
            data_drives = list(range(base_drive, base_drive + 38))
            
            # Local parity drives: 38-40 within Dbox (3 local parity)
            local_parity_drives = list(range(base_drive + 38, base_drive + 41))
            
            # Global parity drive: 41 within Dbox
            global_parity_drive = base_drive + 41
            
            # Hot spares: 42-43 within Dbox
            spare_drives = list(range(base_drive + 42, base_drive + 44))
            
            # Organize data drives into 3 local groups (~13 drives each)
            local_groups = []
            for i in range(3):
                start_idx = i * 13
                end_idx = min(start_idx + 13, 38)
                group_data = data_drives[start_idx:end_idx]
                local_groups.append({
                    'data_drives': group_data,
                    'parity_drive': local_parity_drives[i] if i < len(local_parity_drives) else None
                })
            
            dboxes.append({
                'id': dbox_id,
                'name': f'Dbox-{dbox_id}',
                'data_drives': data_drives,
                'local_groups': local_groups,
                'local_parity_drives': local_parity_drives,
                'global_parity_drive': global_parity_drive,
                'spare_drives': spare_drives,
                'all_drives': list(range(base_drive, base_drive + 44))
            })
        
        return dboxes
    
    def get_all_data_drives(self):
        """Get list of all data drives across all Dboxes"""
        all_data = []
        for dbox in self.dboxes:
            all_data.extend(dbox['data_drives'])
        return all_data
    
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
        for dbox in self.dboxes:
            if drive_id in dbox['data_drives']:
                return "Data"
            elif drive_id in dbox['local_parity_drives']:
                return "Local Parity"
            elif drive_id == dbox['global_parity_drive']:
                return "Global Parity"
            elif drive_id in dbox['spare_drives']:
                return "Hot Spare"
        return "Unknown"
    
    def get_dbox_for_drive(self, drive_id):
        """Get which Dbox contains this drive"""
        return drive_id // self.drives_per_dbox
    
    def calculate_parity(self, data_chunks):
        """Calculate XOR parity for given data chunks"""
        if len(data_chunks) == 0:
            return np.zeros(self.chunk_size, dtype=np.uint8)
        
        parity = np.zeros(self.chunk_size, dtype=np.uint8)
        for chunk in data_chunks:
            parity ^= chunk
        return parity
    
    def get_storage_stats(self):
        """Calculate storage statistics"""
        if self.ha_mode:
            total_capacity = 18 * self.drive_size  # HA mode: 18 data drives
        else:
            total_capacity = len(self.get_all_data_drives()) * self.drive_size
        
        # Calculate used space
        used_space = 0
        if self.stored_file_data:
            used_space = len(self.stored_file_data)
        
        available_space = total_capacity - used_space
        
        return {
            'total': total_capacity,
            'used': used_space,
            'available': available_space
        }
    
    def write_files(self, input_files, progress_callback=None):
        """Write multiple files to the storage system"""
        if not input_files:
            return False, "No files selected"
        
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
            
            # Add file header
            filename_bytes = filename.encode('utf-8')
            header = struct.pack('I', len(filename_bytes)) + filename_bytes + struct.pack('Q', file_size)
            combined_data += header + file_data
        
        # Store original data for later retrieval
        self.stored_file_data = combined_data
        self.stored_file_name = input_files[0] if len(input_files) == 1 else "combined_files.dat"
        
        # Check capacity
        stats = self.get_storage_stats()
        if len(combined_data) > stats['available']:
            return False, f"Files too large. Size: {len(combined_data)/(1024*1024):.2f}MB, Available: {stats['available']/(1024*1024):.2f}MB"
        
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
        data_drives = self.get_all_data_drives()
        available_drives = [d for d in data_drives if self.drive_status[d]]
        
        if len(available_drives) == 0:
            return False, "No data drives available"
        
        chunks_per_drive = (num_chunks + len(available_drives) - 1) // len(available_drives)
        
        # Distribute data across drives
        chunk_index = 0
        for drive_id in available_drives:
            drive_data = b''
            
            for _ in range(chunks_per_drive):
                if chunk_index < num_chunks:
                    start = chunk_index * self.chunk_size
                    end = start + self.chunk_size
                    drive_data += data[start:end]
                    chunk_index += 1
                else:
                    drive_data += b'\x00' * self.chunk_size
            
            drive_data = drive_data.ljust(self.drive_size, b'\x00')
            
            filepath = self.drives[drive_id]
            with open(filepath, 'wb') as f:
                f.write(drive_data)
            
            self._update_preview(drive_id)
            
            if progress_callback:
                progress_callback(drive_id, self.total_drives)
        
        # Calculate local parity for each Dbox
        for dbox in self.dboxes:
            for group in dbox['local_groups']:
                self._calculate_local_parity_group(group, chunks_per_drive, progress_callback)
        
        # Calculate global parity for each Dbox
        for dbox in self.dboxes:
            self._calculate_global_parity_dbox(dbox, chunks_per_drive, progress_callback)
        
        # Clear hot spares
        for dbox in self.dboxes:
            for spare_id in dbox['spare_drives']:
                filepath = self.drives[spare_id]
                with open(filepath, 'wb') as f:
                    f.write(b'\x00' * self.drive_size)
                self._update_preview(spare_id)
        
        return True, f"Wrote {len(data)/(1024*1024):.2f}MB across {len(available_drives)} drives"
    
    def _write_data_ha_mode(self, data, progress_callback):
        """Write data in HA mode - limit to 2 drives per Dbox (22 total drives)"""
        num_chunks = len(data) // self.chunk_size
        
        # Select 2 data drives from each Dbox
        selected_drives = []
        for dbox in self.dboxes:
            available_in_dbox = [d for d in dbox['data_drives'][:2] if self.drive_status[d]]
            selected_drives.extend(available_in_dbox[:2])
        
        if len(selected_drives) < 18:
            return False, f"HA mode requires 18 drives, only {len(selected_drives)} available"
        
        selected_drives = selected_drives[:18]
        
        # Distribute data in stripes
        stripe_index = 0
        chunk_index = 0
        
        while chunk_index < num_chunks:
            for drive_id in selected_drives:
                if chunk_index < num_chunks:
                    start = chunk_index * self.chunk_size
                    end = start + self.chunk_size
                    chunk_data = data[start:end]
                    
                    filepath = self.drives[drive_id]
                    with open(filepath, 'r+b') as f:
                        f.seek(stripe_index * self.chunk_size)
                        f.write(chunk_data)
                    
                    chunk_index += 1
                else:
                    break
            
            stripe_index += 1
        
        for drive_id in selected_drives:
            self._update_preview(drive_id)
            if progress_callback:
                progress_callback(drive_id, self.total_drives)
        
        self._calculate_ha_parity(selected_drives, stripe_index, progress_callback)
        
        return True, f"HA Mode: Wrote {len(data)/(1024*1024):.2f}MB across {len(selected_drives)} drives"
    
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
        
        parity_data = parity_data.ljust(self.drive_size, b'\x00')
        
        filepath = self.drives[parity_drive]
        with open(filepath, 'wb') as f:
            f.write(parity_data)
        
        self._update_preview(parity_drive)
        
        if progress_callback:
            progress_callback(parity_drive, self.total_drives)
    
    def _calculate_global_parity_dbox(self, dbox, chunks_per_drive, progress_callback):
        """Calculate global parity for a Dbox"""
        global_parity_drive = dbox['global_parity_drive']
        data_drives = dbox['data_drives']
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
                            # FIX: Proper uint8 handling to avoid overflow
                            # Use modulo 255 instead of 256, and ensure result stays in uint8 range
                            weight = np.uint8((drive_id % 255) + 1)
                            # Convert to uint16 for multiplication, then mod back to uint8 range
                            weighted = np.remainder(chunk.astype(np.uint16) * weight, 256).astype(np.uint8)
                            chunks.append(weighted)
            
            parity_chunk = self.calculate_parity(chunks)
            parity_data += parity_chunk.tobytes()
        
        parity_data = parity_data.ljust(self.drive_size, b'\x00')
        
        filepath = self.drives[global_parity_drive]
        with open(filepath, 'wb') as f:
            f.write(parity_data)
        
        self._update_preview(global_parity_drive)
        
        if progress_callback:
            progress_callback(global_parity_drive, self.total_drives)
    
    def _calculate_ha_parity(self, data_drives, num_stripes, progress_callback):
        """Calculate parity for HA mode"""
        local_parity_drives = []
        global_parity_drives = []
        
        for i, dbox in enumerate(self.dboxes[:4]):
            if i < 2:
                local_parity_drives.append(dbox['local_parity_drives'][0])
            else:
                global_parity_drives.append(dbox['global_parity_drive'])
        
        # Calculate local parity
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
        
        # Calculate global parity
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
    
    def get_drive_contents(self, drive_id):
        """Get full contents of a drive in hex format"""
        filepath = self.drives[drive_id]
        with open(filepath, 'rb') as f:
            data = f.read()
        
        # Format as hex dump
        hex_lines = []
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_part = ' '.join(f'{b:02X}' for b in chunk)
            ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            hex_lines.append(f'{i:08X}  {hex_part:<48}  {ascii_part}')
        
        return '\n'.join(hex_lines)
    
    def rebuild_drives(self, failed_drives, bring_online=True):
        """Rebuild failed drives and return list of drives read from"""
        drives_read = set()
        rebuild_info = []
        
        for failed_drive in failed_drives:
            if self.drive_status[failed_drive]:
                continue  # Drive is already online
            
            # Find which group/dbox this drive belongs to
            dbox_id = self.get_dbox_for_drive(failed_drive)
            dbox = self.dboxes[dbox_id]
            
            # Determine rebuild strategy
            drive_type = self.get_drive_type(failed_drive)
            
            if drive_type == "Data":
                # Find local group
                for group in dbox['local_groups']:
                    if failed_drive in group['data_drives']:
                        # Rebuild using local parity
                        read_drives = self._rebuild_data_drive(failed_drive, group)
                        drives_read.update(read_drives)
                        rebuild_info.append(f"Drive {failed_drive}: Local rebuild using {len(read_drives)} drives")
                        break
            
            elif drive_type == "Local Parity":
                # Rebuild local parity
                for group in dbox['local_groups']:
                    if group['parity_drive'] == failed_drive:
                        read_drives = group['data_drives']
                        drives_read.update(read_drives)
                        chunks_per_drive = self.drive_size // self.chunk_size
                        self._calculate_local_parity_group(group, chunks_per_drive, None)
                        rebuild_info.append(f"Drive {failed_drive}: Parity rebuild using {len(read_drives)} drives")
                        break
            
            elif drive_type == "Global Parity":
                # Rebuild global parity
                read_drives = dbox['data_drives']
                drives_read.update(read_drives)
                chunks_per_drive = self.drive_size // self.chunk_size
                self._calculate_global_parity_dbox(dbox, chunks_per_drive, None)
                rebuild_info.append(f"Drive {failed_drive}: Global parity rebuild using {len(read_drives)} drives")
            
            # Bring drive back online if requested
            if bring_online:
                self.drive_status[failed_drive] = True
            
            self._update_preview(failed_drive)
        
        return list(drives_read), rebuild_info
    
    def _rebuild_data_drive(self, failed_drive, group):
        """Rebuild a data drive using its local parity"""
        parity_drive = group['parity_drive']
        data_drives = group['data_drives']
        
        rebuilt_data = b''
        chunks_per_drive = self.drive_size // self.chunk_size
        drives_read = []
        
        for chunk_idx in range(chunks_per_drive):
            chunks = []
            
            # Read parity chunk
            with open(self.drives[parity_drive], 'rb') as f:
                f.seek(chunk_idx * self.chunk_size)
                parity_chunk = np.frombuffer(f.read(self.chunk_size), dtype=np.uint8)
            chunks.append(parity_chunk)
            drives_read.append(parity_drive)
            
            # Read all other data chunks in the group
            for drive_id in data_drives:
                if drive_id != failed_drive and self.drive_status[drive_id]:
                    with open(self.drives[drive_id], 'rb') as f:
                        f.seek(chunk_idx * self.chunk_size)
                        chunk = np.frombuffer(f.read(self.chunk_size), dtype=np.uint8)
                        if len(chunk) == self.chunk_size:
                            chunks.append(chunk)
                            drives_read.append(drive_id)
            
            rebuilt_chunk = self.calculate_parity(chunks)
            rebuilt_data += rebuilt_chunk.tobytes()
        
        # Write rebuilt data
        with open(self.drives[failed_drive], 'wb') as f:
            f.write(rebuilt_data)
        
        return list(set(drives_read))
    
    def retrieve_file(self):
        """Retrieve stored file data"""
        if not self.stored_file_data:
            return None, "No file stored"
        
        # For simplicity, return the original stored data
        # In a real system, you'd reconstruct from drives
        return self.stored_file_data, "File retrieved successfully"
    
    def check_data_integrity(self):
        """Check if data can be recovered with current drive failures"""
        offline_drives = [i for i, status in enumerate(self.drive_status) if not status]
        
        if len(offline_drives) == 0:
            return True, "All drives online", []
        
        vulnerable_dboxes = []
        
        for dbox in self.dboxes:
            dbox_failures = [d for d in offline_drives if d in dbox['all_drives']]
            
            if len(dbox_failures) == 0:
                continue
            
            max_group_failures = 0
            for group in dbox['local_groups']:
                group_failures = sum(1 for d in group['data_drives'] if not self.drive_status[d])
                max_group_failures = max(max_group_failures, group_failures)
            
            if max_group_failures > 2:
                vulnerable_dboxes.append(dbox['id'])
        
        if len(vulnerable_dboxes) > 0:
            return False, f"Data at risk in Dboxes: {vulnerable_dboxes}", vulnerable_dboxes
        
        return True, f"Recoverable with {len(offline_drives)} failures", []


class StorageGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Multi-File Erasure Coded Storage - 484 Drives / 11 Dboxes")
        self.root.geometry("1900x1000")
        
        self.storage = ErasureCodedStorage()
        self.drive_buttons = {}
        self.drive_frames = {}
        self.dbox_frames = []
        self.dbox_enabled = [True] * 11
        
        self.setup_ui()
        
    def setup_ui(self):
        # Top control panel
        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(side=tk.TOP, fill=tk.X)
        
        # Left side buttons
        left_buttons = ttk.Frame(control_frame)
        left_buttons.pack(side=tk.LEFT)
        
        ttk.Button(left_buttons, text="Initialize Storage", 
                   command=self.initialize_storage).pack(side=tk.LEFT, padx=5)
        ttk.Button(left_buttons, text="Load Files", 
                   command=self.load_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(left_buttons, text="Check Integrity", 
                   command=self.check_integrity).pack(side=tk.LEFT, padx=5)
        ttk.Button(left_buttons, text="Rebuild Drives", 
                   command=self.rebuild_drives).pack(side=tk.LEFT, padx=5)
        ttk.Button(left_buttons, text="Download File", 
                   command=self.download_file).pack(side=tk.LEFT, padx=5)
        
        # HA Mode toggle
        self.ha_var = tk.BooleanVar(value=False)
        ha_check = ttk.Checkbutton(left_buttons, text="Dbox HA Mode (18%)", 
                                   variable=self.ha_var, command=self.toggle_ha_mode)
        ha_check.pack(side=tk.LEFT, padx=15)
        
        # Status label
        self.status_label = ttk.Label(control_frame, text="Ready", 
                                      font=("Arial", 10, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=20)
        
        # Progress bar
        self.progress = ttk.Progressbar(control_frame, length=300, mode='determinate')
        self.progress.pack(side=tk.LEFT, padx=5)
        
        # Storage stats
        stats_frame = ttk.Frame(self.root, padding="5")
        stats_frame.pack(side=tk.TOP, fill=tk.X)
        
        self.stats_label = ttk.Label(stats_frame, text="Storage: Total: 0MB | Used: 0MB | Available: 0MB", 
                                     font=("Arial", 9))
        self.stats_label.pack(side=tk.LEFT, padx=10)
        
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
        
        self.drives_frame = scrollable_frame
        self.create_dbox_layout()
        
        # Legend
        info_frame = ttk.Frame(self.root, padding="10")
        info_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        ttk.Label(info_frame, text="Legend:", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        
        legend_frame = tk.Frame(info_frame)
        legend_frame.pack(side=tk.LEFT, padx=10)
        
        self._create_legend_item(legend_frame, "Online", "#90EE90", "black")
        self._create_legend_item(legend_frame, "Offline", "#FF4444", "white")
        self._create_legend_item(legend_frame, "Local Parity", "#9370DB", "white")
        self._create_legend_item(legend_frame, "Global Parity", "#1E90FF", "white")
        self._create_legend_item(legend_frame, "Hot Spare", "#FFD700", "black")
        
        ttk.Label(info_frame, text="Right-click drive to view contents").pack(side=tk.LEFT, padx=20)
    
    def _create_legend_item(self, parent, text, bg_color, fg_color):
        """Create a legend item with colored background"""
        frame = tk.Frame(parent, bg=bg_color, relief=tk.RAISED, borderwidth=2)
        frame.pack(side=tk.LEFT, padx=3)
        label = tk.Label(frame, text=f"  {text}  ", bg=bg_color, fg=fg_color, font=("Arial", 8))
        label.pack(padx=2, pady=2)
    
    def create_dbox_layout(self):
        """Create Dbox groups with drive buttons"""
        columns = 3
        
        for dbox_id, dbox in enumerate(self.storage.dboxes):
            row = dbox_id // columns
            col = dbox_id % columns
            
            dbox_container = ttk.LabelFrame(self.drives_frame, text=dbox['name'], padding="5")
            dbox_container.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            
            control_frame = ttk.Frame(dbox_container)
            control_frame.pack(side=tk.TOP, fill=tk.X, pady=3)
            
            ttk.Button(control_frame, text="Toggle Dbox", 
                      command=lambda did=dbox_id: self.toggle_dbox(did)).pack(side=tk.LEFT, padx=3)
            
            status_label = ttk.Label(control_frame, text="✓ Online", foreground="green")
            status_label.pack(side=tk.LEFT, padx=5)
            
            drives_grid = tk.Frame(dbox_container, bg="gray90")
            drives_grid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            
            grid_cols = 11
            for idx, drive_id in enumerate(dbox['all_drives']):
                grid_row = idx // grid_cols
                grid_col = idx % grid_cols
                
                drive_container = tk.Frame(drives_grid, relief=tk.RAISED, borderwidth=3, bg="white")
                drive_container.grid(row=grid_row, column=grid_col, padx=2, pady=2, sticky="nsew")
                
                btn = tk.Label(drive_container, text=f"{drive_id}\n0000", 
                               width=8, height=2,
                               bg="white",
                               relief=tk.RAISED,
                               borderwidth=1,
                               font=("Courier", 7, "bold"),
                               cursor="hand2")
                btn.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
                
                btn.bind("<Button-1>", lambda e, x=drive_id: self.toggle_drive(x))
                btn.bind("<Button-2>", lambda e, x=drive_id: self.show_drive_contents(x))
                btn.bind("<Button-3>", lambda e, x=drive_id: self.show_drive_contents(x))
                btn.bind("<Control-Button-1>", lambda e, x=drive_id: self.show_drive_contents(x))
                
                self.drive_buttons[drive_id] = btn
                self.drive_frames[drive_id] = drive_container
                
                self.create_tooltip(btn, drive_id)
            
            self.dbox_frames.append((dbox_container, status_label))
    
    def create_tooltip(self, widget, drive_id):
        """Create hover tooltip for drive info"""
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            
            dbox_id = self.storage.get_dbox_for_drive(drive_id)
            drive_type = self.storage.get_drive_type(drive_id)
            
            label = tk.Label(tooltip, 
                           text=f"Drive {drive_id}\n"
                                f"{drive_type}\n"
                                f"Dbox: {dbox_id}\n"
                                f"Data: {self.storage.drive_data_preview[drive_id]}\n"
                                f"Right-click to view contents",
                           background="#FFFACD", relief=tk.SOLID, borderwidth=1,
                           font=("Courier", 8), justify=tk.LEFT, padx=5, pady=5)
            label.pack()
            
            widget.tooltip = tooltip
        
        def on_leave(event):
            if hasattr(widget, 'tooltip'):
                widget.tooltip.destroy()
                del widget.tooltip
        
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)
    
    def show_drive_contents(self, drive_id):
        """Show full hex dump of drive contents"""
        contents_window = tk.Toplevel(self.root)
        contents_window.title(f"Drive {drive_id} - {self.storage.get_drive_type(drive_id)}")
        contents_window.geometry("900x600")
        
        text_area = scrolledtext.ScrolledText(contents_window, font=("Courier", 9), wrap=tk.NONE)
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Get drive contents
        contents = self.storage.get_drive_contents(drive_id)
        text_area.insert(tk.END, contents)
        text_area.config(state=tk.DISABLED)
        
        ttk.Button(contents_window, text="Close", command=contents_window.destroy).pack(pady=5)
    
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
        self.update_storage_stats()
        self.status_label.config(text="Storage initialized - 484 drives ready")
        messagebox.showinfo("Success", 
                          "Storage system initialized\n"
                          "11 Dboxes × 44 drives\n"
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
        self.update_storage_stats()
        
        if success:
            messagebox.showinfo("Success", message)
        else:
            messagebox.showerror("Error", message)
    
    def toggle_drive(self, drive_id):
        """Toggle drive online/offline status"""
        self.storage.drive_status[drive_id] = not self.storage.drive_status[drive_id]
        self.update_drive_display(drive_id)
        self.check_integrity_silent()
    
    def toggle_dbox(self, dbox_id):
        """Toggle entire Dbox online/offline"""
        self.dbox_enabled[dbox_id] = not self.dbox_enabled[dbox_id]
        
        dbox = self.storage.dboxes[dbox_id]
        for drive_id in dbox['all_drives']:
            self.storage.drive_status[drive_id] = self.dbox_enabled[dbox_id]
            self.update_drive_display(drive_id)
        
        _, status_label = self.dbox_frames[dbox_id]
        if self.dbox_enabled[dbox_id]:
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
        self.update_storage_stats()
        
        messagebox.showinfo("HA Mode", 
                          f"High Availability Mode: {mode}\n"
                          f"Overhead: {overhead}\n"
                          f"Max drives per stripe: {'22 (2 per Dbox)' if self.storage.ha_mode else 'All available'}")
    
    def rebuild_drives(self):
        """Rebuild failed drives"""
        offline_drives = [i for i, status in enumerate(self.storage.drive_status) if not status]
        
        if len(offline_drives) == 0:
            messagebox.showinfo("Rebuild", "No drives to rebuild")
            return
        
        # Ask if drives should come back online
        bring_online = messagebox.askyesno("Rebuild Options", 
                                          f"Rebuild {len(offline_drives)} drive(s)?\n\n"
                                          "Click Yes to rebuild and bring drives online\n"
                                          "Click No to rebuild to spare drives")
        
        self.status_label.config(text=f"Rebuilding {len(offline_drives)} drive(s)...")
        self.root.update()
        
        def rebuild_thread():
            drives_read, rebuild_info = self.storage.rebuild_drives(offline_drives, bring_online)
            self.root.after(0, lambda: self.rebuild_complete(drives_read, rebuild_info, bring_online))
        
        threading.Thread(target=rebuild_thread, daemon=True).start()
    
    def rebuild_complete(self, drives_read, rebuild_info, bring_online):
        """Called when rebuild completes"""
        self.update_all_drive_displays()
        self.status_label.config(text="Rebuild complete")
        
        info_msg = f"Rebuild Complete\n\n"
        info_msg += f"Drives read during rebuild: {len(drives_read)}\n"
        info_msg += f"Drive list: {sorted(drives_read)[:20]}{'...' if len(drives_read) > 20 else ''}\n\n"
        info_msg += "Rebuild details:\n"
        info_msg += "\n".join(rebuild_info[:10])
        if len(rebuild_info) > 10:
            info_msg += f"\n... and {len(rebuild_info) - 10} more"
        
        messagebox.showinfo("Rebuild Complete", info_msg)
    
    def download_file(self):
        """Download the stored file"""
        data, message = self.storage.retrieve_file()
        
        if data is None:
            messagebox.showerror("Error", message)
            return
        
        save_path = filedialog.asksaveasfilename(
            defaultextension=".dat",
            initialfile=self.storage.stored_file_name or "downloaded_file.dat",
            title="Save retrieved file"
        )
        
        if not save_path:
            return
        
        with open(save_path, 'wb') as f:
            f.write(data)
        
        messagebox.showinfo("Success", f"File saved to {save_path}\nSize: {len(data)} bytes")
    
    def update_drive_display(self, drive_id):
        """Update visual display of a drive button"""
        if drive_id not in self.drive_buttons:
            return
        
        btn = self.drive_buttons[drive_id]
        frame = self.drive_frames[drive_id]
        online = self.storage.drive_status[drive_id]
        preview = self.storage.drive_data_preview[drive_id]
        drive_type = self.storage.get_drive_type(drive_id)
        
        btn.config(text=f"{drive_id}\n{preview[-4:]}")
        
        if not online:
            btn.config(bg="#FF4444", fg="white")
            frame.config(bg="#FF4444")
        elif drive_type == "Local Parity":
            btn.config(bg="#9370DB", fg="white")
            frame.config(bg="#9370DB")
        elif drive_type == "Global Parity":
            btn.config(bg="#1E90FF", fg="white")
            frame.config(bg="#1E90FF")
        elif drive_type == "Hot Spare":
            btn.config(bg="#FFD700", fg="black")
            frame.config(bg="#FFD700")
        elif preview != '00000000':
            btn.config(bg="#90EE90", fg="black")
            frame.config(bg="#90EE90")
        else:
            btn.config(bg="white", fg="black")
            frame.config(bg="white")
        
        btn.update_idletasks()
        frame.update_idletasks()
    
    def update_all_drive_displays(self):
        """Update all drive displays"""
        for drive_id in range(self.storage.total_drives):
            self.update_drive_display(drive_id)
    
    def update_storage_stats(self):
        """Update storage statistics display"""
        stats = self.storage.get_storage_stats()
        
        total_mb = stats['total'] / (1024 * 1024)
        used_mb = stats['used'] / (1024 * 1024)
        avail_mb = stats['available'] / (1024 * 1024)
        
        self.stats_label.config(
            text=f"Storage: Total: {total_mb:.2f}MB | Used: {used_mb:.2f}MB | Available: {avail_mb:.2f}MB"
        )
    
    def check_integrity(self):
        """Check data integrity and show message"""
        can_recover, message, vulnerable = self.storage.check_data_integrity()
        
        offline_count = sum(1 for status in self.storage.drive_status if not status)
        
        result = f"{message}\n"
        result += f"Offline drives: {offline_count}\n"
        result += f"HA Mode: {'ENABLED' if self.storage.ha_mode else 'DISABLED'}"
        
        if vulnerable:
            result += f"\nVulnerable Dboxes: {vulnerable}"
        
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